"""Script Engine and Storyboard Engine: the dialogue, then its staging.

Two calls, two checks each:

1. write_script: three alternative hooks with an editorial score, the chosen one, and the dialogue
   line by line, each line citing the facts or simulations it rests on. Checked by code (length,
   speakers, citations exist, no figure that is not in the fact sheet) and by a second reading of
   the model that looks for a line saying more than its citations do.
2. stage: the storyboard. Claude places the approved lines on a set with characters, objects,
   gestures, camera and effects, choosing only among registered ids; the text of each line is
   copied from the script by code, never retyped by the model.

Scores given by the model are editorial heuristics. They order options; they do not predict views.
"""
import json
import logging
import re

from animation import llm, storyboard
from animation.library import Library
from animation.profile import AnimationProfile
from animation.research import NeedsReview, sheet_text, support_ids
from animation.shared.text import shared_wording

logger = logging.getLogger("animation.script")

# A new script that shares this much of its four-word sequences with an earlier one is a repeat.
MAX_SHARED_WORDING = 0.25
ATTEMPTS = 3

SCRIPT_SYSTEM = """Escribes el guion de un episodio de «{name}»: {about}

Formato: corto vertical de {min_s}-{max_s} segundos, SOLO diálogo entre estos personajes:
{cast}

Reglas del canal:
{rules}

Cómo se escribe:
- Entre {wmin} y {wask} palabras en total, contando todas las líneas: apunta a unas {target}, en
  9 a 12 líneas. Es poco: una idea por línea, y la mayoría de las líneas de 6 a 12 palabras
  (máximo 22). Si te sobra material, quita una idea entera; no aprietes más datos en cada línea.
- Primero escribe TRES ganchos distintos para la primera línea (los dos primeros segundos del video):
  cada uno con una puntuación editorial de 0 a 10 y por qué. Elige el mejor. No es una predicción
  de audiencia; es tu criterio. Un gancho no promete nada que el episodio no cumpla.
- Estructura: gancho con la pregunta → el experimento o conflicto empieza → reacción → la explicación
  avanza paso a paso → consecuencias bajo supuestos dichos en voz alta → cierre que responde la
  pregunta y deja una idea clara.
- Cada línea que afirme algo de ciencia lleva en "supports" los ids de los hechos (h1, h2…) o de la
  simulación (sim:…) en que se apoya. Una línea que solo reacciona o pregunta lleva supports vacío.
- No uses ninguna cifra que no esté en la ficha. Las cifras de una simulación se dicen tal como
  vienen, junto con su carácter («en un modelo simplificado», «sin contar el aire»).
- Si el escenario es hipotético, alguien dice los supuestos en voz alta.
- Apoya lo que afirmes en al menos dos fuentes distintas, y lo central en las institucionales o de
  referencia. No repitas como física una imagen o una exageración de una web de divulgación.
- Escribe los números como se dicen («cuarenta y dos centímetros»), sin símbolos ni abreviaturas.
- El humor sale del carácter de los personajes y nunca cambia un dato.
- "title": la pregunta del episodio, como título de YouTube (máximo 80 caracteres, sin mayúsculas
  sostenidas ni exageraciones). "description": dos o tres frases para la descripción del video.
  "tags": de 5 a 10 etiquetas. "takeaway": la idea con la que se queda el espectador, en una frase."""

VERIFY_SYSTEM = """Eres el revisor científico de un canal de divulgación. Recibes la ficha de hechos de un
episodio y su guion, línea por línea, con lo que cada línea dice apoyarse.

Señala SOLO problemas reales:
- una línea que afirma algo que sus hechos citados no dicen, o que no cita nada y afirma ciencia;
- una hipótesis o un resultado de un modelo simplificado dicho como si fuera un hecho medido;
- una cifra cambiada o inventada;
- un escenario hipotético sin sus supuestos dichos en ninguna parte del guion.
No señales estilo, humor ni preguntas de los personajes. Un verbo en condicional («se perdería»,
«saldríamos») ya dice que es una hipótesis, y a los supuestos del escenario les basta con decirse una
vez en el guion: no pidas repetirlos en cada línea. Una paráfrasis fiel de un hecho citado es correcta.
Si no hay problemas, devuelve una lista vacía."""

