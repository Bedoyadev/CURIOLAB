# Cómo funciona el estudio

Produce cortos animados de ciencia: personajes que hablan, gesticulan y actúan en escenas dibujadas
por Godot, a partir de un guion con fuentes. La instalación y el uso están en el `README.md` de la
raíz; aquí está el detalle de cada parte.

## Dónde vive cada cosa

| Pieza | Dónde vive | Notas |
|---|---|---|
| Motor (investigación, guion, storyboard, voces, planes, calidad, publicación, analítica) | `backend/animation/` | No nombra ningún canal |
| Piezas generales (ajustes y claves, fuentes, voz, medidas, Remotion, YouTube) | `backend/animation/shared/` | |
| Perfil del canal (marca, reparto, voces, formato, límites) | `backend/channels/curiolab.json` | Un archivo por canal, con `"engine": "animation"` |
| Datos del canal (base, caché de voces, episodios, sonido) | `backend/data/channels/curiolab/` | Fuera de git. Base: `animation.db` |
| Motor de dibujo (Godot 4) | `animator/` | Personajes, acciones, escenarios, objetos, cámara |
| Biblioteca de recursos | `animator/library/manifest.json` y `library/characters/*.json` | La única lista de ids válidos, leída por el backend y por Godot |
| Montaje | `renderer/src/animation/` | Proyecto de Remotion |

## Requisitos

- Python 3.12+, Node y FFmpeg.
- **Godot 4.x** (probado con 4.7.2). En `backend/.env`: `GODOT_BIN=ruta/al/ejecutable`. Sin esa
  línea se busca `godot4` o `godot` en el PATH. Godot dibuja en modo Movie Maker
  (`--write-movie --fixed-fps 30`): abre una ventana pequeña mientras trabaja y no funciona con
  `--headless`, que no tiene renderizador.
- `ANTHROPIC_API_KEY` y `ELEVENLABS_API_KEY` en `backend/.env`.

Comprobar la instalación, desde `backend/`:

```
python -m animation --channel curiolab check
```

## Cómo se usa

Panel («Estudio de Animación IA»):

```
python -m animation.server --channel curiolab --port 8200
```

Botón **Generar animación con IA**: con el campo de tema vacío el motor elige la pregunta; con
texto, usa esa. El episodio pasa por la cola (uno a la vez) y queda en `LISTO_PARA_REVISIÓN`.
Desde el panel se ve el guion, los tres ganchos, el storyboard, los recursos usados, las fuentes,
los costos, el informe de calidad y el video; se puede volver a animar una escena, regenerar guion
o storyboard, cancelar, reanudar, descargar el MP4, aprobar y, solo después de aprobar, subir a
YouTube.

Línea de comandos:

```
python -m animation --channel curiolab demo                  # episodio de demostración, sin gasto
python -m animation --channel curiolab produce "¿Pregunta?"  # con Claude y ElevenLabs
python -m animation --channel curiolab produce               # el motor elige el tema
python -m animation --channel curiolab resume 3
python -m animation --channel curiolab retake 3 s2           # vuelve a dibujar la escena s2
python -m animation --channel curiolab redo 3 guion          # rehace desde el guion (o investigacion, storyboard)
python -m animation --channel curiolab list
python -m animation --channel curiolab approve 3
```

Cada episodio deja en `data/channels/curiolab/episodios/NNNN/`: `investigacion.json` (hechos con su
cita literal, fuentes, simulaciones), `guion.json`, `storyboard.json`, `plan_sN.json` (lo que Godot
reprodujo), `escenas/*.mp4`, `dialogo.wav`, `props.json`, `short.mp4`, `miniatura.png` y
`calidad.md`.

## Componentes y contratos

| Componente | Módulo | Entra | Sale |
|---|---|---|---|
| A. Research | `research.py`, `simulations.py` | pregunta | ficha: hechos con cita, fuentes, supuestos, simulaciones |
| B. Script | `script.py` (`write_script`) | ficha | guion: 3 ganchos, líneas con sus apoyos, título |
| C. Storyboard | `script.py` (`stage`), `storyboard.py` | guion + biblioteca | storyboard JSON v1 validado |
| D. Asset Library | `library.py`, `animator/library/` | — | ids registrados y su huella |
| E. Voice | `voice.py`, `lipsync.py` | línea + voz | WAV, tiempos por palabra, estados de boca por cuadro |
| F. Animation | `plan.py`, `godot.py`, `animator/` | storyboard + voces | un plan y un MP4 por escena |
| G. Composition | `compose.py`, `renderer/src/animation/` | escenas + voces | `short.mp4`, miniatura |
| H. Quality | `quality.py` | todo lo anterior | informe medido + lista para quien aprueba |
| I. Publishing | `publish.py` | episodio aprobado | subida a YouTube (privada por defecto) |
| J. Analytics | `analytics.py` | episodios publicados | lecturas fechadas, resumen y «lecciones» para elegir tema |

