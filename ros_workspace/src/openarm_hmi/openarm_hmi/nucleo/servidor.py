"""Servidor HTTP del HMI (biblioteca estándar): rutas REST, ficheros estáticos y flujos.

Cada módulo registra sus rutas con `Enrutador.agregar("GET", "/api/x/{param}", funcion)`.
La función recibe una `Peticion` y devuelve:
  - un dict/list  -> JSON (200)
  - None          -> 204 sin contenido
  - `Respuesta`   -> bytes con su tipo y cabeceras
  - `Flujo`       -> respuesta continua (SSE, MJPEG...) escrita por una función
Para devolver un error se lanza `ErrorHmi(mensaje, estado)`.
"""

import json
import mimetypes
import os
import re
import socket
import traceback
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlsplit

TIPOS_EXTRA = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".dae": "model/vnd.collada+xml",
    ".stl": "model/stl",
    ".urdf": "application/xml",
    ".yaml": "text/yaml; charset=utf-8",
    ".jpg": "image/jpeg",
    ".png": "image/png",
}


class ErrorHmi(Exception):
    def __init__(self, mensaje: str, estado: int = 400) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.estado = estado


@dataclass
class Respuesta:
    cuerpo: bytes
    tipo: str = "application/octet-stream"
    estado: int = 200
    cabeceras: Dict[str, str] = field(default_factory=dict)


@dataclass
class Flujo:
    """Respuesta continua: `escritor(escribir)` llama a escribir(bytes) hasta que acaba.

    escribir() lanza ConnectionError cuando el navegador se desconecta.
    """
    tipo: str
    escritor: Callable[[Callable[[bytes], None]], None]
    cabeceras: Dict[str, str] = field(default_factory=dict)


class Peticion:
    def __init__(self, metodo: str, ruta: str, query: Dict[str, List[str]],
                 params: Dict[str, str], cuerpo: bytes, cabeceras) -> None:
        self.metodo = metodo
        self.ruta = ruta
        self.query = query
        self.params = params
        self.cuerpo = cuerpo
        self.cabeceras = cabeceras
        self._json: Optional[Any] = None

    def q(self, nombre: str, defecto: Any = None) -> Any:
        valores = self.query.get(nombre)
        return valores[0] if valores else defecto

    def json(self) -> Dict[str, Any]:
        if self._json is None:
            if not self.cuerpo:
                self._json = {}
            else:
                try:
                    self._json = json.loads(self.cuerpo.decode("utf-8"))
                except (ValueError, UnicodeDecodeError) as e:
                    raise ErrorHmi(f"JSON inválido: {e}") from e
        return self._json


def _compilar(patron: str) -> "re.Pattern[str]":
    regex = re.sub(r"\{(\w+):\*\}", r"(?P<\1>.+)", patron)
    regex = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", regex)
    return re.compile(f"^{regex}$")


class Enrutador:
    def __init__(self) -> None:
        self._rutas: List[Tuple[str, "re.Pattern[str]", Callable]] = []

    def agregar(self, metodo: str, patron: str, funcion: Callable[[Peticion], Any]) -> None:
        self._rutas.append((metodo.upper(), _compilar(patron), funcion))

    def buscar(self, metodo: str, ruta: str):
        """Devuelve (funcion, params) o (None, metodos que sí admite la ruta)."""
        permitidos = []
        for m, regex, funcion in self._rutas:
            coincidencia = regex.match(ruta)
            if coincidencia:
                if m == metodo:
                    return funcion, {k: unquote(v) for k, v in coincidencia.groupdict().items()}
                permitidos.append(m)
        return None, permitidos

    def listado(self) -> List[Dict[str, str]]:
        return [{"metodo": m, "ruta": r.pattern} for m, r, _ in self._rutas]


def tipo_de(ruta: str) -> str:
    extension = os.path.splitext(ruta)[1].lower()
    return TIPOS_EXTRA.get(extension) or mimetypes.guess_type(ruta)[0] or "application/octet-stream"


def ruta_segura(raiz: str, relativa: str) -> str:
    """Une `relativa` a `raiz` comprobando que el resultado no se sale de `raiz`."""
    raiz_real = os.path.realpath(raiz)
    destino = os.path.realpath(os.path.join(raiz_real, relativa.lstrip("/")))
    # Con colcon --symlink-install los ficheros de share/ son enlaces a src/: se valida la
    # ruta antes de resolver enlaces y después se comprueba que existe
    normalizada = os.path.normpath(os.path.join(raiz, relativa.lstrip("/")))
    if not (normalizada == os.path.normpath(raiz)
            or normalizada.startswith(os.path.normpath(raiz) + os.sep)):
        raise ErrorHmi("Ruta no permitida", 403)
    if not os.path.isfile(destino):
        raise ErrorHmi("No encontrado", 404)
    return destino


