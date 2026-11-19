// Almacén del estado del robot (último evento "estado" del servidor).
// Los componentes se suscriben y se les avisa como mucho una vez por fotograma.

export class Almacen {
  constructor() {
    this.estado = {};
    this.oyentes = new Set();
    this._pendiente = false;
  }

  actualizar(estado) {
    this.estado = estado;
    if (this._pendiente) return;
    this._pendiente = true;
    requestAnimationFrame(() => {
      this._pendiente = false;
      for (const fn of this.oyentes) {
        try { fn(this.estado); } catch (e) { console.error('Error en un suscriptor del estado', e); }
      }
    });
  }

  /** Llama a `fn(estado)` en cada actualización; devuelve la función para darse de baja. */
  suscribir(fn, inmediato = true) {
    this.oyentes.add(fn);
    if (inmediato && Object.keys(this.estado).length) fn(this.estado);
    return () => this.oyentes.delete(fn);
  }
}

// Preferencias del usuario en este navegador (pasos de jog, pestañas, tema...).
// El almacenamiento local puede no estar disponible: se usa un respaldo en memoria.
const memoria = {};
export const preferencias = {
  leer(clave, defecto) {
    try {
      const valor = localStorage.getItem(`hmi.${clave}`);
      return valor === null ? (clave in memoria ? memoria[clave] : defecto) : JSON.parse(valor);
    } catch {
      return clave in memoria ? memoria[clave] : defecto;
    }
  },
  guardar(clave, valor) {
    memoria[clave] = valor;
    try { localStorage.setItem(`hmi.${clave}`, JSON.stringify(valor)); } catch { /* sin almacenamiento */ }
  },
};
