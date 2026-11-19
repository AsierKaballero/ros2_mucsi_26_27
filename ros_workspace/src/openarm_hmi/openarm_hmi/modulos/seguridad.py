"""Parada de emergencia por software (enclavada) y rearme.

Al activarla se emite el evento "parada_emergencia" y cada módulo reacciona:
  - movimiento: ordena a los controladores mantener la posición y cancela los objetivos;
  - pinza: cancela los objetivos de las pinzas;
  - scripts: detiene los scripts en marcha;
  - controladores: desactiva los controladores de brazo y pinza (si así se configura).
Mientras está activa, el HMI rechaza cualquier orden de movimiento (409). El estado se
publica en el topic `seguridad.topic_estado` (std_msgs/Bool, latched) para que otros nodos
del proyecto puedan reaccionar también.

IMPORTANTE: es una parada por software; no sustituye al corte de alimentación del robot.

Rutas:
  POST /api/seguridad/parada   {"motivo": "..."}
  POST /api/seguridad/rearme
"""

import time
from typing import Any, Dict

from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool

from openarm_hmi.nucleo.modulo import Modulo


class Seguridad(Modulo):
    nombre = "seguridad"

    def iniciar(self) -> None:
        self.cfg = self.config.seccion("seguridad")
        self.activa = False
        self.motivo = ""
        self.instante = None
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             reliability=ReliabilityPolicy.RELIABLE)
        topic = self.cfg.get("topic_estado", "/hmi/parada_emergencia")
        self.publicador = self.nodo.create_publisher(Bool, topic, latched) if topic else None
        self._publicar()

        self.ruta("POST", "/api/seguridad/parada", self._ruta_parada)
        self.ruta("POST", "/api/seguridad/rearme", self._ruta_rearme)

    def activar(self, motivo: str = "Parada de emergencia") -> None:
        primera = not self.activa
        self.activa = True
        self.motivo = motivo
        self.instante = time.time()
        self._publicar()
        # Se emite aunque ya estuviera activa: volver a pulsar repite la parada
        self.bus.emitir("parada_emergencia", {"motivo": motivo, "instante": self.instante})
        if primera:
            self.log.error(f"PARADA DE EMERGENCIA: {motivo}")

    def rearmar(self) -> None:
        if not self.activa:
            return
        self.bus.emitir("rearme", {"instante": time.time()})
        self.activa = False
        self.motivo = ""
        self.instante = None
        self._publicar()
        self.log.warning("Parada de emergencia rearmada")

    def _publicar(self) -> None:
        if self.publicador is not None:
            self.publicador.publish(Bool(data=self.activa))

    def _ruta_parada(self, peticion) -> Dict[str, Any]:
        self.activar(str(peticion.json().get("motivo") or "Pulsada en el HMI"))
        return self.estado()

    def _ruta_rearme(self, peticion) -> Dict[str, Any]:
        self.rearmar()
        return self.estado()

    def info(self) -> Dict[str, Any]:
        return {"tecla_parada": self.cfg.get("tecla_parada", "Escape"),
                "desactivar_controladores": bool(self.cfg.get("desactivar_controladores", True))}

    def estado(self) -> Dict[str, Any]:
        return {"activa": self.activa, "motivo": self.motivo, "instante": self.instante}
