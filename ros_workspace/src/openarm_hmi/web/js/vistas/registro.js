// Registro: mensajes de /rosout de todos los nodos, con filtros y exportación.

import { boton, descargar, h, reemplazar } from '../nucleo/ui.js';

const NIVELES = ['DEBUG', 'INFO', 'WARN', 'ERROR', 'FATAL'];

export function montar(contenedor, ctx) {
  let nivelMinimo = 'INFO';
  let texto = '';
  let pausado = false;
  const cuerpo = h('tbody', {});
  const contador = h('span', { class: 'texto-3 pequeno' }, '');
  const contenedorTabla = h('div', { class: 'contenedor-tabla' });

  const pasa = (e) => NIVELES.indexOf(e.nivel) >= NIVELES.indexOf(nivelMinimo)
    && (!texto || `${e.nodo} ${e.texto}`.toLowerCase().includes(texto));

  const fila = (e) => h('tr', {},
    h('td', { class: 'mono pequeno texto-3' }, new Date(e.t * 1000).toLocaleTimeString('es-ES', { hour12: false })),
    h('td', {}, h('span', { class: `nivel ${e.nivel}` }, e.nivel)),
    h('td', { class: 'mono pequeno' }, e.nodo),
    h('td', { class: 'texto' }, e.texto));

  const pintar = () => {
    const entradas = ctx.registro.entradas.filter(pasa).slice(-800);
    reemplazar(cuerpo, entradas.reverse().map(fila));
    contador.textContent = `${entradas.length} de ${ctx.registro.entradas.length}`;
  };

  const selector = h('select', { onchange: (e) => { nivelMinimo = e.target.value; pintar(); } },
    NIVELES.map((n) => h('option', { value: n, selected: n === nivelMinimo }, `≥ ${n}`)));
  const buscador = h('input', { type: 'text', class: 'buscador', placeholder: 'Filtrar por nodo o texto…',
    oninput: (e) => { texto = e.target.value.toLowerCase(); pintar(); } });
  const pausa = boton('Pausar', { clase: 'pequeno', icono: 'parar', onclick: () => {
    pausado = !pausado;
    reemplazar(pausa, pausado ? 'Reanudar' : 'Pausar');
    if (!pausado) pintar();
  } });
  const exportar = boton('Exportar', { clase: 'pequeno', icono: 'descargar', onclick: () => {
    const lineas = ctx.registro.entradas.map((e) => `${new Date(e.t * 1000).toISOString()} [${e.nivel}] [${e.nodo}] ${e.texto}`);
    const url = URL.createObjectURL(new Blob([lineas.join('\n')], { type: 'text/plain' }));
    descargar(url, `registro_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.log`);
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  } });

  contenedorTabla.appendChild(h('table', { class: 'tabla registro' },
    h('thead', {}, h('tr', {}, h('th', {}, 'Hora'), h('th', {}, 'Nivel'), h('th', {}, 'Nodo'), h('th', {}, 'Mensaje'))), cuerpo));
  reemplazar(contenedor, h('section', { class: 'panel' },
    h('div', { class: 'cabecera' }, h('h2', {}, 'Registro (/rosout)'), contador,
      h('div', { class: 'acciones' }, selector, buscador, pausa, exportar,
        boton('Vaciar', { clase: 'pequeno fantasma', onclick: () => { ctx.registro.entradas.length = 0; pintar(); } }))),
    h('div', { class: 'cuerpo' }, contenedorTabla)));

  pintar();
  const baja = ctx.registro.escuchar((e) => {
    if (pausado || !pasa(e)) return;
    cuerpo.prepend(fila(e));
    while (cuerpo.childElementCount > 800) cuerpo.lastChild.remove();
    contador.textContent = `${cuerpo.childElementCount} de ${ctx.registro.entradas.length}`;
  });
  return baja;
}
