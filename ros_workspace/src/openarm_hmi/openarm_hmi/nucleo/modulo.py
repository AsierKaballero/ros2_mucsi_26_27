"""Clase base de los módulos del HMI y contexto compartido.

Un módulo es una funcionalidad completa del servidor (movimiento, cámaras, scripts...).
Para añadir una funcionalidad nueva:

  1. Crea `openarm_hmi/modulos/mi_modulo.py` con una subclase de `Modulo`:

         class MiModulo(Modulo):
             nombre = "mi_modulo"

             def iniciar(self):
                 self.ruta("GET", "/api/mi_modulo/hola", self.hola)

             def hola(self, peticion):
                 return {"mensaje": "hola"}

             def estado(self):          # opcional: se envía ~15 veces/s al navegador
                 return {"contador": 1}

  2. Regístralo en `openarm_hmi/modulos/__init__.py` (diccionario MODULOS).
  3. Añade "mi_modulo" a la lista `modulos` de config/openarm.yaml.
  4. (Interfaz) crea `web/js/vistas/mi_vista.js` y regístrala en `web/js/vistas/indice.js`.

Los módulos se comunican sin importarse entre sí mediante el bus de eventos
(`self.bus.suscribir("parada_emergencia", ...)`) o pidiendo otro módulo por su nombre
(`self.ctx.modulo("movimiento")`), que puede ser None si no está activo.
"""

from typing import Any, Callable, Dict, Optional

from rclpy.callback_groups import ReentrantCallbackGroup

from openarm_hmi.nucleo.servidor import ErrorHmi


class Contexto:
    """Todo lo que comparten los módulos: nodo ROS, configuración, bus, tareas y rutas."""

    def __init__(self, nodo, config, bus, tareas, enrutador) -> None:
        self.nodo = nodo
        self.config = config
        self.bus = bus
        self.tareas = tareas
        self.enrutador = enrutador
        self.modulos: Dict[str, "Modulo"] = {}
        # Grupo reentrante para que los callbacks de acciones y servicios no se bloqueen
        self.grupo_callbacks = ReentrantCallbackGroup()

    def modulo(self, nombre: str) -> Optional["Modulo"]:
        return self.modulos.get(nombre)

    @property
    def log(self):
        return self.nodo.get_logger()

    def comprobar_movimiento_permitido(self) -> None:
        """Lanza ErrorHmi(409) si la parada de emergencia está activa."""
        seguridad = self.modulo("seguridad")
        if seguridad is not None and seguridad.activa:
            raise ErrorHmi("Parada de emergencia activa: rearma antes de mover el robot", 409)


class Modulo:
    nombre = "base"

    def __init__(self, ctx: Contexto) -> None:
        self.ctx = ctx
        self.nodo = ctx.nodo
        self.config = ctx.config
        self.bus = ctx.bus
        self.tareas = ctx.tareas
        self.log = ctx.log

    def ruta(self, metodo: str, patron: str, funcion: Callable) -> None:
        self.ctx.enrutador.agregar(metodo, patron, funcion)

    # --- Ganchos que pueden sobrescribir los módulos ----------------------------------

    def iniciar(self) -> None:
        """Crea suscripciones, clientes y rutas. Se llama una vez al arrancar."""

    def estado(self) -> Any:
        """Estado dinámico que se envía periódicamente al navegador (None = nada)."""
        return None

    def info(self) -> Any:
        """Información estática para la interfaz (se sirve en /api/config).

        Devuelve siempre un dict: la interfaz usa la presencia del módulo en
        config.modulos para saber qué vistas y controles mostrar."""
        return {}

    def detener(self) -> None:
        """Libera recursos al cerrar el servidor."""


def requerir(datos: Dict[str, Any], clave: str, tipo: type = None) -> Any:
    """Lee `clave` del JSON de una petición o lanza ErrorHmi(400)."""
    if clave not in datos:
        raise ErrorHmi(f"Falta el campo '{clave}'")
    valor = datos[clave]
    if tipo is not None:
        try:
            valor = tipo(valor)
        except (TypeError, ValueError) as e:
            raise ErrorHmi(f"Campo '{clave}' inválido: {e}") from e
    return valor
