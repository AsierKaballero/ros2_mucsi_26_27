"""Estado del robot: articulaciones, descripción URDF, límites, pose del efector y salud.

Rutas:
  GET /api/robot/urdf                 URDF tal como lo publica robot_state_publisher
  GET /api/robot/info                 brazos, articulaciones y límites (del URDF)
  GET /paquetes/<paquete>/<ruta>      ficheros de share/ (mallas package:// del gemelo 3D)
"""

import math
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from ament_index_python.packages import PackageNotFoundError, get_package_share_directory
from rclpy.duration import Duration
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from sensor_msgs.msg import JointState
from std_msgs.msg import String
from tf2_ros import Buffer, TransformListener

from openarm_hmi.nucleo import geometria
from openarm_hmi.nucleo.modulo import Modulo
from openarm_hmi.nucleo.servidor import ErrorHmi, Respuesta, respuesta_fichero, ruta_segura


def limites_urdf(urdf: str) -> Dict[str, Dict[str, Any]]:
    """Límites de cada articulación móvil del URDF: tipo, inferior, superior, velocidad, mimic."""
    raiz = ET.fromstring(urdf)
    limites = {}
    # Solo los <joint> hijos directos de <robot>: los bloques <ros2_control> y <transmission>
    # también tienen <joint name="..."> (sin tipo ni límites) y sobrescribirían a los reales
    for articulacion in raiz.findall("joint"):
        tipo = articulacion.get("type")
        if tipo in ("fixed", "floating", "planar"):
            continue
        datos: Dict[str, Any] = {"tipo": tipo}
        limite = articulacion.find("limit")
        if limite is not None:
            for clave, atributo in (("inferior", "lower"), ("superior", "upper"),
                                    ("velocidad", "velocity"), ("esfuerzo", "effort")):
                if limite.get(atributo) is not None:
                    datos[clave] = float(limite.get(atributo))
        if tipo == "continuous":
            datos["inferior"], datos["superior"] = -math.pi, math.pi
        mimic = articulacion.find("mimic")
        if mimic is not None:
            datos["mimic"] = mimic.get("joint")
        limites[articulacion.get("name")] = datos
    return limites