Estados: `PENDIENTE → INVESTIGANDO → ESCRIBIENDO → STORYBOARD → GENERANDO_VOZ → ANIMANDO →
COMPONIENDO → VALIDANDO → LISTO_PARA_REVISIÓN → APROBADO → PUBLICADO`, y `ERROR`. El progreso del
panel sale de la tabla `events` (una fila por línea grabada y por escena dibujada), no de un reloj.

### El storyboard

Claude no escribe código para el renderizador. Escribe datos: escenas hechas de *beats* (una línea
de diálogo o un momento sin diálogo), y todo lo que usan se nombra por un id del manifiesto. La
respuesta llega con la salida estructurada de la API (`output_config.format` con un esquema JSON en
el que cada id es un `enum` de lo registrado), y aun así se valida aquí antes de dibujar nada
(`storyboard.validate`): un recurso que no existe rechaza el storyboard con la lista de problemas;
solo se corrige lo que no cambia la historia (una emoción o una cámara inexistente pasan a la
neutra), y se deja anotado. El director de Godot vuelve a comprobar su plan y se niega a dibujar si
algo no está registrado. El texto de cada línea lo copia el código desde el guion ya revisado; el
modelo solo indica el número de línea.

El storyboard no lleva tiempos: cada línea dura lo que dura su audio y cada escena lo que suman sus
beats. Por eso no hay cuadros vacíos ni líneas cortadas.

### De dónde sale la ciencia

Solo de dos sitios: hechos cuya cita está, letra por letra, en una fuente que el motor leyó; y
simulaciones calculadas por `simulations.py` con fórmulas explícitas.

Las fuentes se clasifican por quién las publica (`institucional`: agencias, universidades, sociedades
científicas; `referencia`: revistas y enciclopedias de referencia; `divulgación`: el resto) y se leen
primero las institucionales. Si de la primera búsqueda se leen menos de tres páginas o ninguna es
institucional, se hace una segunda diciendo cuáles fallaron. Ninguna fuente puede aportar más del
60 % de los hechos de un episodio; un guion cuyas afirmaciones salen todas de una sola fuente se
devuelve; y el informe de calidad comprueba que lo afirmado sale de al menos dos fuentes y que alguna
es institucional o de referencia. Las metáforas y comparaciones llamativas de una web no se recogen
como hechos. Claude elige qué simulación
encaja y con qué entradas; el resultado lo calcula el código. Cada modelo declara si es `exacto` o
`simplificado` y sus supuestos; una escena que muestra una simulación lleva su rótulo en pantalla.
Un guion con una cifra que no esté en la ficha se rechaza, y un segundo pase del modelo busca líneas
que digan más que sus citas.

### Sincronía labial

La boca tiene seis formas: cerrada, entreabierta, «e», «a», «o/u» (redonda) e «i» (ancha). Dentro
del tiempo de cada palabra (los tiempos de ElevenLabs son por palabra) sus letras se reparten en
orden: las vocales toman su forma y la mayor parte del tiempo, m/b/p cierran los labios, la h y la u
muda no cuentan; el volumen de la voz decide cuándo la boca está cerrada, y ninguna forma dura un
solo cuadro. Son visemas estimados a partir de la ortografía del español, no fonemas medidos: los
tiempos por carácter no se tratan como fonemas. Si una línea no tiene tiempos de palabra se usa solo
el volumen (`lipsync.mouth_track`). Un alineador forzado puede sustituir `lipsync.viseme_track` sin
tocar el renderizador, que solo recibe la lista de formas.

### Montaje

FFmpeg une las escenas sin recodificarlas; Remotion renderiza solo la capa que va encima (título,
subtítulos, rótulos, cierre) con fondo transparente y toda la mezcla de sonido; FFmpeg pone esa capa
sobre las escenas y codifica el H.264 final. Así el navegador no decodifica las escenas, que era lo
lento: el montaje de un episodio pasó de unos 4 minutos a menos de 2.

