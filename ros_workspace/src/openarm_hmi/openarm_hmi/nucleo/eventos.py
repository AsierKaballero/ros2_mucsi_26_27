"""Bus de eventos del servidor.

Sirve para dos cosas:
  - comunicar módulos sin que se conozcan (p. ej. la parada de emergencia emite
    "parada_emergencia" y cada módulo reacciona a su manera);
  - enviar eventos a los navegadores conectados por Server-Sent Events (/api/eventos).
"""

import json
import queue
import threading
import traceback
from collections import defaultdict
from typing import Any, Callable, Dict, List


class Bus:
    def __init__(self, registrador=None) -> None:
        self._oyentes: Dict[str, List[Callable[[Any], None]]] = defaultdict(list)
        self._clientes: List[queue.Queue] = []
        self._candado = threading.Lock()
        self._registrador = registrador

    # --- Oyentes internos -------------------------------------------------------------

    def suscribir(self, evento: str, funcion: Callable[[Any], None]) -> None:
        self._oyentes[evento].append(funcion)

    def emitir(self, evento: str, datos: Any = None, navegador: bool = True) -> None:
        """Llama a los oyentes de `evento` y, si `navegador`, lo envía por SSE."""
        for funcion in list(self._oyentes.get(evento, ())):
            try:
                funcion(datos)
            except Exception:  # Un módulo con fallos no debe tumbar a los demás
                if self._registrador:
                    self._registrador.error(
                        f"Error en un oyente de '{evento}':\n{traceback.format_exc()}")
        if navegador:
            self.enviar_navegador(evento, datos)

    # --- Navegadores (SSE) ------------------------------------------------------------

    def enviar_navegador(self, evento: str, datos: Any) -> None:
        mensaje = f"event: {evento}\ndata: {json.dumps(datos, separators=(',', ':'))}\n\n"
        with self._candado:
            clientes = list(self._clientes)
        for cola in clientes:
            try:
                cola.put_nowait(mensaje)
            except queue.Full:
                pass  # Navegador lento: se descartan eventos en lugar de bloquear

    def nuevo_cliente(self) -> queue.Queue:
        cola: queue.Queue = queue.Queue(maxsize=500)
        with self._candado:
            self._clientes.append(cola)
        return cola

    def quitar_cliente(self, cola: queue.Queue) -> None:
        with self._candado:
            if cola in self._clientes:
                self._clientes.remove(cola)

    @property
    def num_clientes(self) -> int:
        with self._candado:
            return len(self._clientes)
