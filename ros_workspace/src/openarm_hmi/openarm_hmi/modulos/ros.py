"""Introspección de ROS 2: nodos, topics, servicios, acciones, parámetros y echo de topics.

Rutas:
  GET /api/ros/grafo                              nodos, topics, servicios y acciones
  GET /api/ros/nodo?nombre=/ns/nodo               publicadores, suscripciones, servicios...
  GET /api/ros/topic?nombre=/t&duracion=1.0       último mensaje, frecuencia y QoS
  GET /api/ros/parametros?nodo=/ns/nodo           parámetros del nodo y sus valores
"""

import array
import threading
import time
from typing import Any, Dict, List, Tuple

from rcl_interfaces.msg import ParameterType
from rcl_interfaces.srv import GetParameters, ListParameters
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rosidl_runtime_py.utilities import get_message

from openarm_hmi.nucleo.modulo import Modulo
from openarm_hmi.nucleo.servidor import ErrorHmi

try:
    from rclpy.action.graph import get_action_names_and_types
except ImportError:  # pragma: no cover - versiones antiguas de rclpy
    get_action_names_and_types = None


def separar_nombre(completo: str) -> Tuple[str, str]:
    """'/ns/nodo' -> ('nodo', '/ns')."""
    completo = completo if completo.startswith("/") else "/" + completo
    espacio, _, nombre = completo.rpartition("/")
    return nombre, espacio or "/"


def mensaje_a_dict(valor: Any, max_elementos: int = 32, profundidad: int = 0) -> Any:
    """Convierte un mensaje a tipos JSON recortando los arrays largos (imágenes, nubes...)."""
    if profundidad > 12:
        return "…"
    if hasattr(valor, "get_fields_and_field_types"):
        return {campo: mensaje_a_dict(getattr(valor, campo), max_elementos, profundidad + 1)
                for campo in valor.get_fields_and_field_types()}
    if isinstance(valor, (bytes, bytearray)):
        return f"<{len(valor)} bytes>"
    if isinstance(valor, (list, tuple, array.array)) or hasattr(valor, "tolist"):
        if hasattr(valor, "tolist") and not isinstance(valor, (list, tuple)):
            n = len(valor)
            recorte = valor[:max_elementos].tolist()
        else:
            n = len(valor)
            recorte = list(valor[:max_elementos])
        resultado = [mensaje_a_dict(v, max_elementos, profundidad + 1) for v in recorte]
        if n > max_elementos:
            resultado.append(f"… ({n} elementos en total)")
        return resultado
    if isinstance(valor, float):
        return valor if valor == valor and abs(valor) != float("inf") else str(valor)
    if isinstance(valor, (int, str, bool)) or valor is None:
        return valor
    return str(valor)


def valor_parametro(valor) -> Any:
    tipo = valor.type
    if tipo == ParameterType.PARAMETER_BOOL:
        return valor.bool_value
    if tipo == ParameterType.PARAMETER_INTEGER:
        return valor.integer_value
    if tipo == ParameterType.PARAMETER_DOUBLE:
        return valor.double_value
    if tipo == ParameterType.PARAMETER_STRING:
        texto = valor.string_value
        return texto if len(texto) < 2000 else texto[:2000] + f"… ({len(texto)} caracteres)"
    if tipo == ParameterType.PARAMETER_BYTE_ARRAY:
        return f"<{len(valor.byte_array_value)} bytes>"
    if tipo == ParameterType.PARAMETER_BOOL_ARRAY:
        return list(valor.bool_array_value)
    if tipo == ParameterType.PARAMETER_INTEGER_ARRAY:
        return list(valor.integer_array_value)
    if tipo == ParameterType.PARAMETER_DOUBLE_ARRAY:
        return list(valor.double_array_value)
    if tipo == ParameterType.PARAMETER_STRING_ARRAY:
        return list(valor.string_array_value)
    return None


