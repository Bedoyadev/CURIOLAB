"""Research Engine: choose a question worth an episode, find sources for it, and build the fact
sheet the script is allowed to draw from.

What Claude does: propose questions, search the web for sources, read them and pull out facts.
What the code does: read every source itself (a page that cannot be read is not a source), keep a
fact only if its quote is literally in the source it names (shared.sources.verify_claims), and
compute the numbers of any simulation with explicit formulas (simulations.py).

An episode's science therefore comes from two places only: quoted sources and the engine's own
models. A question left without enough of either stops here, before a script is written.
"""
import logging
import re
from urllib.parse import urlparse

import httpx

from animation import llm, simulations
from animation.profile import AnimationProfile
from animation.shared.sources import (
    ARTICLE_USER_AGENT, MAX_SOURCE_CHARS, MIN_SOURCE_CHARS, SourceDoc, _plain, find_sources, page_text, verify_claims,
)
from animation.shared.text import similar_titles

logger = logging.getLogger("animation.research")


class NeedsReview(Exception):
    """The episode cannot go on without a person looking at it."""


SOURCES_SYSTEM = """Buscas fuentes para un episodio de divulgación científica.
Usa la búsqueda web y elige las mejores páginas para responder la pregunta con rigor: agencias
espaciales y científicas (NASA, ESA, NOAA, CERN), universidades, museos de ciencia, sociedades
científicas, enciclopedias de referencia con autor, y revistas de divulgación serias. Evita foros,
redes sociales, tiendas, videos, wikis y blogs sin autor. Prefiere páginas que expliquen el fenómeno
con cifras y causas; si la pregunta es hipotética, busca las que expliquen la física que la responde.
Al menos la mitad deben ser de instituciones (agencias, universidades, museos, sociedades científicas):
una sola web de divulgación no basta para sostener un episodio.
Termina tu respuesta con una lista de entre 4 y 6 direcciones, una por línea, sin más texto en esas
líneas."""

# How much a publisher's word weighs. An episode's central statements should rest on the first two.
INSTITUTIONAL = (".gov", ".edu", ".int", ".ac.uk", ".edu.au", ".gob.es", ".gob.mx", "nasa.", "esa.int", "noaa.", "nrao.", "cern.", "nist.",
                 "usgs.", "eso.org", "si.edu", "csic.es", "iac.es", "royalsociety.org", "aps.org", "iop.org", "ucar.edu", "jpl.")
REFERENCE = ("britannica.com", "nature.com", "science.org", "scientificamerican.com", "newscientist.com", "physicsworld.com",
             "quantamagazine.org", "nationalgeographic.", "smithsonianmag.com", "investigacionyciencia.es", "phys.org", "physics.org")
WANTED_SOURCES = 3
MAX_SOURCES = 5
# No single source may supply more than this share of an episode's facts.
MAX_SHARE_PER_SOURCE = 0.6


def tier(publisher: str) -> str:
    host = publisher.casefold()
    if any(host.endswith(mark) or mark in host for mark in INSTITUTIONAL):
        return "institucional"
    if any(mark in host for mark in REFERENCE):
        return "referencia"
    return "divulgación"


async def read_pages(urls: list[str], http: httpx.AsyncClient | None = None) -> list[SourceDoc]:
    """Read each address; pages that cannot be read or carry too little text are left out. A page
    whose article is not marked up in paragraphs (many agency pages are not) is read from its
    whole body instead of being thrown away."""
    docs: list[SourceDoc] = []
    own = http is None
    http = http or httpx.AsyncClient()
    try:
        for url in dict.fromkeys(urls):
            try:
                resp = await http.get(url, headers={"User-Agent": ARTICLE_USER_AGENT}, timeout=30, follow_redirects=True)
                resp.raise_for_status()
                title, text = page_text(resp.text)
                if len(text) < MIN_SOURCE_CHARS:
                    body = re.sub(r"(?is)<(script|style|nav|header|footer|aside|form|noscript|svg)\b.*?</\1>", " ", resp.text)
                    text = _plain(body)[:MAX_SOURCE_CHARS]
            except Exception as e:
                logger.warning("Source not read (%s): %s", url, e)
                continue
            if len(text) < MIN_SOURCE_CHARS:
                logger.warning("Source with too little text (%s chars): %s", len(text), url)
                continue
            docs.append(SourceDoc(url=url, title=title[:200], publisher=urlparse(url).netloc.removeprefix("www."), text=text))
    finally:
        if own:
            await http.aclose()
    return docs


