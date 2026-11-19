"""Seguimiento de órdenes asíncronas (acciones de ROS 2) que lanza el HMI.

Cada orden es una `Tarea` con un ámbito (p. ej. "movimiento:301_izq"). En un ámbito solo
hay una tarea activa: una nueva cancela la anterior. Los cambios de estado se envían a los
navegadores como evento "tarea", y la parada de emergencia cancela todas las tareas.

Las peticiones HTTP no esperan a que la acción termine: devuelven la tarea y el navegador
sigue su progreso por los eventos.

Cada servidor de acción recibe un solo objetivo a la vez: move_group ejecuta un único
objetivo y se cae si le llegan cancelaciones y objetivos nuevos cruzados. Antes de enviar un
objetivo se espera a que el servidor haya terminado (o cancelado) el anterior.
"""

import threading
import time
import uuid
from collections import deque
from typing import Any, Callable, Dict, List, Optional, Tuple

PENDIENTE = "pendiente"
PLANIFICANDO = "planificando"
EJECUTANDO = "ejecutando"
COMPLETADA = "completada"
ERROR = "error"
CANCELADA = "cancelada"
FINALES = {COMPLETADA, ERROR, CANCELADA}

# Valores de action_msgs/GoalStatus (se copian para no importar ROS en este módulo)
_STATUS_SUCCEEDED = 4
_STATUS_CANCELED = 5
_STATUS_ABORTED = 6

# Espera máxima a que un servidor de acción termine el objetivo anterior antes del siguiente
ESPERA_SERVIDOR_S = 120.0

# Función que interpreta el resultado de una acción: (resultado, status) -> (ok, mensaje)
Interprete = Callable[[Any, int], Tuple[bool, str]]


class Tarea:
    def __init__(self, ambito: str, tipo: str, descripcion: str) -> None:
        self.id = uuid.uuid4().hex[:8]
        self.ambito = ambito
        self.tipo = tipo
        self.descripcion = descripcion
        self.estado = PENDIENTE
        self.mensaje = ""
        self.inicio = time.time()
        self.fin: Optional[float] = None
        self.handle = None
        self.cancelar_pendiente = False
        # Se activa cuando el servidor de la acción ya no tiene este objetivo (terminado,
        # cancelado, rechazado o nunca enviado): solo entonces se envía el siguiente
        self.servidor_libre = threading.Event()

    @property
    def terminada(self) -> bool:
        return self.estado in FINALES

    def a_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "ambito": self.ambito,
            "tipo": self.tipo,
            "descripcion": self.descripcion,
            "estado": self.estado,
            "mensaje": self.mensaje,
            "inicio": self.inicio,
            "duracion": (self.fin or time.time()) - self.inicio,
        }


