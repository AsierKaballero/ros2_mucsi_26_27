"""Registro de módulos del servidor.

Para añadir un módulo: impórtalo aquí, añádelo a MODULOS y pon su nombre en la lista
`modulos` de config/openarm.yaml (el orden de esa lista es el orden de arranque; un
módulo que use otro con ctx.modulo(...) debe ir después).
"""

from openarm_hmi.modulos.camaras import Camaras
from openarm_hmi.modulos.controladores import Controladores
from openarm_hmi.modulos.estado import Estado
from openarm_hmi.modulos.movimiento import Movimiento
from openarm_hmi.modulos.pinza import Pinza
from openarm_hmi.modulos.poses import Poses
from openarm_hmi.modulos.registro import Registro
from openarm_hmi.modulos.ros import Ros
from openarm_hmi.modulos.scripts import Scripts
from openarm_hmi.modulos.seguridad import Seguridad
from openarm_hmi.modulos.sistema import Sistema

MODULOS = {
    clase.nombre: clase
    for clase in (Estado, Registro, Seguridad, Controladores, Movimiento, Pinza, Poses,
                  Camaras, Ros, Sistema, Scripts)
}
