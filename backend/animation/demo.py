"""The demonstration episode: «¿Qué pasaría si la gravedad desapareciera durante cinco segundos?»
with a fixed script and storyboard, so the whole chain after the writing (voices, lip sync,
Godot, Remotion, quality control) can be run without a paid call.

It is the episode the end-to-end test produces. With mode "demo" the pipeline takes the research,
the script and the storyboard from here instead of asking Claude, and nothing else changes: the
storyboard goes through the same validation as any other.

Its facts carry no sources (nothing was searched), and the quality report says so: an episode in
demo mode is for trying the renderer, not for publishing.
"""
from copy import deepcopy

from animation import simulations

TOPIC = "¿Qué pasaría si la gravedad desapareciera durante cinco segundos?"

LINES = [
    ("dra_nova", "¿Qué pasaría si la gravedad desapareciera durante cinco segundos?", []),
    ("leo", "¡Fácil! Saldríamos volando como cohetes.", []),
    ("dra_nova", "Vamos a comprobarlo. Apago la gravedad en tres, dos, uno.", []),
    ("leo", "¡Mi café! ¡Doctora, estoy flotando!", []),
    ("dra_nova", "Flotando, sí. Disparado, no: nada te empuja hacia arriba.", ["h1"]),
    ("dra_nova", "La Tierra gira y tú con ella. Sin gravedad seguirías recto mientras el suelo se curva bajo tus pies.", ["h2", "sim:separacion_sin_gravedad"]),
    ("dra_nova", "En un modelo simplificado, en el ecuador te separarías unos cuarenta y dos centímetros.", ["sim:separacion_sin_gravedad"]),
    ("leo", "¿Y el aire?", []),
    ("dra_nova", "También se escaparía hacia arriba. Por eso digo simplificado.", ["h3"]),
    ("dra_nova", "Y cuando la gravedad vuelve…", []),
    ("leo", "¡Ay! Todo cae otra vez.", []),
    ("dra_nova", "La gravedad no nos aplasta: nos mantiene juntos, a nosotros, al aire y a los océanos.", ["h3"]),
]

LAB_CAST = [{"character": "dra_nova", "at": "izquierda", "facing": "right"}, {"character": "leo", "at": "derecha", "facing": "left"}]
LAB_PROPS = [
    {"uid": "matraz", "prop": "matraz", "at": "mesa_1", "params": {}}, {"uid": "taza", "prop": "taza", "at": "mesa_2", "params": {}},
    {"uid": "manzana", "prop": "manzana", "at": "mesa_3", "params": {}}, {"uid": "libro", "prop": "libro", "at": "mesa_4", "params": {}},
    {"uid": "planta", "prop": "planta", "at": "estante_1", "params": {}}, {"uid": "vaso", "prop": "vaso", "at": "estante_2", "params": {}},
    {"uid": "micro", "prop": "microscopio", "at": "estante_3", "params": {}}, {"uid": "lapiz", "prop": "lapiz", "at": "suelo_der", "params": {}},
]


def sheet() -> dict:
    return {
        "topic": TOPIC, "demo": True,
        "facts": [
            {"id": "h1", "text": "Sin gravedad, un cuerpo conserva la velocidad que tenía: no aparece ninguna fuerza que lo lance hacia arriba.", "source": None, "quote": ""},
            {"id": "h2", "text": "El suelo en el ecuador se mueve por la rotación de la Tierra a unos 1.670 km/h.", "source": None, "quote": ""},
            {"id": "h3", "text": "La gravedad es lo que retiene la atmósfera y los océanos contra el planeta.", "source": None, "quote": ""},
        ],
        "dropped": [], "sources": [],
        "answer": "No saldríamos disparados: nos separaríamos despacio del suelo y todo volvería a caer.",
        "assumptions": ["Solo desaparece la gravedad de la Tierra, cinco segundos, y todo lo demás sigue igual."],
        "unknowns": [], "simulations": [simulations.run("separacion_sin_gravedad", {"seconds": 5, "latitude": 0})],
    }


