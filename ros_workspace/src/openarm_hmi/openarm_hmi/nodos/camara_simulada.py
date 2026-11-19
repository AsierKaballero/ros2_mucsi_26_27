"""Cámara simulada: publica una imagen sintética para probar el HMI sin cámaras reales.

La imagen muestra el nombre del brazo, la hora, una cuadrícula en movimiento y los valores
de las articulaciones del brazo (de /joint_states), así que se ve que el vídeo es en vivo.

    ros2 run openarm_hmi camara_simulada --ros-args -p brazo:=301_izq \\
        -p topic:=/robot_301_izq/camara/image_raw
"""

import math
import time

import cv2
import numpy as np
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import Image, JointState


class CamaraSimulada(Node):
    def __init__(self) -> None:
        super().__init__("camara_simulada")
        self.declare_parameter("brazo", "301_izq")
        self.declare_parameter("topic", "")
        self.declare_parameter("ancho", 640)
        self.declare_parameter("alto", 480)
        self.declare_parameter("fps", 15.0)
        self.brazo = self.get_parameter("brazo").value
        topic = self.get_parameter("topic").value or f"/robot_{self.brazo}/camara/image_raw"
        self.ancho = int(self.get_parameter("ancho").value)
        self.alto = int(self.get_parameter("alto").value)
        self.articulaciones = {}
        self.publicador = self.create_publisher(Image, topic, 5)
        self.create_subscription(JointState, "/joint_states", self._cb_articulaciones, 10)
        self.create_timer(1.0 / float(self.get_parameter("fps").value), self._publicar)
        self.inicio = time.time()
        self.get_logger().info(f"Cámara simulada de {self.brazo} en {topic}")

    def _cb_articulaciones(self, msg: JointState) -> None:
        for nombre, posicion in zip(msg.name, msg.position):
            if nombre.startswith(self.brazo):
                self.articulaciones[nombre[len(self.brazo) + 1:]] = posicion

    def _publicar(self) -> None:
        t = time.time() - self.inicio
        imagen = np.zeros((self.alto, self.ancho, 3), np.uint8)
        # Fondo en degradado con una cuadrícula que se desplaza
        imagen[:] = (40, 30, 25)
        imagen[:, :, 0] = np.linspace(60, 20, self.alto, dtype=np.uint8)[:, None]
        desplazamiento = int(t * 30) % 40
        for x in range(-desplazamiento, self.ancho, 40):
            cv2.line(imagen, (x, 0), (x, self.alto), (70, 60, 50), 1)
        for y in range(-desplazamiento, self.alto, 40):
            cv2.line(imagen, (0, y), (self.ancho, y), (70, 60, 50), 1)
        # "Objeto" que gira según joint7 y punto de mira central
        cx, cy = self.ancho // 2, self.alto // 2
        angulo = self.articulaciones.get("joint7", 0.0) + t * 0.5
        radio = min(self.ancho, self.alto) // 4
        puntos = np.array([[cx + radio * math.cos(angulo + k * math.pi / 2),
                            cy + radio * math.sin(angulo + k * math.pi / 2)]
                           for k in range(4)], np.int32)
        cv2.polylines(imagen, [puntos], True, (0, 200, 255), 2)
        cv2.drawMarker(imagen, (cx, cy), (255, 255, 255), cv2.MARKER_CROSS, 30, 1)
        # Textos
        fuente = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(imagen, f"CAMARA SIMULADA {self.brazo}", (16, 32), fuente, 0.7,
                    (255, 255, 255), 2)
        cv2.putText(imagen, time.strftime("%H:%M:%S"), (self.ancho - 130, 32), fuente, 0.7,
                    (200, 200, 200), 2)
        for i in range(1, 8):
            valor = self.articulaciones.get(f"joint{i}")
            texto = f"J{i} {math.degrees(valor):+7.1f}" if valor is not None else f"J{i}   ---"
            cv2.putText(imagen, texto, (16, 70 + 24 * i), fuente, 0.55, (180, 255, 180), 1)
        pinza = self.articulaciones.get("finger_joint1")
        if pinza is not None:
            cv2.putText(imagen, f"pinza {abs(pinza):.3f} rad", (16, self.alto - 20), fuente,
                        0.55, (180, 220, 255), 1)

        msg = Image()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = f"{self.brazo}_camara"
        msg.height, msg.width = self.alto, self.ancho
        msg.encoding = "bgr8"
        msg.step = self.ancho * 3
        msg.data = imagen.tobytes()
        self.publicador.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    nodo = CamaraSimulada()
    try:
        rclpy.spin(nodo)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        nodo.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
