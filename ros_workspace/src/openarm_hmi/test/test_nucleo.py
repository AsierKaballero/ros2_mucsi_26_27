"""Pruebas de las piezas del núcleo que no necesitan ROS (se pueden ejecutar con pytest
fuera del contenedor: `python -m pytest test/`)."""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from openarm_hmi.nucleo import geometria  # noqa: E402
from openarm_hmi.nucleo.configuracion import cargar, desde_dict, rellenar  # noqa: E402
from openarm_hmi.nucleo.servidor import Enrutador, ErrorHmi, ruta_segura  # noqa: E402
from openarm_hmi.nucleo import tareas as T  # noqa: E402

CONFIG = os.path.join(os.path.dirname(__file__), "..", "config", "openarm.yaml")


# --- Configuración ------------------------------------------------------------------

def test_rellenar_deja_variables_desconocidas():
    assert rellenar("robot_{brazo}_{x}", {"brazo": "301_izq"}) == "robot_301_izq_{x}"
    assert rellenar({"a": ["{cuerpo}"]}, {"cuerpo": "302"}) == {"a": ["302"]}


def test_config_por_defecto_301():
    config = cargar(CONFIG)
    assert config.cuerpo == "301"
    assert config.ids_brazos == ["301_izq", "301_der"]
    izq = config.brazo("izq")
    assert izq.articulaciones[0] == "301_izq_joint1"
    assert len(izq.articulaciones) == 7
    assert izq.grupo_moveit == "robot_301_izq"
    assert izq.efector == "301_izq_grasp_frame"
    assert izq.controlador_trayectoria == "robot_301_izq_joint_trajectory_controller"
    assert izq.pinza.accion == "/robot_301_izq/gripper_action"
    assert config.grupo_conjunto == "robots_301"


def test_config_cuerpo_302_y_sobrescritura():
    config = cargar(CONFIG, "302", {"servidor.puerto": 9000, "servidor.host": ""})
    assert config.ids_brazos == ["302_izq", "302_der"]
    assert config.seccion("servidor")["puerto"] == 9000
    assert config.seccion("servidor")["host"] == "127.0.0.1"  # "" no sobrescribe
    perfiles = {p["id"]: p for p in config.seccion("sistema")["perfiles"]}
    assert "sim_302.launch.py" in perfiles["sim"]["comando"]
    # Las variables de los scripts se resuelven al ejecutarlos, no al cargar
    script = config.seccion("scripts")[0]
    assert "{brazos}" in script["comando"]
    assert script["parametros"][0]["defecto"] == "302_izq"


def test_pinza_rad_a_mm():
    pinza = cargar(CONFIG).brazo("der").pinza
    assert pinza.rad_a_mm(-0.7854) == pytest.approx(146.2)
    assert pinza.rad_a_mm(0.0) == 0.0


def test_config_minima():
    config = desde_dict({"robot": {"brazos": [{"sufijo": "a"}], "por_brazo": {
        "articulaciones": ["{brazo}_j1"], "pinza": {}}}}, cuerpo="9")
    assert config.brazos[0].articulaciones == ["9_a_j1"]


# --- Geometría ----------------------------------------------------------------------

def test_rpy_ida_y_vuelta():
    for rpy in [(0.1, -0.4, 2.0), (0.0, 0.0, 0.0), (-1.2, 0.3, -2.9)]:
        assert geometria.a_rpy(geometria.desde_rpy(*rpy)) == pytest.approx(rpy, abs=1e-9)


def test_rotar_vector():
    q = geometria.desde_rpy(0, 0, math.pi / 2)
    assert geometria.rotar(q, (1, 0, 0)) == pytest.approx((0, 1, 0), abs=1e-9)


def test_desplazar_pose_mundo_y_herramienta():
    q = geometria.desde_rpy(0, 0, math.pi / 2)  # herramienta girada 90° en Z
    p, q2 = geometria.desplazar_pose((1, 2, 3), q, (0.1, 0, 0), (0, 0, 0), False)
    assert p == pytest.approx((1.1, 2, 3))
    assert q2 == pytest.approx(q)
    p, _ = geometria.desplazar_pose((1, 2, 3), q, (0.1, 0, 0), (0, 0, 0), True)
    assert p == pytest.approx((1, 2.1, 3), abs=1e-9)  # X de la herramienta = Y del mundo
    _, q3 = geometria.desplazar_pose((0, 0, 0), (0, 0, 0, 1), (0, 0, 0), (0, 0, 0.3), False)
    assert geometria.a_rpy(q3)[2] == pytest.approx(0.3)


# --- Servidor -----------------------------------------------------------------------

def test_enrutador_parametros_y_metodos():
    e = Enrutador()
    e.agregar("GET", "/api/poses/{nombre}", lambda p: "uno")
    e.agregar("POST", "/api/poses/{nombre}/ir", lambda p: "dos")
    e.agregar("GET", "/paquetes/{paquete}/{ruta:*}", lambda p: "tres")
    funcion, params = e.buscar("GET", "/api/poses/home%20alta")
    assert funcion(None) == "uno" and params == {"nombre": "home alta"}
    funcion, params = e.buscar("POST", "/api/poses/home/ir")
    assert funcion(None) == "dos"
    funcion, permitidos = e.buscar("DELETE", "/api/poses/home")
    assert funcion is None and permitidos == ["GET"]
    funcion, params = e.buscar("GET", "/paquetes/pkg/a/b/c.dae")
    assert params == {"paquete": "pkg", "ruta": "a/b/c.dae"}


