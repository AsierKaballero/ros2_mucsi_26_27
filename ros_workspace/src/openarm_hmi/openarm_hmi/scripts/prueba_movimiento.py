"""Pruebas de movimiento de los brazos OpenArm (simulados o reales), lanzables desde el HMI.

Modos:
  basica          gira joint1 el ángulo indicado, vuelve, y abre y cierra la pinza a 30 mm
                  (equivale a ejemplos/prueba_openarm.py)
  articulaciones  mueve cada articulación (joint1-joint7) +ángulo, −ángulo y vuelve
  pinza           abre la pinza a --anchura mm y la cierra

Con dos brazos (--brazos 301_izq,301_der) se mueven a la vez con el grupo conjunto de
MoveIt (robots_301). Respeta la parada de emergencia del HMI (/hmi/parada_emergencia):
si se activa, cancela el movimiento y termina con código 2.

    ros2 run openarm_hmi prueba_movimiento --brazos 301_izq --angulo 0.05 --modo basica
"""

import argparse
import sys
import threading
import time
from typing import Dict, List

import rclpy
from control_msgs.action import GripperCommand
from moveit_msgs.action import MoveGroup
from moveit_msgs.msg import Constraints, JointConstraint, MoveItErrorCodes
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.utilities import remove_ros_args
from sensor_msgs.msg import JointState
from std_msgs.msg import Bool

ARTICULACIONES = [f"joint{i}" for i in range(1, 8)]


class ParadaEmergencia(Exception):
    pass


class Prueba(Node):
    def __init__(self, brazos: List[str], velocidad: float) -> None:
        super().__init__("prueba_movimiento")
        self.brazos = brazos
        self.velocidad = velocidad
        self.posiciones: Dict[str, float] = {}
        self.parada = False
        self.create_subscription(JointState, "/joint_states", self._cb_joint_states, 20)
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             reliability=ReliabilityPolicy.RELIABLE)
        self.create_subscription(Bool, "/hmi/parada_emergencia", self._cb_parada, latched)
        self.cli_mover = ActionClient(self, MoveGroup, "move_action")
        self.cli_pinzas = {b: ActionClient(self, GripperCommand, f"/robot_{b}/gripper_action")
                           for b in brazos}

    def _cb_joint_states(self, msg: JointState) -> None:
        for nombre, posicion in zip(msg.name, msg.position):
            self.posiciones[nombre] = posicion

    def _cb_parada(self, msg: Bool) -> None:
        self.parada = msg.data

    def comprobar_parada(self) -> None:
        if self.parada:
            raise ParadaEmergencia()

    def esperar(self, futuro, timeout_s: float = 120.0, handle=None):
        inicio = time.monotonic()
        while not futuro.done():
            if self.parada:
                if handle is not None:
                    handle.cancel_goal_async()
                raise ParadaEmergencia()
            if time.monotonic() - inicio > timeout_s:
                raise TimeoutError("Tiempo de espera agotado")
            time.sleep(0.02)
        return futuro.result()

    def articulaciones_actuales(self, brazo: str) -> List[float]:
        nombres = [f"{brazo}_{j}" for j in ARTICULACIONES]
        inicio = time.monotonic()
        while not all(n in self.posiciones for n in nombres):
            if time.monotonic() - inicio > 10.0:
                raise RuntimeError(f"No llega /joint_states de {brazo}")
            time.sleep(0.05)
        return [self.posiciones[n] for n in nombres]

    def grupo(self) -> str:
        if len(self.brazos) == 1:
            return f"robot_{self.brazos[0]}"
        return f"robots_{self.brazos[0].split('_')[0]}"

    def mover(self, objetivos: Dict[str, List[float]], texto: str) -> None:
        """Mueve los brazos a `objetivos` ({brazo: [7 valores]}) a la vez."""
        self.comprobar_parada()
        print(f"  → {texto}", flush=True)
        goal = MoveGroup.Goal()
        r = goal.request
        r.group_name = self.grupo()
        r.num_planning_attempts = 5
        r.allowed_planning_time = 5.0
        r.max_velocity_scaling_factor = self.velocidad
        r.max_acceleration_scaling_factor = self.velocidad
        r.start_state.is_diff = True
        restricciones = Constraints()
        for brazo, valores in objetivos.items():
            for articulacion, valor in zip(ARTICULACIONES, valores):
                restricciones.joint_constraints.append(JointConstraint(
                    joint_name=f"{brazo}_{articulacion}", position=float(valor),
                    tolerance_above=0.001, tolerance_below=0.001, weight=1.0))
        r.goal_constraints.append(restricciones)
        goal.planning_options.plan_only = False
        goal.planning_options.planning_scene_diff.is_diff = True
        goal.planning_options.planning_scene_diff.robot_state.is_diff = True

        handle = self.esperar(self.cli_mover.send_goal_async(goal), 10.0)
        if not handle.accepted:
            raise RuntimeError("move_group rechazó el objetivo")
        resultado = self.esperar(handle.get_result_async(), handle=handle).result
        if resultado.error_code.val != MoveItErrorCodes.SUCCESS:
            raise RuntimeError(f"El movimiento falló (código de MoveIt {resultado.error_code.val})")

    def pinzas(self, anchura_mm: float) -> None:
        self.comprobar_parada()
        print(f"  → pinza{'s' if len(self.brazos) > 1 else ''} a {anchura_mm:.0f} mm", flush=True)
        handles = []
        for brazo, cliente in self.cli_pinzas.items():
            if not cliente.wait_for_server(timeout_sec=5.0):
                raise RuntimeError(f"Acción de la pinza de {brazo} no disponible")
            goal = GripperCommand.Goal()
            goal.command.position = float(anchura_mm)
            goal.command.max_effort = 10.0
            handles.append(self.esperar(cliente.send_goal_async(goal), 10.0))
        for handle in handles:
            if handle.accepted:
                self.esperar(handle.get_result_async(), 20.0, handle=handle)


