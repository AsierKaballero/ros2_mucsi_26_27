// Introspección de ROS 2: nodos, topics (echo y frecuencia), servicios, acciones,
// parámetros y controladores de ros2_control.

import { preferencias } from '../nucleo/almacen.js';
import { aviso, boton, h, reemplazar } from '../nucleo/ui.js';

const PESTANAS = [
  ['nodos', 'Nodos'], ['topics', 'Topics'], ['servicios', 'Servicios'], ['acciones', 'Acciones'], ['controladores', 'Controladores'],
];

export function montar(contenedor, ctx) {
  let pestana = preferencias.leer('ros.pestana', 'topics');
  let grafo = null;
  let filtro = '';
  let ocultos = false;
  let seleccion = null;
  let autoEcho = null;
  let vivo = true;

  const lista = h('div', { class: 'contenedor-tabla' });
  const detalle = h('div', { class: 'cuerpo' }, h('div', { class: 'vacio' }, 'Selecciona un elemento de la lista.'));
  const tituloDetalle = h('h2', {}, 'Detalle');
  const accionesDetalle = h('div', { class: 'acciones' });
  const contador = h('span', { class: 'texto-3 pequeno' }, '');
  const pestanas = h('div', { class: 'pestanas' }, PESTANAS.map(([id, texto]) =>
    h('button', { type: 'button', dataset: { id }, class: id === pestana ? 'activa' : '', onclick: () => cambiar(id) }, texto)));

  const cambiar = (id) => {
    pestana = id;
    preferencias.guardar('ros.pestana', id);
    pestanas.querySelectorAll('button').forEach((b) => b.classList.toggle('activa', b.dataset.id === id));
    pintarLista();
  };

  const refrescar = async () => {
    try { grafo = await ctx.api.get('/api/ros/grafo'); } catch (e) { aviso(e.message, 'error'); return; }
    pintarLista();
  };

  const coincide = (texto) => !filtro || texto.toLowerCase().includes(filtro);

  const tabla = (cabeceras, filas) => h('table', { class: 'tabla' },
    h('thead', {}, h('tr', {}, cabeceras.map((c) => h('th', {}, c)))), h('tbody', {}, filas));

  const filaSeleccionable = (clave, celdas, alPulsar) => h('tr', {
    class: `seleccionable ${seleccion === clave ? 'seleccionada' : ''}`,
    onclick: (e) => {
      seleccion = clave;
      lista.querySelectorAll('tr.seleccionada').forEach((x) => x.classList.remove('seleccionada'));
      e.currentTarget.classList.add('seleccionada');
      alPulsar();
    },
  }, celdas);

  const pintarLista = () => {
    if (pestana === 'controladores') { pintarControladores(); return; }
    if (!grafo) { reemplazar(lista, h('div', { class: 'vacio' }, 'Cargando…')); return; }
    let filas = [];
    let cabeceras = [];
    if (pestana === 'nodos') {
      const nodos = grafo.nodos.filter(coincide);
      cabeceras = ['Nodo'];
      filas = nodos.map((n) => filaSeleccionable(`n:${n}`, [h('td', { class: 'mono' }, n)], () => verNodo(n)));
    } else if (pestana === 'topics') {
      const topics = grafo.topics.filter((t) => (ocultos || !t.oculto) && coincide(t.nombre + t.tipos.join()));
      cabeceras = ['Topic', 'Tipo', 'Pub', 'Sub'];
      filas = topics.map((t) => filaSeleccionable(`t:${t.nombre}`, [
        h('td', { class: 'mono' }, t.nombre), h('td', { class: 'mono texto-2' }, t.tipos.join(', ')),
        h('td', { class: 'num' }, t.publicadores), h('td', { class: 'num' }, t.suscriptores)], () => verTopic(t.nombre)));
    } else if (pestana === 'servicios') {
      const servicios = grafo.servicios.filter((s) => (ocultos || !s.oculto) && coincide(s.nombre + s.tipos.join()));
      cabeceras = ['Servicio', 'Tipo'];
      filas = servicios.map((s) => h('tr', {}, h('td', { class: 'mono' }, s.nombre), h('td', { class: 'mono texto-2' }, s.tipos.join(', '))));
    } else if (pestana === 'acciones') {
      const acciones = grafo.acciones.filter((a) => coincide(a.nombre + a.tipos.join()));
      cabeceras = ['Acción', 'Tipo'];
      filas = acciones.map((a) => h('tr', {}, h('td', { class: 'mono' }, a.nombre), h('td', { class: 'mono texto-2' }, a.tipos.join(', '))));
    }
    contador.textContent = `${filas.length} elementos`;
    reemplazar(lista, filas.length ? tabla(cabeceras, filas) : h('div', { class: 'vacio' }, 'Nada que mostrar'));
  };

  // --- Controladores ---
  const pintarControladores = () => {
    const estado = ctx.almacen.estado.controladores;
    if (!estado?.disponible) {
      contador.textContent = '';
      reemplazar(lista, h('div', { class: 'vacio' }, 'controller_manager no disponible (¿está lanzado el robot?)'));
      return;
    }
    const conmutar = (activar, nombre) => ctx.api.post('/api/controladores/conmutar',
      activar ? { activar: [nombre] } : { desactivar: [nombre] }).catch((e) => aviso(e.message, 'error'));
    contador.textContent = `${estado.lista.length} controladores`;
    reemplazar(lista,
      h('div', { class: 'fila', style: { padding: '8px 0' } },
        boton('Activar control de movimiento', { clase: 'pequeno exito', icono: 'juego',
          onclick: () => ctx.api.post('/api/controladores/movimiento', { activo: true }).catch((e) => aviso(e.message, 'error')) }),
        boton('Desactivar control de movimiento', { clase: 'pequeno', icono: 'parar',
          titulo: 'Los brazos dejan de aceptar trayectorias (mantienen la última orden de posición)',
          onclick: () => ctx.api.post('/api/controladores/movimiento', { activo: false }).catch((e) => aviso(e.message, 'error')) })),
      tabla(['Controlador', 'Tipo', 'Estado', ''], estado.lista.map((c) => h('tr', {},
        h('td', { class: 'mono' }, c.nombre),
        h('td', { class: 'mono texto-2' }, c.tipo),
        h('td', {}, h('span', { class: `chip ${c.estado === 'active' ? 'ok' : 'aviso'}` }, c.estado)),
        h('td', {}, c.estado === 'active'
          ? boton('Desactivar', { clase: 'pequeno', onclick: () => conmutar(false, c.nombre) })
          : boton('Activar', { clase: 'pequeno', onclick: () => conmutar(true, c.nombre) }))))));
  };

  // --- Detalle de topic ---
  const verTopic = async (nombre) => {
    pararAuto();
    tituloDetalle.textContent = nombre;
    const auto = boton('Auto', { clase: 'pequeno', titulo: 'Actualizar continuamente' });
    auto.addEventListener('click', () => {
      if (autoEcho) { pararAuto(); return; }
      auto.classList.add('activo', 'primario');
      autoEcho = true;
      const bucle = async () => {
        while (autoEcho && vivo && seleccion === `t:${nombre}`) await echo(nombre, true);
        auto.classList.remove('activo', 'primario');
      };
      bucle();
    });
    reemplazar(accionesDetalle, boton('Leer', { clase: 'pequeno primario', icono: 'refrescar', onclick: () => echo(nombre) }), auto);
    reemplazar(detalle, h('div', { class: 'vacio' }, h('span', { class: 'giro' }), ' Escuchando…'));
    await echo(nombre);
  };

  const echo = async (nombre, silencioso = false) => {
    let datos;
    try {
      datos = await ctx.api.get(`/api/ros/topic?nombre=${encodeURIComponent(nombre)}&duracion=1`);
    } catch (e) {
      if (!silencioso) aviso(e.message, 'error');
      pararAuto();
      return;
    }
    if (seleccion !== `t:${nombre}`) return;
    reemplazar(detalle,
      h('div', { class: 'fila', style: { marginBottom: '8px' } },
        h('span', { class: 'chip sin-punto mono' }, datos.tipo),
        h('span', { class: `chip ${datos.frecuencia_hz ? 'ok' : ''}` }, datos.frecuencia_hz ? `${datos.frecuencia_hz} Hz` : `${datos.mensajes} mensajes en 1 s`)),
      h('div', { class: 'pequeno texto-2', style: { marginBottom: '6px' } },
        h('strong', {}, 'Publicadores: '), datos.publicadores.map((p) => `${p.nodo} (${p.fiabilidad.toLowerCase()}, ${p.durabilidad.toLowerCase()})`).join(', ') || '—'),
      h('div', { class: 'pequeno texto-2', style: { marginBottom: '10px' } },
        h('strong', {}, 'Suscriptores: '), datos.suscriptores.join(', ') || '—'),
      datos.mensaje ? h('pre', { class: 'json' }, JSON.stringify(datos.mensaje, null, 2))
        : h('div', { class: 'vacio' }, 'No ha llegado ningún mensaje'));
  };

  const pararAuto = () => { autoEcho = null; };

  // --- Detalle de nodo ---
  const verNodo = async (nombre) => {
    pararAuto();
    tituloDetalle.textContent = nombre;
    reemplazar(accionesDetalle, boton('Parámetros', { clase: 'pequeno', icono: 'engranaje', onclick: () => verParametros(nombre) }));
    let datos;
    try { datos = await ctx.api.get(`/api/ros/nodo?nombre=${encodeURIComponent(nombre)}`); } catch (e) { aviso(e.message, 'error'); return; }
    const bloque = (titulo, elementos) => h('div', { style: { marginBottom: '12px' } },
      h('div', { class: 'titulo texto-3 pequeno', style: { fontWeight: 700, marginBottom: '4px' } }, `${titulo} (${elementos.length})`),
      elementos.length ? elementos.map((e) => h('div', { class: 'mono pequeno' }, e.nombre, h('span', { class: 'texto-3' }, `  ${e.tipos.join(', ')}`)))
        : h('div', { class: 'texto-3 pequeno' }, '—'));
    reemplazar(detalle, bloque('Publica', datos.publicadores), bloque('Se suscribe a', datos.suscripciones),
      bloque('Servicios', datos.servicios), bloque('Clientes de servicio', datos.clientes));
  };

  const verParametros = async (nombre) => {
    reemplazar(detalle, h('div', { class: 'vacio' }, h('span', { class: 'giro' }), ' Leyendo parámetros…'));
    let datos;
    try { datos = await ctx.api.get(`/api/ros/parametros?nodo=${encodeURIComponent(nombre)}`); } catch (e) { aviso(e.message, 'error'); verNodo(nombre); return; }
    reemplazar(detalle, tabla(['Parámetro', 'Valor'], datos.parametros.map((p) => h('tr', {},
      h('td', { class: 'mono' }, p.nombre),
      h('td', { class: 'mono pequeno', style: { wordBreak: 'break-all' } }, typeof p.valor === 'string' ? p.valor : JSON.stringify(p.valor))))));
  };

  const buscador = h('input', { type: 'text', class: 'buscador', placeholder: 'Filtrar…',
    oninput: (e) => { filtro = e.target.value.toLowerCase(); pintarLista(); } });
  const casilla = h('label', { class: 'fila pequeno texto-2' },
    h('input', { type: 'checkbox', onchange: (e) => { ocultos = e.target.checked; pintarLista(); } }), 'Mostrar ocultos');

  reemplazar(contenedor, h('div', { class: 'dos-columnas' },
    h('section', { class: 'panel' },
      h('div', { class: 'cabecera' }, h('h2', {}, 'Grafo de ROS 2'), contador,
        h('div', { class: 'acciones' }, boton('Actualizar', { clase: 'pequeno', icono: 'refrescar', onclick: refrescar }))),
      pestanas,
      h('div', { class: 'cuerpo' }, h('div', { class: 'fila', style: { marginBottom: '8px' } }, buscador, casilla), lista)),
    h('section', { class: 'panel' }, h('div', { class: 'cabecera' }, tituloDetalle, accionesDetalle), detalle)));

  refrescar();
  const intervalo = setInterval(() => { if (pestana !== 'controladores') refrescar(); }, 4000);
  const baja = ctx.almacen.suscribir(() => { if (pestana === 'controladores') pintarControladoresLimitado(); }, false);
  let ultimo = '';
  const pintarControladoresLimitado = () => {
    const clave = JSON.stringify(ctx.almacen.estado.controladores);
    if (clave !== ultimo) { ultimo = clave; pintarControladores(); }
  };
  return () => { vivo = false; pararAuto(); clearInterval(intervalo); baja(); };
}