STAGE_SYSTEM = """Eres el director de animación de «{name}». Recibes el guion aprobado de un episodio
(líneas numeradas desde 0) y la biblioteca del estudio. Conviertes el guion en un storyboard: escenas
hechas de «beats».

Solo puedes usar lo que está en la biblioteca. No inventes personajes, escenarios, objetos, acciones,
cámaras ni efectos.

{catalog}

Cómo se monta:
- Que se vea, no solo que se cuente. Si el episodio trata de algo que el estudio puede hacer ocurrir
  en escena con un efecto, un objeto o una acción (la gravedad que se apaga y los objetos que se
  sueltan, algo que cae, un personaje que flota), hazlo ocurrir delante de los personajes en el
  momento en que el guion llega a ello, y que reaccionen. Un episodio donde solo se habla es un fallo.
- Entre {smin} y {smax} escenas. Una escena nueva cuando cambia el lugar o la idea.
- "id" de escena: s1, s2… "cast": quién está y en qué sitio (un sitio por personaje). Quien no está
  en la escena solo puede oírse (su beat lleva action "talk").
- "props": objetos de la escena, cada uno con un "uid" propio (minúsculas, sin espacios) en un sitio
  distinto. Pon los objetos que la historia usa, no decorado de relleno.
- Un beat es una línea del guion ("line": su número, "seconds": 0, "actor": "") o un momento sin
  diálogo ("line": -1, "seconds": de 0.8 a 4, "actor": quien actúa o "").
  Todas las líneas del guion aparecen, una vez y en orden.
- "action" y "emotion" son de quien habla (o del actor). "walk" necesita "walk_to" (un sitio libre
  del escenario); en cualquier otro caso "walk_to" es "".
- "reactions": lo que hace mientras tanto quien NO habla. Úsalas: un personaje quieto es un fallo.
- "look_at": a quién o a qué mira quien habla (id de personaje o uid de objeto), o "".
- "camera": muévela con intención, no en cada beat. push_in, pan y follow necesitan "camera_target"
  (personaje u objeto de la escena). Vuelve al plano general ("wide") antes de una acción amplia.
- "effects": gravity_off suelta los objetos sueltos y deja a los personajes flotando hasta
  gravity_on, también a través de los cortes: una escena posterior en el mismo lugar se abre con
  todo flotando. El episodio no puede terminar con la gravedad apagada. "dust" acompaña bien a
  gravity_off; "flash" marca el instante en que algo cambia.
- Para que una escena continúe a otra anterior del mismo escenario, repite el mismo "cast" y los
  mismos "props" en los mismos sitios.
- Una simulación se enseña en una escena con el escenario "simulacion" y el objeto que la dibuja,
  colocado en "centro", sin personajes en pie (se les oye). Esa escena lleva "label" con el tipo de
  modelo, por ejemplo «Simulación simplificada». Las demás escenas llevan "label" "".
- "science_event": en pocas palabras, qué se está mostrando en ese beat ("" si nada).
- Los parámetros de un objeto ("params") solo cuando el objeto los tiene; si no, {{}}."""


def _cast_text(lib: Library, cast: list[str]) -> str:
    return "\n".join(f"- {cid} ({lib.characters[cid]['name']}, {lib.characters[cid]['role']}): "
                     f"{lib.characters[cid]['personality']} {' '.join(lib.characters[cid].get('restrictions', []))}"
                     for cid in cast)


def _digits(text: str) -> set[str]:
    """Figures written with digits, normalised: 1.674 and 1,674 and 1674 are the same number."""
    found = set()
    for raw in re.findall(r"\d[\d.,]*", text):
        raw = raw.rstrip(".,")
        found.add(re.sub(r"[.,]", "", raw))
    return found


