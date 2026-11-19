// Sistema (perfiles de arranque) y scripts de prueba, con la salida de cada proceso.

import { aviso, boton, confirmar, h, reemplazar } from '../nucleo/ui.js';

const TEXTO = { parado: 'Parado', en_marcha: 'En marcha', deteniendo: 'Deteniendo…', terminado: 'Terminado', fallido: 'Fallido' };
const CLASE = { en_marcha: 'ok', deteniendo: 'aviso', fallido: 'error', terminado: '' };

export function montar(contenedor, ctx) {
  const consola = h('div', { class: 'consola', role: 'log' });
  const tituloConsola = h('h3', {}, 'Salida');
  let seleccionado = null; // {tipo: 'sistema'|'scripts', id}
  const tarjetas = {};

  const seleccionar = async (tipo, id, nombre) => {
    seleccionado = { tipo, id };
    tituloConsola.textContent = `Salida: ${nombre}`;
    reemplazar(consola);
    const ruta = tipo === 'sistema' ? `/api/sistema/salida?perfil=${encodeURIComponent(id)}` : `/api/scripts/${encodeURIComponent(id)}/salida`;
    try {
      const datos = await ctx.api.get(ruta);
      datos.lineas.forEach((l) => escribir(l.linea));
    } catch (e) { aviso(e.message, 'error'); }
  };

  const escribir = (linea) => {
    const abajo = consola.scrollTop + consola.clientHeight >= consola.scrollHeight - 30;
    const clase = /\[(ERROR|FATAL)\]|Traceback|ERROR/.test(linea) ? 'error' : /\[WARN\]|AVISO|WARNING/.test(linea) ? 'aviso' : linea.startsWith('$ ') ? 'cmd' : '';
    consola.appendChild(h('div', { class: clase }, linea));
    while (consola.childElementCount > 3000) consola.firstChild.remove();
    if (abajo) consola.scrollTop = consola.scrollHeight;
  };

  // --- Sistema ---
  const perfiles = ctx.config.modulos.sistema?.perfiles || [];
  const zonaSistema = h('div', {}, perfiles.map((p) => {
    const estado = h('span', { class: 'chip' }, 'Parado');
    const iniciar = boton('Iniciar', { icono: 'juego', clase: 'exito pequeno', onclick: async () => {
      if (p.confirmar && !await confirmar(`Iniciar ${p.nombre}`, p.confirmar, { aceptar: 'Iniciar' })) return;
      try { await ctx.api.post('/api/sistema/iniciar', { perfil: p.id }); seleccionar('sistema', p.id, p.nombre); } catch (e) { aviso(e.message, 'error'); }
    } });
    const detener = boton('Detener', { icono: 'parar', clase: 'peligro pequeno', onclick: async () => {
      try { await ctx.api.post('/api/sistema/detener', { perfil: p.id }); } catch (e) { aviso(e.message, 'error'); }
    } });
    tarjetas[`sistema:${p.id}`] = { estado, iniciar, detener };
    return h('div', { class: 'tarjeta-script' },
      h('div', { class: 'fila entre' }, h('h3', {}, p.nombre), estado),
      h('p', {}, p.descripcion || '', p.paralelo ? ' (compatible con otro perfil en marcha)' : ''),
      h('p', { class: 'mono texto-3' }, p.comando),
      h('div', { class: 'fila' }, iniciar, detener,
        boton('Ver salida', { clase: 'pequeno fantasma', icono: 'terminal', onclick: () => seleccionar('sistema', p.id, p.nombre) })));
  }));

  // --- Scripts ---
  const zonaScripts = h('div', {}, h('div', { class: 'vacio' }, 'Cargando…'));
  const cargarScripts = async () => {
    let datos;
    try { datos = await ctx.api.get('/api/scripts'); } catch (e) { reemplazar(zonaScripts, h('div', { class: 'vacio' }, e.message)); return; }
    reemplazar(zonaScripts, datos.scripts.length ? datos.scripts.map((s) => {
      const entradas = {};
      const parametros = s.parametros.map((p) => {
        let entrada;
        if (p.opciones) {
          const opciones = p.opciones.map((o) => h('option', { value: o, selected: String(o) === String(p.defecto) }, o === 'ambos' ? 'Ambos brazos' : o));
          entrada = h('select', {}, opciones);
        } else if (p.tipo === 'numero') {
          entrada = h('input', { type: 'number', value: p.defecto ?? '', min: p.min, max: p.max, step: 'any' });
        } else {
          entrada = h('input', { type: 'text', value: p.defecto ?? '' });
        }
        entradas[p.nombre] = entrada;
        const rango = p.tipo === 'numero' && p.min !== undefined ? ` [${p.min}, ${p.max}]` : '';
        return h('label', { class: 'campo' }, `${p.etiqueta || p.nombre}${rango}`, entrada);
      });
      const estado = h('span', { class: 'chip' }, 'Parado');
      const ejecutar = boton('Ejecutar', { icono: 'juego', clase: 'primario pequeno', onclick: async () => {
        const valores = Object.fromEntries(Object.entries(entradas).map(([k, el]) => [k, el.value]));
        try {
          await ctx.api.post(`/api/scripts/${encodeURIComponent(s.id)}/ejecutar`, { parametros: valores });
          seleccionar('scripts', s.id, s.nombre);
        } catch (e) { aviso(e.message, 'error'); }
      } });
      const detener = boton('Detener', { icono: 'parar', clase: 'peligro pequeno', onclick: () =>
        ctx.api.post(`/api/scripts/${encodeURIComponent(s.id)}/detener`).catch((e) => aviso(e.message, 'error')) });
      tarjetas[`scripts:${s.id}`] = { estado, iniciar: ejecutar, detener };
      return h('div', { class: 'tarjeta-script' },
        h('div', { class: 'fila entre' }, h('h3', {}, s.nombre), estado),
        h('p', {}, s.descripcion),
        parametros.length ? h('div', { class: 'parametros' }, parametros) : null,
        h('div', { class: 'fila' }, ejecutar, detener,
          boton('Ver salida', { clase: 'pequeno fantasma', icono: 'terminal', onclick: () => seleccionar('scripts', s.id, s.nombre) })),
        h('p', { class: 'texto-3 pequeno', style: { margin: '8px 0 0' } }, 'Usa la velocidad actual del panel de Operación.'));
    }) : h('div', { class: 'vacio' }, 'No hay scripts en la configuración.'));
  };

  const pintarEstados = (e) => {
    const procesos = { ...Object.fromEntries(Object.entries(e.sistema?.procesos || {}).map(([k, v]) => [`sistema:${k}`, v.estado])),
      ...Object.fromEntries(Object.entries(e.scripts || {}).map(([k, v]) => [`scripts:${k}`, v.estado])) };
    const bloqueado = !!e.seguridad?.activa;
    for (const [clave, t] of Object.entries(tarjetas)) {
      const estado = procesos[clave] || 'parado';
      t.estado.className = `chip ${CLASE[estado] || ''}`;
      t.estado.textContent = TEXTO[estado] || estado;
      const vivo = estado === 'en_marcha' || estado === 'deteniendo';
      t.iniciar.disabled = vivo || (clave.startsWith('scripts:') && bloqueado);
      t.detener.disabled = !vivo;
    }
  };

  reemplazar(contenedor, h('div', { class: 'dos-columnas' },
    h('div', { class: 'columna', style: { gap: '14px' } },
      'sistema' in ctx.config.modulos ? h('section', { class: 'panel' },
        h('div', { class: 'cabecera' }, h('h2', {}, 'Sistema'),
          h('span', { class: 'texto-3 pequeno' }, 'Equivale a ./launcher.sh sim|robot <id>')),
        h('div', { class: 'cuerpo' }, perfiles.length ? zonaSistema : h('div', { class: 'vacio' }, 'Sin perfiles'))) : null,
      'scripts' in ctx.config.modulos ? h('section', { class: 'panel' },
        h('div', { class: 'cabecera' }, h('h2', {}, 'Scripts de prueba')),
        h('div', { class: 'cuerpo' }, zonaScripts)) : null),
    h('section', { class: 'panel', style: { position: 'sticky', top: '110px' } },
      h('div', { class: 'cabecera' }, tituloConsola,
        h('div', { class: 'acciones' }, boton('Limpiar', { clase: 'pequeno fantasma', onclick: () => reemplazar(consola) }))),
      consola)));

  if ('scripts' in ctx.config.modulos) cargarScripts();
  const bajas = [
    ctx.almacen.suscribir(pintarEstados),
    ctx.conexion.on('proceso', (d) => {
      if (seleccionado && d.tipo === seleccionado.tipo && d.id === seleccionado.id) escribir(d.linea);
    }),
  ];
  const activo = Object.entries(ctx.almacen.estado.sistema?.procesos || {}).find(([, v]) => v.estado === 'en_marcha');
  if (activo) seleccionar('sistema', activo[0], activo[1].nombre);
  return () => bajas.forEach((b) => b());
}
