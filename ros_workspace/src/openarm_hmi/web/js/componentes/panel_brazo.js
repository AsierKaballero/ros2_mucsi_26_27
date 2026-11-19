// Panel de control de un brazo: velocidad, movimiento articular (pasos y objetivo),
// movimiento cartesiano, pinza y poses.

import { preferencias } from '../nucleo/almacen.js';
import {
  aGrados, aRadianes, aviso, boton, h, icono, limitar, num, pedirDatos, reemplazar,
} from '../nucleo/ui.js';

const FINALES = ['completada', 'error', 'cancelada'];
const TEXTO_ESTADO = {
  pendiente: 'Pendiente', planificando: 'Planificando', ejecutando: 'Moviendo',
  completada: 'Completado', error: 'Error', cancelada: 'Cancelado',
};

export function chipTarea(tarea, libre = 'Listo') {
  if (!tarea) return h('span', { class: 'chip ok' }, libre);
  const clase = { planificando: 'info', ejecutando: 'aviso', pendiente: 'info', error: 'error' }[tarea.estado] || '';
  return h('span', { class: `chip ${clase} tarea-chip`, title: `${tarea.descripcion}\n${tarea.mensaje || ''}` },
    `${TEXTO_ESTADO[tarea.estado] || tarea.estado}: ${tarea.descripcion}`);
}

export class PanelBrazo {
  constructor(ctx, brazo) {
    this.ctx = ctx;
    this.brazo = brazo;
    this.mov = ctx.config.modulos.movimiento || {};
    this.limites = brazo.articulaciones.map((n) => (brazo.limites || {})[n] || null);
    this.objetivos = null;
    this.modificado = false;
    this.pulsado = false;
    this.controles = [];
    this.estado = {};
    const clave = `brazo.${brazo.sufijo}`;
    this.pref = { pestana: 'articular', paso: 1, pasoMm: 5, pasoRot: 5, marco: 'mundo', ...preferencias.leer(clave, {}) };
    this.guardarPref = () => preferencias.guardar(clave, this.pref);

    this.elemento = this._construir();
    this.bajas = [
      ctx.almacen.suscribir((e) => this._actualizar(e)),
      ctx.local.escuchar('poses', () => this._cargarPoses()),
    ];
    this._cargarPoses();
  }

  destruir() {
    this.pulsado = false;
    this.bajas.forEach((b) => b());
    this.ctx.visor?.previsualizar(this.brazo.id, null);
  }

  // --- Construcción -----------------------------------------------------------------

  _control(el) { this.controles.push(el); return el; }

  _construir() {
    const b = this.brazo;
    this.chip = h('span', {}, chipTarea(null));
    const parar = boton('Parar', { icono: 'parar', clase: 'pequeno', titulo: 'Detener el movimiento de este brazo',
      onclick: () => this._accion('/api/movimiento/parar', { brazo: b.id }) });

    this.cuerpoArticular = this._construirArticular();
    this.cuerpoCartesiano = this._construirCartesiano();
    const pestanas = h('div', { class: 'pestanas' });
    const mostrar = (p) => {
      this.pref.pestana = p;
      this.guardarPref();
      this.cuerpoArticular.hidden = p !== 'articular';
      this.cuerpoCartesiano.hidden = p !== 'cartesiano';
      pestanas.querySelectorAll('button').forEach((x) => x.classList.toggle('activa', x.dataset.p === p));
    };
    for (const [p, texto] of [['articular', 'Articular'], ['cartesiano', 'Cartesiano']]) {
      pestanas.appendChild(h('button', { type: 'button', dataset: { p }, onclick: () => mostrar(p) }, texto));
    }
    this.poses = h('div', { class: 'lista-poses' });

    const panel = h('section', { class: 'panel panel-brazo' },
      h('div', { class: 'cabecera' },
        h('span', { class: `etiqueta-brazo ${b.sufijo}` }),
        h('h2', {}, b.nombre),
        h('div', { class: 'acciones' }, this.chip, parar)),
      this._construirVelocidad(),
      pestanas,
      this.cuerpoArticular,
      this.cuerpoCartesiano,
      this._construirPinza(),
      h('div', { class: 'seccion' },
        h('div', { class: 'titulo' }, 'Poses',
          h('span', { class: 'extra' }, this._control(boton('Guardar actual', {
            icono: 'guardar', clase: 'pequeno fantasma', onclick: () => this._guardarPose() })))),
        this.poses));
    mostrar(this.pref.pestana);
    return panel;
  }

