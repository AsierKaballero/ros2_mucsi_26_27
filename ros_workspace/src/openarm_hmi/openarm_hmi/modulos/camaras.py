"""Cámaras: vídeo en el navegador, capturas y galería descargable.

Cada cámara es un topic sensor_msgs/Image o sensor_msgs/CompressedImage. La suscripción se
crea al pedir el primer fotograma y se cancela tras `inactividad_s` sin peticiones, así que
una cámara que nadie mira no consume CPU. El navegador pide los fotogramas uno a uno
(long-polling): `GET /frame?desde=N` espera a que haya uno posterior al N y lo devuelve
en JPEG; así un navegador lento recibe menos fotogramas en lugar de acumular retraso, y no
se ocupan conexiones permanentes.

Rutas:
  GET    /api/camaras                       cámaras + topics de imagen disponibles
  POST   /api/camaras                       {topic, nombre?}  añade una cámara temporal
  DELETE /api/camaras/{id}                  quita una cámara temporal
  GET    /api/camaras/{id}/frame?desde=N    siguiente fotograma (JPEG; cabecera X-Seq)
  POST   /api/camaras/{id}/captura          guarda una captura ({id}=todas: todas)
  GET    /api/capturas                      galería
  GET    /api/capturas/zip                  todas las capturas en un .zip
  DELETE /api/capturas/{archivo}
  GET    /capturas/{archivo}[?descargar=1]
"""

import datetime
import io
import os
import re
import threading
import time
import zipfile
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, Image

from openarm_hmi.nucleo.configuracion import rellenar
from openarm_hmi.nucleo.modulo import Modulo, requerir
from openarm_hmi.nucleo.servidor import ErrorHmi, Respuesta, respuesta_fichero, ruta_segura

TIPO_IMAGEN = "sensor_msgs/msg/Image"
TIPO_COMPRIMIDA = "sensor_msgs/msg/CompressedImage"
ARCHIVO_VALIDO = re.compile(r"^[\w.\-]+\.(jpg|png)$")


