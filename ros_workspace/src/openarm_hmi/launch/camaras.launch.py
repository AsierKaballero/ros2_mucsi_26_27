"""Cámaras USB reales del efector final de cada brazo (usb_cam), en los topics del HMI.

    ros2 launch openarm_hmi camaras.launch.py                     # cámaras del 301 (abajo)
    ros2 launch openarm_hmi camaras.launch.py ancho_der:=960 alto_der:=600 fps_der:=30.0
    ros2 launch openarm_hmi camaras.launch.py dispositivo_izq:="" # solo la derecha

Cada cámara publica en /robot_<cuerpo>_<lado>/camara/image_raw, con el frame del URDF
<cuerpo>_<lado>_camera_view_frame. Para ver qué dispositivos hay: `v4l2-ctl --list-devices`,
`ls -l /dev/v4l/by-id/ /dev/v4l/by-path/` (cada cámara crea dos nodos; el de vídeo es el
index0). Deja un dispositivo vacío ("") para no lanzar esa cámara. Necesita un perfil con
acceso a /dev (local o local_gpu).

Por defecto, las cámaras Arducam B0495 del cuerpo 301 (identificadas en
docs_and_extras/OPENARM_PUESTA_EN_MARCHA.md, 4.21): la derecha por número de serie y la izquierda por puerto
USB (si se cambia de puerto, hay que pasar su nueva ruta). La izquierda está en un puerto
USB 2 y solo da 960x600 a 10 fps; la derecha (USB 3) da 1920x1200 hasta 50 fps.

Resolución y fps: `ancho`, `alto` y `fps` valen para las dos; `ancho_izq`, `fps_der`... los
sustituyen para una sola. También se ajustan los controles de la cámara antes de abrirla:
`brillo` (usb_cam pondría 50 por defecto, que quema la imagen; el normal es 0) y
`frecuencia_red` (antiparpadeo: 1 = 50 Hz, el de la red en España).
Si una cámara se desconecta un momento, su nodo se vuelve a lanzar solo a los 3 s.
"""

import os
import shutil
import subprocess

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

CAMARA_IZQ_301 = "/dev/v4l/by-path/pci-0000:00:14.0-usb-0:5.1:1.0-video-index0"
CAMARA_DER_301 = ("/dev/v4l/by-id/usb-Arducam_Arducam_B0495__USB3_2.3MP__"
                  "Arducam_202500915_0001-video-index0")


def _valor(context, nombre, lado):
    """Valor por brazo (<nombre>_<lado>) o, si está vacío, el común (<nombre>)."""
    propio = LaunchConfiguration(f"{nombre}_{lado}").perform(context)
    return propio if propio else LaunchConfiguration(nombre).perform(context)


def _ajustar_controles(dispositivo, controles):
    """Fija controles V4L2 con v4l2-ctl (si está). Devuelve un texto para el log."""
    if shutil.which("v4l2-ctl") is None:
        return f"{dispositivo}: sin v4l2-ctl, no se ajustan los controles"
    resultado = subprocess.run(
        ["v4l2-ctl", "-d", dispositivo, "-c", ",".join(f"{k}={v}" for k, v in controles.items())],
        capture_output=True, text=True, timeout=5)
    if resultado.returncode != 0:
        return f"{dispositivo}: no se pudieron ajustar los controles: {resultado.stderr.strip()}"
    return f"{dispositivo}: " + ", ".join(f"{k}={v}" for k, v in controles.items())


def _nodos(context):
    cuerpo = LaunchConfiguration("cuerpo").perform(context)
    brillo = int(LaunchConfiguration("brillo").perform(context))
    frecuencia_red = int(LaunchConfiguration("frecuencia_red").perform(context))
    acciones = []
    for lado in ("izq", "der"):
        dispositivo = LaunchConfiguration(f"dispositivo_{lado}").perform(context)
        if not dispositivo:
            continue
        # usb_cam no sigue bien los enlaces relativos de /dev/v4l/by-id y by-path (los
        # convierte en /dev/../../videoN): se le pasa el dispositivo real
        dispositivo = os.path.realpath(dispositivo)
        if not os.path.exists(dispositivo):
            acciones.append(LogInfo(msg=f"[camaras] No existe la cámara {lado}: {dispositivo}"))
            continue
        acciones.append(LogInfo(msg="[camaras] " + _ajustar_controles(
            dispositivo, {"power_line_frequency": frecuencia_red})))
        acciones.append(Node(
            package="usb_cam",
            executable="usb_cam_node_exe",
            name="camara",
            namespace=f"robot_{cuerpo}_{lado}/camara",
            output="screen",
            # Si la cámara se desconecta un momento (p. ej. se reinicia el hub USB), usb_cam
            # muere ("Invalid v4l2 format"): se vuelve a lanzar solo
            respawn=True,
            respawn_delay=3.0,
            parameters=[{
                "video_device": dispositivo,
                "image_width": int(_valor(context, "ancho", lado)),
                "image_height": int(_valor(context, "alto", lado)),
                "framerate": float(_valor(context, "fps", lado)),
                "pixel_format": LaunchConfiguration("formato").perform(context),
                "camera_frame_id": f"{cuerpo}_{lado}_camera_view_frame",
                "io_method": "mmap",
                # usb_cam aplica estos al abrir la cámara (brightness=50 por defecto)
                "brightness": brillo,
            }],
        ))
    return acciones


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("cuerpo", default_value="301"),
        DeclareLaunchArgument("dispositivo_izq", default_value=CAMARA_IZQ_301),
        DeclareLaunchArgument("dispositivo_der", default_value=CAMARA_DER_301),
        DeclareLaunchArgument("ancho", default_value="960"),
        DeclareLaunchArgument("alto", default_value="600"),
        DeclareLaunchArgument("fps", default_value="10.0"),
        DeclareLaunchArgument("ancho_izq", default_value=""),
        DeclareLaunchArgument("alto_izq", default_value=""),
        DeclareLaunchArgument("fps_izq", default_value=""),
        DeclareLaunchArgument("ancho_der", default_value="1920"),
        DeclareLaunchArgument("alto_der", default_value="1200"),
        DeclareLaunchArgument("fps_der", default_value="15.0"),
        DeclareLaunchArgument("brillo", default_value="0",
                              description="Brillo (-64..64; 0 es el normal de la Arducam)"),
        DeclareLaunchArgument("frecuencia_red", default_value="1",
                              description="Antiparpadeo: 0 desactivado, 1 = 50 Hz, 2 = 60 Hz"),
        DeclareLaunchArgument("formato", default_value="yuyv",
                              description="Formato de píxel de usb_cam (yuyv, mjpeg2rgb...)"),
        OpaqueFunction(function=_nodos),
    ])
