"""Cámaras USB reales del efector final de cada brazo (usb_cam), en los topics del HMI.

    ros2 launch openarm_hmi camaras.launch.py cuerpo:=301 \\
        dispositivo_izq:=/dev/video0 dispositivo_der:=/dev/video2

Cada cámara publica en /robot_<cuerpo>_<lado>/camara/image_raw. Para ver qué dispositivos
hay: `v4l2-ctl --list-devices` o `ls /dev/video*` (cada cámara suele crear dos nodos; el
de vídeo es el primero). Deja un dispositivo vacío ("") para no lanzar esa cámara.
Necesita un perfil con acceso a /dev (local o local_gpu).
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _nodos(context):
    cuerpo = LaunchConfiguration("cuerpo").perform(context)
    nodos = []
    for lado in ("izq", "der"):
        dispositivo = LaunchConfiguration(f"dispositivo_{lado}").perform(context)
        if not dispositivo:
            continue
        nodos.append(Node(
            package="usb_cam",
            executable="usb_cam_node_exe",
            name="camara",
            namespace=f"robot_{cuerpo}_{lado}/camara",
            output="screen",
            parameters=[{
                "video_device": dispositivo,
                "image_width": int(LaunchConfiguration("ancho").perform(context)),
                "image_height": int(LaunchConfiguration("alto").perform(context)),
                "framerate": float(LaunchConfiguration("fps").perform(context)),
                "pixel_format": LaunchConfiguration("formato").perform(context),
                "camera_frame_id": f"{cuerpo}_{lado}_camara",
                "io_method": "mmap",
            }],
        ))
    return nodos


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("cuerpo", default_value="301"),
        DeclareLaunchArgument("dispositivo_izq", default_value="/dev/video0"),
        DeclareLaunchArgument("dispositivo_der", default_value="/dev/video2"),
        DeclareLaunchArgument("ancho", default_value="640"),
        DeclareLaunchArgument("alto", default_value="480"),
        DeclareLaunchArgument("fps", default_value="15.0"),
        DeclareLaunchArgument("formato", default_value="yuyv",
                              description="Formato de píxel de usb_cam (yuyv, mjpeg2rgb...)"),
        OpaqueFunction(function=_nodos),
    ])