### Analítica

`analytics.collect` lee de la cuenta de YouTube del canal los contadores públicos de cada episodio
publicado y, cuando existe, el informe de Analytics (porcentaje medio visto, suscriptores), y guarda
una lectura fechada. `analytics.lessons` compara el canal consigo mismo (más y menos visto, mejor
retención, con o sin simulación) y no dice nada hasta tener tres episodios públicos con al menos 100
visitas. Ese texto se enseña en el panel («Rendimiento») y se entrega a la elección automática de
tema como demanda observada; no usa cifras de otros canales ni decide nada por sí solo.

## Ampliar la biblioteca

- **Acción nueva**: un archivo en `animator/actions/` que extienda `core/action.gd` y devuelva la
  pose para cada instante, más su entrada en `manifest.json → actions` y en la lista `actions` de
  los personajes que la tengan. El motor no cambia.
- **Objeto**: un caso nuevo en un script de `animator/props/` (o un script nuevo que extienda
  `core/prop.gd`) y su entrada en `manifest.json → props`.
- **Escenario**: un script en `animator/sets/` y su entrada con los sitios (`anchors`,
  `prop_anchors`) donde pueden ir personajes y objetos.
- **Personaje**: `animator/library/characters/<id>.json` (apariencia, personalidad, voz, acciones,
  restricciones), su id en `manifest.json → characters` y su voz en el perfil del canal.
- **Simulación**: una función en `simulations.py` con fórmula, supuestos y exactitud, registrada en
  `REGISTRY` y `CATALOG`; si tiene dibujo, un objeto con `"simulation": "<id>"`.

Cualquier cambio en `animator/` cambia la huella de la biblioteca, y las escenas se vuelven a
dibujar con el motor nuevo.

## Costos y resistencia

- Límite por episodio (`limits.max_usd_per_video`), comprobado antes de cada llamada de pago.
- Una línea de voz se identifica por voz, modelo, ajustes y texto exacto: nunca se paga dos veces,
  ni en este episodio ni en otro (`cache/voz/`).
- Una escena se identifica por su plan y la huella del motor: si nada cambió, no se dibuja.
- Cada etapa guarda su resultado; reanudar un episodio salta lo que ya está.
- Cancelar se atiende entre unidades de trabajo y detiene un render de Godot en curso; lo hecho se
  conserva. No interrumpe el montaje de Remotion ya empezado (termina ese paso y se detiene).
- Si el servidor se apaga a mitad de un episodio, al arrancar lo marca como interrumpido; no lo
  retoma solo.
- Publicar exige estado `APROBADO`, no sube dos veces el mismo episodio y rechaza los de demostración.

## Pruebas

```
python -m pytest tests/test_animation.py                      # ~25 s; las de Godot se saltan si no está
ANIMATION_E2E=1 python -m pytest tests/test_animation.py -k end_to_end   # episodio completo, varios minutos
```

## Arte provisional

Todo lo que se ve está dibujado por código con formas vectoriales y marcado `ARTE PROVISIONAL` en su
archivo: los dos personajes (`core/character_rig.gd`), los cuatro escenarios (`sets/`) y los 21
objetos (`props/`). Necesitan diseño final. El rig se dibuja por capas sobre puntos de articulación
fijos y las acciones solo mueven canales de pose, así que sustituir cada pieza por su sprite no
cambia acciones, storyboards ni planes.

La voz de Leo es la voz clonada del dueño del canal, desde el segundo episodio; el primero se grabó con una voz de catálogo. Música y efectos son
síntesis propia.

## Qué falta

- **Analítica con datos reales**: está escrita y probada con un cliente simulado; el canal aún no
  tiene YouTube conectado ni episodios publicados, así que nunca ha leído datos reales. No hay
  lectura de referencias públicas de otros canales.
- **Visemas medidos**: las formas de la boca se estiman de la ortografía; un alineador forzado daría
  los fonemas reales.
- **AnimationPlayer / AnimationTree**: las acciones son poses calculadas por código y mezcladas por
  el rig, no animaciones de autor. Tiene sentido pasar a AnimationTree cuando haya rigs dibujados
  con sus animaciones hechas en el editor.
- **Manim**: no está instalado ni integrado; las simulaciones se dibujan en Godot.
- **Formatos largos** y más personajes, escenarios y simulaciones.