def script_problems(script: dict, sheet: dict, profile: AnimationProfile, cast: list[str]) -> list[str]:
    """What the code can check without a model."""
    problems = []
    lines = script.get("lines", [])
    known = support_ids(sheet)
    total = sum(len(line["text"].split()) for line in lines)
    fmt = profile.format
    if not (fmt.words_min <= total <= fmt.words_max):
        problems.append(f"el guion tiene {total} palabras; debe tener entre {fmt.words_min} y {fmt.words_max}")
    if len(script.get("hooks", [])) != 3:
        problems.append("hacen falta exactamente tres ganchos alternativos")
    if not (0 <= script.get("chosen_hook", -1) < len(script.get("hooks", []))):
        problems.append("chosen_hook no señala a uno de los ganchos")
    allowed = _digits(json.dumps(sheet, ensure_ascii=False))
    for i, line in enumerate(lines):
        if line["speaker"] not in cast:
            problems.append(f"línea {i}: habla {line['speaker']}, que no está en el reparto")
        if len(line["text"].split()) > 26:
            problems.append(f"línea {i}: demasiado larga para decirla de una vez")
        for ref in line.get("supports", []):
            if ref not in known:
                problems.append(f"línea {i}: cita '{ref}', que no está en la ficha")
        for number in _digits(line["text"]) - allowed:
            problems.append(f"línea {i}: la cifra {number} no está en la ficha de hechos ni en las simulaciones")
    if not any(line.get("supports") for line in lines):
        problems.append("ninguna línea cita un hecho o una simulación")
    by_id = {f["id"]: f for f in sheet["facts"]}
    cited = {by_id[ref]["source"] for line in lines for ref in line.get("supports", []) if ref in by_id}
    available = {f["source"] for f in sheet["facts"]}
    if len(available) > 1 and len(cited) < 2:
        problems.append("todo lo que el guion afirma sale de una sola fuente; apóyalo en al menos dos de la ficha")
    if not (10 <= len(script.get("title", "")) <= 100):
        problems.append("el título debe tener entre 10 y 100 caracteres")
    return problems


def script_text(script: dict) -> str:
    return " ".join(line["text"] for line in script.get("lines", []))