class GestorTareas:
    def __init__(self, bus, registrador) -> None:
        self.bus = bus
        self.log = registrador
        self._activas: Dict[str, Tarea] = {}
        self._historial: deque = deque(maxlen=100)
        self._candado = threading.RLock()
        # Último objetivo enviado a cada servidor de acción (clave: id del ActionClient)
        self._ultima_por_servidor: Dict[int, Tarea] = {}

    # --- Ciclo de vida ----------------------------------------------------------------

    def nueva(self, ambito: str, tipo: str, descripcion: str,
              cancelar: Optional[List[str]] = None) -> Tarea:
        """Crea una tarea en `ambito`, cancelando la activa del mismo ámbito y de `cancelar`."""
        for otro in [ambito] + list(cancelar or []):
            self.cancelar(otro, exacto=True)
        tarea = Tarea(ambito, tipo, descripcion)
        with self._candado:
            self._activas[ambito] = tarea
        self._emitir(tarea)
        return tarea

    def actualizar(self, tarea: Tarea, estado: str, mensaje: Optional[str] = None) -> None:
        with self._candado:
            if tarea.terminada:
                return
            tarea.estado = estado
            if mensaje is not None:
                tarea.mensaje = mensaje
            if tarea.terminada:
                tarea.fin = time.time()
                if self._activas.get(tarea.ambito) is tarea:
                    del self._activas[tarea.ambito]
                self._historial.append(tarea)
        self._emitir(tarea)
        if estado == ERROR:
            self.log.warning(f"{tarea.descripcion}: {tarea.mensaje}")

    def cancelar(self, prefijo: Optional[str] = None, exacto: bool = False,
                 motivo: str = "Cancelada") -> int:
        """Cancela las tareas activas cuyo ámbito empieza por `prefijo` (todas si None)."""
        with self._candado:
            tareas = [t for a, t in self._activas.items()
                      if prefijo is None or (a == prefijo if exacto else a.startswith(prefijo))]
        for tarea in tareas:
            tarea.cancelar_pendiente = True
            if tarea.handle is not None:
                try:
                    tarea.handle.cancel_goal_async()
                except Exception:  # noqa: BLE001
                    pass
            # No se espera la confirmación del servidor de la acción: la tarea queda
            # cancelada para el HMI y su resultado posterior se ignora
            self.actualizar(tarea, CANCELADA, motivo)
        return len(tareas)

    def activa(self, ambito: str) -> Optional[Tarea]:
        with self._candado:
            return self._activas.get(ambito)

    def activas(self) -> Dict[str, Dict[str, Any]]:
        with self._candado:
            return {a: t.a_dict() for a, t in self._activas.items()}

    def historial(self) -> List[Dict[str, Any]]:
        with self._candado:
            return [t.a_dict() for t in reversed(self._historial)]

    def _emitir(self, tarea: Tarea) -> None:
        self.bus.emitir("tarea", tarea.a_dict())

    # --- Acciones de ROS 2 ------------------------------------------------------------

    def enviar_objetivo(self, cliente, objetivo, tarea: Tarea, interpretar: Interprete,
                        feedback: Optional[Callable] = None, nombre_servidor: str = "") -> None:
        """Envía `objetivo` al ActionClient `cliente` y sigue su evolución en `tarea`.

        Si el servidor aún tiene un objetivo anterior (en curso o cancelándose), el envío
        espera en segundo plano a que lo termine.
        """
        if tarea.cancelar_pendiente:
            tarea.servidor_libre.set()
            return
        if not cliente.server_is_ready():
            tarea.servidor_libre.set()
            self.actualizar(tarea, ERROR,
                            f"Servidor de acción {nombre_servidor or ''} no disponible")
            return
        with self._candado:
            previa = self._ultima_por_servidor.get(id(cliente))
            self._ultima_por_servidor[id(cliente)] = tarea
        argumentos = (cliente, objetivo, tarea, interpretar, feedback, nombre_servidor)
        if previa is None or previa.servidor_libre.is_set():
            self._enviar(*argumentos)
        else:
            threading.Thread(target=self._enviar_tras, args=(previa,) + argumentos,
                             daemon=True, name=f"tarea-{tarea.id}").start()

    def _enviar_tras(self, previa: Tarea, cliente, objetivo, tarea: Tarea,
                     interpretar: Interprete, feedback, nombre_servidor: str) -> None:
        if not previa.terminada:
            self.actualizar(tarea, PENDIENTE, f"En espera: {previa.descripcion}")
        limite = time.time() + ESPERA_SERVIDOR_S
        while not previa.servidor_libre.wait(0.2):
            if tarea.cancelar_pendiente:
                break
            if not cliente.server_is_ready():
                # El servidor ha desaparecido: el objetivo anterior ya no existe
                previa.servidor_libre.set()
                break
            if time.time() > limite:
                tarea.servidor_libre.set()
                self.actualizar(tarea, ERROR, f"{nombre_servidor or 'El servidor'} sigue "
                                "ocupado con la orden anterior")
                return
        if tarea.cancelar_pendiente:
            tarea.servidor_libre.set()
            return
        self._enviar(cliente, objetivo, tarea, interpretar, feedback, nombre_servidor)

    def _enviar(self, cliente, objetivo, tarea: Tarea, interpretar: Interprete,
                feedback, nombre_servidor: str) -> None:
        if not cliente.server_is_ready():
            tarea.servidor_libre.set()
            self.actualizar(tarea, ERROR,
                            f"Servidor de acción {nombre_servidor or ''} no disponible")
            return
        self.actualizar(tarea, EJECUTANDO)
        try:
            futuro = cliente.send_goal_async(objetivo, feedback_callback=feedback)
        except Exception as e:  # noqa: BLE001
            tarea.servidor_libre.set()
            self.actualizar(tarea, ERROR, f"No se pudo enviar el objetivo: {e}")
            return
        futuro.add_done_callback(lambda f: self._respuesta(f, tarea, interpretar))

    def _respuesta(self, futuro, tarea: Tarea, interpretar: Interprete) -> None:
        try:
            handle = futuro.result()
        except Exception as e:  # noqa: BLE001
            tarea.servidor_libre.set()
            self.actualizar(tarea, ERROR, f"No se pudo enviar el objetivo: {e}")
            return
        if not handle.accepted:
            tarea.servidor_libre.set()
            self.actualizar(tarea, ERROR, "El servidor rechazó el objetivo")
            return
        tarea.handle = handle
        # El resultado se sigue también si la tarea ya se canceló: marca cuándo queda libre
        # el servidor para el siguiente objetivo
        handle.get_result_async().add_done_callback(
            lambda f: self._resultado(f, tarea, interpretar))
        if tarea.cancelar_pendiente:
            handle.cancel_goal_async()

    def _resultado(self, futuro, tarea: Tarea, interpretar: Interprete) -> None:
        tarea.servidor_libre.set()
        if tarea.terminada:
            return
        try:
            respuesta = futuro.result()
        except Exception as e:  # noqa: BLE001
            self.actualizar(tarea, ERROR, f"Error al obtener el resultado: {e}")
            return
        if respuesta.status == _STATUS_CANCELED:
            self.actualizar(tarea, CANCELADA, "Cancelada por el servidor")
            return
        ok, mensaje = interpretar(respuesta.result, respuesta.status)
        if respuesta.status not in (_STATUS_SUCCEEDED, _STATUS_ABORTED) and ok:
            ok, mensaje = False, f"Estado final inesperado ({respuesta.status})"
        self.actualizar(tarea, COMPLETADA if ok else ERROR, mensaje)
