"""Operaciones con cuaterniones (x, y, z, w) y ángulos RPY, sin dependencias externas."""

import math
from typing import Sequence, Tuple

Cuaternion = Tuple[float, float, float, float]
Vector = Tuple[float, float, float]


def multiplicar(a: Sequence[float], b: Sequence[float]) -> Cuaternion:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def normalizar(q: Sequence[float]) -> Cuaternion:
    n = math.sqrt(sum(c * c for c in q))
    if n < 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    return tuple(c / n for c in q)  # type: ignore[return-value]


def conjugado(q: Sequence[float]) -> Cuaternion:
    return (-q[0], -q[1], -q[2], q[3])


def rotar(q: Sequence[float], v: Sequence[float]) -> Vector:
    """Aplica la rotación q al vector v."""
    p = (v[0], v[1], v[2], 0.0)
    r = multiplicar(multiplicar(q, p), conjugado(q))
    return (r[0], r[1], r[2])


def desde_rpy(roll: float, pitch: float, yaw: float) -> Cuaternion:
    """Cuaternión a partir de roll, pitch, yaw (ejes fijos X, Y, Z; convención de ROS)."""
    cr, sr = math.cos(roll / 2), math.sin(roll / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    return (
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    )


def a_rpy(q: Sequence[float]) -> Vector:
    x, y, z, w = q
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    s = max(-1.0, min(1.0, 2 * (w * y - z * x)))
    pitch = math.asin(s)
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return (roll, pitch, yaw)


def desde_rotacion_vector(r: Sequence[float]) -> Cuaternion:
    """Cuaternión de un vector de rotación (eje · ángulo, en rad)."""
    angulo = math.sqrt(sum(c * c for c in r))
    if angulo < 1e-12:
        return (0.0, 0.0, 0.0, 1.0)
    s = math.sin(angulo / 2) / angulo
    return (r[0] * s, r[1] * s, r[2] * s, math.cos(angulo / 2))


def desplazar_pose(posicion: Sequence[float], orientacion: Sequence[float],
                   traslacion: Sequence[float], rotacion: Sequence[float],
                   marco_herramienta: bool) -> Tuple[Vector, Cuaternion]:
    """Pose desplazada `traslacion` (m) y girada `rotacion` (vector de rotación, rad).

    Con `marco_herramienta` los desplazamientos se expresan en los ejes del efector; si no,
    en los del marco de referencia (mundo). En los dos casos la rotación es alrededor del
    origen del efector (no se mueve la punta al girar).
    """
    dq = desde_rotacion_vector(rotacion)
    if marco_herramienta:
        t = rotar(orientacion, traslacion)
        nueva_q = multiplicar(orientacion, dq)
    else:
        t = tuple(traslacion)
        nueva_q = multiplicar(dq, orientacion)
    nueva_p = (posicion[0] + t[0], posicion[1] + t[1], posicion[2] + t[2])
    return nueva_p, normalizar(nueva_q)
