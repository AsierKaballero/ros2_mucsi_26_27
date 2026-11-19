// Registro de vistas de la interfaz.
//
// Para añadir una vista: crea `js/vistas/mi_vista.js` exportando
//     export function montar(contenedor, ctx) { ...; return () => { /* limpiar */ }; }
// y añade aquí una entrada. `modulos` son los módulos del servidor que necesita: si
// alguno no está activo, la vista no aparece. `ctx` contiene:
//   api       peticiones REST (api.get/post/del)
//   conexion  eventos en tiempo real (conexion.on('tarea', fn), esperarTarea(id))
//   almacen   último estado del robot (almacen.suscribir(fn) -> baja)
//   config    /api/config (robot, brazos, límites e info de cada módulo)
//   local     eventos entre vistas del navegador (local.emitir/escuchar)
//   visor     gemelo digital 3D compartido
//   registro  buffer de mensajes de /rosout

export const VISTAS = [
  { id: 'operacion', titulo: 'Operación', icono: 'mando', modulos: ['movimiento'], cargar: () => import('./operacion.js') },
  { id: 'gemelo', titulo: 'Gemelo 3D', icono: 'cubo', modulos: ['estado'], cargar: () => import('./gemelo.js') },
  { id: 'camaras', titulo: 'Cámaras', icono: 'camara', modulos: ['camaras'], cargar: () => import('./camaras.js') },
  { id: 'poses', titulo: 'Poses', icono: 'marcador', modulos: ['poses'], cargar: () => import('./poses.js') },
  { id: 'procesos', titulo: 'Sistema y scripts', icono: 'terminal', modulos: ['sistema', 'scripts'], alguno: true, cargar: () => import('./procesos.js') },
  { id: 'ros', titulo: 'ROS 2', icono: 'red', modulos: ['ros'], cargar: () => import('./ros.js') },
  { id: 'registro', titulo: 'Registro', icono: 'lista', modulos: ['registro'], cargar: () => import('./registro.js') },
];