class Ros(Modulo):
    nombre = "ros"

    def iniciar(self) -> None:
        self.ruta("GET", "/api/ros/grafo", lambda p: self.grafo())
        self.ruta("GET", "/api/ros/nodo", self._ruta_nodo)
        self.ruta("GET", "/api/ros/topic", self._ruta_topic)
        self.ruta("GET", "/api/ros/parametros", self._ruta_parametros)

    # --- Grafo ------------------------------------------------------------------------

    def grafo(self) -> Dict[str, Any]:
        n = self.nodo
        nodos = sorted((ns.rstrip("/") + "/" + nombre)
                       for nombre, ns in n.get_node_names_and_namespaces())
        topics = []
        for nombre, tipos in sorted(n.get_topic_names_and_types()):
            topics.append({"nombre": nombre, "tipos": tipos,
                           "publicadores": n.count_publishers(nombre),
                           "suscriptores": n.count_subscribers(nombre),
                           "oculto": "/_" in nombre})
        servicios = [{"nombre": nombre, "tipos": tipos,
                      "oculto": "/_" in nombre or nombre.endswith(
                          ("/describe_parameters", "/get_parameter_types", "/get_parameters",
                           "/list_parameters", "/set_parameters",
                           "/set_parameters_atomically", "/get_type_description"))}
                     for nombre, tipos in sorted(n.get_service_names_and_types())]
        acciones = []
        if get_action_names_and_types is not None:
            acciones = [{"nombre": nombre, "tipos": tipos}
                        for nombre, tipos in sorted(get_action_names_and_types(n))]
        return {"nodos": nodos, "topics": topics, "servicios": servicios, "acciones": acciones,
                "instante": time.time()}

    def _ruta_nodo(self, peticion) -> Dict[str, Any]:
        completo = peticion.q("nombre")
        if not completo:
            raise ErrorHmi("Falta el parámetro 'nombre'")
        nombre, espacio = separar_nombre(completo)
        n = self.nodo

        def lista(funcion) -> List[Dict[str, Any]]:
            try:
                return [{"nombre": t, "tipos": tipos}
                        for t, tipos in sorted(funcion(nombre, espacio))]
            except Exception as e:  # noqa: BLE001 - nodo desaparecido
                raise ErrorHmi(f"Nodo no encontrado: {completo} ({e})", 404) from e

        return {
            "nombre": completo,
            "publicadores": lista(n.get_publisher_names_and_types_by_node),
            "suscripciones": lista(n.get_subscriber_names_and_types_by_node),
            "servicios": lista(n.get_service_names_and_types_by_node),
            "clientes": lista(n.get_client_names_and_types_by_node),
        }

    # --- Echo de topics ---------------------------------------------------------------

    def _ruta_topic(self, peticion) -> Dict[str, Any]:
        topic = peticion.q("nombre")
        if not topic:
            raise ErrorHmi("Falta el parámetro 'nombre'")
        try:
            duracion = min(max(float(peticion.q("duracion", 1.0)), 0.1), 5.0)
        except ValueError:
            duracion = 1.0
        tipos = dict(self.nodo.get_topic_names_and_types()).get(topic)
        if not tipos:
            raise ErrorHmi(f"Topic desconocido: {topic}", 404)
        try:
            clase = get_message(tipos[0])
        except (AttributeError, ModuleNotFoundError, ValueError) as e:
            raise ErrorHmi(f"Tipo {tipos[0]} no disponible en este equipo: {e}", 501) from e

        publicadores = self.nodo.get_publishers_info_by_topic(topic)
        qos = self._qos_compatible(publicadores)
        recibidos: List[float] = []
        ultimo: Dict[str, Any] = {}
        evento = threading.Event()

        def callback(msg) -> None:
            recibidos.append(time.monotonic())
            ultimo["msg"] = msg
            evento.set()

        sub = self.nodo.create_subscription(clase, topic, callback, qos)
        try:
            time.sleep(duracion)
            # Topics lentos o latched: se espera un poco más al primer mensaje
            if not recibidos:
                evento.wait(timeout=1.0)
        finally:
            self.nodo.destroy_subscription(sub)

        frecuencia = None
        if len(recibidos) >= 2:
            intervalo = recibidos[-1] - recibidos[0]
            if intervalo > 0:
                frecuencia = (len(recibidos) - 1) / intervalo
        return {
            "nombre": topic,
            "tipo": tipos[0],
            "mensajes": len(recibidos),
            "frecuencia_hz": round(frecuencia, 2) if frecuencia else None,
            "mensaje": mensaje_a_dict(ultimo["msg"]) if "msg" in ultimo else None,
            "publicadores": [{"nodo": f"{p.node_namespace.rstrip('/')}/{p.node_name}",
                              "fiabilidad": p.qos_profile.reliability.name,
                              "durabilidad": p.qos_profile.durability.name}
                             for p in publicadores],
            "suscriptores": [f"{s.node_namespace.rstrip('/')}/{s.node_name}"
                             for s in self.nodo.get_subscriptions_info_by_topic(topic)],
        }

    @staticmethod
    def _qos_compatible(publicadores) -> QoSProfile:
        """QoS que recibe de todos los publicadores (incluido el último mensaje latched)."""
        fiable = all(p.qos_profile.reliability == ReliabilityPolicy.RELIABLE
                     for p in publicadores) and publicadores
        latched = any(p.qos_profile.durability == DurabilityPolicy.TRANSIENT_LOCAL
                      for p in publicadores)
        return QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE if fiable else ReliabilityPolicy.BEST_EFFORT,
            durability=(DurabilityPolicy.TRANSIENT_LOCAL if latched and fiable
                        else DurabilityPolicy.VOLATILE))

    # --- Parámetros -------------------------------------------------------------------

    def _ruta_parametros(self, peticion) -> Dict[str, Any]:
        completo = peticion.q("nodo")
        if not completo:
            raise ErrorHmi("Falta el parámetro 'nodo'")
        completo = completo if completo.startswith("/") else "/" + completo
        listar = self.nodo.create_client(ListParameters, f"{completo}/list_parameters")
        obtener = self.nodo.create_client(GetParameters, f"{completo}/get_parameters")
        try:
            if not listar.wait_for_service(timeout_sec=1.0):
                raise ErrorHmi(f"{completo} no ofrece el servicio de parámetros", 404)
            nombres = self._llamar(listar, ListParameters.Request()).result.names
            peticion_valores = GetParameters.Request(names=list(nombres))
            valores = self._llamar(obtener, peticion_valores).values
        finally:
            self.nodo.destroy_client(listar)
            self.nodo.destroy_client(obtener)
        return {"nodo": completo,
                "parametros": [{"nombre": n, "valor": valor_parametro(v)}
                               for n, v in sorted(zip(nombres, valores), key=lambda x: x[0])]}

    @staticmethod
    def _llamar(cliente, peticion, timeout_s: float = 3.0):
        evento = threading.Event()
        futuro = cliente.call_async(peticion)
        futuro.add_done_callback(lambda f: evento.set())
        if not evento.wait(timeout_s):
            raise ErrorHmi("El nodo no respondió a tiempo", 504)
        return futuro.result()