async def gather_sources(topic: str, ledger, http=None) -> list[SourceDoc]:
    """Search and read. When too few of the pages found can be read, or none is institutional,
    one more search is made, told which pages failed. The best-ranked sources are kept."""
    urls = await find_sources(topic, ledger, system=SOURCES_SYSTEM, label="Pregunta")
    docs = await read_pages(urls, http)
    if len(docs) < WANTED_SOURCES or not any(tier(d.publisher) == "institucional" for d in docs):
        failed = [u for u in urls if u not in {d.url for d in docs}]
        note = (f"{topic}\n(Estas páginas no se pudieron leer, no las repitas: {', '.join(failed) or 'ninguna'}. "
                "Hacen falta más páginas de instituciones científicas, con el texto en la propia página.)")
        more = await find_sources(note, ledger, system=SOURCES_SYSTEM, label="Pregunta")
        docs += await read_pages([u for u in more if u not in urls], http)
    order = {"institucional": 0, "referencia": 1, "divulgación": 2}
    return sorted(docs, key=lambda d: order[tier(d.publisher)])[:MAX_SOURCES]

TOPICS_SYSTEM = """Propones preguntas para el canal «{name}»: {about}

Cada episodio es un corto animado de menos de un minuto en el que dos personajes ponen a prueba una
pregunta científica. Propón {n} preguntas distintas entre sí y distintas de las ya hechas.

Puntúa cada una de 0 a 10 en:
- curiosity: cuánto dan ganas de saber la respuesta.
- narrative: si da para un pequeño conflicto o experimento con principio y final.
- visual: qué tan fácil es mostrarla con personajes, objetos y un diagrama, sin texto.
- differentiation: qué tan poco vista está contada así.
- sources: qué tan fácil es encontrar fuentes serias que la respondan.
- cost: qué tan barata es de producir (pocas escenas, recursos que ya existen).
Son estimaciones editoriales tuyas, no predicciones de audiencia: no inventes cifras de visitas.
«demand» no se puntúa. Lo que se sabe de la demanda son los datos del propio canal:
{observed}
Tenlos en cuenta como pista al proponer (qué tipo de pregunta y de episodio ha retenido mejor), sin
repetir un tema ya hecho.

Recursos que el estudio ya tiene para mostrarla:
{catalog}
Simulaciones con fórmula que el estudio puede calcular: {sims}"""

FACTS_SYSTEM = """Eres el verificador científico de un canal de divulgación. Recibes una pregunta y el
texto de varias fuentes numeradas. Construyes la ficha de hechos del episodio SOLO con lo que dicen
esas fuentes: no añades nada de tu memoria, aunque lo sepas.

Cada hecho lleva:
- "text": el hecho, en español, en una frase clara.
- "source": el número de la fuente.
- "quote": un fragmento LITERAL de esa fuente (copiado tal cual, en su idioma, de 6 a 45 palabras)
  que lo respalda. Sin puntos suspensivos ni cambios: se comprueba letra por letra.

Además:
- "answer": la respuesta a la pregunta en dos o tres frases, usando solo esos hechos.
- "assumptions": si la pregunta es hipotética, los supuestos que hay que decir en voz alta para
  que la respuesta sea honesta (qué se da por cambiado y qué se deja igual).
- "unknowns": lo que las fuentes no permiten afirmar.
- "simulation": si alguna de estas simulaciones del estudio responde parte de la pregunta con un
  cálculo, elige UNA y da sus entradas; si ninguna encaja, "". No calcules tú el resultado.
  {sims}
- Entre 6 y 14 hechos. Prefiere los que tengan cifra, causa o mecanismo.
- Reparte: toma hechos de todas las fuentes que aporten algo, y ninguna debe dar más de la mitad.
  Lo esencial, de las fuentes marcadas como institucional o referencia cuando lo digan.
- Una metáfora o una comparación llamativa del autor («seríamos como…») no es un hecho: no la
  recojas. Tampoco una especulación que la propia fuente no respalde con una causa."""