def imagen_a_bgr(msg: Image) -> np.ndarray:
    """Convierte un sensor_msgs/Image a una matriz BGR (o gris) de OpenCV."""
    codificacion = msg.encoding.lower()
    alto, ancho, paso = msg.height, msg.width, msg.step
    datos = np.frombuffer(bytes(msg.data), dtype=np.uint8)

    def filas(bytes_por_pixel: int) -> np.ndarray:
        return datos.reshape(alto, paso)[:, :ancho * bytes_por_pixel]

    if codificacion in ("bgr8", "rgb8", "8uc3"):
        imagen = filas(3).reshape(alto, ancho, 3)
        return cv2.cvtColor(imagen, cv2.COLOR_RGB2BGR) if codificacion == "rgb8" else imagen
    if codificacion in ("bgra8", "rgba8", "8uc4"):
        imagen = filas(4).reshape(alto, ancho, 4)
        conversion = cv2.COLOR_RGBA2BGR if codificacion == "rgba8" else cv2.COLOR_BGRA2BGR
        return cv2.cvtColor(imagen, conversion)
    if codificacion in ("mono8", "8uc1"):
        return filas(1).reshape(alto, ancho)
    if codificacion in ("yuv422_yuy2", "yuyv"):
        return cv2.cvtColor(filas(2).reshape(alto, ancho, 2), cv2.COLOR_YUV2BGR_YUYV)
    if codificacion in ("yuv422", "uyvy"):
        return cv2.cvtColor(filas(2).reshape(alto, ancho, 2), cv2.COLOR_YUV2BGR_UYVY)
    if codificacion in ("mono16", "16uc1", "32fc1"):
        tipo = np.float32 if codificacion == "32fc1" else np.uint16
        orden = ">" if msg.is_bigendian else "<"
        valores = np.frombuffer(bytes(msg.data), dtype=np.dtype(tipo).newbyteorder(orden))
        valores = valores.reshape(alto, paso // np.dtype(tipo).itemsize)[:, :ancho]
        valores = np.nan_to_num(valores.astype(np.float32))
        return cv2.normalize(valores, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    raise ValueError(f"Codificación de imagen no soportada: {msg.encoding}")


def nombre_seguro(texto: str) -> str:
    return re.sub(r"[^\w\-]+", "_", texto).strip("_") or "camara"


class Camara:
    def __init__(self, modulo: "Camaras", id_camara: str, nombre: str, topic: str,
                 brazo: Optional[str] = None, temporal: bool = False) -> None:
        self.modulo = modulo
        self.id = id_camara
        self.nombre = nombre
        self.topic = topic
        self.brazo = brazo
        self.temporal = temporal
        self.grupo = MutuallyExclusiveCallbackGroup()
        self.sub = None
        self.tipo: Optional[str] = None
        self.condicion = threading.Condition()
        self.jpeg: Optional[bytes] = None
        self.seq = 0
        self.ultimo_msg = None
        self.t_ultimo = 0.0
        self.t_ultimo_jpeg = 0.0
        self.ultima_peticion = 0.0
        self.fps = 0.0
        self.ancho = 0
        self.alto = 0
        self.error = ""

    # --- Suscripción ------------------------------------------------------------------

    def asegurar_suscripcion(self) -> None:
        self.ultima_peticion = time.time()
        if self.sub is not None:
            return
        tipos = dict(self.modulo.nodo.get_topic_names_and_types())
        tipo = tipos.get(self.topic, [])
        if TIPO_COMPRIMIDA in tipo:
            clase, self.tipo = CompressedImage, "comprimida"
        elif TIPO_IMAGEN in tipo:
            clase, self.tipo = Image, "raw"
        else:
            self.error = ("Topic no publicado" if not tipo
                          else f"Tipo no soportado: {', '.join(tipo)}")
            return
        self.error = ""
        self.sub = self.modulo.nodo.create_subscription(
            clase, self.topic, self._cb, qos_profile_sensor_data, callback_group=self.grupo)

    def liberar(self) -> None:
        if self.sub is not None:
            self.modulo.nodo.destroy_subscription(self.sub)
            self.sub = None
            self.fps = 0.0

    def _cb(self, msg) -> None:
        ahora = time.time()
        if self.t_ultimo:
            intervalo = ahora - self.t_ultimo
            if intervalo > 0:
                self.fps = 0.9 * self.fps + 0.1 * (1.0 / intervalo) if self.fps else 1.0 / intervalo
        self.t_ultimo = ahora
        self.ultimo_msg = msg
        if ahora - self.t_ultimo_jpeg < 1.0 / self.modulo.fps_maximo:
            return
        try:
            jpeg = self._a_jpeg(msg, self.modulo.calidad)
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            return
        self.error = ""
        self.t_ultimo_jpeg = ahora
        with self.condicion:
            self.jpeg = jpeg
            self.seq += 1
            self.condicion.notify_all()

    def _a_jpeg(self, msg, calidad: int) -> bytes:
        if self.tipo == "comprimida":
            if "jpeg" in msg.format.lower() or "jpg" in msg.format.lower():
                if not self.ancho:
                    imagen = cv2.imdecode(np.frombuffer(bytes(msg.data), np.uint8),
                                          cv2.IMREAD_COLOR)
                    if imagen is not None:
                        self.alto, self.ancho = imagen.shape[:2]
                return bytes(msg.data)
            imagen = cv2.imdecode(np.frombuffer(bytes(msg.data), np.uint8), cv2.IMREAD_COLOR)
            if imagen is None:
                raise ValueError(f"No se pudo decodificar la imagen ({msg.format})")
        else:
            imagen = imagen_a_bgr(msg)
        self.alto, self.ancho = imagen.shape[:2]
        ok, datos = cv2.imencode(".jpg", imagen, [cv2.IMWRITE_JPEG_QUALITY, int(calidad)])
        if not ok:
            raise ValueError("Fallo al codificar JPEG")
        return datos.tobytes()

    # --- Acceso -----------------------------------------------------------------------

    def siguiente(self, desde: int, espera_s: float) -> Optional[Tuple[int, bytes]]:
        self.asegurar_suscripcion()
        with self.condicion:
            if self.seq <= desde or self.jpeg is None:
                self.condicion.wait_for(lambda: self.seq > desde and self.jpeg is not None,
                                        timeout=espera_s)
            if self.jpeg is None or self.seq <= desde:
                return None
            return self.seq, self.jpeg

    def captura(self, calidad: int) -> bytes:
        msg = self.ultimo_msg
        if msg is None or time.time() - self.t_ultimo > 5.0:
            raise ErrorHmi(f"{self.nombre}: sin imagen reciente", 409)
        return self._a_jpeg(msg, calidad)

    def a_dict(self) -> Dict[str, Any]:
        edad = time.time() - self.t_ultimo if self.t_ultimo else None
        return {"id": self.id, "nombre": self.nombre, "topic": self.topic, "brazo": self.brazo,
                "temporal": self.temporal, "activa": self.sub is not None, "tipo": self.tipo,
                "fps": round(self.fps, 1), "ancho": self.ancho, "alto": self.alto,
                "edad": round(edad, 2) if edad is not None else None, "error": self.error}


class Camaras(Modulo):
    nombre = "camaras"

    def iniciar(self) -> None:
        cfg = self.config.seccion("camaras")
        self.fps_maximo = float(cfg.get("fps_maximo", 15))
        self.calidad = int(cfg.get("calidad_jpeg", 80))
        self.calidad_captura = int(cfg.get("calidad_captura", 95))
        self.inactividad = float(cfg.get("inactividad_s", 10))
        self.directorio = os.path.join(self.config.directorio_datos, "capturas")
        self.camaras: Dict[str, Camara] = {}
        self._candado = threading.Lock()

        plantilla = cfg.get("por_brazo")
        if plantilla:
            for brazo in self.config.brazos:
                datos = rellenar(plantilla, self.config.variables_brazo(brazo))
                self._agregar(Camara(self, str(datos["id"]), datos.get("nombre", brazo.nombre),
                                     datos["topic"], brazo=brazo.id))
        for datos in cfg.get("adicionales", []) or []:
            self._agregar(Camara(self, str(datos["id"]), datos.get("nombre", datos["id"]),
                                 datos["topic"], brazo=datos.get("brazo")))

        self._parar = threading.Event()
        threading.Thread(target=self._limpieza, daemon=True, name="camaras").start()

        self.ruta("GET", "/api/camaras", self._ruta_listado)
        self.ruta("POST", "/api/camaras", self._ruta_agregar)
        self.ruta("DELETE", "/api/camaras/{id}", self._ruta_quitar)
        self.ruta("GET", "/api/camaras/{id}/frame", self._ruta_frame)
        self.ruta("POST", "/api/camaras/{id}/captura", self._ruta_captura)
        self.ruta("GET", "/api/capturas", lambda p: self.galeria())
        self.ruta("GET", "/api/capturas/zip", self._ruta_zip)
        self.ruta("DELETE", "/api/capturas/{archivo}", self._ruta_borrar_captura)
        self.ruta("GET", "/capturas/{archivo}", self._ruta_archivo)

    def detener(self) -> None:
        self._parar.set()

    def _agregar(self, camara: Camara) -> None:
        with self._candado:
            self.camaras[camara.id] = camara

    def camara(self, id_camara: str) -> Camara:
        with self._candado:
            if id_camara not in self.camaras:
                raise ErrorHmi(f"Cámara desconocida: {id_camara}", 404)
            return self.camaras[id_camara]

    def _limpieza(self) -> None:
        while not self._parar.wait(2.0):
            ahora = time.time()
            with self._candado:
                camaras = list(self.camaras.values())
            for camara in camaras:
                if camara.sub is not None and ahora - camara.ultima_peticion > self.inactividad:
                    camara.liberar()

    def topics_imagen(self) -> List[Dict[str, str]]:
        return [{"topic": nombre, "tipo": tipo}
                for nombre, tipos in self.nodo.get_topic_names_and_types()
                for tipo in tipos if tipo in (TIPO_IMAGEN, TIPO_COMPRIMIDA)]

    # --- Capturas ---------------------------------------------------------------------

    def capturar(self, camara: Camara) -> Dict[str, Any]:
        datos = camara.captura(self.calidad_captura)
        os.makedirs(self.directorio, exist_ok=True)
        instante = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        archivo = f"{nombre_seguro(camara.id)}_{instante}.jpg"
        with open(os.path.join(self.directorio, archivo), "wb") as f:
            f.write(datos)
        self.log.info(f"Captura de {camara.nombre}: {archivo}")
        entrada = self._entrada(archivo)
        self.bus.emitir("captura", entrada)
        return entrada

    def _entrada(self, archivo: str) -> Dict[str, Any]:
        ruta = os.path.join(self.directorio, archivo)
        info = os.stat(ruta)
        return {"archivo": archivo, "url": f"/capturas/{archivo}",
                "descarga": f"/capturas/{archivo}?descargar=1",
                "tamano": info.st_size, "fecha": info.st_mtime}

    def galeria(self) -> Dict[str, Any]:
        if not os.path.isdir(self.directorio):
            return {"capturas": [], "directorio": self.directorio}
        archivos = [a for a in os.listdir(self.directorio) if ARCHIVO_VALIDO.match(a)]
        capturas = sorted((self._entrada(a) for a in archivos), key=lambda e: -e["fecha"])
        return {"capturas": capturas, "directorio": self.directorio}

    def _archivo(self, archivo: str) -> str:
        if not ARCHIVO_VALIDO.match(archivo):
            raise ErrorHmi("Nombre de archivo inválido", 400)
        return ruta_segura(self.directorio, archivo)

    # --- Rutas ------------------------------------------------------------------------

    def _ruta_listado(self, peticion) -> Dict[str, Any]:
        with self._candado:
            camaras = [c.a_dict() for c in self.camaras.values()]
        return {"camaras": camaras, "topics": self.topics_imagen()}

    def _ruta_agregar(self, peticion) -> Dict[str, Any]:
        datos = peticion.json()
        topic = str(requerir(datos, "topic"))
        if not topic.startswith("/"):
            raise ErrorHmi("El topic debe empezar por /")
        id_camara = nombre_seguro(datos.get("id") or topic)
        camara = Camara(self, id_camara, str(datos.get("nombre") or topic), topic,
                        temporal=True)
        self._agregar(camara)
        return camara.a_dict()

    def _ruta_quitar(self, peticion) -> None:
        camara = self.camara(peticion.params["id"])
        if not camara.temporal:
            raise ErrorHmi("Las cámaras de la configuración no se pueden quitar")
        camara.liberar()
        with self._candado:
            del self.camaras[camara.id]

    def _ruta_frame(self, peticion) -> Any:
        camara = self.camara(peticion.params["id"])
        try:
            desde = int(peticion.q("desde", 0))
        except ValueError:
            desde = 0
        resultado = camara.siguiente(desde, espera_s=2.0)
        if resultado is None:
            return None  # 204: sin fotograma nuevo (el navegador vuelve a pedir)
        seq, jpeg = resultado
        return Respuesta(jpeg, "image/jpeg", 200,
                         {"X-Seq": str(seq), "Cache-Control": "no-store"})

    def _ruta_captura(self, peticion) -> Any:
        id_camara = peticion.params["id"]
        if id_camara != "todas":
            return self.capturar(self.camara(id_camara))
        with self._candado:
            camaras = list(self.camaras.values())
        capturas, errores = [], []
        for camara in camaras:
            if camara.sub is None:
                continue
            try:
                capturas.append(self.capturar(camara))
            except ErrorHmi as e:
                errores.append(e.mensaje)
        if not capturas:
            raise ErrorHmi("Ninguna cámara activa con imagen" +
                           (f": {'; '.join(errores)}" if errores else ""), 409)
        return {"capturas": capturas, "errores": errores}

    def _ruta_zip(self, peticion) -> Respuesta:
        memoria = io.BytesIO()
        with zipfile.ZipFile(memoria, "w", zipfile.ZIP_STORED) as z:
            for entrada in self.galeria()["capturas"]:
                z.write(os.path.join(self.directorio, entrada["archivo"]), entrada["archivo"])
        nombre = f"capturas_{datetime.datetime.now():%Y%m%d_%H%M%S}.zip"
        return Respuesta(memoria.getvalue(), "application/zip", 200,
                         {"Content-Disposition": f'attachment; filename="{nombre}"'})

    def _ruta_borrar_captura(self, peticion) -> None:
        os.remove(self._archivo(peticion.params["archivo"]))

    def _ruta_archivo(self, peticion) -> Respuesta:
        return respuesta_fichero(self._archivo(peticion.params["archivo"]),
                                 descargar=peticion.q("descargar") == "1", cache_s=3600)

    def estado(self) -> Dict[str, Any]:
        with self._candado:
            return {c.id: {"activa": c.sub is not None, "fps": round(c.fps, 1),
                           "edad": round(time.time() - c.t_ultimo, 1) if c.t_ultimo else None,
                           "error": c.error} for c in self.camaras.values()}

    def info(self) -> Dict[str, Any]:
        with self._candado:
            return {"camaras": [c.a_dict() for c in self.camaras.values()]}
