"""Arranque y parada del sistema (botones Iniciar/Detener) con los perfiles de la config.

Un perfil es un comando fijo (p. ej. `ros2 launch ... sim_301.launch.py`). Solo puede haber
un perfil principal en marcha; los perfiles con `paralelo: true` (cámaras simuladas...)
pueden convivir con él. Si el robot se lanzó por otro lado (terminal, launcher.sh), el
estado lo indica como "externo".

Rutas:
  GET  /api/sistema
  POST /api/sistema/iniciar   {perfil}
  POST /api/sistema/detener   {perfil?}       (sin perfil: el principal)
  GET  /api/sistema/salida?perfil=id&desde=N
"""

from typing import Any, Dict, Optional

from openarm_hmi.nucleo.modulo import Modulo, requerir
from openarm_hmi.nucleo.procesos import Proceso
from openarm_hmi.nucleo.servidor import ErrorHmi


class Sistema(Modulo):
    nombre = "sistema"

    def iniciar(self) -> None:
        cfg = self.config.seccion("sistema")
        self.tiempo_parada = float(cfg.get("tiempo_parada_s", 15))
        self.perfiles: Dict[str, Dict[str, Any]] = {}
        self.procesos: Dict[str, Proceso] = {}
        for perfil in cfg.get("perfiles", []) or []:
            id_perfil = str(perfil["id"])
            self.perfiles[id_perfil] = perfil
            self.procesos[id_perfil] = Proceso(
                id_perfil, perfil.get("nombre", id_perfil),
                [str(c) for c in perfil["comando"]], self.bus, self.log, tipo="sistema")

        self.ruta("GET", "/api/sistema", lambda p: self.estado())
        self.ruta("POST", "/api/sistema/iniciar", self._ruta_iniciar)
        self.ruta("POST", "/api/sistema/detener", self._ruta_detener)
        self.ruta("GET", "/api/sistema/salida", self._ruta_salida)

    def detener(self) -> None:
        for proceso in self.procesos.values():
            proceso.detener(self.tiempo_parada, bloquear=True)

    def principal(self) -> Optional[Proceso]:
        for id_perfil, proceso in self.procesos.items():
            if proceso.vivo and not self.perfiles[id_perfil].get("paralelo"):
                return proceso
        return None

    def _perfil(self, id_perfil: str) -> Proceso:
        if id_perfil not in self.procesos:
            raise ErrorHmi(f"Perfil desconocido: {id_perfil}", 404)
        return self.procesos[id_perfil]

    def _ruta_iniciar(self, peticion) -> Dict[str, Any]:
        id_perfil = str(requerir(peticion.json(), "perfil"))
        proceso = self._perfil(id_perfil)
        if proceso.vivo:
            raise ErrorHmi(f"{proceso.nombre} ya está en marcha", 409)
        if not self.perfiles[id_perfil].get("paralelo"):
            actual = self.principal()
            if actual is not None:
                raise ErrorHmi(f"Ya está en marcha {actual.nombre}: detenlo antes", 409)
            if self._externo():
                raise ErrorHmi("Ya hay un robot lanzado fuera del HMI (controller_manager o "
                               "move_group activos). Páralo antes desde su terminal.", 409)
        try:
            proceso.iniciar()
        except (OSError, RuntimeError) as e:
            raise ErrorHmi(f"No se pudo iniciar {proceso.nombre}: {e}", 500) from e
        self.log.info(f"Sistema: iniciado '{proceso.nombre}'")
        return self.estado()

    def _ruta_detener(self, peticion) -> Dict[str, Any]:
        id_perfil = peticion.json().get("perfil")
        proceso = self._perfil(str(id_perfil)) if id_perfil else self.principal()
        if proceso is None or not proceso.vivo:
            raise ErrorHmi("No hay ningún sistema en marcha lanzado desde el HMI", 409)
        movimiento = self.ctx.modulo("movimiento")
        if movimiento is not None and not self.perfiles[proceso.id].get("paralelo"):
            movimiento.parar(None, "Parada del sistema")
        proceso.detener(self.tiempo_parada)
        self.log.info(f"Sistema: deteniendo '{proceso.nombre}'")
        return self.estado()

    def _ruta_salida(self, peticion) -> Dict[str, Any]:
        proceso = self._perfil(str(peticion.q("perfil", "")))
        try:
            desde = int(peticion.q("desde", 0))
        except ValueError:
            desde = 0
        return {"perfil": proceso.id, "lineas": proceso.lineas(desde)}

    def _externo(self) -> bool:
        estado = self.ctx.modulo("estado")
        if estado is None:
            return False
        robot = self.config.datos["robot"]
        return (estado.nodo_activo(robot.get("gestor_controladores", "/controller_manager"))
                or estado.nodo_activo(robot.get("nodo_move_group", "move_group")))

    def info(self) -> Dict[str, Any]:
        return {"perfiles": [{"id": i, "nombre": p.get("nombre", i),
                              "descripcion": p.get("descripcion", ""),
                              "confirmar": p.get("confirmar", ""),
                              "paralelo": bool(p.get("paralelo")),
                              "comando": " ".join(str(c) for c in p["comando"])}
                             for i, p in self.perfiles.items()]}

    def estado(self) -> Dict[str, Any]:
        principal = self.principal()
        return {
            "principal": principal.id if principal else None,
            "externo": principal is None and self._externo(),
            "procesos": {i: p.a_dict() for i, p in self.procesos.items()},
        }