def weights() -> dict[str, float]:
    return {"curiosity": 25, "narrative": 20, "visual": 20, "differentiation": 15, "sources": 15, "cost": 5}


def score(components: dict) -> float:
    w = weights()
    return round(sum(w[k] * min(10.0, max(0.0, float(components.get(k, 0)))) / 10 for k in w), 1)


async def choose_topic(profile: AnimationProfile, catalog: str, previous: list[str], ledger, n: int = 6,
                       observed: str = "Sin datos de demanda observada.") -> dict:
    """{"topic", "candidates": [...]}: the best-scored question that is not like one already made.
    observed: what the channel's own published episodes say (analytics.lessons)."""
    o, a = llm.obj, llm.arr
    schema = o({"candidates": a(o({
        "question": llm.STR, "angle": llm.STR, "curiosity": llm.NUM, "narrative": llm.NUM, "visual": llm.NUM,
        "differentiation": llm.NUM, "sources": llm.NUM, "cost": llm.NUM, "why": llm.STR}))})
    sims = "; ".join(f"{k} ({v})" for k, v in simulations.CATALOG.items())
    user = "PREGUNTAS YA HECHAS:\n" + ("\n".join(f"- {t}" for t in previous) or "(ninguna)")
    data = await llm.ask(profile.claude_model, TOPICS_SYSTEM.format(name=profile.name, about=profile.about, n=n,
                                                                    catalog=catalog, sims=sims, observed=observed),
                         user, schema, ledger, "tema:candidatos", effort="low")
    candidates = []
    for c in data["candidates"]:
        question = " ".join(str(c["question"]).split())
        if len(question) < 12:
            continue
        components = {k: c[k] for k in weights()}
        candidates.append({"question": question, "angle": c["angle"], "components": components, "why": c["why"],
                           # Editorial heuristic of the model, not a forecast of views.
                           "score": score(components), "repeated": bool(similar_titles(question, previous))})
    fresh = sorted((c for c in candidates if not c["repeated"]), key=lambda c: -c["score"])
    if not fresh:
        raise NeedsReview("no se propuso ninguna pregunta que el canal no haya hecho ya")
    return {"topic": fresh[0]["question"], "candidates": candidates, "demand": observed}


