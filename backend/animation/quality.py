"""Quality Engine: what can be measured on the finished episode is measured (with the documentary
engine's probes), and what no program can decide is listed for the person who approves.

Four kinds of checks, each a line of the report:
- técnico: the file is what YouTube Shorts takes and nothing in it is black, silent or clipped;
- sincronía: the captions cover the dialogue and every scene's video lasts what its plan says;
- científico: every line that states science cites a fact with a quoted source or a simulation;
- editorial: it is not a repeat of an earlier episode, in title or in wording.

Passing does not approve anything. The episode waits for the owner either way.
"""
from pathlib import Path

from animation.profile import AnimationProfile
from animation.shared.text import shared_wording, similar_titles
from animation.shared.probes import HEIGHT, LOUDNESS_RANGE, MAX_TRUE_PEAK, MIN_FPS, WIDTH, black_spans, loudness, probe

MAX_SHARED_WORDING = 0.25

HUMAN = [
    "Ver el episodio entero: que los gestos acompañen a lo que se dice y nada se mueva a destiempo.",
    "Escuchar las voces: pronunciación de los términos científicos y que cada personaje suene a sí mismo.",
    "Leer el guion contra la ficha de hechos: que ningún supuesto suene a hecho medido.",
    "Comprobar que la simulación mostrada lleva su rótulo y que lo que se dice de ella coincide con sus supuestos.",
    "Contenido sintético: las voces son generadas. Decidir si procede declararlo al publicar (YouTube lo exige para contenido realista alterado o sintético; una animación claramente no realista normalmente no lo requiere).",
    "Monetización: historia e información propias de este episodio; personajes y escenarios recurrentes son identidad del canal.",
    "Arte provisional: personajes, escenarios y objetos son formas vectoriales hechas por código, a la espera de diseño final.",
]


def _check(group: str, name: str, ok: bool, detail: str) -> dict:
    return {"group": group, "name": name, "ok": bool(ok), "detail": detail}


