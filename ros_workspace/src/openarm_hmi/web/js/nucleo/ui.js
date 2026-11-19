// Utilidades de interfaz: creación de elementos, iconos, avisos, diálogos y formatos.

/**
 * Crea un elemento: h('button', {class: 'btn', onclick: f}, 'Texto', otroNodo).
 * Atributos especiales: class, style (objeto o texto), dataset, on<evento>, y
 * propiedades DOM (value, checked, disabled, hidden...).
 */
export function h(etiqueta, atributos = {}, ...hijos) {
  const el = document.createElement(etiqueta);
  for (const [clave, valor] of Object.entries(atributos || {})) {
    if (valor === undefined || valor === null || valor === false) continue;
    if (clave === 'class') el.className = valor;
    else if (clave === 'style' && typeof valor === 'object') Object.assign(el.style, valor);
    else if (clave === 'dataset') Object.assign(el.dataset, valor);
    else if (clave.startsWith('on') && typeof valor === 'function') el.addEventListener(clave.slice(2), valor);
    else if (clave in el && typeof valor !== 'string') el[clave] = valor;
    else if (['value', 'checked', 'disabled', 'hidden', 'selected', 'title'].includes(clave)) el[clave] = valor;
    else el.setAttribute(clave, valor === true ? '' : valor);
  }
  agregar(el, hijos);
  return el;
}

function agregar(el, hijos) {
  for (const hijo of hijos.flat(Infinity)) {
    if (hijo === null || hijo === undefined || hijo === false) continue;
    el.appendChild(hijo instanceof Node ? hijo : document.createTextNode(String(hijo)));
  }
}

/** Sustituye el contenido de `el` por `hijos`. */
export function reemplazar(el, ...hijos) {
  el.replaceChildren();
  agregar(el, hijos);
  return el;
}

// Iconos (trazos de 24x24 estilo "lucide")
const TRAZOS = {
  juego: 'M6 4l14 8-14 8z',
  parar: 'M6 6h12v12H6z',
  camara: 'M3 8h3l2-3h8l2 3h3v11H3z M12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z',
  descargar: 'M12 3v12 M7 10l5 5 5-5 M4 21h16',
  basura: 'M4 7h16 M9 7V4h6v3 M6 7l1 13h10l1-13',
  casa: 'M3 11l9-8 9 8 M5 10v10h14V10',
  cubo: 'M12 2l9 5v10l-9 5-9-5V7z M3 7l9 5 9-5 M12 12v10',
  red: 'M5 5h4v4H5z M15 5h4v4h-4z M10 15h4v4h-4z M7 9v3h10V9 M12 12v3',
  lista: 'M8 6h13 M8 12h13 M8 18h13 M3 6h1 M3 12h1 M3 18h1',
  terminal: 'M4 17l6-5-6-5 M12 19h8',
  mando: 'M6 12h4 M8 10v4 M15 11h.01 M18 13h.01 M7 6h10a5 5 0 0 1 5 5v2a5 5 0 0 1-9 3h-2a5 5 0 0 1-9-3v-2a5 5 0 0 1 5-5z',
  marcador: 'M6 3h12v18l-6-4-6 4z',
  refrescar: 'M21 12a9 9 0 1 1-3-6.7L21 8 M21 3v5h-5',
  ojo: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
  maximizar: 'M4 9V4h5 M20 9V4h-5 M4 15v5h5 M20 15v5h-5',
  mas: 'M12 5v14 M5 12h14',
  menos: 'M5 12h14',
  aviso: 'M12 3l10 18H2z M12 10v4 M12 17h.01',
  sol: 'M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10z M12 1v2 M12 21v2 M4.2 4.2l1.4 1.4 M18.4 18.4l1.4 1.4 M1 12h2 M21 12h2 M4.2 19.8l1.4-1.4 M18.4 5.6l1.4-1.4',
  luna: 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z',
  pinza: 'M7 3v7l-3 4v7 M17 3v7l3 4v7 M7 10h10',
  guardar: 'M5 3h11l3 3v15H5z M8 3v5h7V3 M8 21v-7h8v7',
  objetivo: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
  copiar: 'M9 9h11v11H9z M5 15H4V4h11v1',
  engranaje: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z',
};

export function icono(nombre) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  const ruta = document.createElementNS(ns, 'path');
  ruta.setAttribute('d', TRAZOS[nombre] || TRAZOS.aviso);
  svg.appendChild(ruta);
  return svg;
}

/** Botón con icono opcional: boton('Texto', {icono:'juego', clase:'primario', onclick}). */
export function boton(texto, { icono: nombre, clase = '', titulo, onclick, disabled } = {}) {
  return h('button', { class: `btn ${clase}`.trim(), title: titulo, onclick, disabled, type: 'button' },
    nombre ? icono(nombre) : null, texto);
}

