// Gemelo digital 3D: el URDF que publica robot_state_publisher, movido en tiempo real con
// /joint_states. Incluye un "fantasma" semitransparente para previsualizar objetivos
// articulares antes de ejecutarlos, y ejes en el punto de agarre de cada pinza.
//
// Es un objeto único (singleton) que se recoloca en la vista que lo muestra, para no
// volver a cargar las mallas al cambiar de vista.

import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import URDFLoader from '/vendor/urdf-loader/URDFLoader.js';
import { preferencias } from '../nucleo/almacen.js';
import { boton, h } from '../nucleo/ui.js';

function preferenciasVisor() {
  const valores = { rejilla: true, ejes: true, fantasma: true, vista: 'iso',
    ...preferencias.leer('visor3d', {}) };
  valores.guardar = () => {
    const { guardar, ...datos } = valores;
    preferencias.guardar('visor3d', datos);
  };
  return valores;
}

const VISTAS_CAMARA = {
  frontal: [1.6, 0.9, 0], // [x, y, z] en coordenadas de three (Y arriba)
  lateral: [0, 0.9, 1.6],
  superior: [0.01, 2.2, 0],
  iso: [1.3, 1.2, 1.3],
};

export class Visor3D {
  constructor(api) {
    this.api = api;
    this.robot = null;
    this.fantasma = null;
    this.ejes = [];
    this.cargando = false;
    this.contenedor = null;
    this.animando = false;
    this.pref = preferenciasVisor();

    this.escena = new THREE.Scene();
    this.camara = new THREE.PerspectiveCamera(45, 1, 0.01, 50);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

    this.controles = new OrbitControls(this.camara, this.renderer.domElement);
    this.controles.enableDamping = true;
    this.controles.target.set(0, 0.55, 0);

    this.escena.add(new THREE.HemisphereLight(0xffffff, 0x334155, 1.6));
    const sol = new THREE.DirectionalLight(0xffffff, 1.6);
    sol.position.set(2, 4, 3);
    this.escena.add(sol);
    const contraluz = new THREE.DirectionalLight(0xffffff, 0.6);
    contraluz.position.set(-3, 2, -2);
    this.escena.add(contraluz);

    this.rejilla = new THREE.GridHelper(3, 30, 0x64748b, 0x334155);
    this.escena.add(this.rejilla);
    this.ejesMundo = new THREE.AxesHelper(0.25);
    this.ejesMundo.rotation.x = -Math.PI / 2; // ejes de ROS (Z arriba)
    this.escena.add(this.ejesMundo);

    this.mensaje = h('div', { class: 'mensaje' }, 'Esperando la descripción del robot…');
    this.leyenda = h('div', { class: 'leyenda' }, '');
    this.elemento = h('div', { class: 'visor3d' }, this.renderer.domElement, this.mensaje,
      this._herramientas(), this.leyenda);
    this.observador = new ResizeObserver(() => this._redimensionar());
    this.colocarCamara(this.pref.vista || 'iso');
  }

  _herramientas() {
    const alternar = (texto, clave, titulo) => {
      const b = boton(texto, { clase: `pequeno ${this.pref[clave] ? 'activo' : ''}`, titulo });
      b.addEventListener('click', () => {
        this.pref[clave] = !this.pref[clave];
        b.classList.toggle('activo', this.pref[clave]);
        this.pref.guardar();
        this._aplicarVisibilidad();
      });
      return b;
    };
    return h('div', { class: 'herramientas' },
      ['iso', 'frontal', 'lateral', 'superior'].map((v) =>
        boton(v[0].toUpperCase() + v.slice(1), { clase: 'pequeno', onclick: () => this.colocarCamara(v) })),
      alternar('Rejilla', 'rejilla', 'Mostrar la rejilla del suelo'),
      alternar('Ejes', 'ejes', 'Ejes del mundo y del punto de agarre de cada pinza'),
      alternar('Fantasma', 'fantasma', 'Previsualizar los objetivos articulares'));
  }

  colocarCamara(vista) {
    const [x, y, z] = VISTAS_CAMARA[vista] || VISTAS_CAMARA.iso;
    this.camara.position.set(x, y, z);
    this.controles.target.set(0, 0.55, 0);
    this.controles.update();
    this.pref.vista = vista;
    this.pref.guardar();
  }

  _aplicarVisibilidad() {
    this.rejilla.visible = this.pref.rejilla;
    this.ejesMundo.visible = this.pref.ejes;
    this.ejes.forEach((e) => { e.visible = this.pref.ejes; });
    if (this.fantasma) this.fantasma.visible = this.pref.fantasma && this._fantasmaActivo;
  }

  // --- Carga del robot --------------------------------------------------------------