def check(profile: AnimationProfile, video: Path, sb: dict, sheet: dict, timeline: dict, scene_videos: list[Path],
          spent: float, previous: list[dict] | None = None, tail: float = 0.0) -> dict:
    """previous: earlier episodes as {"title", "text"}. Returns {"passed", "checks", "human", ...}."""
    info = probe(video)
    checks = [
        _check("técnico", "Formato vertical 1080×1920", (info["width"], info["height"]) == (WIDTH, HEIGHT), f"{info['width']}×{info['height']}"),
        _check("técnico", "30 cuadros por segundo", info["fps"] >= MIN_FPS, f"{info['fps']:.0f} fps"),
        _check("técnico", "Tiene audio", info["audio"], "sí" if info["audio"] else "no"),
    ]
    fmt = profile.format
    checks.append(_check("técnico", f"Duración de {fmt.min_seconds} a {fmt.max_seconds} s", fmt.min_seconds <= info["duration"] <= fmt.max_seconds,
                         f"{info['duration']:.1f} s"))
    black = black_spans(video)
    checks.append(_check("técnico", "Sin tramos en negro", not black, ", ".join(f"{a:.1f}-{b:.1f} s" for a, b in black) or "ninguno"))
    loud = loudness(video)
    if loud is not None:
        checks.append(_check("técnico", "Volumen de emisión", LOUDNESS_RANGE[0] <= loud["integrated"] <= LOUDNESS_RANGE[1],
                             f"{loud['integrated']:.1f} LUFS"))
        checks.append(_check("técnico", "Sin saturación", loud["true_peak"] <= MAX_TRUE_PEAK, f"pico {loud['true_peak']:.1f} dBTP"))

    # Sync: every scene's file lasts what its plan says, and the captions cover the spoken words.
    off = []
    for scene, path in zip(timeline["scenes"], scene_videos):
        real = probe(path)["duration"]
        if abs(real - scene["duration"]) > 0.05:
            off.append(f"{scene['id']}: {real:.2f} s frente a {scene['duration']:.2f} s")
    checks.append(_check("sincronía", "Cada escena dura lo que su audio", not off, "; ".join(off) or f"{len(scene_videos)} escenas exactas"))
    spoken = sum(len(b["text"].split()) for s in sb["scenes"] for b in s["beats"] if b["text"].strip())
    checks.append(_check("sincronía", "Subtítulos para todo el diálogo", len(timeline["words"]) >= spoken * 0.9,
                         f"{len(timeline['words'])} palabras con tiempo de {spoken}"))
    overlap = [f"{a['start']:.1f} s" for a, b in zip(timeline["lines"], timeline["lines"][1:]) if a["start"] + a["duration"] > b["start"] + 0.01]
    checks.append(_check("sincronía", "Ninguna línea pisa a la siguiente", not overlap, ", ".join(overlap) or "ninguna"))
    checks.append(_check("sincronía", "El video termina con el cierre", abs(info["duration"] - (timeline["duration"] + tail)) < 0.25,
                         f"{info['duration']:.1f} s frente a {timeline['duration'] + tail:.1f} s"))

    # Science: where each statement comes from.
    cited = sorted({ref for s in sb["scenes"] for b in s["beats"] for ref in b["supports"]})
    sourced = [f for f in sheet["facts"] if f.get("quote")]
    demo = bool(sheet.get("demo"))
    checks.append(_check("científico", "Hechos con cita literal de su fuente", bool(sourced) and len(sourced) == len(sheet["facts"]),
                         "MODO DEMO: los hechos no tienen fuente; no publicar" if demo else
                         f"{len(sourced)} de {len(sheet['facts'])} hechos, {len(sheet['sources'])} fuentes"))
    checks.append(_check("científico", "El diálogo cita hechos o simulaciones", bool(cited), ", ".join(cited) or "ninguna cita"))
    by_id = {f["id"]: f for f in sheet["facts"]}
    used = {by_id[ref]["source"] for ref in cited if ref in by_id and by_id[ref].get("quote")}
    names = [f"{sheet['sources'][i]['publisher']} ({sheet['sources'][i].get('tier', '?')})" for i in sorted(used)]
    checks.append(_check("científico", "Lo que se afirma sale de al menos dos fuentes", len(used) >= 2,
                         "MODO DEMO" if demo else ", ".join(names) or "ninguna"))
    solid = [i for i in used if sheet["sources"][i].get("tier") in ("institucional", "referencia")]
    checks.append(_check("científico", "Alguna fuente citada es institucional o de referencia", bool(solid),
                         "MODO DEMO" if demo else f"{len(solid)} de {len(used)} fuentes citadas"))
    simulated = [p["prop"] for s in sb["scenes"] for p in s["props"] if p["prop"].startswith("sim_")]
    labelled = all(s["label"].strip() for s in sb["scenes"] if any(p["prop"].startswith("sim_") for p in s["props"]))
    checks.append(_check("científico", "Las simulaciones van rotuladas", labelled,
                         "; ".join(f"{s['id']}: {s['exactness']}" for s in sheet["simulations"]) if simulated else "el episodio no muestra simulaciones"))

    # Editorial: is it its own episode.
    previous = previous or []
    same = similar_titles(sb["title"], [p["title"] for p in previous if p.get("title")])
    checks.append(_check("editorial", "Título distinto de los anteriores", not same, "; ".join(same) or "único"))
    text = " ".join(b["text"] for s in sb["scenes"] for b in s["beats"])
    shared = max((shared_wording(text, p["text"]) for p in previous if p.get("text")), default=0.0)
    checks.append(_check("editorial", "Redacción propia", shared <= MAX_SHARED_WORDING, f"{shared:.0%} de frases compartidas con un episodio anterior"))
    sets = [s["set"] for s in sb["scenes"]]
    checks.append(_check("editorial", "Los escenarios cambian con la historia", len(set(sets)) > 1 or len(sets) <= 2,
                         " → ".join(sets)))
    checks.append(_check("editorial", "Dentro del presupuesto", spent <= profile.limits.max_usd_per_video,
                         f"{spent:.2f} de {profile.limits.max_usd_per_video:.2f} USD"))
    return {"passed": all(c["ok"] for c in checks), "checks": checks, "human": HUMAN, "duration": info["duration"],
            "spent_usd": round(spent, 4), "demo": demo}


def report(profile: AnimationProfile, title: str, result: dict) -> str:
    lines = [f"# Control de calidad · {profile.name}", "", f"**{title}**", "",
             "Resultado: " + ("pasa las comprobaciones automáticas" if result["passed"] else "NO pasa las comprobaciones automáticas"), ""]
    group = None
    for c in result["checks"]:
        if c["group"] != group:
            group = c["group"]
            lines += ["", f"## {group.capitalize()}"]
        lines.append(f"- [{'x' if c['ok'] else ' '}] {c['name']}: {c['detail']}")
    lines += ["", "## Para quien aprueba"] + [f"- {h}" for h in result["human"]]
    return "\n".join(lines) + "\n"
