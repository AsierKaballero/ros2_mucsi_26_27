"""Scripts de prueba ejecutables desde el HMI, definidos en la configuración.

Cada script es un comando fijo con parámetros tipados que se validan antes de sustituirse
(nunca se pasa por una shell). Solo puede haber un script en marcha a la vez, y la parada
de emergencia los detiene.

Tipos de parámetro: brazo, brazos (admite "ambos"), numero (min, max), opcion (opciones),
texto (solo [A-Za-z0-9_.-]). Variables extra en el comando: {cuerpo} y {velocidad}
(la menor de las velocidades actuales de los brazos).

Rutas:
  GET  /api/scripts
  POST /api/scripts/{id}/ejecutar   {parametros: {...}}
  POST /api/scripts/{id}/detener
  GET  /api/scripts/{id}/salida?desde=N
"""

import math
import re
from typing import Any, Dict, List

from openarm_hmi.nucleo.configuracion import rellenar
from openarm_hmi.nucleo.modulo import Modulo
from openarm_hmi.nucleo.procesos import Proceso
from openarm_hmi.nucleo.servidor import ErrorHmi

TEXTO_VALIDO = re.compile(r"^[\w.\-]{0,64}$")


class Scripts(Modulo):
    nombre = "scripts"

    def iniciar(self) -> None:
        self.definiciones: Dict[str, Dict[str, Any]] = {}
        self.procesos: Dict[str, Proceso] = {}
        for definicion in self.config.seccion("scripts", []) or []:
            id_script = str(definicion["id"])
            self.definiciones[id_script] = definicion
            self.procesos[id_script] = Proceso(id_script, definicion.get("nombre", id_script),
                                               [], self.bus, self.log, tipo="scripts")

        if self.config.seccion("seguridad").get("detener_scripts", True):
            self.bus.suscribir("parada_emergencia", lambda datos: self.detener_todos(1.0))

        self.ruta("GET", "/api/scripts", lambda p: self.listado())
        self.ruta("POST", "/api/scripts/{id}/ejecutar", self._ruta_ejecutar)
        self.ruta("POST", "/api/scripts/{id}/detener", self._ruta_detener)
        self.ruta("GET", "/api/scripts/{id}/salida", self._ruta_salida)

    def detener(self) -> None:
        self.detener_todos(3.0, bloquear=True)

    def detener_todos(self, espera_s: float, bloquear: bool = False) -> None:
        for proceso in self.procesos.values():
            proceso.detener(espera_s, bloquear=bloquear)

    # --- Parámetros -------------------------------------------------------------------

    def _opciones_brazo(self, admite_ambos: bool) -> List[str]:
        return self.config.ids_brazos + (["ambos"] if admite_ambos else [])

    def validar(self, definicion: Dict[str, Any], valores: Dict[str, Any]) -> Dict[str, str]:
        resultado: Dict[str, str] = {}
        for parametro in definicion.get("parametros", []) or []:
            nombre = parametro["nombre"]
            tipo = parametro.get("tipo", "texto")
            valor = valores.get(nombre, parametro.get("defecto"))
            if valor is None:
                raise ErrorHmi(f"Falta el parámetro '{nombre}'")
            if tipo in ("brazo", "brazos"):
                valor = str(valor)
                if valor not in self._opciones_brazo(tipo == "brazos"):
                    raise ErrorHmi(f"'{nombre}': brazo inválido ({valor})")
                if valor == "ambos":
                    valor = ",".join(self.config.ids_brazos)
            elif tipo == "numero":
                try:
                    numero = float(valor)
                except (TypeError, ValueError) as e:
                    raise ErrorHmi(f"'{nombre}' debe ser un número") from e
                if not math.isfinite(numero):
                    raise ErrorHmi(f"'{nombre}' debe ser un número finito")
                if "min" in parametro and numero < float(parametro["min"]):
                    raise ErrorHmi(f"'{nombre}' debe ser ≥ {parametro['min']}")
                if "max" in parametro and numero > float(parametro["max"]):
                    raise ErrorHmi(f"'{nombre}' debe ser ≤ {parametro['max']}")
                valor = f"{numero:g}"
            elif tipo == "opcion":
                if str(valor) not in [str(o) for o in parametro.get("opciones", [])]:
                    raise ErrorHmi(f"'{nombre}': opción inválida ({valor})")
                valor = str(valor)
            else:
                valor = str(valor)
                if not TEXTO_VALIDO.match(valor):
                    raise ErrorHmi(f"'{nombre}': solo letras, números, '.', '_' y '-'")
            resultado[nombre] = valor
        return resultado

    def _velocidad(self) -> str:
        movimiento = self.ctx.modulo("movimiento")
        if movimiento is None:
            return "0.1"
        return f"{min(movimiento.velocidades.values()):g}"

    # --- Rutas ------------------------------------------------------------------------

    def listado(self) -> Dict[str, Any]:
        scripts = []
        for id_script, d in self.definiciones.items():
            parametros = []
            for p in d.get("parametros", []) or []:
                entrada = dict(p)
                if p.get("tipo") in ("brazo", "brazos"):
                    entrada["opciones"] = self._opciones_brazo(p.get("tipo") == "brazos")
                parametros.append(entrada)
            scripts.append({"id": id_script, "nombre": d.get("nombre", id_script),
                            "descripcion": d.get("descripcion", ""),
                            "parametros": parametros,
                            "proceso": self.procesos[id_script].a_dict()})
        return {"scripts": scripts}

    def _ruta_ejecutar(self, peticion) -> Dict[str, Any]:
        id_script = peticion.params["id"]
        if id_script not in self.definiciones:
            raise ErrorHmi(f"Script desconocido: {id_script}", 404)
        self.ctx.comprobar_movimiento_permitido()
        en_marcha = [p.nombre for p in self.procesos.values() if p.vivo]
        if en_marcha:
            raise ErrorHmi(f"Ya hay un script en marcha: {en_marcha[0]}", 409)
        definicion = self.definiciones[id_script]
        valores = self.validar(definicion, peticion.json().get("parametros", {}) or {})
        variables = {"cuerpo": self.config.cuerpo, "velocidad": self._velocidad(), **valores}
        comando = [str(rellenar(str(c), variables)) for c in definicion["comando"]]
        proceso = self.procesos[id_script]
        proceso.comando = comando
        try:
            proceso.iniciar()
        except (OSError, RuntimeError) as e:
            raise ErrorHmi(f"No se pudo ejecutar: {e}", 500) from e
        self.log.info(f"Script '{proceso.nombre}' iniciado: {' '.join(comando)}")
        return proceso.a_dict()

    def _ruta_detener(self, peticion) -> Dict[str, Any]:
        id_script = peticion.params["id"]
        if id_script not in self.procesos:
            raise ErrorHmi(f"Script desconocido: {id_script}", 404)
        self.procesos[id_script].detener(3.0)
        return self.procesos[id_script].a_dict()

    def _ruta_salida(self, peticion) -> Dict[str, Any]:
        id_script = peticion.params["id"]
        if id_script not in self.procesos:
            raise ErrorHmi(f"Script desconocido: {id_script}", 404)
        try:
            desde = int(peticion.q("desde", 0))
        except ValueError:
            desde = 0
        return {"id": id_script, "lineas": self.procesos[id_script].lineas(desde)}

    def estado(self) -> Dict[str, Any]:
        return {i: {"estado": p.estado, "codigo": p.codigo} for i, p in self.procesos.items()}
