"""Procesos hijo (ros2 launch, ros2 run, scripts) gestionados desde el HMI.

Cada proceso se lanza en su propio grupo de procesos para poder pararlo con todos sus
hijos (ros2 launch arranca varios nodos), primero con SIGINT (como Ctrl+C) y, si no
termina a tiempo, con SIGTERM y SIGKILL. La salida se guarda en un buffer circular y
cada línea se envía a los navegadores como evento "proceso".
"""

import os
import signal
import subprocess
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional

PARADO = "parado"
EN_MARCHA = "en_marcha"
DETENIENDO = "deteniendo"
TERMINADO = "terminado"
FALLIDO = "fallido"


class Proceso:
    def __init__(self, id_proceso: str, nombre: str, comando: List[str], bus,
                 registrador, tipo: str = "", lineas_max: int = 3000) -> None:
        self.id = id_proceso
        self.tipo = tipo  # Módulo dueño ("sistema", "scripts"...): distingue ids repetidos
        self.nombre = nombre
        self.comando = comando
        self.bus = bus
        self.log = registrador
        self.salida: deque = deque(maxlen=lineas_max)
        self._contador = 0
        self._popen: Optional[subprocess.Popen] = None
        self._candado = threading.Lock()
        self.estado = PARADO
        self.codigo: Optional[int] = None
        self.inicio: Optional[float] = None
        self.fin: Optional[float] = None

    @property
    def vivo(self) -> bool:
        return self._popen is not None and self._popen.poll() is None

    def iniciar(self) -> None:
        with self._candado:
            if self.vivo:
                raise RuntimeError(f"{self.nombre} ya está en marcha")
            entorno = dict(os.environ, PYTHONUNBUFFERED="1", RCUTILS_COLORIZED_OUTPUT="0")
            self.salida.clear()
            self._contador = 0
            self._agregar(f"$ {' '.join(self.comando)}")
            self._popen = subprocess.Popen(
                self.comando,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=entorno,
                start_new_session=True,  # Grupo propio: se para con todos sus hijos
                bufsize=1,
                text=True,
                errors="replace",
            )
            self.estado = EN_MARCHA
            self.codigo = None
            self.inicio = time.time()
            self.fin = None
        threading.Thread(target=self._leer, args=(self._popen,), daemon=True,
                         name=f"salida-{self.id}").start()
        self._emitir_estado()

    def detener(self, espera_s: float = 10.0, bloquear: bool = False) -> None:
        """Para el proceso (SIGINT → SIGTERM → SIGKILL). Sin `bloquear` lo hace en segundo plano."""
        popen = self._popen
        if popen is None or popen.poll() is not None:
            return
        self.estado = DETENIENDO
        self._emitir_estado()
        hilo = threading.Thread(target=self._detener, args=(popen, espera_s), daemon=True)
        hilo.start()
        if bloquear:
            hilo.join()

    def _detener(self, popen: subprocess.Popen, espera_s: float) -> None:
        for senal, espera in ((signal.SIGINT, espera_s), (signal.SIGTERM, 5.0),
                              (signal.SIGKILL, 2.0)):
            try:
                os.killpg(popen.pid, senal)
            except (ProcessLookupError, PermissionError):
                return
            try:
                popen.wait(timeout=espera)
                return
            except subprocess.TimeoutExpired:
                self._agregar(f"[HMI] El proceso no terminó con {senal.name}; se insiste")

    def _leer(self, popen: subprocess.Popen) -> None:
        assert popen.stdout is not None
        for linea in popen.stdout:
            self._agregar(linea.rstrip("\n"))
        codigo = popen.wait()
        with self._candado:
            if popen is not self._popen:
                return
            self.codigo = codigo
            self.fin = time.time()
            # -2 (SIGINT) y 0 son finales normales tras pedir la parada
            self.estado = TERMINADO if codigo in (0, -2, -15, 130) else FALLIDO
        self._agregar(f"[HMI] Proceso terminado (código {codigo})")
        self._emitir_estado()

    def _agregar(self, linea: str) -> None:
        self._contador += 1
        self.salida.append((self._contador, linea))
        self.bus.emitir("proceso", {"tipo": self.tipo, "id": self.id, "n": self._contador,
                                    "linea": linea})

    def lineas(self, desde: int = 0) -> List[Dict[str, Any]]:
        return [{"n": n, "linea": linea} for n, linea in list(self.salida) if n > desde]

    def a_dict(self) -> Dict[str, Any]:
        return {
            "tipo": self.tipo,
            "id": self.id,
            "nombre": self.nombre,
            "estado": self.estado,
            "codigo": self.codigo,
            "pid": self._popen.pid if self.vivo and self._popen else None,
            "inicio": self.inicio,
            "fin": self.fin,
            "comando": self.comando,
        }

    def _emitir_estado(self) -> None:
        self.bus.emitir("proceso_estado", self.a_dict())
