# openarm_hmi: HMI web para los brazos OpenArm

Interfaz web (consola de operación, sustituto del *teach pendant*) para manejar los dos
brazos de un cuerpo OpenArm (301 o 302) del laboratorio, en simulación o con el robot real.
Se abre en el navegador y habla con ROS 2 a través de un nodo servidor escrito en Python.

Es un paquete autocontenido: no modifica ningún otro paquete del espacio de trabajo y solo
usa los topics, acciones y servicios que ya publican los lanzadores de
`launcher_robots_lab_robotica` (MoveIt, ros2_control y los nodos de pinza).

> **Estado:** la lógica del servidor sin ROS tiene pruebas unitarias (`test/`) y la
> interfaz se ha probado en un navegador contra un servidor simulado. **Falta probarlo en
> el contenedor con la simulación (`hmi_sim.launch.py`) y después con el robot real.**

## Índice

1. [Funcionalidades](#1-funcionalidades)
2. [Puesta en marcha](#2-puesta-en-marcha)
3. [Seguridad](#3-seguridad)
4. [Arquitectura](#4-arquitectura)
5. [Configuración](#5-configuración)
6. [Cómo ampliarlo](#6-cómo-ampliarlo)
7. [API del servidor](#7-api-del-servidor)
8. [Pruebas](#8-pruebas)
9. [Limitaciones y trabajo futuro](#9-limitaciones-y-trabajo-futuro)

## 1. Funcionalidades

| Vista | Qué hace |
|---|---|
| **Operación** | Un panel por brazo y el gemelo 3D en el centro. Para cada brazo: **velocidad** con un deslizante (1-100 %); **movimiento articular** por pasos (botones −/+ de cada articulación; mantener pulsado repite el paso) o a un objetivo (deslizantes con **previsualización en 3D** antes de ejecutar); **movimiento cartesiano** por pasos en X/Y/Z y giros Rx/Ry/Rz, en el marco del mundo o de la herramienta; **ir a una pose absoluta** (XYZ en mm y RPY en °); **pinza** con un deslizante de apertura en mm y botones Abrir/Cerrar; **poses** (home y las guardadas) y Parar. Barra conjunta: poses de los dos brazos a la vez (movimiento sincronizado), velocidad común, pinzas y "Parar todo". Vídeo de las cámaras de los efectores. |
| **Gemelo 3D** | Modelo URDF del robot movido en tiempo real con `/joint_states`, a pantalla grande, con posiciones, velocidades y límites de cada articulación y la pose de cada efector. Vistas predefinidas, rejilla, ejes y "fantasma" de previsualización. |
| **Cámaras** | Vídeo de las cámaras de los efectores (y de cualquier otro topic de imagen que se añada). **Capturas** individuales o de todas a la vez, guardadas en una **galería** desde la que se descargan una a una o todas en un `.zip`. |
| **Poses** | Poses predefinidas (configuración) y guardadas (enseñadas desde el HMI): ir a ellas con un brazo o con los dos, guardar la pose actual, borrar y exportar a YAML. |
| **Sistema y scripts** | Perfiles de **arranque/parada** del sistema (simulación, simulación + RViz, robot real, cámaras simuladas) y **scripts de prueba** con parámetros (prueba de movimiento, recorrido articular, prueba de pinzas), con su salida en vivo. |
| **ROS 2** | Nodos (publicaciones, suscripciones, servicios y **parámetros**), topics (tipo, publicadores, suscriptores, **último mensaje y frecuencia**), servicios, acciones y **controladores** de ros2_control (activar o desactivar). |
| **Registro** | Mensajes de `/rosout` de todos los nodos, con filtros por nivel y texto, pausa y exportación. |

La **barra superior** está siempre visible y contiene:

- el estado de la conexión, del robot (`/joint_states`), de MoveIt y de los controladores;
- los botones **Iniciar/Detener** del sistema con el perfil elegido;
- el selector de tema claro u oscuro;
- el botón de **PARADA** de emergencia, que también se activa con la tecla `Esc`.

Otras mejoras incluidas:

- **Validación de límites:** los objetivos se comprueban contra los límites del URDF antes de enviarlos, y en el movimiento por pasos se recorta al límite. La barra de cada articulación se pone roja cerca de sus límites.
- **Estado de cada orden:** se muestra planificando, moviendo, completado o error, con el mensaje de MoveIt traducido.
- **Escena de planificación:** se pueden configurar objetos de colisión (mesa...) que se añaden a MoveIt al arrancar.
- **Cámara simulada:** imagen sintética para probar el apartado de cámaras sin hardware.
- **Topic para el resto del proyecto:** `/hmi/parada_emergencia` (`std_msgs/Bool`, latched), para que los nodos propios también se detengan.
- **Varios navegadores a la vez:** todos ven el mismo estado (por ejemplo, un portátil y una tableta).
- **Funciona sin Internet:** three.js y urdf-loader van incluidos en `web/vendor`.

## 2. Puesta en marcha

Todo se ejecuta dentro del contenedor. La primera vez hay que compilar:

```bash
./launcher.sh compilar        # o, dentro del contenedor: cd ~/ros_workspace && colcon build --symlink-install
```

### Opción A: todo en uno (simulación + HMI + cámaras simuladas)

```bash
ros2 launch openarm_hmi hmi_sim.launch.py              # cuerpo 301
ros2 launch openarm_hmi hmi_sim.launch.py cuerpo:=302 launch_rviz:=true
```

Abre **http://localhost:8080**.

### Opción B: solo el HMI (el robot se arranca desde el botón Iniciar)

```bash
ros2 launch openarm_hmi hmi.launch.py                  # o: cuerpo:=302 puerto:=8081
```

En el HMI elige el perfil ("Simulación 301", "Robot real 301"...) y pulsa **Iniciar**. Si el
robot ya está lanzado desde otra terminal (`./launcher.sh sim 301`), el HMI lo detecta
("Lanzado fuera del HMI") y lo maneja igual; en ese caso Detener no lo para.

### Según el perfil de Docker

| Perfil | Cómo abrir el HMI |
|---|---|
| `local` / `local_gpu` (red del anfitrión) | Directamente en el navegador del anfitrión: http://localhost:8080 |
| `desktop` (noVNC) | Publica el puerto con el fichero de este paquete y lanza el HMI con `host:=0.0.0.0`: `docker compose -f docker-compose.yml -f ros_workspace/src/openarm_hmi/docker/docker-compose.hmi.yml up -d desktop`. Después abre http://localhost:8080 en el anfitrión. |

### Robot real

1. Levanta los buses CAN en el anfitrión: `./launcher.sh can 301`.
2. Inicia el perfil "Robot real 301" desde el HMI (o `./launcher.sh robot 301`). **Al arrancar, los brazos van a la posición cero.**
3. Si los brazos tienen cámara en el efector: `ros2 launch openarm_hmi camaras.launch.py cuerpo:=301 dispositivo_izq:=/dev/video0 dispositivo_der:=/dev/video2`. Cada cámara publica en `/robot_<brazo>/camara/image_raw`.
4. Empieza con la velocidad baja (el 10 % por defecto) y prueba primero el script "Prueba de movimiento".

## 3. Seguridad

- **La parada del HMI es una parada por software. No sustituye al corte de alimentación del robot, que debe estar siempre a mano.**
- Al pulsar **PARADA** (o la tecla `Esc`) ocurre lo siguiente:
  1. se ordena a los controladores mantener la posición actual;
  2. se cancelan todas las órdenes en curso (MoveIt, pinzas);
  3. se detienen los scripts;
  4. se desactivan los controladores de brazo y pinza, que dejan de aceptar órdenes de cualquier nodo (`seguridad.desactivar_controladores`);
  5. se publica `true` en `/hmi/parada_emergencia`.
- Mientras la parada está activa, el HMI rechaza cualquier orden de movimiento. **Rearmar** reactiva los controladores.
- La parada **no** detiene el sistema (el `ros2 launch` del robot). Con el robot real, pararlo deshabilita los motores y los brazos pueden caer por gravedad.
- El HMI **no tiene autenticación**. Por defecto escucha solo en `127.0.0.1`; usa `host:=0.0.0.0` únicamente en redes de confianza.
- Todos los movimientos se planifican con MoveIt, que comprueba las colisiones con el propio robot y la escena. Los objetivos fuera de los límites del URDF se rechazan.
- El HMI solo ejecuta los comandos de los perfiles y scripts de la configuración. Los parámetros se validan por tipo y nunca pasan por una shell.

## 4. Arquitectura

```
 Navegador (HTML + JS sin compilación)            Contenedor (ROS 2 Jazzy)
┌──────────────────────────────────┐        ┌───────────────────────────────────────────┐
│ app.js  barra · navegación       │  REST  │ hmi_servidor (nodo openarm_hmi)           │
│ vistas/ operacion gemelo camaras │◄──────►│  servidor HTTP (stdlib) ── enrutador      │
│         poses procesos ros       │  SSE   │  bus de eventos ── gestor de tareas       │
│         registro                 │◄───────│  módulos:                                 │
│ componentes/ panel_brazo visor3d │        │   estado  seguridad  controladores        │
│              visor_camara        │ JPEG   │   movimiento  pinza  poses  camaras       │
│ vendor/ three.js urdf-loader     │◄───────│   ros  sistema  scripts  registro         │
└──────────────────────────────────┘        └─────────┬─────────────────────────────────┘
                                                      │ topics / acciones / servicios
                         move_group (MoveIt) · controller_manager · pinza_openarm_node
                         robot_state_publisher · cámaras (usb_cam / camara_simulada)
```

- **Servidor** (`openarm_hmi/`): un nodo de rclpy con un ejecutor multihilo y un servidor HTTP de la biblioteca estándar, sin dependencias nuevas. Cada funcionalidad es un **módulo** (`modulos/`) que registra sus rutas, publica su parte del estado y reacciona a eventos del bus. El núcleo (`nucleo/`) no sabe nada de robots.
- **Tiempo real:** el estado completo (articulaciones, poses, tareas, controladores...) se envía unas 15 veces por segundo por *Server-Sent Events* (`/api/eventos`), junto con eventos puntuales (`tarea`, `log`, `proceso`, `parada_emergencia`...). Las órdenes son peticiones REST que devuelven una tarea cuyo progreso llega por eventos.
- **Cámaras:** la suscripción se crea al pedir el primer fotograma y se cancela cuando nadie mira. El navegador pide los fotogramas JPEG de uno en uno, así que una conexión lenta recibe menos fotogramas en lugar de acumular retraso.
- **Gemelo 3D:** el URDF se lee de `/robot_description` y las mallas `package://` se sirven desde `/paquetes/<paquete>/...`.
- **Interfaz** (`web/`): módulos ES nativos sin compilación. Cada vista es un fichero con `montar(contenedor, ctx)`, y `vistas/indice.js` las registra.

```
openarm_hmi/
├── config/openarm.yaml          Configuración (brazos, poses, cámaras, perfiles, scripts...)
├── launch/                      hmi, hmi_sim, camaras (usb_cam), camaras_simuladas
├── docker/docker-compose.hmi.yml  Puerto del HMI para el perfil desktop
├── openarm_hmi/
│   ├── principal.py             Nodo hmi_servidor: carga módulos y arranca el servidor
│   ├── nucleo/                  configuracion, servidor HTTP, eventos, tareas, procesos,
│   │                            geometria, clase base Modulo
│   ├── modulos/                 Una funcionalidad por fichero (+ registro en __init__.py)
│   ├── nodos/camara_simulada.py
│   └── scripts/prueba_movimiento.py
├── web/                         index.html, css/, js/{nucleo,componentes,vistas}, vendor/
├── test/                        Pruebas sin ROS (pytest)
└── datos/                       Capturas y poses guardadas (ignorado por git)
```

## 5. Configuración

Todo está en `config/openarm.yaml`, comentado. Lo más habitual:

| Quiero... | Sección |
|---|---|
| Otro puerto o aceptar conexiones de la red | `servidor` (o los argumentos `puerto:=`/`host:=`) |
| Limitar la velocidad máxima del deslizante | `movimiento.velocidad_maxima` |
| Cambiar los pasos del movimiento por pasos | `movimiento.pasos_*` |
| Añadir una pose fija (p. ej. "preparado") | `poses_predefinidas` |
| Añadir una mesa u obstáculo a MoveIt | `escena` |
| Cambiar el topic de las cámaras o añadir una cenital | `camaras.por_brazo` / `camaras.adicionales` |
| Añadir un perfil de arranque | `sistema.perfiles` |
| Añadir un script ejecutable desde el HMI | `scripts` |
| Que la parada no desactive los controladores | `seguridad.desactivar_controladores` |
| Cambiar la carpeta de capturas y poses | `datos.directorio` |

Las cadenas admiten `{cuerpo}` y, en los campos por brazo, `{brazo}`, así que la misma
configuración sirve para el 301 y el 302 (`cuerpo:=302`). Para otro fichero:
`ros2 launch openarm_hmi hmi.launch.py config:=/ruta/mi_config.yaml`.

## 6. Cómo ampliarlo

El diseño separa núcleo, módulos y vistas para que añadir algo no obligue a tocar lo existente.

**Un script nuevo (sin programar en el HMI):** añade una entrada en `scripts` con su comando y
parámetros tipados. Aparece en "Sistema y scripts" con su formulario. El script puede ser
cualquier ejecutable (`ros2 run mi_paquete mi_nodo`, `python3 /ruta/script.py`...). Conviene que
escuche `/hmi/parada_emergencia`, como `scripts/prueba_movimiento.py`.

**Una funcionalidad nueva en el servidor:**

1. Crea `openarm_hmi/modulos/mi_modulo.py`:

   ```python
   from openarm_hmi.nucleo.modulo import Modulo

   class MiModulo(Modulo):
       nombre = "mi_modulo"

       def iniciar(self):
           self.contador = 0
           self.nodo.create_subscription(...)            # el nodo ROS compartido
           self.bus.suscribir("parada_emergencia", lambda d: self.parar())
           self.ruta("POST", "/api/mi_modulo/accion", self.accion)

       def accion(self, peticion):
           self.ctx.comprobar_movimiento_permitido()       # respeta la parada
           datos = peticion.json()
           return {"ok": True}                            # dict -> JSON

       def estado(self):                                  # llega al navegador ~15 Hz
           return {"contador": self.contador}
   ```

2. Regístralo en `modulos/__init__.py` y añade `mi_modulo` a `modulos` en la configuración.
3. Para usar otros módulos: `self.ctx.modulo("movimiento").mover_articulaciones(...)`. Para seguir una acción de ROS como tarea: `self.tareas.nueva(...)` y `self.tareas.enviar_objetivo(...)`.

**Una vista nueva en la interfaz:**

1. Crea `web/js/vistas/mi_vista.js`:

   ```js
   import { h, boton, aviso } from '../nucleo/ui.js';

   export function montar(contenedor, ctx) {
     const valor = h('span', {}, '—');
     contenedor.append(h('section', { class: 'panel' },
       h('div', { class: 'cabecera' }, h('h2', {}, 'Mi vista')),
       h('div', { class: 'cuerpo' }, valor,
         boton('Acción', { clase: 'primario', onclick: () =>
           ctx.api.post('/api/mi_modulo/accion').catch((e) => aviso(e.message, 'error')) }))));
     const baja = ctx.almacen.suscribir((e) => { valor.textContent = e.mi_modulo?.contador; });
     return () => baja();                                  // limpieza al cambiar de vista
   }
   ```

2. Regístrala en `web/js/vistas/indice.js` con los módulos que necesita.
3. Con `--symlink-install` basta con recargar el navegador. Los cambios en Python requieren reiniciar el HMI.

Los componentes reutilizables (`PanelBrazo`, `VisorCamara`, el visor 3D compartido) están en
`web/js/componentes/`, y los estilos usan variables CSS (`--acento`, `--panel`...) definidas en
`css/hmi.css` para los dos temas.

## 7. API del servidor

Todas las respuestas son JSON (los errores son `{"error": "..."}` con su código HTTP).
`GET /api/rutas` lista todas las rutas registradas.

| Ruta | Descripción |
|---|---|
| `GET /api/config` | Robot, brazos, límites e información de cada módulo |
| `GET /api/estado` · `GET /api/eventos` | Estado actual · flujo SSE de estado y eventos |
| `GET /api/robot/urdf` · `GET /paquetes/<pkg>/<ruta>` | URDF · ficheros de `share/` (mallas) |
| `POST /api/movimiento/articulaciones` | `{brazo, posiciones}` (rad; `ambos`: `{id: [...]}`) |
| `POST /api/movimiento/jog_articular` | `{brazo, indice, delta}` |
| `POST /api/movimiento/jog_cartesiano` | `{brazo, traslacion: [m], rotacion: [rad], marco: mundo\|herramienta}` |
| `POST /api/movimiento/pose` | `{brazo, posicion: [m], rpy: [rad]}` |
| `POST /api/movimiento/parar` · `velocidad` | `{brazo?}` · `{brazo?, valor: 0-1}` |
| `POST /api/pinza` | `{brazo, anchura_mm, esfuerzo?}` |
| `GET/POST /api/poses` · `POST /api/poses/<n>/ir` · `DELETE /api/poses/<n>` | Poses |
| `POST /api/seguridad/parada` · `rearme` | Parada de emergencia |
| `GET /api/controladores` · `POST .../conmutar` · `POST .../movimiento` | ros2_control |
| `GET /api/camaras` · `GET /api/camaras/<id>/frame?desde=N` · `POST /api/camaras/<id>/captura` | Cámaras |
| `GET /api/capturas` · `GET /api/capturas/zip` · `GET /capturas/<f>` · `DELETE /api/capturas/<f>` | Galería |
| `GET /api/ros/grafo` · `nodo?nombre=` · `topic?nombre=` · `parametros?nodo=` | Introspección |
| `GET /api/sistema` · `POST .../iniciar` · `POST .../detener` · `GET .../salida` | Perfiles de arranque |
| `GET /api/scripts` · `POST /api/scripts/<id>/ejecutar` · `.../detener` · `GET .../salida` | Scripts |
| `GET /api/registro?desde=N` · `GET /api/tareas` | Registro de `/rosout` · tareas |

Con `curl` se puede automatizar cualquier cosa que haga la interfaz, por ejemplo:
`curl -X POST localhost:8080/api/poses/home/ir -d '{"brazo":"ambos"}'`.

## 8. Pruebas

```bash
cd ~/ros_workspace/src/openarm_hmi && python3 -m pytest test/ -q     # no necesita ROS
colcon test --packages-select openarm_hmi                              # o con colcon
```

Prueba manual recomendada en simulación (`hmi_sim.launch.py`):

1. Comprueba que los cuatro indicadores de la barra se ponen en verde.
2. Mueve J1 por pasos y con un objetivo.
3. Haz un paso cartesiano en Z.
4. Lleva los dos brazos a la pose "hands_up".
5. Abre y cierra las pinzas.
6. Haz una captura de cada cámara y descárgala.
7. Ejecuta "Prueba de movimiento".
8. Pulsa PARADA durante un movimiento: el robot se detiene y los controladores pasan a inactivos. Después rearma.
9. Revisa las vistas ROS 2 y Registro.

## 9. Limitaciones y trabajo futuro

- **Sin probar todavía en el contenedor ni con el robot real** (ver el estado al principio).
- El movimiento por pasos planifica cada paso con MoveIt (unas décimas de segundo por paso). Para un jog continuo y fluido, el siguiente paso sería MoveIt Servo (`moveit_servo`), como un módulo más.
- No hay usuarios ni permisos. Si se abre a la red, conviene añadir un token o un proxy con autenticación.
- La conversión de la anchura de la pinza (mm ↔ rad) es la lineal del nodo `pinza_openarm_node` (±8 mm).
- Ideas para nuevos módulos:
  - grabar y reproducir secuencias de poses (programas);
  - mostrar la nube de puntos o la profundidad de una ZED;
  - añadir y editar objetos de la escena desde el 3D;
  - registrar datos (rosbag) desde el HMI;
  - publicar en un topic desde la vista ROS 2.