  async cargar(efectores = []) {
    if (this.robot || this.cargando) return;
    this.cargando = true;
    try {
      const respuesta = await fetch('/api/robot/urdf');
      if (!respuesta.ok) throw new Error((await respuesta.json()).error);
      const urdf = await respuesta.text();
      this.mensaje.textContent = 'Cargando mallas…';

      const gestor = new THREE.LoadingManager();
      const cargador = new URDFLoader(gestor);
      cargador.packages = (paquete) => `/paquetes/${paquete}`;
      cargador.parseCollision = false;
      const robot = cargador.parse(urdf);
      robot.rotation.x = -Math.PI / 2; // ROS: Z arriba; three: Y arriba
      this.robot = robot;
      this.escena.add(robot);

      gestor.onLoad = () => {
        this.mensaje.hidden = true;
        this._crearFantasma();
        this._aplicarVisibilidad();
      };
      // Sin mallas (o ya en caché) onLoad puede no dispararse
      setTimeout(() => { if (!this.mensaje.hidden && !gestor.itemsLoading) gestor.onLoad(); }, 4000);

      for (const marco of efectores) {
        const enlace = robot.links[marco] || robot.frames?.[marco];
        if (!enlace) continue;
        const ejes = new THREE.AxesHelper(0.08);
        enlace.add(ejes);
        this.ejes.push(ejes);
      }
      this.leyenda.textContent = `${Object.keys(robot.joints).length} articulaciones · ${Object.keys(robot.links).length} enlaces`;
      this._aplicarVisibilidad();
    } catch (e) {
      this.mensaje.textContent = `Sin modelo del robot: ${e.message}. Se reintentará al lanzar el robot.`;
      this.robot = null;
    } finally {
      this.cargando = false;
    }
  }

  _crearFantasma() {
    if (!this.robot || this.fantasma) return;
    const fantasma = this.robot.clone();
    const material = new THREE.MeshStandardMaterial({
      color: 0x22d3ee, transparent: true, opacity: 0.28, depthWrite: false, emissive: 0x0e7490,
    });
    fantasma.traverse((o) => { if (o.isMesh) { o.material = material; o.renderOrder = 2; } });
    fantasma.traverse((o) => { if (o.isAxesHelper) o.visible = false; });
    fantasma.visible = false;
    this.fantasma = fantasma;
    this.escena.add(fantasma);
  }

  // --- Actualización ----------------------------------------------------------------

  /** Mueve el robot a `posiciones` ({articulación: rad}). */
  actualizar(posiciones) {
    if (!this.robot || !posiciones) return;
    for (const [nombre, valor] of Object.entries(posiciones)) {
      const articulacion = this.robot.joints[nombre];
      if (articulacion) articulacion.setJointValue(valor);
    }
  }

  /**
   * Muestra en el fantasma el objetivo `posiciones` ({articulación: rad}) de `clave` (cada
   * panel de brazo usa la suya; null la quita). El resto de articulaciones toma `actuales`.
   */
  previsualizar(clave, posiciones, actuales) {
    this.previas = this.previas || {};
    if (posiciones) this.previas[clave] = posiciones;
    else delete this.previas[clave];
    const combinadas = Object.assign({}, ...Object.values(this.previas));
    this._fantasmaActivo = Object.keys(combinadas).length > 0;
    if (!this.fantasma) return;
    if (this._fantasmaActivo) {
      for (const [nombre, valor] of Object.entries({ ...actuales, ...combinadas })) {
        const articulacion = this.fantasma.joints[nombre];
        if (articulacion) articulacion.setJointValue(valor);
      }
    }
    this.fantasma.visible = this.pref.fantasma && this._fantasmaActivo;
  }

  // --- Montaje en una vista ---------------------------------------------------------

  montar(contenedor) {
    this.contenedor = contenedor;
    contenedor.appendChild(this.elemento);
    this.observador.observe(contenedor);
    this._redimensionar();
    if (!this.animando) {
      this.animando = true;
      const bucle = () => {
        if (!this.animando) return;
        this.controles.update();
        this.renderer.render(this.escena, this.camara);
        requestAnimationFrame(bucle);
      };
      requestAnimationFrame(bucle);
    }
  }

  desmontar() {
    this.animando = false;
    if (this.contenedor) this.observador.unobserve(this.contenedor);
    this.elemento.remove();
    this.contenedor = null;
  }

  _redimensionar() {
    if (!this.contenedor) return;
    const { clientWidth: ancho, clientHeight: alto } = this.contenedor;
    if (!ancho || !alto) return;
    this.renderer.setSize(ancho, alto, false);
    this.camara.aspect = ancho / alto;
    this.camara.updateProjectionMatrix();
  }
}

let unico = null;
/** Devuelve el visor compartido por todas las vistas. */
export function visorCompartido(api) {
  if (!unico) unico = new Visor3D(api);
  return unico;
}
