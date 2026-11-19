"""Movimiento de los brazos con MoveIt 2 (move_group), con la velocidad de cada brazo.

Todos los movimientos se planifican (evitan colisiones con el propio robot y la escena) y
respetan los límites del URDF. Las órdenes devuelven una tarea; su progreso llega al
navegador como evento "tarea".

`brazo` en las peticiones es el id ("301_izq"), el sufijo ("izq") o "ambos" (grupo
conjunto: los dos brazos se mueven a la vez y llegan juntos).

Rutas:
  POST /api/movimiento/articulaciones   {brazo, posiciones: [rad...]}  (ambos: {id: [...]})
  POST /api/movimiento/jog_articular    {brazo, indice, delta}          (delta en rad)
  POST /api/movimiento/jog_cartesiano   {brazo, traslacion: [m], rotacion: [rad], marco}
  POST /api/movimiento/pose             {brazo, posicion: [m], rpy: [rad]}
  POST /api/movimiento/parar            {brazo?}                         (sin brazo: todos)
  POST /api/movimiento/velocidad        {brazo?, valor}                  (0-1)
  GET  /api/movimiento/historial
  POST /api/movimiento/escena/aplicar
"""

import math
import threading
from typing import Any, Dict, List, Optional, Sequence

from builtin_interfaces.msg import Duration as DuracionMsg
from geometry_msgs.msg import Pose
from moveit_msgs.action import ExecuteTrajectory, MoveGroup
from moveit_msgs.msg import (
    CollisionObject,
    Constraints,
    JointConstraint,
    MoveItErrorCodes,
    OrientationConstraint,
    PlanningScene,
    PositionConstraint,
)
from moveit_msgs.srv import ApplyPlanningScene, GetCartesianPath
from rclpy.action import ActionClient
from shape_msgs.msg import SolidPrimitive
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

from openarm_hmi.nucleo import geometria
from openarm_hmi.nucleo import tareas as T
from openarm_hmi.nucleo.configuracion import Brazo
from openarm_hmi.nucleo.modulo import Modulo, requerir
from openarm_hmi.nucleo.servidor import ErrorHmi

AMBOS = "ambos"

MENSAJES_MOVEIT = {
    "SUCCESS": "Movimiento completado",
    "FAILURE": "Fallo",
    "PLANNING_FAILED": "No se encontró una trayectoria (planificación fallida)",
    "INVALID_MOTION_PLAN": "Plan de movimiento inválido",
    "MOTION_PLAN_INVALIDATED_BY_ENVIRONMENT_CHANGE":
        "El plan dejó de ser válido por un cambio del entorno",
    "CONTROL_FAILED":
        "Fallo del controlador (¿desactivado, o el robot se desvió de la trayectoria?)",
    "TIMED_OUT": "Tiempo agotado",
    "PREEMPTED": "Interrumpido por otra orden",
    "START_STATE_IN_COLLISION": "El estado inicial está en colisión",
    "GOAL_IN_COLLISION": "El objetivo está en colisión",
    "GOAL_CONSTRAINTS_VIOLATED": "No se cumplen las restricciones del objetivo",
    "INVALID_GROUP_NAME": "Grupo de planificación desconocido",
    "INVALID_GOAL_CONSTRAINTS": "Objetivo inválido",
    "INVALID_ROBOT_STATE": "Estado del robot inválido",
    "INVALID_LINK_NAME": "Enlace desconocido",
    "FRAME_TRANSFORM_FAILURE": "Error de transformación entre marcos",
    "NO_IK_SOLUTION": "Pose inalcanzable (sin solución de cinemática inversa)",
}
# Código numérico -> nombre de la constante (según la versión instalada de moveit_msgs)
NOMBRES_CODIGOS = {getattr(MoveItErrorCodes, n): n for n in dir(MoveItErrorCodes)
                   if n.isupper() and isinstance(getattr(MoveItErrorCodes, n), int)}


def mensaje_moveit(codigo: int) -> str:
    nombre = NOMBRES_CODIGOS.get(codigo, str(codigo))
    return MENSAJES_MOVEIT.get(nombre, f"Error de MoveIt {nombre}")


def interpretar_moveit(resultado, status) -> tuple:
    codigo = resultado.error_code.val
    return codigo == MoveItErrorCodes.SUCCESS, mensaje_moveit(codigo)


