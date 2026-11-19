"""Carga de la configuración YAML del HMI y resolución de las plantillas {cuerpo}/{brazo}.

No depende de ROS, así que se puede probar con pytest fuera del contenedor.
"""

import copy
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

_VARIABLE = re.compile(r"\{([a-z_]+)\}")


def rellenar(valor: Any, variables: Dict[str, str]) -> Any:
    """Sustituye {variable} en todas las cadenas de `valor` (recursivo).

    Las variables desconocidas se dejan tal cual, para resolverlas más tarde (por ejemplo
    {brazo} en la configuración global, o los parámetros de un script).
    """
    if isinstance(valor, str):
        return _VARIABLE.sub(lambda m: str(variables.get(m.group(1), m.group(0))), valor)
    if isinstance(valor, list):
        return [rellenar(v, variables) for v in valor]
    if isinstance(valor, dict):
        return {k: rellenar(v, variables) for k, v in valor.items()}
    return valor


@dataclass
class Pinza:
    accion: str
    articulacion: str
    anchura_maxima_mm: float
    rad_abierta: float
    esfuerzo: float

    def rad_a_mm(self, rad: float) -> float:
        """Anchura entre dedos (mm) a partir del ángulo de finger_joint1 (cualquier signo)."""
        return abs(rad) / self.rad_abierta * self.anchura_maxima_mm


@dataclass
class Brazo:
    id: str
    sufijo: str
    nombre: str
    articulaciones: List[str]
    grupo_moveit: str
    efector: str
    controlador_trayectoria: str
    controlador_pinza: str
    pinza: Pinza

    def a_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "sufijo": self.sufijo,
            "nombre": self.nombre,
            "articulaciones": self.articulaciones,
            "grupo_moveit": self.grupo_moveit,
            "efector": self.efector,
            "controlador_trayectoria": self.controlador_trayectoria,
            "controlador_pinza": self.controlador_pinza,
            "pinza": {
                "accion": self.pinza.accion,
                "articulacion": self.pinza.articulacion,
                "anchura_maxima_mm": self.pinza.anchura_maxima_mm,
                "esfuerzo": self.pinza.esfuerzo,
            },
        }


@dataclass
class Configuracion:
    """Configuración resuelta. `datos` contiene el YAML completo (con {cuerpo} sustituido)."""

    datos: Dict[str, Any]
    cuerpo: str
    brazos: List[Brazo] = field(default_factory=list)

    def seccion(self, nombre: str, defecto: Any = None) -> Any:
        valor = self.datos.get(nombre)
        if valor is None:
            return {} if defecto is None else defecto
        return valor

    def brazo(self, id_brazo: str) -> Brazo:
        for b in self.brazos:
            if b.id == id_brazo or b.sufijo == id_brazo:
                return b
        raise KeyError(id_brazo)

    @property
    def ids_brazos(self) -> List[str]:
        return [b.id for b in self.brazos]

    @property
    def grupo_conjunto(self) -> str:
        return self.datos["robot"]["grupo_conjunto"]

    @property
    def marco_referencia(self) -> str:
        return self.datos["robot"].get("marco_referencia", "world")

    @property
    def directorio_datos(self) -> str:
        return os.path.expanduser(self.seccion("datos").get("directorio", "~/.openarm_hmi"))

    def variables_brazo(self, brazo: Brazo) -> Dict[str, str]:
        return {"cuerpo": self.cuerpo, "brazo": brazo.id, "sufijo": brazo.sufijo,
                "nombre": brazo.nombre}


def cargar(ruta: str, cuerpo: Optional[str] = None,
           sobrescribir: Optional[Dict[str, Any]] = None) -> Configuracion:
    """Lee el YAML, aplica `cuerpo` y las claves de `sobrescribir` (sección.clave) y lo resuelve."""
    with open(ruta, encoding="utf-8") as f:
        datos = yaml.safe_load(f) or {}
    return desde_dict(datos, cuerpo, sobrescribir)


def desde_dict(datos: Dict[str, Any], cuerpo: Optional[str] = None,
               sobrescribir: Optional[Dict[str, Any]] = None) -> Configuracion:
    datos = copy.deepcopy(datos)
    for clave, valor in (sobrescribir or {}).items():
        if valor in (None, ""):
            continue
        seccion, _, nombre = clave.partition(".")
        datos.setdefault(seccion, {})[nombre] = valor

    robot = datos.setdefault("robot", {})
    cuerpo = str(cuerpo or robot.get("cuerpo", "301"))
    robot["cuerpo"] = cuerpo
    datos = rellenar(datos, {"cuerpo": cuerpo})

    config = Configuracion(datos=datos, cuerpo=cuerpo)
    plantilla = datos["robot"].get("por_brazo", {})
    for entrada in datos["robot"].get("brazos", []):
        sufijo = entrada["sufijo"]
        variables = {"cuerpo": cuerpo, "brazo": f"{cuerpo}_{sufijo}", "sufijo": sufijo,
                     "nombre": entrada.get("nombre", sufijo)}
        campos = rellenar(plantilla, variables)
        pinza = campos.get("pinza", {})
        config.brazos.append(Brazo(
            id=variables["brazo"],
            sufijo=sufijo,
            nombre=variables["nombre"],
            articulaciones=list(campos.get("articulaciones", [])),
            grupo_moveit=campos.get("grupo_moveit", ""),
            efector=campos.get("efector", ""),
            controlador_trayectoria=campos.get("controlador_trayectoria", ""),
            controlador_pinza=campos.get("controlador_pinza", ""),
            pinza=Pinza(
                accion=pinza.get("accion", ""),
                articulacion=pinza.get("articulacion", ""),
                anchura_maxima_mm=float(pinza.get("anchura_maxima_mm", 100.0)),
                rad_abierta=float(pinza.get("rad_abierta", 1.0)),
                esfuerzo=float(pinza.get("esfuerzo", 10.0)),
            ),
        ))
    return config