async def investigate(profile: AnimationProfile, topic: str, ledger, urls: list[str] | None = None, http=None) -> dict:
    """The fact sheet of a question: {"topic", "facts", "dropped", "sources", "answer",
    "assumptions", "unknowns", "simulations"}. Raises NeedsReview when it is too thin."""
    docs = await read_pages(list(urls), http) if urls else await gather_sources(topic, ledger, http)
    rules = profile.research
    if len(docs) < rules.min_sources:
        raise NeedsReview(f"solo se pudo leer {len(docs)} fuente(s); hacen falta {rules.min_sources}")
    o, a = llm.obj, llm.arr
    schema = o({
        "facts": a(o({"text": llm.STR, "source": llm.INT, "quote": llm.STR})),
        "answer": llm.STR, "assumptions": a(llm.STR), "unknowns": a(llm.STR),
        "simulation": llm.enum(["", *simulations.REGISTRY]),
        "simulation_inputs": o({"seconds": llm.NUM, "latitude": llm.NUM, "height": llm.NUM, "mass": llm.NUM,
                                "world": llm.enum(["", *simulations.SURFACE_GRAVITY])}),
    })
    listing = "\n\n".join(f"[FUENTE {i}] {d.title} ({d.publisher} · {tier(d.publisher)})\n{d.text}" for i, d in enumerate(docs))
    sims = "\n  ".join(f"- {k}: {v}" for k, v in simulations.CATALOG.items())
    data = await llm.ask(profile.claude_model, FACTS_SYSTEM.format(sims=sims),
                         f"PREGUNTA: {topic}\n\nReglas del canal:\n{profile.rules()}\n\n{listing}",
                         schema, ledger, "investigacion:ficha")
    kept, dropped = verify_claims([{**f, "kind": "hecho"} for f in data["facts"]], docs)
    # One source cannot carry the episode: what it gives beyond its share is left out (its
    # first facts are kept, in the order the verifier chose them).
    limit = max(2, int(len(kept) * MAX_SHARE_PER_SOURCE)) if len({c["source"] for c in kept}) > 1 else len(kept)
    taken: dict[int, int] = {}
    balanced = []
    for c in kept:
        taken[c["source"]] = taken.get(c["source"], 0) + 1
        if taken[c["source"]] <= limit:
            balanced.append(c)
        else:
            dropped.append({"text": c["text"][:200], "problem": "su fuente ya aporta demasiados hechos del episodio"})
    facts = [{"id": f"h{i}", "text": c["text"], "source": c["source"], "quote": c["quote"],
              "tier": tier(docs[c["source"]].publisher)} for i, c in enumerate(balanced, 1)]
    sims_run = []
    if data["simulation"]:
        fn = simulations.REGISTRY[data["simulation"]]
        wanted = fn.__code__.co_varnames[:fn.__code__.co_argcount]
        inputs = {k: v for k, v in data["simulation_inputs"].items() if k in wanted and v not in ("", 0, 0.0)}
        try:
            sims_run.append(simulations.run(data["simulation"], inputs))
        except simulations.SimulationError as e:
            logger.warning("Simulation %s not run: %s", data["simulation"], e)
    sheet = {
        "topic": topic, "facts": facts, "dropped": dropped,
        "sources": [{"id": i, "url": d.url, "title": d.title, "publisher": d.publisher, "tier": tier(d.publisher)}
                    for i, d in enumerate(docs)],
        "answer": data["answer"], "assumptions": data["assumptions"], "unknowns": data["unknowns"],
        "simulations": sims_run,
    }
    if len(facts) < rules.min_facts:
        raise NeedsReview(f"solo {len(facts)} hechos quedaron respaldados por una cita literal; hacen falta {rules.min_facts}")
    if len({f["source"] for f in facts}) < rules.min_sources:
        raise NeedsReview("todos los hechos salen de una sola fuente")
    return sheet


def support_ids(sheet: dict) -> set[str]:
    """What a line of the script may cite."""
    return {f["id"] for f in sheet["facts"]} | {f"sim:{s['id']}" for s in sheet["simulations"]}


def sheet_text(sheet: dict) -> str:
    """The fact sheet as the writer reads it."""
    lines = [f"PREGUNTA: {sheet['topic']}", f"RESPUESTA SEGÚN LAS FUENTES: {sheet['answer']}", "HECHOS (cítalos por su id):"]
    lines += [f"- {f['id']} [fuente {f['source']}, {f.get('tier', 'sin fuente')}]: {f['text']}" for f in sheet["facts"]]
    for s in sheet["simulations"]:
        lines.append(f"SIMULACIÓN sim:{s['id']} ({s['exactness']}): {s['statement']}")
        lines.append("  Supuestos: " + " ".join(s["assumptions"]))
    if sheet["assumptions"]:
        lines.append("SUPUESTOS DEL ESCENARIO: " + " ".join(sheet["assumptions"]))
    if sheet["unknowns"]:
        lines.append("NO SE PUEDE AFIRMAR: " + " ".join(sheet["unknowns"]))
    return "\n".join(lines)
