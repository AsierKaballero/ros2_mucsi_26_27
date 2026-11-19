"""Registro: mensajes de /rosout de todos los nodos (incluido el propio HMI).

Rutas:
  GET /api/registro?desde=N    últimas entradas (las posteriores a N)
"""

import threading
from collections import deque
from typing import Any, Dict, List

from rcl_interfaces.msg import Log
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

from openarm_hmi.nucleo.modulo import Modulo

NIVELES = {10: "DEBUG", 20: "INFO", 30: "WARN", 40: "ERROR", 50: "FATAL"}


class Registro(Modulo):
    nombre = "registro"

    def iniciar(self) -> None:
        self._entradas: deque = deque(maxlen=2000)
        self._contador = 0
        self._candado = threading.Lock()
        qos = QoSProfile(depth=200, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.VOLATILE)
        self.nodo.create_subscription(Log, "/rosout", self._cb, qos,
                                      callback_group=self.ctx.grupo_callbacks)
        self.ruta("GET", "/api/registro", self._ruta_registro)

    def _cb(self, msg: Log) -> None:
        nivel = msg.level if isinstance(msg.level, int) else ord(msg.level)
        with self._candado:
            self._contador += 1
            entrada = {
                "n": self._contador,
                "t": msg.stamp.sec + msg.stamp.nanosec * 1e-9,
                "nivel": NIVELES.get(nivel, str(nivel)),
                "nodo": msg.name,
                "texto": msg.msg,
                "fichero": f"{msg.file}:{msg.line}" if msg.file else "",
            }
            self._entradas.append(entrada)
        self.bus.enviar_navegador("log", entrada)

    def entradas(self, desde: int = 0) -> List[Dict[str, Any]]:
        with self._candado:
            return [e for e in self._entradas if e["n"] > desde]

    def _ruta_registro(self, peticion) -> Dict[str, Any]:
        try:
            desde = int(peticion.q("desde", 0))
        except ValueError:
            desde = 0
        return {"entradas": self.entradas(desde)}