  _construirVelocidad() {
    const maximo = Math.round((this.mov.velocidad_maxima || 1) * 100);
    this.velValor = h('span', { class: 'valor' }, '—');
    const enviar = limitar((valor) => {
      this.ctx.api.post('/api/movimiento/velocidad', { brazo: this.brazo.id, valor: valor / 100 })
        .catch((e) => aviso(e.message, 'error'));
    }, 250);
    this.velDeslizante = h('input', {
      type: 'range', min: 1, max: maximo, step: 1, value: 10,
      'aria-label': `Velocidad de ${this.brazo.nombre}`,
      oninput: (e) => { this.velValor.textContent = `${e.target.value} %`; enviar(Number(e.target.value)); },
      onpointerdown: () => { this.arrastrandoVel = true; },
      onpointerup: () => { setTimeout(() => { this.arrastrandoVel = false; }, 500); },
    });
    return h('div', { class: 'seccion' },
      h('div', { class: 'titulo' }, 'Velocidad', h('span', { class: 'extra texto-3' }, `máx. ${maximo} %`)),
      h('div', { class: 'deslizante' }, this.velDeslizante, this.velValor));
  }

  _selectorPasos(valores, actual, unidad, alElegir) {
    const grupo = h('div', { class: 'grupo-botones' });
    for (const v of valores) {
      const b = boton(`${v}${unidad}`, { clase: `pequeno ${v === actual ? 'activo' : ''}` });
      b.addEventListener('click', () => {
        grupo.querySelectorAll('.btn').forEach((x) => x.classList.remove('activo'));
        b.classList.add('activo');
        alElegir(v);
      });
      grupo.appendChild(b);
    }
    return grupo;
  }

