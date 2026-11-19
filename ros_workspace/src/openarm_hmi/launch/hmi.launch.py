"""Servidor web del HMI (sin lanzar el robot: se inicia desde el botón Iniciar del HMI o
desde otra terminal).

    ros2 launch openarm_hmi hmi.launch.py                       # cuerpo 301, puerto 8080
    ros2 launch openarm_hmi hmi.launch.py cuerpo:=302 puerto:=8081
    ros2 launch openarm_hmi hmi.launch.py host:=0.0.0.0          # accesible desde la red
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    cuerpo = LaunchConfiguration("cuerpo")
    config = LaunchConfiguration("config")
    return LaunchDescription([
        DeclareLaunchArgument("cuerpo", default_value="301", description="Cuerpo OpenArm"),
        DeclareLaunchArgument("puerto", default_value="0",
                              description="Puerto web (0 = el de la configuración, 8080)"),
        DeclareLaunchArgument("host", default_value="",
                              description="Dirección de escucha ('' = la de la configuración)"),
        DeclareLaunchArgument(
            "config",
            default_value=PathJoinSubstitution([FindPackageShare("openarm_hmi"), "config",
                                                "openarm.yaml"]),
            description="Fichero de configuración del HMI"),
        DeclareLaunchArgument("directorio_datos", default_value="",
                              description="Carpeta de capturas y poses ('' = configuración)"),
        DeclareLaunchArgument("camaras_simuladas", default_value="false",
                              description="Publicar imágenes sintéticas en las cámaras"),
        Node(
            package="openarm_hmi",
            executable="hmi_servidor",
            name="openarm_hmi",
            output="screen",
            emulate_tty=True,
            # Tipos explícitos: sin ellos "301" llegaría como entero y "" como nulo
            parameters=[{
                "config": ParameterValue(config, value_type=str),
                "cuerpo": ParameterValue(cuerpo, value_type=str),
                "puerto": ParameterValue(LaunchConfiguration("puerto"), value_type=int),
                "host": ParameterValue(LaunchConfiguration("host"), value_type=str),
                "directorio_datos": ParameterValue(LaunchConfiguration("directorio_datos"),
                                                   value_type=str),
            }],
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(PathJoinSubstitution(
                [FindPackageShare("openarm_hmi"), "launch", "camaras_simuladas.launch.py"])),
            launch_arguments={"cuerpo": cuerpo}.items(),
            condition=IfCondition(LaunchConfiguration("camaras_simuladas")),
        ),
    ])
