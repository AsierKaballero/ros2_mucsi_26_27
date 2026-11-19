// Arranque de la interfaz: configuración, conexión, barra superior, navegación y vistas.

import { api, Conexion } from './nucleo/api.js';
import { Almacen, preferencias } from './nucleo/almacen.js';
import { aviso, boton, confirmar, h, icono, reemplazar } from './nucleo/ui.js';
import { visorCompartido } from './componentes/visor3d.js';
import { VISTAS } from './vistas/indice.js';

/** Eventos entre componentes del navegador (p. ej. "poses" cuando cambia la lista). */
function crearBusLocal() {
  const oyentes = new Map();
  return {
    emitir(evento, datos) { (oyentes.get(evento) || []).forEach((fn) => fn(datos)); },
    escuchar(evento, fn) {
      if (!oyentes.has(evento)) oyentes.set(evento, new Set());
      oyentes.get(evento).add(fn);
      return () => oyentes.get(evento).delete(fn);
    },
  };
}

/** Buffer de mensajes de /rosout, compartido para no perderlos al cambiar de vista. */
function crearRegistro(conexion) {
  const oyentes = new Set();
  const registro = {
    entradas: [],
    escuchar(fn) { oyentes.add(fn); return () => oyentes.delete(fn); },
    agregar(e) {
      registro.entradas.push(e);
      if (registro.entradas.length > 3000) registro.entradas.splice(0, 500);
      oyentes.forEach((fn) => fn(e));
    },
  };
  conexion.on('log', (e) => registro.agregar(e));
  api.get('/api/registro').then((d) => {
    const conocidos = new Set(registro.entradas.map((e) => e.n));
    d.entradas.filter((e) => !conocidos.has(e.n)).forEach((e) => registro.entradas.push(e));
    registro.entradas.sort((a, b) => a.n - b.n);
  }).catch(() => {});
  return registro;
}

async function cargarConfig() {
  for (;;) {
    try {
      return await api.get('/api/config');
    } catch (e) {
      reemplazar(document.getElementById('vista'), h('div', { class: 'vacio' },
        `No se puede contactar con el servidor del HMI (${e.message}). Reintentando…`));
      await new Promise((r) => setTimeout(r, 2000));
    }
  }
}

function aplicarTema(tema) {
  document.documentElement.dataset.theme = tema;
  preferencias.guardar('tema', tema);
}

async function iniciar() {
  aplicarTema(preferencias.leer('tema', 'dark'));
  const config = await cargarConfig();
  const conexion = new Conexion();
  const almacen = new Almacen();
  const ctx = {
    api, conexion, almacen, config,
    local: crearBusLocal(),
    registro: crearRegistro(conexion),
    visor: visorCompartido(api),
  };
  conexion.on('estado', (e) => almacen.actualizar(e));
  conexion.conectar();
  window.hmi = ctx; // Para depurar desde la consola del navegador

  construirBarra(ctx);
  const enrutador = construirNavegacion(ctx);
  configurarParada(ctx);

  // Errores de órdenes que no se ven en un panel (poses, objetivos, pinzas...)
  conexion.on('tarea', (t) => {
    if (t.estado === 'error' && !['jog', 'cartesiano'].includes(t.tipo)) aviso(`${t.descripcion}: ${t.mensaje}`, 'error', 7000);
  });
  // Cuando llega la descripción del robot (al lanzarlo después del HMI) se recargan los
  // límites y el modelo 3D
  conexion.on('robot_descripcion', async () => {
    ctx.config = await cargarConfig();
    ctx.visor.robot || ctx.visor.cargar(ctx.config.robot.brazos.map((b) => b.efector));
    enrutador.recargar();
  });
  let conectadoAntes = null;
  conexion.on('conexion', (conectado) => {
    if (conectadoAntes === false && conectado) aviso('Conexión con el servidor recuperada', 'exito');
    if (conectado === false && conectadoAntes) aviso('Conexión con el servidor perdida', 'error');
    conectadoAntes = conectado;
  });
}

// --- Barra superior ------------------------------------------------------------------

