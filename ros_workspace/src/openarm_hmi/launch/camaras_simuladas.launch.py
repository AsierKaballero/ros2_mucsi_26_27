"""Una cámara simulada por brazo, en los topics que espera el HMI.

    ros2 launch openarm_hmi camaras_simuladas.launch.py cuerpo:=301
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

LADOS = ("izq", "der")


def _nodos(context):
    cuerpo = LaunchConfiguration("cuerpo").perform(context)
    return [
        Node(
            package="openarm_hmi",
            executable="camara_simulada",
            name=f"camara_simulada_{cuerpo}_{lado}",
            output="log",
            parameters=[{"brazo": f"{cuerpo}_{lado}",
                         "topic": f"/robot_{cuerpo}_{lado}/camara/image_raw",
                         "fps": float(LaunchConfiguration("fps").perform(context))}],
        )
        for lado in LADOS
    ]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("cuerpo", default_value="301"),
        DeclareLaunchArgument("fps", default_value="15.0"),
        OpaqueFunction(function=_nodos),
    ])
