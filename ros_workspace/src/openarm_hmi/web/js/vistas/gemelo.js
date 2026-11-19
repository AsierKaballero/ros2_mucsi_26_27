// Gemelo digital a pantalla grande con el estado numérico de todas las articulaciones.

import { aGrados, boton, h, num, reemplazar } from '../nucleo/ui.js';

export function montar(contenedor, ctx) {
  const brazos = ctx.config.robot.brazos;
  const contenedorVisor = h('div', { class: 'panel contenedor-visor' });
  ctx.visor.montar(contenedorVisor);
  ctx.visor.cargar(brazos.map((b) => b.efector));

  const tablas = brazos.map((b) => {
    const filas = [...b.articulaciones, b.pinza.articulacion].map((n) => {
      const celdas = { pos: h('td', { class: 'num' }, '—'), vel: h('td', { class: 'num' }, '—') };
      const limite = (b.limites || {})[n] || (n === b.pinza.articulacion ? b.limites_pinza : null);
      const rango = limite && limite.inferior !== undefined
        ? `${num(aGrados(limite.inferior), 0)} … ${num(aGrados(limite.superior), 0)}` : '—';
      return { n, celdas, el: h('tr', {}, h('td', { class: 'mono' }, n.replace(`${b.id}_`, '')), celdas.pos, celdas.vel, h('td', { class: 'num texto-3' }, rango)) };
    });
    const pose = h('div', { class: 'pose-actual' }, '—');
    const el = h('section', { class: 'panel' },
      h('div', { class: 'cabecera' }, h('span', { class: `etiqueta-brazo ${b.sufijo}` }), h('h3', {}, b.nombre)),
      h('div', { class: 'cuerpo' },
        h('table', { class: 'tabla' },
          h('thead', {}, h('tr', {}, h('th', {}, 'Articulación'), h('th', {}, 'Pos (°)'), h('th', {}, 'Vel (°/s)'), h('th', {}, 'Límites (°)'))),
          h('tbody', {}, filas.map((f) => f.el))),
        h('div', { class: 'titulo texto-3 pequeno', style: { margin: '10px 0 4px' } }, `Efector (${b.efector}), mm y °`),
        pose));
    return { b, filas, pose, el };
  });

  const recargar = boton('Recargar modelo', { icono: 'refrescar', clase: 'pequeno', onclick: () => location.reload() });
  reemplazar(contenedor, h('div', { class: 'gemelo' },
    contenedorVisor,
    h('div', { class: 'columna' }, tablas.map((t) => t.el), h('div', { class: 'fila' }, recargar,
      h('span', { class: 'texto-3 pequeno' }, 'Arrastra para girar, rueda para acercar, botón derecho para desplazar.')))));

  const baja = ctx.almacen.suscribir((e) => {
    const posiciones = e.estado?.posiciones || {};
    const velocidades = e.estado?.velocidades || {};
    ctx.visor.actualizar(posiciones);
    for (const t of tablas) {
      for (const f of t.filas) {
        if (posiciones[f.n] !== undefined) f.celdas.pos.textContent = num(aGrados(posiciones[f.n]), 2);
        if (velocidades[f.n] !== undefined) f.celdas.vel.textContent = num(aGrados(velocidades[f.n]), 1);
      }
      const p = e.estado?.poses?.[t.b.id];
      if (p) {
        const v = [...p.posicion.map((x) => x * 1000), ...p.rpy.map(aGrados)];
        reemplazar(t.pose, ['X', 'Y', 'Z', 'R', 'P', 'Y'].map((eje, i) => h('div', {}, h('span', {}, eje), num(v[i]))));
      }
    }
  });

  return () => { baja(); ctx.visor.desmontar(); };
}
