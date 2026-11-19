"""Pinzas: apertura en milímetros a través de la acción GripperCommand de cada brazo.

La acción `/robot_<brazo>/gripper_action` (nodo pinza_openarm_node del lanzador) recibe la
anchura total entre dedos en mm. La anchura actual se calcula a partir de finger_joint1.

Rutas:
  POST /api/pinza   {brazo, anchura_mm, esfuerzo?}   (brazo admite "ambos")
"""

import math
from typing import Any, Dict

from control_msgs.action import GripperCommand
from rclpy.action import ActionClient

from openarm_hmi.nucleo.modulo import Modulo, requerir
from openarm_hmi.nucleo.servidor import ErrorHmi


def interpretar_pinza(resultado, status) -> tuple:
    if resultado.reached_goal:
        return True, f"Pinza en {resultado.position:.1f} mm"
    if resultado.stalled:
        return True, f"Pinza bloqueada en {resultado.position:.1f} mm (¿objeto agarrado?)"
    return False, f"La pinza no alcanzó el objetivo ({resultado.position:.1f} mm)"


class Pinza(Modulo):
    nombre = "pinza"

    def iniciar(self) -> None:
        self.estado_robot = self.ctx.modulo("estado")
        self.clientes = {
            b.id: ActionClient(self.nodo, GripperCommand, b.pinza.accion,
                               callback_group=self.ctx.grupo_callbacks)
            for b in self.config.brazos
        }
        self.bus.suscribir("parada_emergencia",
                           lambda datos: self.tareas.cancelar("pinza:", motivo="Parada de emergencia"))
        self.ruta("POST", "/api/pinza", self._ruta_pinza)

    def mover(self, id_brazo: str, anchura_mm: float, esfuerzo: float = None) -> Dict[str, Any]:
        self.ctx.comprobar_movimiento_permitido()
        brazo = self.config.brazo(id_brazo)
        if not math.isfinite(anchura_mm):
            raise ErrorHmi("Anchura inválida")
        anchura = min(max(anchura_mm, 0.0), brazo.pinza.anchura_maxima_mm)
        cliente = self.clientes[brazo.id]
        if not cliente.server_is_ready():
            raise ErrorHmi(f"Acción {brazo.pinza.accion} no disponible "
                           "(¿está lanzado el robot?)", 503)
        goal = GripperCommand.Goal()
        goal.command.position = float(anchura)
        goal.command.max_effort = float(esfuerzo if esfuerzo is not None else brazo.pinza.esfuerzo)
        tarea = self.tareas.nueva(f"pinza:{brazo.id}", "pinza",
                                  f"{brazo.nombre}: pinza a {anchura:.0f} mm")
        self.tareas.enviar_objetivo(cliente, goal, tarea, interpretar_pinza,
                                    nombre_servidor=brazo.pinza.accion)
        return tarea.a_dict()

    def _ruta_pinza(self, peticion) -> Any:
        datos = peticion.json()
        objetivo = str(requerir(datos, "brazo"))
        anchura = requerir(datos, "anchura_mm", float)
        esfuerzo = datos.get("esfuerzo")
        esfuerzo = float(esfuerzo) if esfuerzo is not None else None
        try:
            ids = self.config.ids_brazos if objetivo == "ambos" else [self.config.brazo(objetivo).id]
        except KeyError as e:
            raise ErrorHmi(f"Brazo desconocido: {objetivo}") from e
        tareas = [self.mover(i, anchura, esfuerzo) for i in ids]
        return tareas[0] if len(tareas) == 1 else {"tareas": tareas}

    def estado(self) -> Dict[str, Any]:
        activas = self.tareas.activas()
        resultado = {}
        for brazo in self.config.brazos:
            rad = self.estado_robot.posicion(brazo.pinza.articulacion) if self.estado_robot else None
            resultado[brazo.id] = {
                "anchura_mm": round(brazo.pinza.rad_a_mm(rad), 1) if rad is not None else None,
                "disponible": self.clientes[brazo.id].server_is_ready(),
                "tarea": activas.get(f"pinza:{brazo.id}"),
            }
        return resultado