class Estado(Modulo):
    nombre = "estado"

    def iniciar(self) -> None:
        self._candado = threading.Lock()
        self._posiciones: Dict[str, float] = {}
        self._velocidades: Dict[str, float] = {}
        self._ultimo_joint_states = 0.0
        self.urdf: Optional[str] = None
        self.limites: Dict[str, Dict[str, Any]] = {}
        self._nodos_cache: List[str] = []
        self._nodos_t = 0.0

        self.nodo.create_subscription(JointState, "/joint_states", self._cb_joint_states, 50,
                                      callback_group=self.ctx.grupo_callbacks)
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             reliability=ReliabilityPolicy.RELIABLE)
        self.nodo.create_subscription(String, "/robot_description", self._cb_descripcion,
                                      latched, callback_group=self.ctx.grupo_callbacks)
        self.tf = Buffer(cache_time=Duration(seconds=10))
        self._tf_listener = TransformListener(self.tf, self.nodo, spin_thread=False)

        self.ruta("GET", "/api/robot/urdf", self._ruta_urdf)
        self.ruta("GET", "/api/robot/info", lambda p: self.info())
        self.ruta("GET", "/paquetes/{paquete}/{ruta:*}", self._ruta_paquete)

    # --- Suscripciones ----------------------------------------------------------------

    def _cb_joint_states(self, msg: JointState) -> None:
        # Varios nodos publican en /joint_states (broadcaster y articulaciones miméticas
        # de las pinzas): se combinan por nombre
        with self._candado:
            for i, nombre in enumerate(msg.name):
                if i < len(msg.position):
                    self._posiciones[nombre] = msg.position[i]
                if i < len(msg.velocity):
                    self._velocidades[nombre] = msg.velocity[i]
            self._ultimo_joint_states = time.time()

    def _cb_descripcion(self, msg: String) -> None:
        if msg.data == self.urdf:
            return
        try:
            limites = limites_urdf(msg.data)
        except ET.ParseError as e:
            self.log.error(f"robot_description no es un URDF válido: {e}")
            return
        self.urdf = msg.data
        self.limites = limites
        self.log.info(f"Descripción del robot recibida ({len(limites)} articulaciones móviles)")
        self.bus.emitir("robot_descripcion", {"articulaciones": len(limites)})

    # --- API para otros módulos -------------------------------------------------------

    def posiciones(self, nombres: List[str]) -> List[float]:
        """Posiciones actuales de `nombres`; ErrorHmi(503) si falta alguna."""
        with self._candado:
            faltan = [n for n in nombres if n not in self._posiciones]
            if faltan:
                raise ErrorHmi(
                    f"Sin estado de {', '.join(faltan)}: ¿está lanzado el robot?", 503)
            return [self._posiciones[n] for n in nombres]

    def posicion(self, nombre: str) -> Optional[float]:
        with self._candado:
            return self._posiciones.get(nombre)

    def edad_joint_states(self) -> float:
        return time.time() - self._ultimo_joint_states if self._ultimo_joint_states else math.inf

    def pose_efector(self, marco: str, timeout_s: float = 0.0) -> Optional[Dict[str, Any]]:
        """Pose de `marco` en el marco de referencia, o None si TF no la conoce."""
        try:
            t = self.tf.lookup_transform(self.config.marco_referencia, marco, Time(),
                                         timeout=Duration(seconds=timeout_s))
        except Exception:  # noqa: BLE001 - tf2 lanza varias excepciones distintas
            return None
        p = t.transform.translation
        q = t.transform.rotation
        cuaternion = (q.x, q.y, q.z, q.w)
        return {"posicion": [p.x, p.y, p.z], "orientacion": list(cuaternion),
                "rpy": list(geometria.a_rpy(cuaternion))}

    def validar_objetivo(self, nombres: List[str], valores: List[float]) -> None:
        """Comprueba que los valores estén dentro de los límites del URDF."""
        margen = float(self.config.seccion("movimiento").get("margen_limites", 0.0))
        for nombre, valor in zip(nombres, valores):
            if not math.isfinite(valor):
                raise ErrorHmi(f"{nombre}: valor no numérico")
            limite = self.limites.get(nombre)
            if not limite or "inferior" not in limite:
                continue
            inferior, superior = limite["inferior"] + margen, limite["superior"] - margen
            if not inferior - 1e-6 <= valor <= superior + 1e-6:
                raise ErrorHmi(
                    f"{nombre} = {math.degrees(valor):.1f}° fuera de límites "
                    f"[{math.degrees(inferior):.1f}°, {math.degrees(superior):.1f}°]")

    def nodos_activos(self) -> List[str]:
        """Nombres completos de los nodos del grafo (caché de 1 s)."""
        if time.time() - self._nodos_t > 1.0:
            self._nodos_cache = [
                (ns.rstrip("/") + "/" + n) for n, ns in
                self.nodo.get_node_names_and_namespaces()]
            self._nodos_t = time.time()
        return self._nodos_cache

    def nodo_activo(self, nombre: str) -> bool:
        nombre = nombre if nombre.startswith("/") else "/" + nombre
        return nombre in self.nodos_activos()

    # --- Rutas ------------------------------------------------------------------------

    def _ruta_urdf(self, peticion) -> Respuesta:
        if not self.urdf:
            raise ErrorHmi("Aún no se ha recibido /robot_description (¿está lanzado el robot?)",
                           503)
        return Respuesta(self.urdf.encode("utf-8"), "application/xml; charset=utf-8")

    def _ruta_paquete(self, peticion) -> Respuesta:
        try:
            raiz = get_package_share_directory(peticion.params["paquete"])
        except PackageNotFoundError as e:
            raise ErrorHmi(f"Paquete desconocido: {peticion.params['paquete']}", 404) from e
        return respuesta_fichero(ruta_segura(raiz, peticion.params["ruta"]), cache_s=3600)

    # --- Estado e info ----------------------------------------------------------------

    def info(self) -> Dict[str, Any]:
        brazos = []
        for brazo in self.config.brazos:
            d = brazo.a_dict()
            d["limites"] = {n: self.limites.get(n) for n in brazo.articulaciones}
            pinza = self.limites.get(brazo.pinza.articulacion)
            d["limites_pinza"] = pinza
            brazos.append(d)
        return {
            "cuerpo": self.config.cuerpo,
            "nombre": self.config.datos["robot"].get("nombre", ""),
            "marco_referencia": self.config.marco_referencia,
            "grupo_conjunto": self.config.grupo_conjunto,
            "brazos": brazos,
            "urdf_disponible": self.urdf is not None,
        }

    def estado(self) -> Dict[str, Any]:
        with self._candado:
            posiciones = {n: round(v, 5) for n, v in self._posiciones.items()}
            velocidades = {n: round(v, 4) for n, v in self._velocidades.items()}
        robot = self.config.datos["robot"]
        return {
            "posiciones": posiciones,
            "velocidades": velocidades,
            "edad_joint_states": round(min(self.edad_joint_states(), 9999.0), 2),
            "poses": {b.id: self.pose_efector(b.efector) for b in self.config.brazos},
            "move_group": self.nodo_activo(robot.get("nodo_move_group", "move_group")),
            "controller_manager": self.nodo_activo(robot.get("gestor_controladores",
                                                             "/controller_manager")),
            "urdf": self.urdf is not None,
        }
