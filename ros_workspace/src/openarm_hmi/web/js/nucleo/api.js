// Cliente del servidor del HMI: peticiones REST y eventos en tiempo real (SSE).

export const FINALES = ['completada', 'error', 'cancelada'];

export class ErrorApi extends Error {
  constructor(mensaje, estado) {
    super(mensaje);
    this.estado = estado;
  }
}

async function pedir(metodo, ruta, cuerpo) {
  const opciones = { method: metodo, headers: {} };
  if (cuerpo !== undefined) {
    opciones.headers['Content-Type'] = 'application/json';
    opciones.body = JSON.stringify(cuerpo);
  }
  let respuesta;
  try {
    respuesta = await fetch(ruta, opciones);
  } catch (e) {
    throw new ErrorApi('Sin conexión con el servidor del HMI', 0);
  }
  if (respuesta.status === 204) return null;
  const tipo = respuesta.headers.get('Content-Type') || '';
  const datos = tipo.includes('json') ? await respuesta.json() : await respuesta.text();
  if (!respuesta.ok) {
    throw new ErrorApi((datos && datos.error) || `${respuesta.status} ${respuesta.statusText}`, respuesta.status);
  }
  return datos;
}

export const api = {
  get: (ruta) => pedir('GET', ruta),
  post: (ruta, cuerpo = {}) => pedir('POST', ruta, cuerpo),
  del: (ruta) => pedir('DELETE', ruta),
};

/**
 * Conexión de eventos con el servidor (EventSource, se reconecta sola).
 * conexion.on('estado', fn) devuelve una función para darse de baja.
 * Eventos: estado, tarea, log, proceso, proceso_estado, captura, parada_emergencia,
 * rearme, velocidad... y 'conexion' (true/false) generado en el navegador.
 */
export class Conexion {
  constructor(url = '/api/eventos') {
    this.url = url;
    this.oyentes = new Map();
    this.registrados = new Set();
    this.fuente = null;
    this.conectado = false;
    // Últimas tareas terminadas, por si el evento llega antes de que alguien lo espere
    this.finales = new Map();
    this.on('tarea', (t) => {
      if (!FINALES.includes(t.estado)) return;
      this.finales.set(t.id, t);
      if (this.finales.size > 100) this.finales.delete(this.finales.keys().next().value);
    });
  }

  conectar() {
    this.fuente = new EventSource(this.url);
    this.registrados.clear();
    for (const evento of this.oyentes.keys()) this._registrar(evento);
    this.fuente.onopen = () => this._cambiarConexion(true);
    this.fuente.onerror = () => this._cambiarConexion(false);
  }

  _cambiarConexion(conectado) {
    if (conectado === this.conectado) return;
    this.conectado = conectado;
    this._despachar('conexion', conectado);
  }

  _registrar(evento) {
    if (!this.fuente || this.registrados.has(evento) || evento === 'conexion') return;
    this.registrados.add(evento);
    this.fuente.addEventListener(evento, (e) => {
      let datos;
      try { datos = JSON.parse(e.data); } catch { return; }
      this._despachar(evento, datos);
    });
  }

  _despachar(evento, datos) {
    for (const fn of this.oyentes.get(evento) || []) {
      try { fn(datos); } catch (err) { console.error(`Error en el oyente de '${evento}'`, err); }
    }
  }

  on(evento, fn) {
    if (!this.oyentes.has(evento)) this.oyentes.set(evento, new Set());
    this.oyentes.get(evento).add(fn);
    this._registrar(evento);
    return () => this.oyentes.get(evento)?.delete(fn);
  }

  /** Espera a que la tarea `id` termine; resuelve con su estado final. */
  esperarTarea(id, timeoutMs = 60000) {
    return new Promise((resolver) => {
      if (this.finales.has(id)) { resolver(this.finales.get(id)); return; }
      const fin = (resultado) => { clearTimeout(temporizador); baja(); resolver(resultado); };
      const baja = this.on('tarea', (t) => {
        if (t.id === id && FINALES.includes(t.estado)) fin(t);
      });
      const temporizador = setTimeout(() => fin({ id, estado: 'error', mensaje: 'Tiempo de espera agotado' }), timeoutMs);
    });
  }
}