// --- Avisos ------------------------------------------------------------------------

export function aviso(texto, tipo = 'info', ms = 4500) {
  const raiz = document.getElementById('toasts');
  const el = h('div', { class: `toast ${tipo}`, role: tipo === 'error' ? 'alert' : 'status' },
    h('div', {}, texto),
    h('button', { class: 'cerrar', onclick: () => el.remove(), title: 'Cerrar' }, '×'));
  raiz.appendChild(el);
  while (raiz.children.length > 5) raiz.firstChild.remove();
  if (ms) setTimeout(() => el.remove(), ms);
  return el;
}

// --- Diálogos ----------------------------------------------------------------------

export function modal({ titulo, contenido, botones = [], ancho = false, alCerrar }) {
  const raiz = document.getElementById('modal-raiz');
  let cerrado = false;
  const cerrar = () => {
    if (cerrado) return;
    cerrado = true;
    fondo.remove();
    document.removeEventListener('keydown', teclado, true);
    alCerrar?.();
  };
  const teclado = (e) => { if (e.key === 'Escape' && !e.hmiParada) { e.stopPropagation(); cerrar(); } };
  const fondo = h('div', { class: 'modal-fondo', onclick: (e) => { if (e.target === fondo) cerrar(); } },
    h('div', { class: `modal ${ancho ? 'ancho' : ''}`, role: 'dialog', 'aria-modal': 'true' },
      h('h3', {}, titulo),
      h('div', { class: 'contenido' }, contenido),
      botones.length ? h('div', { class: 'pie' }, botones.map((b) => {
        const el = boton(b.texto, { clase: b.clase, icono: b.icono });
        el.addEventListener('click', () => { if (b.accion?.() !== false) cerrar(); });
        return el;
      })) : null));
  raiz.appendChild(fondo);
  document.addEventListener('keydown', teclado, true);
  fondo.querySelector('input, select, .btn.primario, .btn.peligro')?.focus();
  return cerrar;
}

export function confirmar(titulo, texto, { aceptar = 'Aceptar', peligro = false } = {}) {
  return new Promise((resolver) => {
    let respuesta = false;
    modal({
      titulo,
      contenido: h('p', { style: { margin: 0 } }, texto),
      botones: [
        { texto: 'Cancelar', clase: 'fantasma' },
        { texto: aceptar, clase: peligro ? 'peligro' : 'primario', accion: () => { respuesta = true; } },
      ],
      alCerrar: () => resolver(respuesta),
    });
  });
}

export function pedirDatos(titulo, campos, { aceptar = 'Aceptar' } = {}) {
  // campos: [{nombre, etiqueta, tipo: 'text'|'select', opciones, valor}]
  return new Promise((resolver) => {
    let resultado = null;
    const entradas = {};
    const contenido = campos.map((c) => {
      const entrada = c.tipo === 'select'
        ? h('select', {}, c.opciones.map((o) => h('option', { value: o.valor, selected: o.valor === c.valor }, o.texto)))
        : h('input', { type: 'text', value: c.valor ?? '', placeholder: c.ayuda || '' });
      entradas[c.nombre] = entrada;
      return h('label', { class: 'campo' }, c.etiqueta, entrada);
    });
    const leer = () => {
      resultado = Object.fromEntries(Object.entries(entradas).map(([k, el]) => [k, el.value]));
    };
    const cerrar = modal({
      titulo,
      contenido,
      botones: [{ texto: 'Cancelar', clase: 'fantasma' }, { texto: aceptar, clase: 'primario', accion: leer }],
      alCerrar: () => resolver(resultado),
    });
    Object.values(entradas).forEach((el) => el.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { leer(); cerrar(); }
    }));
  });
}

// --- Formatos ----------------------------------------------------------------------

export const aGrados = (rad) => (rad * 180) / Math.PI;
export const aRadianes = (grados) => (grados * Math.PI) / 180;

export function num(valor, decimales = 1) {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return '—';
  return Number(valor).toFixed(decimales);
}

export function hora(segundos) {
  return new Date(segundos * 1000).toLocaleTimeString('es-ES', { hour12: false });
}

export function tamano(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

/** Ejecuta `fn` como mucho una vez cada `ms` (la última llamada siempre se ejecuta). */
export function limitar(fn, ms) {
  let temporizador = null;
  let ultimos = null;
  return (...args) => {
    ultimos = args;
    if (temporizador) return;
    temporizador = setTimeout(() => { temporizador = null; fn(...ultimos); }, ms);
  };
}

/** Descarga una URL como fichero. */
export function descargar(url, nombre = '') {
  const a = h('a', { href: url, download: nombre });
  document.body.appendChild(a);
  a.click();
  a.remove();
}
