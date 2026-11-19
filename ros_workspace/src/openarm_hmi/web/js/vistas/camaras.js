// Cámaras: vídeo de todas las cámaras, capturas y galería descargable.

import { aviso, boton, confirmar, descargar, h, hora, modal, pedirDatos, reemplazar, tamano } from '../nucleo/ui.js';
import { VisorCamara } from '../componentes/visor_camara.js';

export function montar(contenedor, ctx) {
  const rejilla = h('div', { class: 'rejilla-camaras' });
  const galeria = h('div', { class: 'galeria' });
  const resumen = h('span', { class: 'texto-3 pequeno' }, '');
  let visores = [];

  const cargarCamaras = async () => {
    let datos;
    try { datos = await ctx.api.get('/api/camaras'); } catch (e) { aviso(e.message, 'error'); return; }
    visores.forEach((v) => v.destruir());
    visores = datos.camaras.map((c) => new VisorCamara(ctx, c, c.temporal ? {
      quitar: async () => {
        try { await ctx.api.del(`/api/camaras/${encodeURIComponent(c.id)}`); cargarCamaras(); } catch (e) { aviso(e.message, 'error'); }
      },
    } : {}));
    reemplazar(rejilla, visores.length ? visores.map((v) => v.elemento)
      : h('div', { class: 'vacio' }, 'No hay cámaras configuradas.'));
    return datos;
  };

  const cargarGaleria = async () => {
    let datos;
    try { datos = await ctx.api.get('/api/capturas'); } catch (e) { return; }
    resumen.textContent = `${datos.capturas.length} capturas · ${datos.directorio}`;
    reemplazar(galeria, datos.capturas.length ? datos.capturas.map((c) => h('div', { class: 'miniatura' },
      h('img', { src: c.url, alt: c.archivo, loading: 'lazy', onclick: () => ampliar(c) }),
      h('div', { class: 'pie' },
        h('span', { class: 'nombre', title: `${c.archivo}\n${hora(c.fecha)} · ${tamano(c.tamano)}` }, c.archivo),
        h('a', { class: 'btn pequeno icono fantasma', href: c.descarga, download: c.archivo, title: 'Descargar' }, '⤓'),
        h('button', { class: 'btn pequeno icono fantasma', type: 'button', title: 'Borrar', onclick: () => borrar(c) }, '✕'))))
      : h('div', { class: 'vacio' }, 'Sin capturas. Pulsa "Capturar" en una cámara.'));
  };

  const ampliar = (c) => modal({
    titulo: c.archivo, ancho: true,
    contenido: [h('img', { src: c.url, alt: c.archivo }), h('div', { class: 'texto-3 pequeno' }, `${hora(c.fecha)} · ${tamano(c.tamano)}`)],
    botones: [{ texto: 'Descargar', clase: 'primario', icono: 'descargar', accion: () => descargar(c.descarga, c.archivo) }, { texto: 'Cerrar' }],
  });

  const borrar = async (c) => {
    if (!await confirmar('Borrar captura', `¿Borrar ${c.archivo}?`, { aceptar: 'Borrar', peligro: true })) return;
    try { await ctx.api.del(`/api/capturas/${encodeURIComponent(c.archivo)}`); cargarGaleria(); } catch (e) { aviso(e.message, 'error'); }
  };

  const capturarTodas = async () => {
    try {
      const r = await ctx.api.post('/api/camaras/todas/captura');
      aviso(`${r.capturas.length} capturas guardadas${r.errores.length ? ` (${r.errores.length} con error)` : ''}`, 'exito');
      cargarGaleria();
    } catch (e) { aviso(e.message, 'error'); }
  };

  const agregar = async () => {
    let datos;
    try { datos = await ctx.api.get('/api/camaras'); } catch (e) { aviso(e.message, 'error'); return; }
    const usados = new Set(datos.camaras.map((c) => c.topic));
    const libres = datos.topics.filter((t) => !usados.has(t.topic));
    if (!libres.length) { aviso('No hay otros topics de imagen publicándose', 'aviso'); return; }
    const r = await pedirDatos('Añadir cámara', [
      { nombre: 'topic', etiqueta: 'Topic', tipo: 'select', valor: libres[0].topic,
        opciones: libres.map((t) => ({ valor: t.topic, texto: `${t.topic} (${t.tipo.split('/').pop()})` })) },
      { nombre: 'nombre', etiqueta: 'Nombre', ayuda: 'opcional' },
    ], { aceptar: 'Añadir' });
    if (!r) return;
    try { await ctx.api.post('/api/camaras', r); cargarCamaras(); } catch (e) { aviso(e.message, 'error'); }
  };

  reemplazar(contenedor, h('div', { class: 'columna', style: { gap: '14px' } },
    h('div', { class: 'fila entre' },
      h('div', { class: 'fila' },
        boton('Capturar todas', { icono: 'camara', clase: 'primario', onclick: capturarTodas }),
        boton('Añadir cámara', { icono: 'mas', onclick: agregar, titulo: 'Ver otro topic de imagen (temporal)' })),
      h('span', { class: 'texto-3 pequeno' }, 'Las capturas se guardan en el servidor y se pueden descargar desde la galería.')),
    rejilla,
    h('section', { class: 'panel' },
      h('div', { class: 'cabecera' }, h('h2', {}, 'Galería'), resumen,
        h('div', { class: 'acciones' },
          boton('Actualizar', { icono: 'refrescar', clase: 'pequeno', onclick: cargarGaleria }),
          boton('Descargar todo (.zip)', { icono: 'descargar', clase: 'pequeno', onclick: () => descargar('/api/capturas/zip') }))),
      h('div', { class: 'cuerpo' }, galeria))));

  cargarCamaras();
  cargarGaleria();
  const bajas = [ctx.local.escuchar('captura', cargarGaleria)];
  return () => { visores.forEach((v) => v.destruir()); bajas.forEach((b) => b()); };
}
