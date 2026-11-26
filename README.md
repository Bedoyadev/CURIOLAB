# CURIOLAB

Estudio de animación 2D automatizado: de una pregunta de ciencia a un Short animado listo para
revisar. Investiga con fuentes, escribe el guion, planifica las escenas, graba las voces, anima con
Godot, monta con Remotion y FFmpeg, comprueba la calidad y espera tu aprobación. No publica solo.

Este proyecto es independiente: no necesita ningún otro repositorio.

## Estructura

| Carpeta | Qué es |
|---|---|
| `backend/animation/` | El motor: investigación, guion, storyboard, voces, tiempos, calidad, publicación, analítica y panel |
| `backend/animation/shared/` | Piezas generales: ajustes y claves, lectura de fuentes, llamada de voz, medidas de video, Remotion, YouTube |
| `backend/channels/curiolab.json` | Perfil del canal: marca, reparto, voces, formato, límites |
| `backend/data/` | Datos del canal: base, caché de voces, episodios (fuera de git) |
| `animator/` | Proyecto de Godot 4 que dibuja las escenas; `animator/library/` es la biblioteca de recursos |
| `renderer/` | Proyecto de Remotion que pone título, subtítulos, rótulos y cierre |
| `docs/animacion.md` | Cómo funciona por dentro y cómo ampliar la biblioteca |

## Requisitos

- Python 3.12 o superior, Node 20 o superior y FFmpeg en el PATH.
- Godot 4.x (probado con 4.7.2).
- Claves de Anthropic y ElevenLabs.

## Instalación

```
cd backend
pip install -e ".[dev]"
cd ../renderer
npm ci
```

Copia `.env.example` a `backend/.env` y rellénalo:

```
ANTHROPIC_API_KEY=...
ELEVENLABS_API_KEY=...
GODOT_BIN=C:/ruta/a/Godot_v4.x_win64_console.exe
```

Comprueba que todo está en su sitio, desde `backend/`:

```
python -m animation --channel curiolab check
```

## Uso

Panel («Estudio de Animación IA»):

```
cd backend
python -m animation.server --channel curiolab --port 8200
```

Abre http://127.0.0.1:8200 y pulsa **Generar animación con IA**. Con el tema vacío, el estudio elige
la pregunta. El episodio queda en `LISTO_PARA_REVISIÓN`; se sube a YouTube solo después de aprobarlo
y pulsar «Subir a YouTube».

Línea de comandos, desde `backend/`:

```
python -m animation --channel curiolab demo                  # episodio de demostración, sin gasto
python -m animation --channel curiolab produce "¿Pregunta?"  # con Claude y ElevenLabs
python -m animation --channel curiolab produce               # el motor elige el tema
python -m animation --channel curiolab resume 3
python -m animation --channel curiolab retake 3 s2           # vuelve a dibujar una escena
python -m animation --channel curiolab redo 3 guion          # rehace desde investigacion | guion | storyboard
python -m animation --channel curiolab list
python -m animation --channel curiolab approve 3
```

Cada episodio queda en `backend/data/channels/curiolab/episodios/NNNN/` con su video (`short.mp4`),
miniatura, guion, storyboard, investigación con fuentes e informe de calidad (`calidad.md`).

## YouTube

Para publicar hace falta el archivo de la aplicación de Google del canal,
`youtube_client_secret.json`, en `backend/data/channels/curiolab/`. Después, en el panel, «Conectar el
canal de YouTube».

## Pruebas

```
cd backend
python -m pytest                                         # unos 25 s
ANIMATION_E2E=1 python -m pytest -k end_to_end           # episodio completo, varios minutos
```

## Pendiente

- El arte es provisional: personajes, escenarios y objetos son formas vectoriales hechas por código.
- La analítica nunca ha leído datos reales (no hay canal conectado ni episodios publicados).
- Detalle completo en `docs/animacion.md`.
