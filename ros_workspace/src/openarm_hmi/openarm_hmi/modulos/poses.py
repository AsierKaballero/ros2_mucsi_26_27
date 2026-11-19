"""Poses con nombre: predefinidas (config, solo lectura) y guardadas desde el HMI.

Las poses guardadas se escriben en <datos>/poses.yaml indexadas por sufijo de brazo
(izq/der), así que sirven para cualquier cuerpo (301 o 302).

Rutas:
  GET    /api/poses
  POST   /api/poses                 {nombre, brazo, descripcion?}  guarda la pose actual
  POST   /api/poses/{nombre}/ir     {brazo}                         brazo admite "ambos"
  DELETE /api/poses/{nombre}
  GET    /api/poses/exportar        poses.yaml para descargar
"""

import datetime
import os
import re
import threading
from typing import Any, Dict, List

import yaml

from openarm_hmi.nucleo.modulo import Modulo, requerir
from openarm_hmi.nucleo.servidor import ErrorHmi, Respuesta

NOMBRE_VALIDO = re.compile(r"^[\w .\-áéíóúñÁÉÍÓÚÑ]{1,40}$")


class Poses(Modulo):
    nombre = "poses"

    def iniciar(self) -> None:
        self.movimiento = self.ctx.modulo("movimiento")
        self.estado_robot = self.ctx.modulo("estado")
        self.fichero = os.path.join(self.config.directorio_datos, "poses.yaml")
        self._candado = threading.Lock()
        self.predefinidas = self._cargar_predefinidas()
        self.guardadas = self._leer()

        self.ruta("GET", "/api/poses", lambda p: self.listado())
        self.ruta("GET", "/api/poses/exportar", self._ruta_exportar)
        self.ruta("POST", "/api/poses", self._ruta_guardar)
        self.ruta("POST", "/api/poses/{nombre}/ir", self._ruta_ir)
        self.ruta("DELETE", "/api/poses/{nombre}", self._ruta_borrar)

    # --- Persistencia -----------------------------------------------------------------

    def _cargar_predefinidas(self) -> List[Dict[str, Any]]:
        poses = []
        sufijos = [b.sufijo for b in self.config.brazos]
        for entrada in self.config.seccion("poses_predefinidas", []):
            if "por_brazo" in entrada:
                articulaciones = {s: list(entrada["por_brazo"][s])
                                  for s in sufijos if s in entrada["por_brazo"]}
            else:
                articulaciones = {s: list(entrada["articulaciones"]) for s in sufijos}
            poses.append({"nombre": str(entrada["nombre"]),
                          "descripcion": entrada.get("descripcion", ""),
                          "articulaciones": articulaciones, "predefinida": True})
        return poses

    def _leer(self) -> List[Dict[str, Any]]:
        if not os.path.isfile(self.fichero):
            return []
        try:
            with open(self.fichero, encoding="utf-8") as f:
                datos = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as e:
            self.log.error(f"No se pudo leer {self.fichero}: {e}")
            return []
        poses = []
        for p in datos.get("poses", []):
            p["predefinida"] = False
            poses.append(p)
        return poses

    def _escribir(self) -> None:
        os.makedirs(os.path.dirname(self.fichero), exist_ok=True)
        datos = {"poses": [{k: v for k, v in p.items() if k != "predefinida"}
                           for p in self.guardadas]}
        temporal = self.fichero + ".tmp"
        with open(temporal, "w", encoding="utf-8") as f:
            f.write("# Poses guardadas desde el HMI (articulaciones en radianes, por sufijo de brazo)\n")
            yaml.safe_dump(datos, f, sort_keys=False, allow_unicode=True)
        os.replace(temporal, self.fichero)

    # --- Operaciones ------------------------------------------------------------------

    def listado(self) -> Dict[str, Any]:
        return {"poses": self.predefinidas + self.guardadas, "fichero": self.fichero}

    def buscar(self, nombre: str) -> Dict[str, Any]:
        for pose in self.guardadas + self.predefinidas:
            if pose["nombre"] == nombre:
                return pose
        raise ErrorHmi(f"Pose desconocida: {nombre}", 404)

    def guardar(self, nombre: str, objetivo: str, descripcion: str = "") -> Dict[str, Any]:
        nombre = nombre.strip()
        if not NOMBRE_VALIDO.match(nombre):
            raise ErrorHmi("Nombre inválido (1-40 caracteres: letras, números, espacio, . _ -)")
        if any(p["nombre"] == nombre for p in self.predefinidas):
            raise ErrorHmi(f"'{nombre}' es una pose predefinida")
        brazos = self.movimiento.brazos_de(objetivo)
        articulaciones = {b.sufijo: [round(v, 5) for v in
                                     self.estado_robot.posiciones(b.articulaciones)]
                          for b in brazos}
        pose = {"nombre": nombre, "descripcion": descripcion,
                "articulaciones": articulaciones,
                "creada": datetime.datetime.now().isoformat(timespec="seconds"),
                "predefinida": False}
        with self._candado:
            self.guardadas = [p for p in self.guardadas if p["nombre"] != nombre] + [pose]
            self._escribir()
        self.log.info(f"Pose '{nombre}' guardada ({', '.join(articulaciones)})")
        return pose

    def ir(self, nombre: str, objetivo: str) -> Dict[str, Any]:
        pose = self.buscar(nombre)
        brazos = self.movimiento.brazos_de(objetivo)
        destino: Dict[str, float] = {}
        for brazo in brazos:
            valores = pose["articulaciones"].get(brazo.sufijo)
            if valores is None:
                raise ErrorHmi(f"La pose '{nombre}' no tiene valores para {brazo.nombre}")
            if len(valores) != len(brazo.articulaciones):
                raise ErrorHmi(f"La pose '{nombre}' no tiene {len(brazo.articulaciones)} valores")
            destino.update(zip(brazo.articulaciones, (float(v) for v in valores)))
        quien = brazos[0].nombre if len(brazos) == 1 else "Ambos brazos"
        return self.movimiento.mover_articulaciones(brazos, destino, f"{quien}: pose '{nombre}'",
                                                    tipo="pose")

    def borrar(self, nombre: str) -> None:
        if any(p["nombre"] == nombre for p in self.predefinidas):
            raise ErrorHmi("Las poses predefinidas se cambian en config/openarm.yaml")
        with self._candado:
            antes = len(self.guardadas)
            self.guardadas = [p for p in self.guardadas if p["nombre"] != nombre]
            if len(self.guardadas) == antes:
                raise ErrorHmi(f"Pose desconocida: {nombre}", 404)
            self._escribir()

    # --- Rutas ------------------------------------------------------------------------

    def _ruta_guardar(self, peticion) -> Dict[str, Any]:
        datos = peticion.json()
        return self.guardar(str(requerir(datos, "nombre")), str(requerir(datos, "brazo")),
                            str(datos.get("descripcion", "")))

    def _ruta_ir(self, peticion) -> Dict[str, Any]:
        return self.ir(peticion.params["nombre"], str(requerir(peticion.json(), "brazo")))

    def _ruta_borrar(self, peticion) -> None:
        self.borrar(peticion.params["nombre"])

    def _ruta_exportar(self, peticion) -> Respuesta:
        datos = {"poses": [{k: v for k, v in p.items() if k != "predefinida"}
                           for p in self.predefinidas + self.guardadas]}
        texto = yaml.safe_dump(datos, sort_keys=False, allow_unicode=True)
        return Respuesta(texto.encode("utf-8"), "text/yaml; charset=utf-8", 200,
                         {"Content-Disposition": 'attachment; filename="poses.yaml"'})