function construirBarra(ctx) {
  const robot = ctx.config.robot;
  const chips = {
    conexion: h('span', { class: 'chip error', title: 'Conexión del navegador con el servidor del HMI' }, 'Servidor'),
    robot: h('span', { class: 'chip', title: 'Llegan /joint_states' }, 'Robot'),
    moveit: h('span', { class: 'chip', title: 'move_group de MoveIt' }, 'MoveIt'),
    control: h('span', { class: 'chip', title: 'Controladores de ros2_control' }, 'Control'),
  };

  // Iniciar/Detener del sistema
  const perfiles = (ctx.config.modulos.sistema?.perfiles || []).filter((p) => !p.paralelo);
  const selector = h('select', { 'aria-label': 'Perfil de arranque', title: 'Perfil de arranque' },
    perfiles.map((p) => h('option', { value: p.id, selected: p.id === preferencias.leer('perfil', perfiles[0]?.id) }, p.nombre)));
  selector.addEventListener('change', () => preferencias.guardar('perfil', selector.value));
  const sistemaChip = h('span', { class: 'chip' }, 'Sistema parado');
  const iniciar = boton('Iniciar', { icono: 'juego', clase: 'exito', onclick: async () => {
    const perfil = perfiles.find((p) => p.id === selector.value);
    if (!perfil) return;
    if (perfil.confirmar && !await confirmar(`Iniciar ${perfil.nombre}`, perfil.confirmar, { aceptar: 'Iniciar' })) return;
    try {
      await ctx.api.post('/api/sistema/iniciar', { perfil: perfil.id });
      aviso(`Iniciando ${perfil.nombre}… (la salida está en "Sistema y scripts")`, 'info');
    } catch (e) { aviso(e.message, 'error'); }
  } });
  const detener = boton('Detener', { icono: 'parar', clase: 'peligro', onclick: async () => {
    if (!await confirmar('Detener el sistema', 'Se pararán los controladores y MoveIt. Con el robot real los motores se deshabilitan: sujeta los brazos si pueden caer.', { aceptar: 'Detener', peligro: true })) return;
    try { await ctx.api.post('/api/sistema/detener', {}); } catch (e) { aviso(e.message, 'error'); }
  } });
  const zonaSistema = 'sistema' in ctx.config.modulos && perfiles.length
    ? h('div', { class: 'sistema' }, selector, iniciar, detener, sistemaChip) : null;

  const tema = h('button', { class: 'btn icono fantasma', type: 'button', title: 'Tema claro/oscuro',
    onclick: () => { aplicarTema(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light'); pintarTema(); } });
  const pintarTema = () => reemplazar(tema, icono(document.documentElement.dataset.theme === 'light' ? 'luna' : 'sol'));
  pintarTema();

  const parada = h('button', { class: 'boton-parada', type: 'button', title: `Parada de emergencia (tecla ${ctx.config.modulos.seguridad?.tecla_parada || '—'})`,
    onclick: () => activarParada(ctx) }, icono('aviso'), 'PARADA');

  reemplazar(document.getElementById('barra'),
    h('div', { class: 'marca' }, h('div', { class: 'logo' }, icono('mando')),
      h('div', {}, robot.nombre || `OpenArm ${robot.cuerpo}`, h('br'), h('small', {}, 'HMI de control'))),
    h('div', { class: 'chips' }, Object.values(chips)),
    h('div', { class: 'espaciador' }),
    zonaSistema,
    tema,
    'seguridad' in ctx.config.modulos ? parada : null);

  ctx.conexion.on('conexion', (ok) => { chips.conexion.className = `chip ${ok ? 'ok' : 'error'}`; });
  ctx.almacen.suscribir((e) => {
    const edad = e.estado?.edad_joint_states;
    chips.robot.className = `chip ${edad < 1 ? 'ok' : edad < 5 ? 'aviso' : 'error'}`;
    chips.robot.title = edad < 9999 ? `Último /joint_states hace ${edad.toFixed(1)} s` : 'Sin /joint_states';
    chips.moveit.className = `chip ${e.movimiento?.disponible ? 'ok' : 'error'}`;
    const lista = e.controladores?.lista || [];
    const activos = lista.filter((c) => c.estado === 'active').length;
    chips.control.className = `chip ${!lista.length ? 'error' : activos === lista.length ? 'ok' : 'aviso'}`;
    chips.control.textContent = lista.length ? `Control ${activos}/${lista.length}` : 'Control';

    const s = e.sistema;
    if (s && zonaSistema) {
      const principal = s.principal ? s.procesos[s.principal] : null;
      if (principal) {
        sistemaChip.className = `chip ${principal.estado === 'deteniendo' ? 'aviso' : 'ok'}`;
        sistemaChip.textContent = principal.estado === 'deteniendo' ? 'Deteniendo…' : principal.nombre;
      } else if (s.externo) {
        sistemaChip.className = 'chip info';
        sistemaChip.textContent = 'Lanzado fuera del HMI';
      } else {
        sistemaChip.className = 'chip';
        sistemaChip.textContent = 'Sistema parado';
      }
      iniciar.disabled = !!principal || s.externo;
      detener.disabled = !principal || principal.estado === 'deteniendo';
      selector.disabled = !!principal;
    }
    parada.classList.toggle('activa', !!e.seguridad?.activa);
  });
}

// --- Parada de emergencia -------------------------------------------------------------

async function activarParada(ctx) {
  try {
    await ctx.api.post('/api/seguridad/parada', { motivo: 'Pulsada en el HMI' });
  } catch (e) {
    aviso(`¡No se pudo activar la parada! ${e.message}. Usa el corte de alimentación.`, 'error', 0);
  }
}

function configurarParada(ctx) {
  const tecla = ctx.config.modulos.seguridad?.tecla_parada;
  if (tecla) {
    // En fase de captura, antes que cualquier otro manejador (incluidos los diálogos)
    window.addEventListener('keydown', (e) => {
      if (e.key === tecla && !e.repeat) { e.hmiParada = true; activarParada(ctx); }
    }, true);
  }
  const banda = document.getElementById('aviso-parada');
  const motivo = h('span', {});
  const rearmar = boton('Rearmar', { icono: 'refrescar', clase: 'pequeno', onclick: async () => {
    const ok = await confirmar('Rearmar',
      'Se reactivarán los controladores y el HMI volverá a aceptar órdenes de movimiento. ¿Está la zona despejada y resuelta la causa de la parada?',
      { aceptar: 'Rearmar' });
    if (!ok) return;
    try { await ctx.api.post('/api/seguridad/rearme'); aviso('Sistema rearmado', 'exito'); } catch (e) { aviso(e.message, 'error'); }
  } });
  reemplazar(banda, icono('aviso'), h('span', {}, 'PARADA DE EMERGENCIA ACTIVA'), motivo, rearmar);
  ctx.almacen.suscribir((e) => {
    const activa = !!e.seguridad?.activa;
    banda.hidden = !activa;
    motivo.textContent = activa && e.seguridad.motivo ? `(${e.seguridad.motivo})` : '';
  });
  ctx.conexion.on('parada_emergencia', () => aviso('Parada de emergencia activada', 'error', 6000));
}

// --- Navegación ----------------------------------------------------------------------

function construirNavegacion(ctx) {
  const activos = new Set(Object.keys(ctx.config.modulos));
  const vistas = VISTAS.filter((v) => (v.alguno ? v.modulos.some((m) => activos.has(m)) : v.modulos.every((m) => activos.has(m))));
  const nav = document.getElementById('navegacion');
  const contenedor = document.getElementById('vista');
  const enlaces = {};
  reemplazar(nav, vistas.map((v) => {
    enlaces[v.id] = h('a', { href: `#${v.id}` }, icono(v.icono), v.titulo);
    return enlaces[v.id];
  }));

  let desmontar = null;
  let actual = null;
  let generacion = 0;
  const mostrar = async (forzar = false) => {
    const id = location.hash.slice(1) || vistas[0]?.id;
    const vista = vistas.find((v) => v.id === id) || vistas[0];
    if (!vista || (vista.id === actual && !forzar)) return;
    const mia = ++generacion;
    if (desmontar) { try { desmontar(); } catch (e) { console.error(e); } desmontar = null; }
    actual = vista.id;
    Object.entries(enlaces).forEach(([k, a]) => a.classList.toggle('activa', k === vista.id));
    reemplazar(contenedor, h('div', { class: 'vacio' }, 'Cargando…'));
    try {
      const modulo = await vista.cargar();
      if (mia !== generacion) return;
      desmontar = modulo.montar(contenedor, ctx) || null;
    } catch (e) {
      console.error(e);
      reemplazar(contenedor, h('div', { class: 'vacio' }, `Error al cargar la vista: ${e.message}`));
    }
  };
  window.addEventListener('hashchange', () => mostrar());
  mostrar();
  return { recargar: () => mostrar(true) };
}

iniciar();