  _botonJog(contenido, titulo, peticion) {
    const b = this._control(h('button', { type: 'button', class: 'btn icono', title: titulo }, contenido));
    const soltar = () => { this.pulsado = false; b.classList.remove('pulsado'); };
    b.addEventListener('pointerdown', (e) => {
      if (b.disabled || e.button > 0) return;
      b.setPointerCapture?.(e.pointerId);
      b.classList.add('pulsado');
      this.pulsado = true;
      this._jog(peticion);
    });
    ['pointerup', 'pointercancel', 'lostpointercapture'].forEach((ev) => b.addEventListener(ev, soltar));
    b.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.pulsado = false; this._jog(peticion); } });
    return b;
  }

  /** Movimiento por pasos: repite el paso mientras el botón siga pulsado. */
  async _jog(peticion) {
    if (this.enJog) return;
    this.enJog = true;
    try {
      do {
        const [ruta, cuerpo] = peticion();
        let tarea;
        try {
          tarea = await this.ctx.api.post(ruta, cuerpo);
        } catch (e) {
          aviso(e.message, 'error');
          break;
        }
        const fin = await this.ctx.conexion.esperarTarea(tarea.id, 30000);
        if (fin.estado !== 'completada') {
          if (fin.estado === 'error') aviso(`${this.brazo.nombre}: ${fin.mensaje}`, 'error');
          break;
        }
      } while (this.pulsado);
    } finally {
      this.enJog = false;
    }
  }

  _construirArticular() {
    const pasos = this.mov.pasos_articulares_grados || [1, 5, 10];
    if (!pasos.includes(this.pref.paso)) this.pref.paso = pasos[Math.min(1, pasos.length - 1)];
    this.filas = this.brazo.articulaciones.map((nombre, i) => this._filaArticulacion(nombre, i));
    const ir = this._control(boton('Ir al objetivo', { icono: 'juego', clase: 'primario',
      onclick: () => this._irObjetivo() }));
    const copiar = boton('Copiar actual', { icono: 'copiar', titulo: 'Objetivo = posición actual',
      onclick: () => { this.modificado = false; this._sincronizarObjetivos(true); } });
    return h('div', {},
      h('div', { class: 'seccion' },
        h('div', { class: 'titulo' }, 'Paso', h('span', { class: 'extra' },
          this._selectorPasos(pasos, this.pref.paso, '°', (v) => { this.pref.paso = v; this.guardarPref(); }))),
        this.filas.map((f) => f.el),
        h('div', { class: 'fila entre', style: { marginTop: '10px' } }, copiar, ir)));
  }

  _filaArticulacion(nombre, i) {
    const conocido = this.limites[i];
    const limite = Number.isFinite(conocido?.inferior) && Number.isFinite(conocido?.superior)
      ? conocido : { inferior: -Math.PI, superior: Math.PI };
    const minimo = aGrados(limite.inferior);
    const maximo = aGrados(limite.superior);
    const actual = h('span', { class: 'actual' }, '—');
    const objetivo = h('span', { class: 'objetivo' }, '');
    const pos = h('div', { class: 'pos' });
    const meta = h('div', { class: 'meta' });
    const cero = h('div', { class: 'cero', style: { left: `${(-minimo / (maximo - minimo)) * 100}%` } });
    const barra = h('div', { class: 'barra-limites', title: `Límites: ${num(minimo)}° … ${num(maximo)}°` }, cero, meta, pos);
    const deslizante = h('input', { type: 'range', min: minimo, max: maximo, step: 0.1, value: 0,
      'aria-label': `Objetivo J${i + 1}` });
    const numero = h('input', { type: 'number', min: num(minimo), max: num(maximo), step: 0.5, value: 0,
      'aria-label': `Objetivo J${i + 1} en grados` });
    const fijar = (grados) => {
      const g = Math.min(Math.max(Number(grados), minimo), maximo);
      if (!this.objetivos || Number.isNaN(g)) return;
      this.objetivos[i] = aRadianes(g);
      this.modificado = true;
      this._pintarObjetivos();
    };
    deslizante.addEventListener('input', () => fijar(deslizante.value));
    numero.addEventListener('change', () => fijar(numero.value));

    const jog = (signo) => () => [
      '/api/movimiento/jog_articular',
      { brazo: this.brazo.id, indice: i, delta: signo * aRadianes(this.pref.paso) },
    ];
    const el = h('div', { class: 'articulacion' },
      h('span', { class: 'nombre', title: nombre }, `J${i + 1}`),
      this._botonJog(icono('menos'), `J${i + 1} −paso`, jog(-1)),
      h('div', { class: 'medida' }, h('div', { class: 'linea' }, actual, objetivo), barra),
      this._botonJog(icono('mas'), `J${i + 1} +paso`, jog(1)),
      h('div', { class: 'objetivo-fila' }, this._control(deslizante), this._control(numero)));
    const porcentaje = (g) => `${Math.min(Math.max((g - minimo) / (maximo - minimo), 0), 1) * 100}%`;
    return { el, actual, objetivo, pos, meta, barra, deslizante, numero, minimo, maximo, porcentaje };
  }

  _construirCartesiano() {
    this.poseTexto = h('div', { class: 'pose-actual' }, '—');
    const pasosMm = this.mov.pasos_cartesianos_mm || [1, 5, 10];
    const pasosRot = this.mov.pasos_rotacion_grados || [1, 5, 10];
    const marco = h('div', { class: 'grupo-botones' });
    for (const [valor, texto] of [['mundo', 'Mundo'], ['herramienta', 'Herramienta']]) {
      const b = boton(texto, { clase: `pequeno ${this.pref.marco === valor ? 'activo' : ''}` });
      b.addEventListener('click', () => {
        this.pref.marco = valor;
        this.guardarPref();
        marco.querySelectorAll('.btn').forEach((x) => x.classList.toggle('activo', x === b));
      });
      marco.appendChild(b);
    }
    const tras = (eje, signo) => () => {
      const t = [0, 0, 0];
      t[eje] = (signo * this.pref.pasoMm) / 1000;
      return ['/api/movimiento/jog_cartesiano', { brazo: this.brazo.id, traslacion: t, rotacion: [0, 0, 0], marco: this.pref.marco }];
    };
    const rot = (eje, signo) => () => {
      const r = [0, 0, 0];
      r[eje] = signo * aRadianes(this.pref.pasoRot);
      return ['/api/movimiento/jog_cartesiano', { brazo: this.brazo.id, traslacion: [0, 0, 0], rotacion: r, marco: this.pref.marco }];
    };
    const ejes = ['x', 'y', 'z'];
    const padTras = h('div', { class: 'pad-cartesiano' },
      ejes.map((e, i) => this._botonJog(h('span', { class: `eje-${e}` }, `${e.toUpperCase()}+`), `${e.toUpperCase()} +`, tras(i, 1))),
      ejes.map((e, i) => this._botonJog(h('span', { class: `eje-${e}` }, `${e.toUpperCase()}−`), `${e.toUpperCase()} −`, tras(i, -1))));
    const padRot = h('div', { class: 'pad-cartesiano' },
      ejes.map((e, i) => this._botonJog(h('span', { class: `eje-${e}` }, `R${e}+`), `Giro en ${e.toUpperCase()} +`, rot(i, 1))),
      ejes.map((e, i) => this._botonJog(h('span', { class: `eje-${e}` }, `R${e}−`), `Giro en ${e.toUpperCase()} −`, rot(i, -1))));
    padTras.querySelectorAll('.btn').forEach((b) => b.classList.remove('icono'));
    padRot.querySelectorAll('.btn').forEach((b) => b.classList.remove('icono'));

    // Ir a una pose absoluta
    this.entradasPose = ['x', 'y', 'z', 'roll', 'pitch', 'yaw'].map((n) =>
      this._control(h('input', { type: 'number', step: n.length === 1 ? 1 : 0.5, 'aria-label': n })));
    const etiquetas = ['X mm', 'Y mm', 'Z mm', 'R °', 'P °', 'Y °'];
    const copiar = boton('Copiar actual', { icono: 'copiar', clase: 'pequeno', onclick: () => this._copiarPose() });
    const ir = this._control(boton('Ir a la pose', { icono: 'objetivo', clase: 'pequeno primario', onclick: () => this._irPose() }));

    return h('div', {},
      h('div', { class: 'seccion' },
        h('div', { class: 'titulo' }, 'Pose del efector', h('span', { class: 'extra' }, marco)),
        this.poseTexto),
      h('div', { class: 'seccion' },
        h('div', { class: 'titulo' }, 'Traslación', h('span', { class: 'extra' },
          this._selectorPasos(pasosMm, this.pref.pasoMm, ' mm', (v) => { this.pref.pasoMm = v; this.guardarPref(); }))),
        padTras),
      h('div', { class: 'seccion' },
        h('div', { class: 'titulo' }, 'Rotación', h('span', { class: 'extra' },
          this._selectorPasos(pasosRot, this.pref.pasoRot, '°', (v) => { this.pref.pasoRot = v; this.guardarPref(); }))),
        padRot),
      h('div', { class: 'seccion' },
        h('div', { class: 'titulo' }, 'Ir a pose absoluta'),
        h('div', { class: 'rejilla-pose' }, this.entradasPose.map((el, i) => h('label', { class: 'campo' }, etiquetas[i], el))),
        h('div', { class: 'fila entre', style: { marginTop: '8px' } }, copiar, ir)));
  }

  _construirPinza() {
    const maximo = this.brazo.pinza.anchura_maxima_mm;
    this.pinzaActual = h('span', { class: 'mono' }, '— mm');
    this.pinzaValor = h('span', { class: 'valor' }, '0 mm');
    this.pinzaChip = h('span', {});
    this.pinzaDeslizante = this._control(h('input', {
      type: 'range', min: 0, max: maximo, step: 1, value: 0, 'aria-label': `Apertura de la pinza de ${this.brazo.nombre}`,
      oninput: (e) => { this.pinzaValor.textContent = `${e.target.value} mm`; this.arrastrandoPinza = true; },
      onchange: (e) => { this.arrastrandoPinza = false; this._pinza(Number(e.target.value)); },
    }));
    return h('div', { class: 'seccion' },
      h('div', { class: 'titulo' }, 'Pinza', h('span', { class: 'extra' }, 'actual ', this.pinzaActual)),
      h('div', { class: 'deslizante' }, this.pinzaDeslizante, this.pinzaValor),
      h('div', { class: 'fila entre', style: { marginTop: '8px' } },
        this.pinzaChip,
        h('div', { class: 'fila' },
          this._control(boton('Cerrar', { clase: 'pequeno', onclick: () => this._pinza(0) })),
          this._control(boton('Abrir', { clase: 'pequeno', onclick: () => this._pinza(maximo) })))));
  }

  // --- Acciones ---------------------------------------------------------------------

  async _accion(ruta, cuerpo) {
    try {
      return await this.ctx.api.post(ruta, cuerpo);
    } catch (e) {
      aviso(e.message, 'error');
      return null;
    }
  }

  async _irObjetivo() {
    if (!this.objetivos) return;
    const tarea = await this._accion('/api/movimiento/articulaciones', { brazo: this.brazo.id, posiciones: this.objetivos });
    if (tarea) {
      const fin = await this.ctx.conexion.esperarTarea(tarea.id);
      if (fin.estado === 'completada') { this.modificado = false; this._pintarObjetivos(); }
    }
  }

  _pinza(anchura) {
    this.pinzaDeslizante.value = anchura;
    this.pinzaValor.textContent = `${Math.round(anchura)} mm`;
    this._accion('/api/pinza', { brazo: this.brazo.id, anchura_mm: anchura });
  }

  _copiarPose() {
    const pose = this.estado.estado?.poses?.[this.brazo.id];
    if (!pose) { aviso('Pose del efector desconocida (TF)', 'aviso'); return; }
    const valores = [...pose.posicion.map((v) => v * 1000), ...pose.rpy.map(aGrados)];
    this.entradasPose.forEach((el, i) => { el.value = valores[i].toFixed(i < 3 ? 1 : 1); });
  }

  _irPose() {
    const v = this.entradasPose.map((el) => Number(el.value));
    if (this.entradasPose.some((el) => el.value === '') || v.some(Number.isNaN)) {
      aviso('Completa los seis valores (pulsa "Copiar actual" para partir de la pose actual)', 'aviso');
      return;
    }
    this._accion('/api/movimiento/pose', {
      brazo: this.brazo.id,
      posicion: v.slice(0, 3).map((x) => x / 1000),
      rpy: v.slice(3).map(aRadianes),
    });
  }

  async _cargarPoses() {
    let datos;
    try { datos = await this.ctx.api.get('/api/poses'); } catch { return; }
    const poses = datos.poses.filter((p) => p.articulaciones[this.brazo.sufijo]);
    reemplazar(this.poses, poses.length ? poses.map((p) => {
      const b = this._control(boton(p.nombre, {
        icono: p.predefinida ? 'casa' : 'marcador', clase: 'pequeno',
        titulo: `${p.descripcion || ''}\n${p.articulaciones[this.brazo.sufijo].map((x) => `${num(aGrados(x))}°`).join('  ')}`,
        onclick: () => this._accion(`/api/poses/${encodeURIComponent(p.nombre)}/ir`, { brazo: this.brazo.id }),
      }));
      b.addEventListener('mouseenter', () => this._previsualizarPose(p));
      b.addEventListener('mouseleave', () => this._previsualizarPose(null));
      return b;
    }) : h('span', { class: 'texto-3 pequeno' }, 'Sin poses'));
    this._aplicarBloqueo();
  }

  _previsualizarPose(pose) {
    if (!this.ctx.visor) return;
    if (!pose) { this._pintarObjetivos(); return; }
    const valores = pose.articulaciones[this.brazo.sufijo];
    const objetivo = Object.fromEntries(this.brazo.articulaciones.map((n, i) => [n, valores[i]]));
    this.ctx.visor.previsualizar(this.brazo.id, objetivo, this.estado.estado?.posiciones || {});
  }

  async _guardarPose() {
    const datos = await pedirDatos('Guardar pose actual', [
      { nombre: 'nombre', etiqueta: 'Nombre', ayuda: 'p. ej. sobre_mesa' },
      { nombre: 'brazo', etiqueta: 'Brazos', tipo: 'select', valor: this.brazo.id, opciones: [
        { valor: this.brazo.id, texto: this.brazo.nombre }, { valor: 'ambos', texto: 'Ambos brazos' }] },
    ], { aceptar: 'Guardar' });
    if (!datos || !datos.nombre) return;
    const pose = await this._accion('/api/poses', datos);
    if (pose) {
      aviso(`Pose '${pose.nombre}' guardada`, 'exito');
      this.ctx.local.emitir('poses');
    }
  }

  // --- Actualización con el estado del servidor -------------------------------------

  _sincronizarObjetivos(forzar = false) {
    const posiciones = this.estado.estado?.posiciones;
    if (!posiciones) return;
    const actuales = this.brazo.articulaciones.map((n) => posiciones[n]);
    if (actuales.some((v) => v === undefined)) return;
    if (forzar || !this.objetivos || !this.modificado) this.objetivos = actuales;
    this._pintarObjetivos();
  }

  _pintarObjetivos() {
    if (!this.objetivos) return;
    const posiciones = this.estado.estado?.posiciones || {};
    let distinto = false;
    this.filas.forEach((f, i) => {
      const g = aGrados(this.objetivos[i]);
      const actual = posiciones[this.brazo.articulaciones[i]];
      const diferente = this.modificado && actual !== undefined && Math.abs(aGrados(actual) - g) > 0.05;
      distinto = distinto || diferente;
      f.objetivo.textContent = diferente ? `→ ${num(g)}°` : '';
      f.meta.style.left = f.porcentaje(g);
      f.meta.hidden = !diferente;
      if (document.activeElement !== f.deslizante) f.deslizante.value = g;
      if (document.activeElement !== f.numero) f.numero.value = num(g);
    });
    const objetivo = distinto
      ? Object.fromEntries(this.brazo.articulaciones.map((n, i) => [n, this.objetivos[i]])) : null;
    this.ctx.visor?.previsualizar(this.brazo.id, objetivo, posiciones);
  }

  _aplicarBloqueo() {
    const s = this.estado;
    const bloqueado = !!s.seguridad?.activa || s.movimiento?.disponible === false;
    const titulo = s.seguridad?.activa ? 'Parada de emergencia activa' : 'move_group no disponible';
    for (const el of this.controles) {
      el.disabled = bloqueado;
      if (bloqueado) el.dataset.bloqueo = titulo; else delete el.dataset.bloqueo;
    }
    const pinzaDisponible = s.pinza?.[this.brazo.id]?.disponible;
    if (!s.seguridad?.activa && pinzaDisponible !== undefined) this.pinzaDeslizante.disabled = !pinzaDisponible;
  }

  _actualizar(estado) {
    this.estado = estado;
    const posiciones = estado.estado?.posiciones || {};
    const b = this.brazo;

    // Articulaciones
    this.filas.forEach((f, i) => {
      const v = posiciones[b.articulaciones[i]];
      if (v === undefined) return;
      const g = aGrados(v);
      f.actual.textContent = `${num(g)}°`;
      f.pos.style.left = f.porcentaje(g);
      const margen = (f.maximo - f.minimo) * 0.03;
      f.barra.classList.toggle('cerca', g < f.minimo + margen || g > f.maximo - margen);
    });
    this._sincronizarObjetivos();

    // Pose cartesiana
    const pose = estado.estado?.poses?.[b.id];
    if (pose) {
      const [x, y, z] = pose.posicion.map((v) => v * 1000);
      const [r, p, yw] = pose.rpy.map(aGrados);
      reemplazar(this.poseTexto,
        h('div', {}, h('span', {}, 'X'), num(x)), h('div', {}, h('span', {}, 'Y'), num(y)), h('div', {}, h('span', {}, 'Z'), num(z)),
        h('div', {}, h('span', {}, 'R'), `${num(r)}°`), h('div', {}, h('span', {}, 'P'), `${num(p)}°`), h('div', {}, h('span', {}, 'Y'), `${num(yw)}°`));
    }

    // Velocidad
    const vel = estado.movimiento?.velocidades?.[b.id];
    if (vel !== undefined && !this.arrastrandoVel) {
      this.velDeslizante.value = Math.round(vel * 100);
      this.velValor.textContent = `${Math.round(vel * 100)} %`;
    }

    // Tarea en curso
    const tareas = estado.movimiento?.tareas || {};
    const tarea = tareas[b.id] || tareas.ambos;
    const clave = tarea ? `${tarea.id}${tarea.estado}` : '';
    if (clave !== this._ultimaTarea) {
      this._ultimaTarea = clave;
      reemplazar(this.chip, chipTarea(tarea));
    }

    // Pinza
    const pinza = estado.pinza?.[b.id];
    if (pinza) {
      this.pinzaActual.textContent = pinza.anchura_mm === null ? '— mm' : `${num(pinza.anchura_mm, 0)} mm`;
      const clavePinza = pinza.tarea ? `${pinza.tarea.id}${pinza.tarea.estado}` : '';
      if (clavePinza !== this._ultimaPinza) {
        this._ultimaPinza = clavePinza;
        reemplazar(this.pinzaChip, pinza.tarea ? chipTarea(pinza.tarea) : '');
      }
      if (!this.arrastrandoPinza && !pinza.tarea && pinza.anchura_mm !== null && document.activeElement !== this.pinzaDeslizante) {
        this.pinzaDeslizante.value = pinza.anchura_mm;
        this.pinzaValor.textContent = `${num(pinza.anchura_mm, 0)} mm`;
      }
    }
    this._aplicarBloqueo();
  }
}

export { FINALES };