def pose_msg(posicion: Sequence[float], orientacion: Sequence[float]) -> Pose:
    pose = Pose()
    pose.position.x, pose.position.y, pose.position.z = (float(v) for v in posicion)
    (pose.orientation.x, pose.orientation.y,
     pose.orientation.z, pose.orientation.w) = (float(v) for v in orientacion)
    return pose


class Movimiento(Modulo):
    nombre = "movimiento"

    def iniciar(self) -> None:
        self.cfg = self.config.seccion("movimiento")
        self.estado_robot = self.ctx.modulo("estado")
        if self.estado_robot is None:
            raise RuntimeError("El módulo 'movimiento' necesita el módulo 'estado'")
        self.vel_maxima = float(self.cfg.get("velocidad_maxima", 1.0))
        defecto = min(float(self.cfg.get("velocidad_defecto", 0.1)), self.vel_maxima)
        self.velocidades = {b.id: defecto for b in self.config.brazos}

        grupo = self.ctx.grupo_callbacks
        self.cli_mover = ActionClient(self.nodo, MoveGroup, "move_action", callback_group=grupo)
        self.cli_ejecutar = ActionClient(self.nodo, ExecuteTrajectory, "execute_trajectory",
                                         callback_group=grupo)
        self.cli_cartesiano = self.nodo.create_client(GetCartesianPath, "compute_cartesian_path",
                                                      callback_group=grupo)
        self.cli_escena = self.nodo.create_client(ApplyPlanningScene, "apply_planning_scene",
                                                  callback_group=grupo)
        self.pub_trayectoria = {
            b.id: self.nodo.create_publisher(
                JointTrajectory, f"/{b.controlador_trayectoria}/joint_trajectory", 10)
            for b in self.config.brazos
        }

        self.bus.suscribir("parada_emergencia",
                           lambda datos: self.parar(None, "Parada de emergencia"))
        self._escena_aplicada = False
        self._parar_hilo = threading.Event()
        threading.Thread(target=self._vigilar_escena, daemon=True, name="escena").start()

        self.ruta("POST", "/api/movimiento/articulaciones", self._ruta_articulaciones)
        self.ruta("POST", "/api/movimiento/jog_articular", self._ruta_jog_articular)
        self.ruta("POST", "/api/movimiento/jog_cartesiano", self._ruta_jog_cartesiano)
        self.ruta("POST", "/api/movimiento/pose", self._ruta_pose)
        self.ruta("POST", "/api/movimiento/parar", self._ruta_parar)
        self.ruta("POST", "/api/movimiento/velocidad", self._ruta_velocidad)
        self.ruta("GET", "/api/movimiento/historial", lambda p: self.tareas.historial())
        self.ruta("POST", "/api/movimiento/escena/aplicar", self._ruta_escena)

    def detener(self) -> None:
        self._parar_hilo.set()

    # --- Utilidades -------------------------------------------------------------------

    def brazos_de(self, objetivo: str) -> List[Brazo]:
        if objetivo == AMBOS:
            return list(self.config.brazos)
        try:
            return [self.config.brazo(objetivo)]
        except KeyError as e:
            raise ErrorHmi(f"Brazo desconocido: {objetivo}") from e

    @staticmethod
    def ambito(brazos: List[Brazo]) -> str:
        return f"movimiento:{brazos[0].id if len(brazos) == 1 else AMBOS}"

    def _ambitos_en_conflicto(self, brazos: List[Brazo]) -> List[str]:
        """Una orden de un brazo cancela la conjunta, y la conjunta cancela las de cada brazo."""
        if len(brazos) == 1:
            return [f"movimiento:{AMBOS}"]
        return [f"movimiento:{b.id}" for b in brazos]

    def velocidad(self, brazos: List[Brazo]) -> float:
        return min(self.velocidades[b.id] for b in brazos)

    def _comprobar(self) -> None:
        self.ctx.comprobar_movimiento_permitido()
        if not self.cli_mover.server_is_ready():
            raise ErrorHmi("move_group no está disponible: inicia el sistema (simulación o "
                           "robot real)", 503)

    def _peticion_base(self, goal: MoveGroup.Goal, grupo: str, velocidad: float) -> None:
        r = goal.request
        r.group_name = grupo
        r.num_planning_attempts = int(self.cfg.get("intentos_planificacion", 5))
        r.allowed_planning_time = float(self.cfg.get("tiempo_planificacion", 5.0))
        r.max_velocity_scaling_factor = velocidad
        r.max_acceleration_scaling_factor = min(
            1.0, velocidad * float(self.cfg.get("aceleracion_relativa", 1.0)))
        r.start_state.is_diff = True
        goal.planning_options.plan_only = False
        goal.planning_options.planning_scene_diff.is_diff = True
        goal.planning_options.planning_scene_diff.robot_state.is_diff = True

    def _enviar_move_group(self, brazos: List[Brazo], restricciones: Constraints,
                           tipo: str, descripcion: str) -> Dict[str, Any]:
        grupo = brazos[0].grupo_moveit if len(brazos) == 1 else self.config.grupo_conjunto
        goal = MoveGroup.Goal()
        self._peticion_base(goal, grupo, self.velocidad(brazos))
        goal.request.goal_constraints.append(restricciones)

        tarea = self.tareas.nueva(self.ambito(brazos), tipo, descripcion,
                                  cancelar=self._ambitos_en_conflicto(brazos))
        self.tareas.actualizar(tarea, T.PLANIFICANDO)

        def feedback(msg) -> None:
            estado = msg.feedback.state
            if estado == "MONITOR" and tarea.estado != T.EJECUTANDO:
                self.tareas.actualizar(tarea, T.EJECUTANDO, "Ejecutando")
            elif estado == "PLANNING" and tarea.estado != T.PLANIFICANDO:
                self.tareas.actualizar(tarea, T.PLANIFICANDO, "Planificando")

        self.tareas.enviar_objetivo(self.cli_mover, goal, tarea, interpretar_moveit,
                                    feedback=feedback, nombre_servidor="move_group")
        return tarea.a_dict()

    # --- Movimientos ------------------------------------------------------------------

    def mover_articulaciones(self, brazos: List[Brazo], objetivo: Dict[str, float],
                             descripcion: str, tipo: str = "articular") -> Dict[str, Any]:
        """Mueve las articulaciones de `brazos` a `objetivo` ({articulación: rad})."""
        self._comprobar()
        nombres = [n for b in brazos for n in b.articulaciones]
        faltan = [n for n in nombres if n not in objetivo]
        if faltan:
            raise ErrorHmi(f"Faltan valores para: {', '.join(faltan)}")
        valores = [float(objetivo[n]) for n in nombres]
        self.estado_robot.validar_objetivo(nombres, valores)

        tolerancia = float(self.cfg.get("tolerancia_articular", 0.001))
        restricciones = Constraints()
        for nombre, valor in zip(nombres, valores):
            restricciones.joint_constraints.append(JointConstraint(
                joint_name=nombre, position=valor, tolerance_above=tolerancia,
                tolerance_below=tolerancia, weight=1.0))
        return self._enviar_move_group(brazos, restricciones, tipo, descripcion)

    def jog_articular(self, brazo: Brazo, indice: int, delta: float) -> Dict[str, Any]:
        if not 0 <= indice < len(brazo.articulaciones):
            raise ErrorHmi(f"Índice de articulación inválido: {indice}")
        actuales = self.estado_robot.posiciones(brazo.articulaciones)
        nombre = brazo.articulaciones[indice]
        valor = actuales[indice] + delta
        # En el movimiento por pasos se recorta al límite en lugar de rechazar la orden
        limite = self.estado_robot.limites.get(nombre) or {}
        if "inferior" in limite:
            recortado = min(max(valor, limite["inferior"]), limite["superior"])
            if abs(recortado - actuales[indice]) < 1e-4:
                raise ErrorHmi(f"{nombre} ya está en su límite")
            valor = recortado
        objetivo = dict(zip(brazo.articulaciones, actuales))
        objetivo[nombre] = valor
        return self.mover_articulaciones(
            [brazo], objetivo, f"{brazo.nombre}: J{indice + 1} {math.degrees(delta):+.1f}°",
            tipo="jog")

    def jog_cartesiano(self, brazo: Brazo, traslacion: Sequence[float],
                       rotacion: Sequence[float], marco_herramienta: bool) -> Dict[str, Any]:
        self._comprobar()
        if not self.cli_cartesiano.service_is_ready():
            raise ErrorHmi("Servicio compute_cartesian_path no disponible", 503)
        pose = self.estado_robot.pose_efector(brazo.efector, timeout_s=0.5)
        if pose is None:
            raise ErrorHmi(f"No se conoce la pose de {brazo.efector} (TF)", 503)
        posicion, orientacion = geometria.desplazar_pose(
            pose["posicion"], pose["orientacion"], traslacion, rotacion, marco_herramienta)

        peticion = GetCartesianPath.Request()
        peticion.header.frame_id = self.config.marco_referencia
        peticion.start_state.is_diff = True
        peticion.group_name = brazo.grupo_moveit
        peticion.link_name = brazo.efector
        peticion.waypoints = [pose_msg(posicion, orientacion)]
        peticion.max_step = 0.005
        peticion.jump_threshold = 0.0
        peticion.avoid_collisions = True
        velocidad = self.velocidad([brazo])
        peticion.max_velocity_scaling_factor = velocidad
        peticion.max_acceleration_scaling_factor = min(
            1.0, velocidad * float(self.cfg.get("aceleracion_relativa", 1.0)))

        mm = [round(v * 1000, 1) for v in traslacion]
        grados = [round(math.degrees(v), 1) for v in rotacion]
        texto = "".join(f" {eje}{v:+g}mm" for eje, v in zip("XYZ", mm) if v) + "".join(
            f" R{eje}{v:+g}°" for eje, v in zip("xyz", grados) if v)
        tarea = self.tareas.nueva(
            self.ambito([brazo]), "cartesiano",
            f"{brazo.nombre}:{texto} ({'herramienta' if marco_herramienta else 'mundo'})",
            cancelar=self._ambitos_en_conflicto([brazo]))
        self.tareas.actualizar(tarea, T.PLANIFICANDO, "Calculando trayectoria cartesiana")
        futuro = self.cli_cartesiano.call_async(peticion)
        futuro.add_done_callback(lambda f: self._tras_cartesiano(f, tarea))
        return tarea.a_dict()

    def _tras_cartesiano(self, futuro, tarea: T.Tarea) -> None:
        if tarea.cancelar_pendiente or tarea.terminada:
            return
        try:
            respuesta = futuro.result()
        except Exception as e:  # noqa: BLE001
            self.tareas.actualizar(tarea, T.ERROR, f"compute_cartesian_path falló: {e}")
            return
        if respuesta.error_code.val != MoveItErrorCodes.SUCCESS:
            self.tareas.actualizar(tarea, T.ERROR, mensaje_moveit(respuesta.error_code.val))
            return
        minima = float(self.cfg.get("fraccion_cartesiana_minima", 0.95))
        if respuesta.fraction < minima:
            self.tareas.actualizar(
                tarea, T.ERROR,
                f"Solo es alcanzable el {respuesta.fraction * 100:.0f} % del recorrido "
                "(límite, singularidad o colisión)")
            return
        seguridad = self.ctx.modulo("seguridad")
        if seguridad is not None and seguridad.activa:
            self.tareas.actualizar(tarea, T.CANCELADA, "Parada de emergencia")
            return
        goal = ExecuteTrajectory.Goal()
        goal.trajectory = respuesta.solution
        self.tareas.enviar_objetivo(self.cli_ejecutar, goal, tarea, interpretar_moveit,
                                    nombre_servidor="execute_trajectory")

    def ir_a_pose(self, brazo: Brazo, posicion: Sequence[float],
                  orientacion: Sequence[float]) -> Dict[str, Any]:
        """Lleva el efector a una pose absoluta (planificación con cinemática inversa)."""
        self._comprobar()
        objetivo = pose_msg(posicion, orientacion)
        marco = self.config.marco_referencia

        r_posicion = PositionConstraint()
        r_posicion.header.frame_id = marco
        r_posicion.link_name = brazo.efector
        r_posicion.constraint_region.primitives.append(
            SolidPrimitive(type=SolidPrimitive.SPHERE, dimensions=[0.001]))
        r_posicion.constraint_region.primitive_poses.append(objetivo)
        r_posicion.weight = 1.0

        r_orientacion = OrientationConstraint()
        r_orientacion.header.frame_id = marco
        r_orientacion.link_name = brazo.efector
        r_orientacion.orientation = objetivo.orientation
        r_orientacion.absolute_x_axis_tolerance = 0.01
        r_orientacion.absolute_y_axis_tolerance = 0.01
        r_orientacion.absolute_z_axis_tolerance = 0.01
        r_orientacion.weight = 1.0

        restricciones = Constraints()
        restricciones.position_constraints.append(r_posicion)
        restricciones.orientation_constraints.append(r_orientacion)
        mm = ", ".join(f"{v * 1000:.0f}" for v in posicion)
        return self._enviar_move_group([brazo], restricciones, "pose",
                                       f"{brazo.nombre}: ir a pose ({mm}) mm")

    # --- Parada -----------------------------------------------------------------------

    def parar(self, objetivo: Optional[str], motivo: str = "Parado por el usuario") -> int:
        """Cancela los movimientos y ordena a los controladores mantener la posición."""
        brazos = self.config.brazos if objetivo in (None, AMBOS) else self.brazos_de(objetivo)
        for brazo in brazos:
            self.mantener_posicion(brazo)
        canceladas = self.tareas.cancelar(f"movimiento:{AMBOS}", exacto=True, motivo=motivo)
        for brazo in brazos:
            canceladas += self.tareas.cancelar(f"movimiento:{brazo.id}", exacto=True,
                                               motivo=motivo)
        return canceladas

    def mantener_posicion(self, brazo: Brazo) -> None:
        """Envía al controlador de trayectoria un único punto: la posición actual."""
        try:
            actuales = self.estado_robot.posiciones(brazo.articulaciones)
        except ErrorHmi:
            return
        msg = JointTrajectory()
        msg.joint_names = list(brazo.articulaciones)
        punto = JointTrajectoryPoint()
        punto.positions = [float(v) for v in actuales]
        punto.velocities = [0.0] * len(actuales)
        punto.time_from_start = DuracionMsg(sec=0, nanosec=100_000_000)
        msg.points = [punto]
        self.pub_trayectoria[brazo.id].publish(msg)

    # --- Escena de planificación ------------------------------------------------------

    def _vigilar_escena(self) -> None:
        """Aplica los objetos de config.escena cada vez que aparece move_group."""
        while not self._parar_hilo.wait(2.0):
            listo = self.cli_escena.service_is_ready()
            if listo and not self._escena_aplicada:
                self._escena_aplicada = self.aplicar_escena()
            elif not listo:
                self._escena_aplicada = False

    def aplicar_escena(self) -> bool:
        objetos = self.config.seccion("escena", [])
        if not objetos:
            return True
        escena = PlanningScene()
        escena.is_diff = True
        escena.robot_state.is_diff = True
        for objeto in objetos:
            caja = CollisionObject()
            caja.id = str(objeto["id"])
            caja.header.frame_id = objeto.get("marco", self.config.marco_referencia)
            caja.primitives.append(SolidPrimitive(
                type=SolidPrimitive.BOX, dimensions=[float(v) for v in objeto["tamano"]]))
            rpy = objeto.get("rpy", [0.0, 0.0, 0.0])
            caja.primitive_poses.append(pose_msg(objeto.get("posicion", [0, 0, 0]),
                                                 geometria.desde_rpy(*rpy)))
            caja.operation = CollisionObject.ADD
            escena.world.collision_objects.append(caja)
        self.cli_escena.call_async(ApplyPlanningScene.Request(scene=escena))
        self.log.info(f"Escena de planificación: {len(objetos)} objeto(s) añadidos")
        return True

    # --- Rutas ------------------------------------------------------------------------

    def _ruta_articulaciones(self, peticion) -> Dict[str, Any]:
        datos = peticion.json()
        brazos = self.brazos_de(str(requerir(datos, "brazo")))
        posiciones = requerir(datos, "posiciones")
        objetivo: Dict[str, float] = {}
        if isinstance(posiciones, dict):  # {id_brazo: [...]} para varios brazos
            for brazo in brazos:
                valores = posiciones.get(brazo.id, posiciones.get(brazo.sufijo))
                if valores is None:
                    raise ErrorHmi(f"Faltan las posiciones de {brazo.id}")
                objetivo.update(self._emparejar(brazo, valores))
        else:
            if len(brazos) != 1:
                raise ErrorHmi("Con 'ambos', 'posiciones' debe ser {id_brazo: [...]}")
            objetivo = self._emparejar(brazos[0], posiciones)
        nombre = brazos[0].nombre if len(brazos) == 1 else "Ambos brazos"
        return self.mover_articulaciones(brazos, objetivo, f"{nombre}: objetivo articular")

    @staticmethod
    def _emparejar(brazo: Brazo, valores) -> Dict[str, float]:
        if len(valores) != len(brazo.articulaciones):
            raise ErrorHmi(f"Se esperaban {len(brazo.articulaciones)} valores para {brazo.id}")
        return {n: float(v) for n, v in zip(brazo.articulaciones, valores)}

    def _ruta_jog_articular(self, peticion) -> Dict[str, Any]:
        datos = peticion.json()
        brazo = self.brazos_de(str(requerir(datos, "brazo")))[0]
        return self.jog_articular(brazo, requerir(datos, "indice", int),
                                  requerir(datos, "delta", float))

    def _ruta_jog_cartesiano(self, peticion) -> Dict[str, Any]:
        datos = peticion.json()
        brazo = self.brazos_de(str(requerir(datos, "brazo")))[0]
        traslacion = [float(v) for v in datos.get("traslacion", [0, 0, 0])]
        rotacion = [float(v) for v in datos.get("rotacion", [0, 0, 0])]
        if len(traslacion) != 3 or len(rotacion) != 3:
            raise ErrorHmi("traslacion y rotacion deben tener 3 componentes")
        if max(abs(v) for v in traslacion) > 0.2 or max(abs(v) for v in rotacion) > 1.0:
            raise ErrorHmi("Paso demasiado grande (máx. 200 mm y 57°)")
        return self.jog_cartesiano(brazo, traslacion, rotacion,
                                   datos.get("marco", "mundo") == "herramienta")

    def _ruta_pose(self, peticion) -> Dict[str, Any]:
        datos = peticion.json()
        brazo = self.brazos_de(str(requerir(datos, "brazo")))[0]
        posicion = [float(v) for v in requerir(datos, "posicion")]
        if "orientacion" in datos:
            orientacion = geometria.normalizar([float(v) for v in datos["orientacion"]])
        else:
            orientacion = geometria.desde_rpy(*[float(v) for v in requerir(datos, "rpy")])
        return self.ir_a_pose(brazo, posicion, orientacion)

    def _ruta_parar(self, peticion) -> Dict[str, Any]:
        objetivo = peticion.json().get("brazo")
        return {"canceladas": self.parar(str(objetivo) if objetivo else None)}

    def _ruta_velocidad(self, peticion) -> Dict[str, Any]:
        datos = peticion.json()
        valor = requerir(datos, "valor", float)
        if not math.isfinite(valor):
            raise ErrorHmi("Velocidad inválida")
        valor = min(max(valor, 0.01), self.vel_maxima)
        objetivo = datos.get("brazo") or AMBOS
        for brazo in self.brazos_de(str(objetivo)):
            self.velocidades[brazo.id] = valor
        self.bus.emitir("velocidad", dict(self.velocidades))
        return {"velocidades": self.velocidades}

    def _ruta_escena(self, peticion) -> Dict[str, Any]:
        if not self.cli_escena.service_is_ready():
            raise ErrorHmi("move_group no está disponible", 503)
        self.aplicar_escena()
        return {"objetos": len(self.config.seccion("escena", []))}

    # --- Estado e info ----------------------------------------------------------------

    def info(self) -> Dict[str, Any]:
        return {
            "velocidad_maxima": self.vel_maxima,
            "pasos_articulares_grados": self.cfg.get("pasos_articulares_grados", [1, 5, 10]),
            "pasos_cartesianos_mm": self.cfg.get("pasos_cartesianos_mm", [1, 5, 10]),
            "pasos_rotacion_grados": self.cfg.get("pasos_rotacion_grados", [1, 5, 10]),
            "escena": self.config.seccion("escena", []),
        }

    def estado(self) -> Dict[str, Any]:
        activas = self.tareas.activas()
        return {
            "disponible": self.cli_mover.server_is_ready(),
            "cartesiano": self.cli_cartesiano.service_is_ready(),
            "velocidades": self.velocidades,
            "tareas": {a.split(":", 1)[1]: t for a, t in activas.items()
                       if a.startswith("movimiento:")},
        }