async def write_script(profile: AnimationProfile, lib: Library, cast: list[str], sheet: dict, ledger,
                       previous: list[str] | None = None) -> dict:
    """The checked script. previous: the text of earlier episodes' scripts (a script that repeats
    their wording is rejected). Raises NeedsReview when two attempts do not pass."""
    o, a = llm.obj, llm.arr
    schema = o({
        "title": llm.STR,
        "hooks": a(o({"text": llm.STR, "score": llm.NUM, "why": llm.STR})), "chosen_hook": llm.INT,
        "lines": a(o({"speaker": llm.enum(cast), "text": llm.STR, "supports": a(llm.STR)})),
        "takeaway": llm.STR, "description": llm.STR, "tags": a(llm.STR),
    })
    fmt = profile.format
    system = SCRIPT_SYSTEM.format(name=profile.name, about=profile.about, min_s=fmt.min_seconds, max_s=fmt.max_seconds,
                                  cast=_cast_text(lib, cast), rules=profile.rules(), wmin=fmt.words_min,
                                  # Asked for shorter than what is accepted: models overshoot a word count.
                                  wask=fmt.words_max - 10, target=(fmt.words_min + fmt.words_max) // 2 - 8)
    base = sheet_text(sheet)
    feedback, last = "", []
    for attempt in range(ATTEMPTS):
        script = await llm.ask(profile.claude_model, system, base + feedback, schema, ledger, f"guion:intento {attempt + 1}")
        script["lines"] = [{**line, "text": " ".join(line["text"].split())} for line in script["lines"] if line["text"].strip()]
        problems = script_problems(script, sheet, profile, cast)
        repeats = max((shared_wording(script_text(script), old) for old in previous or []), default=0.0)
        if repeats > MAX_SHARED_WORDING:
            problems.append(f"repite la redacción de un episodio anterior ({repeats:.0%} de sus frases)")
        if not problems:
            listing = "\n".join(f"{i}. [{line['speaker']}] {line['text']}  (apoyo: {', '.join(line['supports']) or 'ninguno'})"
                                for i, line in enumerate(script["lines"]))
            verdict = await llm.ask(profile.claude_model, VERIFY_SYSTEM, f"{base}\n\nGUION:\n{listing}",
                                    o({"problems": a(o({"line": llm.INT, "problem": llm.STR}))}), ledger,
                                    "guion:revisión científica", effort="low")
            problems = [f"línea {p['line']}: {p['problem']}" for p in verdict["problems"]]
        if not problems:
            script["checks"] = {"words": sum(len(line["text"].split()) for line in script["lines"]),
                                "shared_wording": repeats, "attempts": attempt + 1}
            return script
        last = problems
        logger.info("Script attempt %s rejected: %s", attempt + 1, problems)
        total = sum(len(line["text"].split()) for line in script["lines"])
        over = total - fmt.words_max
        # A model does not count words well: tell it how much to cut, and show it what it wrote.
        size = (f"\nTenía {total} palabras en {len(script['lines'])} líneas: sobran al menos {over + 8}. Quita líneas o ideas enteras."
                if over > 0 else "")
        feedback = ("\n\nTU GUION ANTERIOR FUE RECHAZADO. Corrige esto y vuelve a escribirlo entero:\n" + "\n".join(f"- {p}" for p in problems)
                    + size + "\n\nEL GUION RECHAZADO:\n" + "\n".join(f"[{line['speaker']}] {line['text']}" for line in script["lines"]))
    raise NeedsReview("el guion no pasó la revisión: " + "; ".join(last)[:800])


async def stage(profile: AnimationProfile, lib: Library, cast: list[str], script: dict, sheet: dict, ledger,
                episode_id: str) -> tuple[dict, list[str]]:
    """(storyboard document, notes of what was repaired). Raises storyboard.StoryboardRejected
    when two attempts still name something the library does not have."""
    fmt = profile.format
    system = STAGE_SYSTEM.format(name=profile.name, catalog=lib.catalog(cast), smin=fmt.min_scenes, smax=fmt.max_scenes)
    listing = "\n".join(f"{i}. [{line['speaker']}] {line['text']}" for i, line in enumerate(script["lines"]))
    sims = "\n".join(f"- sim:{s['id']}: {s['statement']}" for s in sheet["simulations"]) or "(ninguna)"
    base = f"TÍTULO: {script['title']}\n\nGUION:\n{listing}\n\nSIMULACIONES DISPONIBLES EN ESTE EPISODIO:\n{sims}"
    schema = storyboard.staging_schema(lib, cast)
    known = support_ids(sheet)
    feedback, problems = "", []
    for attempt in range(2):
        staging = await llm.ask(profile.claude_model, system, base + feedback, schema, ledger, f"storyboard:intento {attempt + 1}")
        problems = storyboard.lines_in_order(staging, len(script["lines"]))
        count = len(staging.get("scenes", []))
        if not (fmt.min_scenes <= count <= fmt.max_scenes):
            problems.append(f"hay {count} escenas; deben ser entre {fmt.min_scenes} y {fmt.max_scenes}")
        notes: list[str] = []
        if not problems:
            document = storyboard.assemble(staging, script, episode_id, cast, sheet["sources"], fmt.max_seconds)
            try:
                sb = storyboard.parse(document)
                notes = storyboard.repair(sb, lib)
                problems = storyboard.validate(sb, lib, known)
            except storyboard.StoryboardRejected as e:
                problems = e.problems
            if not problems:
                return sb.model_dump(), notes
        logger.info("Storyboard attempt %s rejected: %s", attempt + 1, problems)
        feedback = "\n\nTU STORYBOARD ANTERIOR FUE RECHAZADO. Corrige esto y devuélvelo entero:\n" + "\n".join(f"- {p}" for p in problems[:20])
    raise storyboard.StoryboardRejected(problems)
