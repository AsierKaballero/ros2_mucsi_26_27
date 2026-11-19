// Vista principal: un panel por brazo, el gemelo 3D, órdenes conjuntas y las cámaras.

import { preferencias } from '../nucleo/almacen.js';
import { aviso, boton, h, icono, limitar, reemplazar } from '../nucleo/ui.js';
import { PanelBrazo } from '../componentes/panel_brazo.js';
import { VisorCamara } from '../componentes/visor_camara.js';

export function montar(contenedor, ctx) {
  const brazos = ctx.config.robot.brazos;
  const paneles = brazos.map((b) => new PanelBrazo(ctx, b));
  const limpiezas = [];

  // Gemelo digital
  const contenedorVisor = h('div', { class: 'panel contenedor-visor' });
  ctx.visor.montar(contenedorVisor);
  ctx.visor.cargar(brazos.map((b) => b.efector));
  limpiezas.push(() => ctx.visor.desmontar());
  limpiezas.push(ctx.almacen.suscribir((e) => ctx.visor.actualizar(e.estado?.posiciones)));

  // Órdenes para los dos brazos a la vez
  const barra = barraConjunta(ctx, brazos, limpiezas);

  // Cámaras de los efectores
  const zonaCamaras = h('div', { class: 'camaras-mini' });
  const visores = [];
  const camarasInfo = ctx.config.modulos.camaras?.camaras || [];
  let mostrarCamaras = preferencias.leer('operacion.camaras', true);
  const alternarCamaras = boton('', { clase: 'pequeno fantasma', onclick: () => {
    mostrarCamaras = !mostrarCamaras;
    preferencias.guardar('operacion.camaras', mostrarCamaras);
    pintarCamaras();
  } });
  const pintarCamaras = () => {
    visores.splice(0).forEach((v) => v.destruir());
    reemplazar(alternarCamaras, icono(mostrarCamaras ? 'ojo' : 'camara'), mostrarCamaras ? 'Ocultar cámaras' : 'Mostrar cámaras');
    if (!mostrarCamaras) { reemplazar(zonaCamaras); return; }
    for (const camara of camarasInfo.filter((c) => c.brazo)) visores.push(new VisorCamara(ctx, camara));
    reemplazar(zonaCamaras, visores.map((v) => v.elemento));
  };
  if (camarasInfo.length) pintarCamaras();
  limpiezas.push(() => visores.forEach((v) => v.destruir()));

  const centro = h('div', { class: 'centro' },
    contenedorVisor,
    barra,
    camarasInfo.length ? h('div', { class: 'fila entre' },
      h('span', { class: 'texto-3 pequeno' }, 'Cámaras de los efectores'), alternarCamaras) : null,
    zonaCamaras);

  const [primero, segundo, ...resto] = paneles;
  reemplazar(contenedor, h('div', { class: 'operacion' },
    primero?.elemento, centro, segundo?.elemento, resto.map((p) => p.elemento)));

  return () => {
    paneles.forEach((p) => p.destruir());
    limpiezas.forEach((f) => f());
  };
}

function barraConjunta(ctx, brazos, limpiezas) {
  const post = (ruta, cuerpo) => ctx.api.post(ruta, cuerpo).catch((e) => aviso(e.message, 'error'));
  const maximo = Math.round((ctx.config.modulos.movimiento?.velocidad_maxima || 1) * 100);

  const valor = h('span', { class: 'mono' }, '');
  const enviar = limitar((v) => post('/api/movimiento/velocidad', { brazo: 'ambos', valor: v / 100 }), 250);
  const velocidad = h('input', {
    type: 'range', min: 1, max: maximo, value: 10, style: { width: '120px' }, 'aria-label': 'Velocidad de ambos brazos',
    oninput: (e) => { valor.textContent = `${e.target.value} %`; enviar(Number(e.target.value)); },
  });
  limpiezas.push(ctx.almacen.suscribir((e) => {
    const v = Object.values(e.movimiento?.velocidades || {});
    if (v.length && document.activeElement !== velocidad) {
      const minimo = Math.round(Math.min(...v) * 100);
      velocidad.value = minimo;
      valor.textContent = v.every((x) => Math.round(x * 100) === minimo) ? `${minimo} %` : `${minimo} % (mín.)`;
    }
  }));

  const poses = h('div', { class: 'bloque' });
  const cargarPoses = async () => {
    let datos;
    try { datos = await ctx.api.get('/api/poses'); } catch { return; }
    const sufijos = brazos.map((b) => b.sufijo);
    const conjuntas = datos.poses.filter((p) => sufijos.every((s) => p.articulaciones[s]));
    reemplazar(poses, h('span', {}, 'Poses'), conjuntas.map((p) => boton(p.nombre, {
      icono: p.predefinida ? 'casa' : 'marcador', clase: 'pequeno', titulo: p.descripcion || '',
      onclick: () => post(`/api/poses/${encodeURIComponent(p.nombre)}/ir`, { brazo: 'ambos' }),
    })));
  };
  cargarPoses();
  limpiezas.push(ctx.local.escuchar('poses', cargarPoses));

  const maximoPinza = Math.min(...brazos.map((b) => b.pinza.anchura_maxima_mm));
  return h('section', { class: 'panel' },
    h('div', { class: 'barra-conjunta' },
      h('strong', {}, 'Ambos brazos'),
      poses,
      h('div', { class: 'bloque' }, h('span', {}, 'Velocidad'), velocidad, valor),
      h('div', { class: 'bloque' }, h('span', {}, 'Pinzas'),
        boton('Cerrar', { clase: 'pequeno', onclick: () => post('/api/pinza', { brazo: 'ambos', anchura_mm: 0 }) }),
        boton('Abrir', { clase: 'pequeno', onclick: () => post('/api/pinza', { brazo: 'ambos', anchura_mm: maximoPinza }) })),
      h('div', { class: 'bloque', style: { marginLeft: 'auto' } },
        boton('Parar todo', { icono: 'parar', clase: 'pequeno peligro', titulo: 'Detener todos los movimientos (sin parada de emergencia)',
          onclick: () => post('/api/movimiento/parar', {}) }))));
}