def script() -> dict:
    return {
        "title": TOPIC,
        "hooks": [
            {"text": LINES[0][1], "score": 8.5, "why": "La pregunta completa, sin rodeos."},
            {"text": "Apaga la gravedad cinco segundos. ¿Qué es lo primero que pasa?", "score": 7.5, "why": "Directo al experimento."},
            {"text": "Sin gravedad no saldrías volando. Pasaría algo más raro.", "score": 7.0, "why": "Contradice la intuición."},
        ],
        "chosen_hook": 0,
        "lines": [{"speaker": s, "text": t, "supports": list(sup)} for s, t, sup in LINES],
        "takeaway": "Sin gravedad no saldríamos disparados: nos separaríamos despacio de un suelo que sigue girando.",
        "description": "La Dra. Nova apaga la gravedad cinco segundos en el laboratorio. Lo que pasa no es lo que Leo esperaba.",
        "tags": ["ciencia", "gravedad", "física", "curiosidades", "qué pasaría si"],
        "checks": {"words": sum(len(t.split()) for _, t, _ in LINES), "shared_wording": 0.0, "attempts": 0},
    }


def _line(index: int, **fields) -> dict:
    speaker, text, supports = LINES[index]
    return {"speaker": speaker, "text": text, "supports": list(supports), **fields}


def storyboard(episode_id: str = "demo") -> dict:
    # A fresh copy each time: the cast and props lists are shared by three scenes.
    return deepcopy(_storyboard(episode_id))


def _storyboard(episode_id: str) -> dict:
    return {
        "schema_version": 1, "episode_id": episode_id, "title": TOPIC, "format": "short", "target_seconds": 60,
        "characters": ["dra_nova", "leo"], "sources": [],
        "scenes": [
            {"id": "s1", "set": "laboratorio", "label": "", "cast": LAB_CAST, "props": LAB_PROPS, "beats": [
                _line(0, emotion="happy", action="talk", camera="push_in", camera_target="dra_nova",
                      reactions=[{"character": "leo", "action": "thinking", "emotion": "thinking"}], science_event="la pregunta"),
                _line(1, emotion="happy", action="point", camera="pan", camera_target="leo",
                      reactions=[{"character": "dra_nova", "action": "confused", "emotion": "confused"}]),
                _line(2, emotion="neutral", action="point", camera="wide", look_at="taza",
                      reactions=[{"character": "leo", "action": "look_left", "emotion": "worried"}]),
            ]},
            {"id": "s2", "set": "laboratorio", "label": "", "cast": LAB_CAST, "props": LAB_PROPS, "beats": [
                {"actor": "dra_nova", "seconds": 2.4, "action": "look_up", "emotion": "surprised", "camera": "shake",
                 "effects": ["flash", "gravity_off", "dust"], "science_event": "la gravedad se apaga: los objetos sueltos se separan despacio",
                 "reactions": [{"character": "leo", "action": "surprised", "emotion": "surprised"}]},
                _line(3, emotion="worried", action="talk", look_at="taza", camera="push_in", camera_target="leo",
                      reactions=[{"character": "dra_nova", "action": "happy", "emotion": "happy"}]),
                _line(4, emotion="neutral", action="talk", camera="drift_up",
                      reactions=[{"character": "leo", "action": "confused", "emotion": "confused"}], science_event="flotar no es salir disparado"),
            ]},
            {"id": "s3", "set": "simulacion", "label": "Simulación simplificada", "cast": [],
             "props": [{"uid": "sim", "prop": "sim_tangente", "at": "centro", "params": {}}], "beats": [
                _line(5, science_event="el objeto sigue recto; el suelo se curva"),
                _line(6, science_event="separación calculada con el modelo"),
                _line(7), _line(8),
            ]},
            {"id": "s4", "set": "laboratorio", "label": "", "cast": LAB_CAST, "props": LAB_PROPS, "beats": [
                _line(9, emotion="neutral", action="point", camera="wide", effects=["gravity_on"],
                      reactions=[{"character": "leo", "action": "surprised", "emotion": "worried"}], science_event="la gravedad vuelve: todo cae"),
                {"actor": "", "seconds": 0.9, "action": "idle", "camera": "shake"},
                _line(10, emotion="worried", action="confused", camera="push_in", camera_target="leo"),
                _line(11, emotion="happy", action="talk", camera="push_in", camera_target="dra_nova",
                      reactions=[{"character": "leo", "action": "happy", "emotion": "happy"}], science_event="la gravedad nos mantiene juntos"),
                {"actor": "leo", "seconds": 1.0, "action": "happy", "emotion": "happy", "camera": "wide"},
            ]},
        ],
    }