def main(args=None) -> None:
    argumentos_ros = remove_ros_args(args if args is not None else sys.argv)
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--brazos", default="301_izq",
                        help="Brazo o brazos separados por comas (301_izq,301_der)")
    parser.add_argument("--angulo", type=float, default=0.05, help="Ángulo en rad")
    parser.add_argument("--velocidad", type=float, default=0.1, help="Escala de velocidad 0-1")
    parser.add_argument("--anchura", type=float, default=30.0, help="Anchura de la pinza (mm)")
    parser.add_argument("--modo", choices=["basica", "articulaciones", "pinza"], default="basica")
    opciones = parser.parse_args(argumentos_ros[1:])
    brazos = [b.strip() for b in opciones.brazos.split(",") if b.strip()]
    if abs(opciones.angulo) > 0.5:
        parser.error("Por seguridad el ángulo está limitado a ±0,5 rad")
    velocidad = min(max(opciones.velocidad, 0.01), 1.0)

    rclpy.init(args=args)
    prueba = Prueba(brazos, velocidad)
    ejecutor = MultiThreadedExecutor()
    ejecutor.add_node(prueba)
    threading.Thread(target=ejecutor.spin, daemon=True).start()

    codigo = 0
    try:
        print(f"Prueba '{opciones.modo}' de {', '.join(brazos)} "
              f"(velocidad {velocidad * 100:.0f} %)", flush=True)
        if opciones.modo != "pinza":
            print("Esperando a move_group...", flush=True)
            if not prueba.cli_mover.wait_for_server(timeout_sec=15.0):
                raise RuntimeError("move_group no está disponible")
            inicio = {b: prueba.articulaciones_actuales(b) for b in brazos}
            for brazo, valores in inicio.items():
                print(f"Inicio {brazo}: {[round(v, 3) for v in valores]}", flush=True)
            a = opciones.angulo

            def con_delta(indice: int, delta: float) -> Dict[str, List[float]]:
                objetivo = {}
                for brazo, valores in inicio.items():
                    nuevo = list(valores)
                    nuevo[indice] += delta
                    objetivo[brazo] = nuevo
                return objetivo

            if opciones.modo == "basica":
                prueba.mover(con_delta(0, a), f"joint1 {a:+.3f} rad")
                prueba.mover(inicio, "vuelta a la posición inicial")
                prueba.pinzas(30.0)
                prueba.pinzas(0.0)
            else:
                for i in range(7):
                    print(f"joint{i + 1}:", flush=True)
                    prueba.mover(con_delta(i, a), f"+{a:.3f} rad")
                    prueba.mover(con_delta(i, -a), f"-{a:.3f} rad")
                    prueba.mover(inicio, "vuelta")
        else:
            prueba.pinzas(opciones.anchura)
            prueba.pinzas(0.0)
        print("Prueba completada correctamente", flush=True)
    except ParadaEmergencia:
        print("PARADA DE EMERGENCIA: prueba interrumpida", flush=True)
        codigo = 2
    except KeyboardInterrupt:
        print("Prueba interrumpida por el usuario", flush=True)
        codigo = 130
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}", flush=True)
        codigo = 1
    finally:
        ejecutor.shutdown()
        prueba.destroy_node()
        rclpy.try_shutdown()
    sys.exit(codigo)


if __name__ == "__main__":
    main()
