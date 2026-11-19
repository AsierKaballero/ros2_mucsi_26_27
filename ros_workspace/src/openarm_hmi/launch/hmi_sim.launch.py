"""Todo en uno para desarrollar: simulación del OpenArm + HMI + cámaras simuladas.

    ros2 launch openarm_hmi hmi_sim.launch.py                  # cuerpo 301, sin RViz
    ros2 launch openarm_hmi hmi_sim.launch.py cuerpo:=302 launch_rviz:=true

Después abre http://localhost:8080 en el navegador.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def _incluir(context):
    cuerpo = LaunchConfiguration("cuerpo").perform(context)
    simulacion = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(PathJoinSubstitution(
            [FindPackageShare("launcher_robots_lab_robotica"), "launch",
             f"sim_{cuerpo}.launch.py"])),
        launch_arguments={"launch_rviz": LaunchConfiguration("launch_rviz")}.items(),
    )
    hmi = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(PathJoinSubstitution(
            [FindPackageShare("openarm_hmi"), "launch", "hmi.launch.py"])),
        launch_arguments={
            "cuerpo": cuerpo,
            "puerto": LaunchConfiguration("puerto"),
            "host": LaunchConfiguration("host"),
            "camaras_simuladas": LaunchConfiguration("camaras_simuladas"),
        }.items(),
    )
    return [simulacion, hmi]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("cuerpo", default_value="301"),
        DeclareLaunchArgument("launch_rviz", default_value="false"),
        DeclareLaunchArgument("puerto", default_value="0"),
        DeclareLaunchArgument("host", default_value=""),
        DeclareLaunchArgument("camaras_simuladas", default_value="true"),
        OpaqueFunction(function=_incluir),
    ])
