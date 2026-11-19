// Vídeo de una cámara: pide los fotogramas uno a uno (long-polling) mientras está montado.

import { aviso, boton, h, icono, num } from '../nucleo/ui.js';

export class VisorCamara {
  constructor(ctx, camara, { quitar } = {}) {
    this.ctx = ctx;
    this.camara = camara;
    this.activo = true;
    this.seq = 0;
    this.ultimoFotograma = 0;
    this.url = null;

    this.img = h('img', { alt: camara.nombre, hidden: true });
    this.sinSenal = h('div', { class: 'sin-senal' }, 'Conectando…');
    this.info = h('div', { class: 'info' }, '');
    this.rec = h('div', { class: 'rec', hidden: true, title: 'En vivo' });
    const brazo = camara.brazo ? camara.brazo.split('_').pop() : '';
    this.elemento = h('section', { class: 'panel camara' },
      h('div', { class: 'cabecera' },
        brazo ? h('span', { class: `etiqueta-brazo ${brazo}` }) : null,
        h('h3', {}, camara.nombre),
        h('span', { class: 'texto-3 pequeno mono', title: camara.topic }, camara.topic),
        h('div', { class: 'acciones' },
          boton('Capturar', { icono: 'camara', clase: 'pequeno primario', titulo: 'Guardar una captura en la galería',
            onclick: () => this.capturar() }),
          h('button', { class: 'btn pequeno icono', type: 'button', title: 'Pantalla completa',
            onclick: () => this.elemento.classList.toggle('pantalla-completa') }, icono('maximizar')),
          quitar ? h('button', { class: 'btn pequeno icono', type: 'button', title: 'Quitar cámara',
            onclick: quitar }, icono('basura')) : null)),
      h('div', { class: 'imagen' }, this.img, this.sinSenal, this.rec, this.info));

    this.img.addEventListener('load', () => {
      if (this.urlAnterior) URL.revokeObjectURL(this.urlAnterior);
      this.urlAnterior = null;
    });
    this.baja = ctx.almacen.suscribir((e) => this._estado(e.camaras?.[camara.id]));
    this._bucle();
  }

  destruir() {
    this.activo = false;
    this.controlador?.abort();
    this.baja();
    if (this.url) URL.revokeObjectURL(this.url);
  }

  async _bucle() {
    while (this.activo) {
      this.controlador = new AbortController();
      try {
        const r = await fetch(`/api/camaras/${encodeURIComponent(this.camara.id)}/frame?desde=${this.seq}`,
          { signal: this.controlador.signal, cache: 'no-store' });
        if (r.status === 200) {
          this.vacios = 0;
          this.seq = Number(r.headers.get('X-Seq')) || 0;
          const blob = await r.blob();
          this.urlAnterior = this.url;
          this.url = URL.createObjectURL(blob);
          this.img.src = this.url;
          this.img.hidden = false;
          this.sinSenal.hidden = true;
          this.rec.hidden = false;
          this.ultimoFotograma = Date.now();
          continue;
        }
        if (r.status !== 204) await esperar(2000);
        // Si el servidor se ha reiniciado su contador empieza de nuevo: se vuelve a 0
        this.vacios = (this.vacios || 0) + 1;
        if (this.vacios >= 2) this.seq = 0;
      } catch (e) {
        if (!this.activo) return;
        await esperar(2000);
      }
      if (Date.now() - this.ultimoFotograma > 3000) {
        this.rec.hidden = true;
        this.img.hidden = true;
        this.sinSenal.hidden = false;
      }
    }
  }

  _estado(e) {
    if (!e) return;
    if (e.error) this.sinSenal.textContent = `Sin señal: ${e.error}`;
    else if (!this.ultimoFotograma) this.sinSenal.textContent = 'Esperando imágenes…';
    this.info.textContent = e.activa && e.fps ? `${num(e.fps)} fps` : '';
  }

  async capturar() {
    try {
      const entrada = await this.ctx.api.post(`/api/camaras/${encodeURIComponent(this.camara.id)}/captura`);
      this.elemento.classList.remove('destello');
      void this.elemento.offsetWidth; // reinicia la animación
      this.elemento.classList.add('destello');
      const enlace = h('a', { href: entrada.descarga, download: entrada.archivo }, 'Descargar');
      aviso(h('span', {}, `Captura guardada: ${entrada.archivo} · `, enlace), 'exito');
      this.ctx.local.emitir('captura', entrada);
    } catch (e) {
      aviso(e.message, 'error');
    }
  }
}

const esperar = (ms) => new Promise((r) => setTimeout(r, ms));
