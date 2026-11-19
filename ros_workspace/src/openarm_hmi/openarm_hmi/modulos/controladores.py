"""Controladores de ros2_control: listado, activación y desactivación.

Rutas:
  GET  /api/controladores
  POST /api/controladores/conmutar   {"activar": [...], "desactivar": [...]}
  POST /api/controladores/movimiento {"activo": true|false}   brazos + pinzas del cuerpo
"""

import threading
import time
from typing import Any, Dict, List

from controller_manager_msgs.srv import ListControllers, SwitchController
from rclpy.duration import Duration

from openarm_hmi.nucleo.modulo import Modulo, requerir
from openarm_hmi.nucleo.servidor import ErrorHmi


class Controladores(Modulo):
    nombre = "controladores"

    def iniciar(self) -> None:
        gestor = self.config.datos["robot"].get("gestor_controladores", "/controller_manager")
        grupo = self.ctx.grupo_callbacks
        self.cli_listar = self.nodo.create_client(
            ListControllers, f"{gestor}/list_controllers", callback_group=grupo)
        self.cli_conmutar = self.nodo.create_client(
            SwitchController, f"{gestor}/switch_controller", callback_group=grupo)
        self._lista: List[Dict[str, Any]] = []
        self._actualizado = 0.0
        self._parar = threading.Event()
        threading.Thread(target=self._sondeo, daemon=True, name="controladores").start()

        self.bus.suscribir("parada_emergencia", self._en_parada)
        self.bus.suscribir("rearme", self._en_rearme)

        self.ruta("GET", "/api/controladores", lambda p: self.estado())
        self.ruta("POST", "/api/controladores/conmutar", self._ruta_conmutar)
        self.ruta("POST", "/api/controladores/movimiento", self._ruta_movimiento)

    def detener(self) -> None:
        self._parar.set()

    # --- Consulta periódica -----------------------------------------------------------

    def _sondeo(self) -> None:
        while not self._parar.wait(2.0):
            self.refrescar()

    def refrescar(self) -> None:
        if not self.cli_listar.service_is_ready():
            if self._lista:
                self._lista = []
            return
        respuesta = self._llamar(self.cli_listar, ListControllers.Request(), 2.0)
        if respuesta is None:
            return
        self._lista = [{"nombre": c.name, "estado": c.state, "tipo": c.type,
                        "interfaces": list(c.claimed_interfaces)}
                       for c in respuesta.controller]
        self._actualizado = time.time()

    @staticmethod
    def _llamar(cliente, peticion, timeout_s: float):
        evento = threading.Event()
        futuro = cliente.call_async(peticion)
        futuro.add_done_callback(lambda f: evento.set())
        if not evento.wait(timeout_s):
            futuro.cancel()
            return None
        return futuro.result()

    # --- Conmutación ------------------------------------------------------------------

    def controladores_movimiento(self) -> List[str]:
        nombres = []
        for brazo in self.config.brazos:
            nombres += [brazo.controlador_trayectoria, brazo.controlador_pinza]
        return [n for n in nombres if n]

    def conmutar(self, activar: List[str], desactivar: List[str],
                 esperar: bool = True) -> bool:
        if not self.cli_conmutar.service_is_ready():
            raise ErrorHmi("controller_manager no disponible (¿está lanzado el robot?)", 503)
        existentes = {c["nombre"]: c["estado"] for c in self._lista}
        if existentes:
            activar = [c for c in activar if existentes.get(c, "active") != "active"]
            desactivar = [c for c in desactivar if existentes.get(c) == "active"]
        if not activar and not desactivar:
            return True
        peticion = SwitchController.Request()
        peticion.activate_controllers = activar
        peticion.deactivate_controllers = desactivar
        peticion.strictness = SwitchController.Request.BEST_EFFORT
        peticion.activate_asap = True
        peticion.timeout = Duration(seconds=5.0).to_msg()
        if not esperar:
            self.cli_conmutar.call_async(peticion)
            return True
        respuesta = self._llamar(self.cli_conmutar, peticion, 6.0)
        threading.Thread(target=self.refrescar, daemon=True).start()
        if respuesta is None:
            raise ErrorHmi("El controller_manager no respondió a tiempo", 504)
        return bool(respuesta.ok)

    def _en_parada(self, datos) -> None:
        seguridad = self.config.seccion("seguridad")
        if not seguridad.get("desactivar_controladores", True):
            return

        def desactivar() -> None:
            try:
                # Sin esperar: la parada no puede quedarse bloqueada por un servicio lento
                self.conmutar([], self.controladores_movimiento(), esperar=False)
            except ErrorHmi:
                pass
            threading.Timer(1.0, self.refrescar).start()

        # Breve espera para que antes llegue a los controladores la orden de mantener la
        # posición (módulo movimiento) y las cancelaciones de los objetivos en curso
        threading.Timer(0.2, desactivar).start()

    def _en_rearme(self, datos) -> None:
        seguridad = self.config.seccion("seguridad")
        if not seguridad.get("desactivar_controladores", True):
            return
        try:
            if not self.conmutar(self.controladores_movimiento(), []):
                self.log.warning("No se pudieron reactivar todos los controladores")
        except ErrorHmi as e:
            self.log.warning(f"Rearme: {e.mensaje}")

    # --- Rutas ------------------------------------------------------------------------

    def _ruta_conmutar(self, peticion) -> Dict[str, Any]:
        datos = peticion.json()
        activar = [str(c) for c in datos.get("activar", [])]
        if activar:
            self.ctx.comprobar_movimiento_permitido()
        ok = self.conmutar(activar, [str(c) for c in datos.get("desactivar", [])])
        return {"ok": ok, **self.estado()}

    def _ruta_movimiento(self, peticion) -> Dict[str, Any]:
        activo = bool(requerir(peticion.json(), "activo"))
        if activo:
            self.ctx.comprobar_movimiento_permitido()
            ok = self.conmutar(self.controladores_movimiento(), [])
        else:
            movimiento = self.ctx.modulo("movimiento")
            if movimiento is not None:
                movimiento.parar(None)
            ok = self.conmutar([], self.controladores_movimiento())
        return {"ok": ok, **self.estado()}

    def estado(self) -> Dict[str, Any]:
        return {"disponible": self.cli_listar.service_is_ready(), "lista": self._lista,
                "actualizado": self._actualizado}