def respuesta_fichero(ruta: str, descargar: bool = False, cache_s: int = 0) -> Respuesta:
    with open(ruta, "rb") as f:
        contenido = f.read()
    cabeceras = {"Cache-Control": f"max-age={cache_s}" if cache_s else "no-cache"}
    if descargar:
        cabeceras["Content-Disposition"] = f'attachment; filename="{os.path.basename(ruta)}"'
    return Respuesta(contenido, tipo_de(ruta), 200, cabeceras)


class _ServidorHilos(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Servidor:
    def __init__(self, host: str, puerto: int, enrutador: Enrutador, dir_web: str,
                 registrador) -> None:
        self.enrutador = enrutador
        self.dir_web = dir_web
        self.log = registrador
        self.http = _ServidorHilos((host, puerto), self._clase_manejador())

    def servir(self) -> None:
        self.http.serve_forever(poll_interval=0.5)

    def parar(self) -> None:
        self.http.shutdown()
        self.http.server_close()

    def _clase_manejador(self):
        servidor = self

        class Manejador(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "OpenArmHMI/0.1"

            def log_message(self, formato, *args):  # Silencia el registro por petición
                pass

            def do_GET(self):
                self._atender("GET")

            def do_POST(self):
                self._atender("POST")

            def do_PUT(self):
                self._atender("PUT")

            def do_DELETE(self):
                self._atender("DELETE")

            def _atender(self, metodo: str) -> None:
                partes = urlsplit(self.path)
                ruta = unquote(partes.path)
                longitud = int(self.headers.get("Content-Length") or 0)
                cuerpo = self.rfile.read(longitud) if longitud else b""
                try:
                    funcion, params = servidor.enrutador.buscar(metodo, ruta)
                    if funcion is None:
                        if params:
                            raise ErrorHmi(f"Método {metodo} no permitido", 405)
                        if metodo == "GET" and not ruta.startswith("/api/"):
                            self._enviar(self._estatico(ruta))
                            return
                        raise ErrorHmi(f"Ruta desconocida: {ruta}", 404)
                    peticion = Peticion(metodo, ruta, parse_qs(partes.query), params, cuerpo,
                                        self.headers)
                    self._enviar(funcion(peticion))
                except ErrorHmi as e:
                    self._json({"error": e.mensaje}, e.estado)
                except (BrokenPipeError, ConnectionResetError, socket.timeout):
                    pass
                except Exception as e:  # noqa: BLE001 - se informa al navegador
                    servidor.log.error(f"Error en {metodo} {ruta}:\n{traceback.format_exc()}")
                    try:
                        self._json({"error": f"Error interno: {e}"}, 500)
                    except OSError:
                        pass

            def _estatico(self, ruta: str) -> Respuesta:
                if ruta in ("", "/"):
                    ruta = "/index.html"
                fichero = ruta_segura(servidor.dir_web, ruta)
                # Las librerías de vendor no cambian: se pueden cachear
                cache = 86400 if "/vendor/" in ruta else 0
                return respuesta_fichero(fichero, cache_s=cache)

            def _json(self, datos: Any, estado: int = 200) -> None:
                cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
                self._enviar(Respuesta(cuerpo, "application/json; charset=utf-8", estado))

            def _enviar(self, resultado: Any) -> None:
                if resultado is None:
                    self.send_response(204)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if isinstance(resultado, Flujo):
                    self._flujo(resultado)
                    return
                if not isinstance(resultado, Respuesta):
                    self._json(resultado)
                    return
                self.send_response(resultado.estado)
                self.send_header("Content-Type", resultado.tipo)
                self.send_header("Content-Length", str(len(resultado.cuerpo)))
                for clave, valor in resultado.cabeceras.items():
                    self.send_header(clave, valor)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(resultado.cuerpo)

            def _flujo(self, flujo: Flujo) -> None:
                self.close_connection = True
                self.send_response(200)
                self.send_header("Content-Type", flujo.tipo)
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.send_header("X-Accel-Buffering", "no")
                for clave, valor in flujo.cabeceras.items():
                    self.send_header(clave, valor)
                self.end_headers()

                def escribir(datos: bytes) -> None:
                    try:
                        self.wfile.write(datos)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError) as e:
                        raise ConnectionError() from e

                try:
                    flujo.escritor(escribir)
                except ConnectionError:
                    pass

        return Manejador