def test_ruta_segura(tmp_path):
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_text("hola")
    (tmp_path / "secreto.txt").write_text("no")
    raiz = str(tmp_path / "web")
    assert ruta_segura(raiz, "/index.html").endswith("index.html")
    with pytest.raises(ErrorHmi) as error:
        ruta_segura(raiz, "/../secreto.txt")
    assert error.value.estado == 403
    with pytest.raises(ErrorHmi) as error:
        ruta_segura(raiz, "/no_existe.js")
    assert error.value.estado == 404


# --- Tareas -------------------------------------------------------------------------

class BusFalso:
    def __init__(self):
        self.eventos = []

    def emitir(self, evento, datos=None, navegador=True):
        self.eventos.append((evento, datos))


class LogFalso:
    def warning(self, *a):
        pass


def test_tareas_ambito_y_cancelacion():
    bus = BusFalso()
    gestor = T.GestorTareas(bus, LogFalso())
    primera = gestor.nueva("movimiento:301_izq", "jog", "uno")
    segunda = gestor.nueva("movimiento:301_izq", "jog", "dos")
    assert primera.estado == T.CANCELADA  # la nueva del mismo ámbito cancela la anterior
    assert gestor.activa("movimiento:301_izq") is segunda
    conjunta = gestor.nueva("movimiento:ambos", "pose", "tres", cancelar=["movimiento:301_izq"])
    assert segunda.estado == T.CANCELADA
    gestor.actualizar(conjunta, T.COMPLETADA, "ok")
    assert gestor.activas() == {}
    gestor.actualizar(conjunta, T.ERROR, "tarde")  # una tarea terminada no cambia
    assert conjunta.estado == T.COMPLETADA
    assert [t["descripcion"] for t in gestor.historial()][:1] == ["tres"]


def test_tareas_servidor_no_disponible():
    class Cliente:
        def server_is_ready(self):
            return False

    gestor = T.GestorTareas(BusFalso(), LogFalso())
    tarea = gestor.nueva("pinza:301_izq", "pinza", "x")
    gestor.enviar_objetivo(Cliente(), object(), tarea, lambda r, s: (True, ""), nombre_servidor="/a")
    assert tarea.estado == T.ERROR and "no disponible" in tarea.mensaje


class FuturoFalso:
    def __init__(self):
        self.valor = None
        self.hecho = False
        self.callbacks = []

    def result(self):
        return self.valor

    def add_done_callback(self, cb):
        if self.hecho:
            cb(self)
        else:
            self.callbacks.append(cb)

    def completar(self, valor):
        self.valor, self.hecho = valor, True
        for cb in self.callbacks:
            cb(self)


class ServidorAccionFalso:
    """ActionClient falso: acepta los objetivos y deja terminarlos a mano."""

    def __init__(self):
        self.enviados = []
        self.cancelados = []

    def server_is_ready(self):
        return True

    def send_goal_async(self, objetivo, feedback_callback=None):
        servidor = self
        resultado = FuturoFalso()

        class Handle:
            accepted = True

            def get_result_async(self):
                return resultado

            def cancel_goal_async(self):
                servidor.cancelados.append(objetivo)

        self.enviados.append((objetivo, resultado))
        futuro = FuturoFalso()
        futuro.completar(Handle())
        return futuro


class RespuestaFalsa:
    def __init__(self, status):
        self.status = status
        self.result = None


def test_tareas_un_objetivo_a_la_vez_por_servidor():
    import time

    servidor = ServidorAccionFalso()
    gestor = T.GestorTareas(BusFalso(), LogFalso())
    ok = lambda r, s: (True, "ok")  # noqa: E731
    primera = gestor.nueva("movimiento:301_izq", "jog", "uno")
    gestor.enviar_objetivo(servidor, "A", primera, ok)
    assert [o for o, _ in servidor.enviados] == ["A"]

    # Otro brazo: espera a que el servidor termine el objetivo anterior
    segunda = gestor.nueva("movimiento:301_der", "jog", "dos")
    gestor.enviar_objetivo(servidor, "B", segunda, ok)
    time.sleep(0.3)
    assert [o for o, _ in servidor.enviados] == ["A"] and segunda.estado == T.PENDIENTE

    servidor.enviados[0][1].completar(RespuestaFalsa(4))
    assert primera.estado == T.COMPLETADA
    for _ in range(50):
        if len(servidor.enviados) == 2:
            break
        time.sleep(0.05)
    assert [o for o, _ in servidor.enviados] == ["A", "B"]

    # Mismo ámbito: la nueva cancela la anterior y no se envía hasta que el servidor la suelta
    tercera = gestor.nueva("movimiento:301_der", "jog", "tres")
    assert servidor.cancelados == ["B"] and segunda.estado == T.CANCELADA
    gestor.enviar_objetivo(servidor, "C", tercera, ok)
    time.sleep(0.3)
    assert len(servidor.enviados) == 2
    servidor.enviados[1][1].completar(RespuestaFalsa(5))
    for _ in range(50):
        if len(servidor.enviados) == 3:
            break
        time.sleep(0.05)
    assert [o for o, _ in servidor.enviados] == ["A", "B", "C"]
    assert segunda.estado == T.CANCELADA


def test_limites_urdf_ignora_ros2_control():
    from openarm_hmi.modulos.estado import limites_urdf

    urdf = """<robot name="r">
      <joint name="j1" type="revolute"><limit lower="-1" upper="2" velocity="1" effort="1"/></joint>
      <joint name="fijo" type="fixed"/>
      <ros2_control name="hw" type="system"><joint name="j1"><command_interface name="position"/></joint></ros2_control>
      <transmission name="t"><joint name="j1"/></transmission>
    </robot>"""
    limites = limites_urdf(urdf)
    assert limites == {"j1": {"tipo": "revolute", "inferior": -1.0, "superior": 2.0,
                              "velocidad": 1.0, "esfuerzo": 1.0}}
