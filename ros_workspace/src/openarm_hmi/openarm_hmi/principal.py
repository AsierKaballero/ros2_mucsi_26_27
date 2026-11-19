"""Nodo `hmi_servidor`: servidor web del HMI del OpenArm.

    ros2 run openarm_hmi hmi_servidor --ros-args -p cuerpo:=301 -p puerto:=8080

Parámetros (vacíos = valor de la configuración):
  config            ruta del YAML (por defecto share/openarm_hmi/config/openarm.yaml)
  cuerpo            301 / 302
  host, puerto      dirección de escucha del servidor web
  directorio_datos  carpeta de capturas y poses guardadas
"""

import os
import queue
import signal
import threading
import time
import traceback
from typing import Any, Dict

import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.signals import SignalHandlerOptions

from openarm_hmi.modulos import MODULOS
from openarm_hmi.nucleo.configuracion import cargar
from openarm_hmi.nucleo.eventos import Bus
from openarm_hmi.nucleo.modulo import Contexto
from openarm_hmi.nucleo.servidor import Enrutador, Flujo, Servidor
from openarm_hmi.nucleo.tareas import GestorTareas

VERSION = "0.1.0"


class Aplicacion:
    def __init__(self, nodo: Node) -> None:
        self.nodo = nodo
        self.log = nodo.get_logger()
        compartido = get_package_share_directory("openarm_hmi")
        self.dir_web = os.path.join(compartido, "web")

        nodo.declare_parameter("config", os.path.join(compartido, "config", "openarm.yaml"))
        nodo.declare_parameter("cuerpo", "")
        nodo.declare_parameter("host", "")
        nodo.declare_parameter("puerto", 0)
        nodo.declare_parameter("directorio_datos", "")
        parametro = lambda n: nodo.get_parameter(n).value  # noqa: E731

        self.config = cargar(
            parametro("config"), str(parametro("cuerpo")) or None,
            {"servidor.host": parametro("host"), "servidor.puerto": parametro("puerto") or None,
             "datos.directorio": parametro("directorio_datos")})

        self.bus = Bus(self.log)
        self.tareas = GestorTareas(self.bus, self.log)
        self.enrutador = Enrutador()
        self.ctx = Contexto(nodo, self.config, self.bus, self.tareas, self.enrutador)
        self._cargar_modulos()

        self.enrutador.agregar("GET", "/api/config", lambda p: self.info())
        self.enrutador.agregar("GET", "/api/estado", lambda p: self.instantanea())
        self.enrutador.agregar("GET", "/api/eventos", lambda p: Flujo("text/event-stream",
                                                                      self._sse))
        self.enrutador.agregar("GET", "/api/rutas", lambda p: self.enrutador.listado())
        self.enrutador.agregar("GET", "/api/tareas", lambda p: {
            "activas": self.tareas.activas(), "historial": self.tareas.historial()})

    def _cargar_modulos(self) -> None:
        for nombre in self.config.seccion("modulos", list(MODULOS)):
            clase = MODULOS.get(nombre)
            if clase is None:
                self.log.error(f"Módulo desconocido en la configuración: '{nombre}'")
                continue
            try:
                modulo = clase(self.ctx)
                self.ctx.modulos[nombre] = modulo
                modulo.iniciar()
            except Exception:  # noqa: BLE001 - un módulo roto no debe tumbar el HMI
                self.ctx.modulos.pop(nombre, None)
                self.log.error(f"No se pudo iniciar el módulo '{nombre}':\n"
                               f"{traceback.format_exc()}")
        self.log.info(f"Módulos activos: {', '.join(self.ctx.modulos)}")

    # --- Información y estado ---------------------------------------------------------

    def info(self) -> Dict[str, Any]:
        estado = self.ctx.modulo("estado")
        robot = estado.info() if estado else {
            "cuerpo": self.config.cuerpo, "brazos": [b.a_dict() for b in self.config.brazos]}
        modulos = {}
        for nombre, modulo in self.ctx.modulos.items():
            try:
                modulos[nombre] = modulo.info() or {}
            except Exception as e:  # noqa: BLE001
                modulos[nombre] = {"error": str(e)}
        return {"version": VERSION, "robot": robot, "modulos": modulos}

    def instantanea(self) -> Dict[str, Any]:
        datos: Dict[str, Any] = {"t": time.time()}
        for nombre, modulo in self.ctx.modulos.items():
            try:
                valor = modulo.estado()
            except Exception as e:  # noqa: BLE001
                valor = {"error": str(e)}
            if valor is not None:
                datos[nombre] = valor
        return datos

    def _sse(self, escribir) -> None:
        cola = self.bus.nuevo_cliente()
        try:
            escribir(b"retry: 2000\n\n")
            while True:
                try:
                    mensaje = cola.get(timeout=15.0)
                except queue.Empty:
                    escribir(b": ping\n\n")
                    continue
                escribir(mensaje.encode("utf-8"))
        finally:
            self.bus.quitar_cliente(cola)

    def difundir_estado(self, parar: threading.Event) -> None:
        periodo = 1.0 / float(self.config.seccion("servidor").get("frecuencia_estado_hz", 15))
        while not parar.wait(periodo):
            if self.bus.num_clientes:
                try:
                    self.bus.enviar_navegador("estado", self.instantanea())
                except Exception:  # noqa: BLE001
                    self.log.error(f"Error al difundir el estado:\n{traceback.format_exc()}")

    def detener_modulos(self) -> None:
        for nombre, modulo in reversed(list(self.ctx.modulos.items())):
            try:
                modulo.detener()
            except Exception:  # noqa: BLE001
                self.log.error(f"Error al detener '{nombre}':\n{traceback.format_exc()}")


def main(args=None) -> None:
    # Las señales se gestionan aquí para cerrar el servidor web y los procesos hijo en orden
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    nodo = Node("openarm_hmi")
    app = Aplicacion(nodo)

    ejecutor = MultiThreadedExecutor(num_threads=8)
    ejecutor.add_node(nodo)
    threading.Thread(target=ejecutor.spin, daemon=True, name="ejecutor").start()

    parar = threading.Event()
    threading.Thread(target=app.difundir_estado, args=(parar,), daemon=True,
                     name="difusion").start()

    servidor_cfg = app.config.seccion("servidor")
    host = str(servidor_cfg.get("host", "127.0.0.1"))
    puerto = int(servidor_cfg.get("puerto", 8080))
    try:
        servidor = Servidor(host, puerto, app.enrutador, app.dir_web, nodo.get_logger())
    except OSError as e:
        nodo.get_logger().fatal(f"No se pudo abrir {host}:{puerto}: {e}")
        app.detener_modulos()
        ejecutor.shutdown()
        nodo.destroy_node()
        rclpy.try_shutdown()
        raise SystemExit(1) from e

    def al_recibir_senal(numero, marco) -> None:
        if not parar.is_set():
            parar.set()
            # shutdown() bloquea hasta que serve_forever termina: desde otro hilo
            threading.Thread(target=servidor.parar, daemon=True).start()

    signal.signal(signal.SIGINT, al_recibir_senal)
    signal.signal(signal.SIGTERM, al_recibir_senal)

    visible = "localhost" if host in ("0.0.0.0", "127.0.0.1") else host
    nodo.get_logger().info(
        f"HMI de {app.config.datos['robot'].get('nombre', '')} en http://{visible}:{puerto} "
        f"(escuchando en {host})")
    try:
        servidor.servir()
    finally:
        parar.set()
        nodo.get_logger().info("Cerrando el HMI...")
        app.detener_modulos()
        ejecutor.shutdown(timeout_sec=2.0)
        nodo.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
