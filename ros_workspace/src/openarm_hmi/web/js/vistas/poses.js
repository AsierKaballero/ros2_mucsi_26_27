// Poses: predefinidas y guardadas; ir a ellas, guardar la actual, borrar y exportar.

import { aGrados, aviso, boton, confirmar, descargar, h, num, pedirDatos, reemplazar } from '../nucleo/ui.js';

export function montar(contenedor, ctx) {
  const brazos = ctx.config.robot.brazos;
  const cuerpo = h('tbody', {});
  const fichero = h('span', { class: 'texto-3 pequeno mono' }, '');

  const post = async (ruta, datos) => {
    try { return await ctx.api.post(ruta, datos); } catch (e) { aviso(e.message, 'error'); return null; }
  };

  const cargar = async () => {
    let datos;
    try { datos = await ctx.api.get('/api/poses'); } catch (e) { aviso(e.message, 'error'); return; }
    fichero.textContent = datos.fichero;
    reemplazar(cuerpo, datos.poses.map((p) => {
      const ir = (objetivo) => post(`/api/poses/${encodeURIComponent(p.nombre)}/ir`, { brazo: objetivo });
      const disponibles = brazos.filter((b) => p.articulaciones[b.sufijo]);
      const valores = brazos.map((b) => {
        const v = p.articulaciones[b.sufijo];
        return h('div', { class: 'mono pequeno' },
          h('span', { class: `etiqueta-brazo ${b.sufijo}`, style: { marginRight: '6px' } }),
          v ? v.map((x) => num(aGrados(x), 1)).join('  ') : h('span', { class: 'texto-3' }, '—'));
      });
      return h('tr', {},
        h('td', {}, h('strong', {}, p.nombre), h('div', { class: 'texto-3 pequeno' }, p.predefinida ? 'Predefinida' : `Guardada ${p.creada || ''}`),
          p.descripcion ? h('div', { class: 'texto-2 pequeno' }, p.descripcion) : null),
        h('td', {}, valores),
        h('td', {}, h('div', { class: 'fila' },
          disponibles.map((b) => boton(b.sufijo === 'izq' ? 'Izq.' : b.sufijo === 'der' ? 'Der.' : b.nombre,
            { clase: 'pequeno', icono: 'juego', titulo: `Mover ${b.nombre}`, onclick: () => ir(b.id) })),
          disponibles.length === brazos.length && brazos.length > 1
            ? boton('Ambos', { clase: 'pequeno primario', icono: 'juego', onclick: () => ir('ambos') }) : null,
          p.predefinida ? null : boton('', { clase: 'pequeno icono fantasma', icono: 'basura', titulo: 'Borrar',
            onclick: async () => {
              if (!await confirmar('Borrar pose', `¿Borrar la pose '${p.nombre}'?`, { aceptar: 'Borrar', peligro: true })) return;
              try { await ctx.api.del(`/api/poses/${encodeURIComponent(p.nombre)}`); ctx.local.emitir('poses'); } catch (e) { aviso(e.message, 'error'); }
            } }))));
    }));
  };

  const guardar = async () => {
    const r = await pedirDatos('Guardar la pose actual', [
      { nombre: 'nombre', etiqueta: 'Nombre', ayuda: 'p. ej. sobre_mesa' },
      { nombre: 'brazo', etiqueta: 'Brazos', tipo: 'select', valor: 'ambos', opciones: [
        { valor: 'ambos', texto: 'Ambos brazos' }, ...brazos.map((b) => ({ valor: b.id, texto: b.nombre }))] },
      { nombre: 'descripcion', etiqueta: 'Descripción', ayuda: 'opcional' },
    ], { aceptar: 'Guardar' });
    if (!r || !r.nombre) return;
    if (await post('/api/poses', r)) { aviso(`Pose '${r.nombre}' guardada`, 'exito'); ctx.local.emitir('poses'); }
  };

  reemplazar(contenedor, h('section', { class: 'panel' },
    h('div', { class: 'cabecera' }, h('h2', {}, 'Poses'), fichero,
      h('div', { class: 'acciones' },
        boton('Guardar pose actual', { icono: 'guardar', clase: 'primario pequeno', onclick: guardar }),
        boton('Exportar YAML', { icono: 'descargar', clase: 'pequeno', onclick: () => descargar('/api/poses/exportar', 'poses.yaml') }))),
    h('div', { class: 'cuerpo contenedor-tabla' },
      h('table', { class: 'tabla' },
        h('thead', {}, h('tr', {}, h('th', {}, 'Pose'), h('th', {}, 'Articulaciones J1…J7 (°)'), h('th', {}, 'Mover'))),
        cuerpo)),
    h('div', { class: 'seccion texto-3 pequeno' },
      'Las poses predefinidas se definen en config/openarm.yaml (poses_predefinidas). ',
      'Las guardadas se comparten entre los cuerpos 301 y 302 (se indexan por izq/der).')));

  cargar();
  const baja = ctx.local.escuchar('poses', cargar);
  return baja;
}
