"""The animation engine (backend/animation) and its asset library (animator/): everything that does
not need a paid call or the network. The tests that draw with the real Godot are skipped when it
is not installed; the full end-to-end episode also needs ANIMATION_E2E=1 (it takes minutes)."""
import asyncio
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from animation import analytics, compose, demo, godot, lipsync, pipeline, plan, quality, research, script, simulations, storyboard, voice
from animation.db import APROBADO, ERROR, LISTO, PENDIENTE, PUBLICADO, Cost, Episode, ErrorLog, Event, Publication, open_db
from animation.godot import Cancelled, RenderFailed
from animation.ledger import BudgetExceeded, Ledger
from animation.library import ANIMATOR, LibraryError, default_library, load_library
from animation.profile import load_profile
from animation.publish import PublishRejected, publish
from animation.research import NeedsReview
from animation.server import create_app
from animation.shared.settings import Voice
from animation.shared.sources import SourceDoc
from animation.shared.remotion import RenderOutput

GODOT = godot.find_godot()
needs_godot = pytest.mark.skipif(not (GODOT and shutil.which("ffmpeg")), reason="Godot 4 o FFmpeg no están instalados")


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setenv("ANIMATION_DATA_DIR", str(tmp_path / "channels"))
    return load_profile("curiolab")


@pytest.fixture
def db(profile):
    session = open_db(profile.data_dir)
    yield session
    session.close()


@pytest.fixture
def lib():
    return default_library()


def demo_board() -> storyboard.Storyboard:
    return storyboard.parse(demo.storyboard())


def tone_voices(sb, lib, cache: Path) -> dict:
    out = {}
    for si, bi, beat in sb.lines():
        r = voice.speak(Voice(provider="tono", voice_id=beat.speaker), beat.text, cache)
        out[f"{si}:{bi}"] = {"speaker": beat.speaker, "path": str(r["path"]), "duration": r["duration"], "words": r["words"],
                             "mouth": lipsync.mouth_track(r["path"], lib.fps, r["words"])}
    return out


# ---------------------------------------------------------------- channels kept apart

def test_profile_is_its_own_channel_with_its_own_data(profile, tmp_path):
    assert profile.name == "CURIOLAB" and profile.cast == ["dra_nova", "leo"]
    assert profile.data_dir == tmp_path / "channels" / "curiolab"
    assert profile.publishing.approval == "manual" and profile.publishing.privacy == "private"
    assert set(profile.voices) == {"dra_nova", "leo"} and profile.limits.max_usd_per_video > 0
    # A profile that is not an animated channel's is refused, and so is one with unknown fields.
    other = tmp_path / "profiles"
    other.mkdir()
    good = json.loads((Path(__file__).resolve().parents[1] / "channels" / "curiolab.json").read_text(encoding="utf-8"))
    (other / "documental.json").write_text(json.dumps({**good, "key": "documental", "engine": "documentary"}), encoding="utf-8")
    (other / "raro.json").write_text(json.dumps({**good, "key": "raro", "autopublish": True}), encoding="utf-8")
    for key in ("documental", "raro"):
        with pytest.raises(Exception):
            load_profile(key, other)
    with pytest.raises(FileNotFoundError):
        load_profile("no_existe")


def test_each_channel_keeps_its_own_database_and_files(profile, db, tmp_path):
    db.add(Episode(topic="x"))
    db.commit()
    assert (profile.data_dir / "animation.db").is_file()
    other = profile.model_copy(update={"key": "otro_canal"})
    assert other.data_dir == tmp_path / "channels" / "otro_canal" and other.data_dir != profile.data_dir
    with open_db(other.data_dir) as other_db:
        assert other_db.query(Episode).count() == 0 and db.query(Episode).count() == 1


# ---------------------------------------------------------------- library and registry

def test_library_registers_what_the_spec_asks_and_every_script_exists(lib):
    assert set(lib.actions) >= {"idle", "talk", "blink", "walk", "point", "surprised", "happy", "confused", "thinking",
                                "look_up", "look_left", "float"}
    assert lib.missing_files() == []
    assert set(lib.sets) >= {"laboratorio", "espacio", "exterior"}
    assert set(lib.props) >= {"tierra", "luna", "sol", "planeta", "atomo", "molecula_agua", "flecha_fuerza", "particulas",
                              "regla", "linea_tiempo", "grafico", "matraz", "microscopio"}
    for cid, c in lib.characters.items():
        assert c["id"] == cid and c["voice"] and c["appearance"]["height"] > 0
        assert set(c["actions"]) <= set(lib.actions) and set(c["emotions"]) <= set(lib.emotions)
        assert c["personality"] and c["role"] and c["restrictions"]


def test_a_new_action_is_a_script_and_a_manifest_entry_and_missing_files_are_reported(tmp_path):
    root = tmp_path / "animator"
    shutil.copytree(ANIMATOR, root, ignore=shutil.ignore_patterns(".godot"))
    manifest = json.loads((root / "library" / "manifest.json").read_text(encoding="utf-8"))
    manifest["actions"]["wave"] = {"script": "res://actions/wave.gd", "desc": "saluda"}
    (root / "library" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    grown = load_library(root)
    assert "wave" in grown.actions and grown.missing_files() == ["res://actions/wave.gd"]
    assert grown.fingerprint != load_library(ANIMATOR).fingerprint
    (root / "actions" / "wave.gd").write_text('extends "res://core/action.gd"\n', encoding="utf-8")
    assert load_library(root).missing_files() == []
    (root / "library" / "characters" / "leo.json").unlink()
    with pytest.raises(LibraryError):
        load_library(root)


# ---------------------------------------------------------------- storyboard: schema and validation

def test_demo_storyboard_is_valid(lib):
    sb = demo_board()
    known = research.support_ids(demo.sheet())
    assert storyboard.repair(sb, lib) == [] and storyboard.validate(sb, lib, known, (95, 130)) == []
    assert sb.schema_version == 1 and len(sb.lines()) == len(demo.LINES)


@pytest.mark.parametrize("change, expected", [
    (lambda d: d["scenes"][0].update(set="volcan"), "escenario no registrado"),
    (lambda d: d["scenes"][0]["props"].append({"uid": "x", "prop": "dragon", "at": "aire", "params": {}}), "objeto no registrado"),
    (lambda d: d["scenes"][0]["beats"][0].update(action="backflip"), "acción no registrada"),
    (lambda d: d["scenes"][0]["cast"][0].update(at="techo"), "no es un sitio para personajes"),
    (lambda d: d["scenes"][0]["props"][0].update(at="luna"), "no es un sitio para objetos"),
    (lambda d: d["scenes"][0]["beats"][0].update(speaker="capitan_x"), "no está en el reparto"),
    (lambda d: d["scenes"][0]["beats"][0].update(camera_target="fantasma"), "la cámara apunta"),
    (lambda d: d["scenes"][0]["beats"][0].update(effects=["explosion"]), "efecto no registrado"),
    (lambda d: d["scenes"][0]["beats"][0].update(supports=["h99"]), "no está en la ficha"),
    (lambda d: d["scenes"][0]["beats"][0].update(action="walk", walk_to=""), "caminar necesita un destino"),
    (lambda d: d["scenes"][2].update(label=""), "lleva rótulo"),
    (lambda d: d["scenes"][3]["beats"][0].update(effects=[]), "termina con la gravedad apagada"),
    (lambda d: d["scenes"][0]["beats"][0]["reactions"].append({"character": "leo", "action": "walk", "emotion": "happy"}), "no puede ser caminar"),
])
def test_storyboard_naming_anything_unregistered_is_rejected(lib, change, expected):
    data = demo.storyboard()
    change(data)
    problems = storyboard.validate(storyboard.parse(data), lib, research.support_ids(demo.sheet()))
    assert any(expected in p for p in problems), problems


def test_storyboard_shape_is_strict_and_harmless_slips_are_repaired(lib):
    data = demo.storyboard()
    data["scenes"][0]["beats"][0]["gdscript"] = "OS.execute('calc')"       # no field carries code
    with pytest.raises(storyboard.StoryboardRejected):
        storyboard.parse(data)
    with pytest.raises(storyboard.StoryboardRejected):
        storyboard.parse({**demo.storyboard(), "schema_version": 2})
    data = demo.storyboard()
    data["scenes"][0]["beats"][0].update(emotion="eufórico", camera="dolly_zoom")
    data["scenes"][1]["beats"][0]["seconds"] = 40
    sb = storyboard.parse(data)
    notes = storyboard.repair(sb, lib)
    assert len(notes) == 3 and sb.scenes[0].beats[0].emotion == "neutral" and sb.scenes[0].beats[0].camera == "static"
    assert sb.scenes[1].beats[0].seconds == 6.0 and storyboard.validate(sb, lib) == []


def test_schema_given_to_claude_only_offers_registered_ids(lib):
    schema = storyboard.staging_schema(lib, ["dra_nova", "leo"])
    beat = schema["properties"]["scenes"]["items"]["properties"]["beats"]["items"]["properties"]
    scene = schema["properties"]["scenes"]["items"]["properties"]
    assert beat["action"]["enum"] == list(lib.actions) and beat["camera"]["enum"] == list(lib.cameras)
    assert beat["effects"]["items"]["enum"] == list(lib.effects) and scene["set"]["enum"] == list(lib.sets)
    assert scene["props"]["items"]["properties"]["prop"]["enum"] == list(lib.props)
    assert scene["cast"]["items"]["properties"]["character"]["enum"] == ["dra_nova", "leo"]
    # Structured outputs need every object closed.
    def closed(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
            for value in node.values():
                closed(value)
        elif isinstance(node, list):
            for value in node:
                closed(value)
    closed(schema)


def test_staging_takes_its_words_from_the_script_not_from_the_model():
    sc = demo.script()
    staging = {"scenes": [{"id": "s1", "set": "laboratorio", "label": "", "cast": [], "props": [], "beats": [
        {"line": i, "seconds": 0, "actor": "", "emotion": "neutral", "action": "talk", "walk_to": "", "look_at": "", "camera": "static",
         "camera_target": "", "effects": [], "reactions": [], "science_event": ""} for i in range(len(sc["lines"]))]}]}
    assert storyboard.lines_in_order(staging, len(sc["lines"])) == []
    doc = storyboard.assemble(staging, sc, "ep", ["dra_nova", "leo"], [], 60)
    assert [b["text"] for b in doc["scenes"][0]["beats"]] == [line["text"] for line in sc["lines"]]
    assert doc["scenes"][0]["beats"][4]["supports"] == ["h1"]
    staging["scenes"][0]["beats"].pop(3)
    assert storyboard.lines_in_order(staging, len(sc["lines"]))


# ---------------------------------------------------------------- science: models and sources

def test_simulation_results_come_from_the_formula():
    r = simulations.run("separacion_sin_gravedad", {"seconds": 5, "latitude": 0})
    # ½·ω²·R·t² with ω = 7.2921e-5 rad/s and R = 6 378 137 m.
    assert r["results"]["gap_m"] == pytest.approx(0.5 * 7.2921159e-5 ** 2 * 6378137 * 25, abs=1e-3) == pytest.approx(0.424, abs=1e-3)
    assert r["results"]["ground_speed_kmh"] == 1674 and r["exactness"] == "simplificado" and len(r["assumptions"]) >= 3
    assert "42 centímetros" in r["statement"] and "simplificado" in r["statement"]
    assert simulations.run("separacion_sin_gravedad", {"seconds": 5, "latitude": 60})["results"]["gap_m"] == pytest.approx(0.106, abs=2e-3)
    assert simulations.run("caida_libre", {"height": 4.9, "world": "tierra"})["results"]["seconds"] == pytest.approx(1.0, abs=0.01)
    assert simulations.run("peso_en_otro_mundo", {"mass": 60, "world": "luna"})["results"]["scale_kg"] == pytest.approx(9.9, abs=0.1)
    for bad in (("teletransporte", {}), ("separacion_sin_gravedad", {"seconds": 9999}), ("caida_libre", {"world": "pluton"}),
                ("caida_libre", {"speed": 3})):
        with pytest.raises(simulations.SimulationError):
            simulations.run(*bad)


async def test_fact_sheet_keeps_only_quoted_facts_and_computes_the_simulation_itself(profile, db, monkeypatch):
    docs = [SourceDoc("https://a.example/g", "Gravedad", "a.example", "La gravedad mantiene la atmósfera unida al planeta y a los océanos en su sitio. " * 20),
            SourceDoc("https://b.example/r", "Rotación", "b.example", "En el ecuador la superficie de la Tierra se mueve a unos 1670 kilómetros por hora debido a la rotación. " * 20)]
    facts = [{"text": f"La gravedad retiene la atmósfera ({i}).", "source": 0, "quote": "La gravedad mantiene la atmósfera unida al planeta"} for i in range(3)]
    facts += [{"text": f"El ecuador gira a 1670 km/h ({i}).", "source": 1, "quote": "la superficie de la Tierra se mueve a unos 1670 kilómetros por hora"} for i in range(3)]
    facts.append({"text": "La gravedad viaja a 3 km/s.", "source": 0, "quote": "la gravedad viaja a tres kilómetros por segundo"})   # not in the source

    async def fake_ask(model, system, user, schema, ledger, detail, effort="medium"):
        ledger.add("claude", 0.01, detail)
        return {"facts": facts, "answer": "No saldríamos disparados.", "assumptions": ["Solo desaparece la gravedad."], "unknowns": [],
                "simulation": "separacion_sin_gravedad",
                "simulation_inputs": {"seconds": 5, "latitude": 0, "height": 0, "mass": 0, "world": ""}}

    async def fake_read(urls, http=None):
        return docs

    monkeypatch.setattr(research.llm, "ask", fake_ask)
    monkeypatch.setattr(research, "read_pages", fake_read)
    ledger = Ledger(db, None, 2.0)
    sheet = await research.investigate(profile, "¿Y si la gravedad desapareciera?", ledger, urls=["https://a.example/g", "https://b.example/r"])
    assert len(sheet["facts"]) == 6 and len(sheet["dropped"]) == 1 and sheet["dropped"][0]["problem"] == "la cita no está en la fuente"
    assert sheet["simulations"][0]["results"]["gap_m"] == pytest.approx(0.424, abs=1e-3)
    assert research.support_ids(sheet) == {"h1", "h2", "h3", "h4", "h5", "h6", "sim:separacion_sin_gravedad"}
    assert ledger.spent() == pytest.approx(0.01)
    # Too thin to be an episode: it stops before a script is written.
    facts[:] = facts[:2]
    with pytest.raises(NeedsReview):
        await research.investigate(profile, "¿Y si…?", ledger, urls=["https://a.example/g", "https://b.example/r"])
    docs.pop()
    with pytest.raises(NeedsReview):
        await research.investigate(profile, "¿Y si…?", ledger, urls=["https://a.example/g"])


async def test_sources_are_ranked_balanced_and_searched_again_when_thin(profile, db, monkeypatch):
    assert research.tier("science.nasa.gov") == "institucional" and research.tier("public.nrao.edu") == "institucional"
    assert research.tier("physics.mit.edu") == "institucional" and research.tier("britannica.com") == "referencia"
    assert research.tier("scienceabc.com") == "divulgación"
    # A page without paragraph markup (many agency pages) is read from its body, not thrown away.
    pages = {"https://nasa.gov/plain": "<html><title>Gravity</title><body><nav>menu</nav><div>" + "Gravity holds the atmosphere. " * 40 + "</div></body></html>",
             "https://blog.example/short": "<html><body><p>Nada.</p></body></html>"}
    transport = research.httpx.MockTransport(lambda request: research.httpx.Response(200, text=pages[str(request.url)]) if str(request.url) in pages
                                             else research.httpx.Response(410))
    async with research.httpx.AsyncClient(transport=transport) as http:
        docs = await research.read_pages([*pages, "https://gone.example/x"], http)
    assert [d.publisher for d in docs] == ["nasa.gov"] and "menu" not in docs[0].text and len(docs[0].text) > 600

    # One popular site found: a second search is made, told what failed; institutions go first.
    searches = []

    async def fake_find(topic, ledger, system="", label=""):
        searches.append(topic)
        return ["https://pop.example/a", "https://dead.example/b"] if len(searches) == 1 else ["https://nasa.gov/g", "https://uni.edu/r"]

    async def fake_read(urls, http=None):
        return [SourceDoc(u, "t", research.urlparse(u).netloc, "x" * 700) for u in urls if "dead" not in u]

    monkeypatch.setattr(research, "find_sources", fake_find)
    monkeypatch.setattr(research, "read_pages", fake_read)
    docs = await research.gather_sources("¿Por qué el cielo es azul?", Ledger(db, None, 2.0))
    assert len(searches) == 2 and "dead.example" in searches[1] and [d.publisher for d in docs] == ["nasa.gov", "uni.edu", "pop.example"]

    # No source carries more than its share of the facts, however much it has to say.
    facts = [{"text": f"Dato popular {i}.", "source": 2, "quote": "x" * 30} for i in range(9)] + \
            [{"text": "Dato de agencia.", "source": 0, "quote": "x" * 30}, {"text": "Dato de universidad.", "source": 1, "quote": "x" * 30}]

    async def fake_ask(model, system, user, schema, ledger, detail, effort="medium"):
        return {"facts": facts, "answer": "r", "assumptions": [], "unknowns": [], "simulation": "",
                "simulation_inputs": {"seconds": 0, "latitude": 0, "height": 0, "mass": 0, "world": ""}}

    monkeypatch.setattr(research.llm, "ask", fake_ask)
    monkeypatch.setattr(research, "verify_claims", lambda claims, docs: ([{**c, "id": i} for i, c in enumerate(claims, 1)], []))
    searches.clear()
    sheet = await research.investigate(profile, "¿Por qué el cielo es azul?", Ledger(db, None, 2.0))
    per_source = [sum(f["source"] == i for f in sheet["facts"]) for i in range(3)]
    assert per_source == [1, 1, 6] and len(sheet["dropped"]) == 3 and sheet["facts"][0]["id"] == "h1"
    assert {f["tier"] for f in sheet["facts"]} == {"institucional", "divulgación"} and sheet["sources"][0]["tier"] == "institucional"
    assert "[fuente 2, divulgación]" in research.sheet_text(sheet)


def test_a_script_resting_on_one_source_is_sent_back(profile):
    sheet = demo.sheet()
    sheet["facts"] = [{**f, "source": i % 2, "quote": "cita"} for i, f in enumerate(sheet["facts"])]      # h1→0, h2→1, h3→0
    sheet["sources"] = [{"id": 0, "url": "u0", "title": "", "publisher": "nasa.gov", "tier": "institucional"},
                        {"id": 1, "url": "u1", "title": "", "publisher": "blog.example", "tier": "divulgación"}]
    sc = demo.script()
    assert script.script_problems(sc, sheet, profile, ["dra_nova", "leo"]) == []          # cites h1, h2 and h3
    for line in sc["lines"]:
        line["supports"] = [r for r in line["supports"] if r != "h2"]
    assert any("una sola fuente" in p for p in script.script_problems(sc, sheet, profile, ["dra_nova", "leo"]))


def test_script_checks_catch_invented_figures_and_citations(profile, lib):
    sheet, sc = demo.sheet(), demo.script()
    assert script.script_problems(sc, sheet, profile, ["dra_nova", "leo"]) == []
    sc["lines"][4] = {"speaker": "dra_nova", "text": "Subirías 900 metros en un segundo.", "supports": ["h7"]}
    problems = script.script_problems(sc, sheet, profile, ["dra_nova", "leo"])
    assert any("cifra 900" in p for p in problems) and any("'h7'" in p for p in problems)
    sc = demo.script()
    sc["lines"] = sc["lines"][:3]
    assert any("palabras" in p for p in script.script_problems(sc, sheet, profile, ["dra_nova", "leo"]))


async def test_write_script_retries_with_the_problems_and_then_gives_up(profile, db, lib, monkeypatch):
    calls = []

    async def fake_ask(model, system, user, schema, ledger, detail, effort="medium"):
        calls.append((detail, user))
        if detail.startswith("guion:revisión"):
            return {"problems": []}
        good = demo.script()
        if len([c for c in calls if c[0].startswith("guion:intento")]) == 1:
            good["lines"][4]["text"] = "Subirías 900 metros en un segundo."
        return good

    monkeypatch.setattr(script.llm, "ask", fake_ask)
    ledger = Ledger(db, None, 2.0)
    out = await script.write_script(profile, lib, ["dra_nova", "leo"], demo.sheet(), ledger)
    assert out["checks"]["attempts"] == 2 and "cifra 900" in calls[1][1] and len(out["hooks"]) == 3
    # A script that repeats an earlier episode is not original work.
    calls.clear()
    with pytest.raises(NeedsReview):
        await script.write_script(profile, lib, ["dra_nova", "leo"], demo.sheet(), ledger, previous=[script.script_text(demo.script())])


async def test_stage_rejects_a_storyboard_that_keeps_naming_missing_things(profile, db, lib, monkeypatch):
    sc = demo.script()
    profile.format.min_scenes = 1

    def staging(prop: str) -> dict:
        beat = {"seconds": 0, "actor": "", "emotion": "neutral", "action": "talk", "walk_to": "", "look_at": "", "camera": "static",
                "camera_target": "", "effects": [], "reactions": [], "science_event": ""}
        return {"scenes": [{"id": "s1", "set": "laboratorio", "label": "",
                            "cast": [{"character": "dra_nova", "at": "izquierda", "facing": "right"}, {"character": "leo", "at": "derecha", "facing": "left"}],
                            "props": [{"uid": "cosa", "prop": prop, "at": "mesa_1", "params": {"label": "", "scale": None}}],
                            "beats": [{**beat, "line": i} for i in range(len(sc["lines"]))]}]}

    answers = [staging("unicornio"), staging("matraz")]

    async def fake_ask(model, system, user, schema, ledger, detail, effort="medium"):
        return answers.pop(0)

    monkeypatch.setattr(script.llm, "ask", fake_ask)
    document, _ = await script.stage(profile, lib, ["dra_nova", "leo"], sc, demo.sheet(), Ledger(db, None, 2.0), "ep-1")
    assert document["scenes"][0]["props"][0] == {"uid": "cosa", "prop": "matraz", "at": "mesa_1", "params": {
        "label": None, "scale": None, "color": None, "angle": None, "length": None, "values": None, "marks": None}}
    answers[:] = [staging("unicornio"), staging("dragon")]
    with pytest.raises(storyboard.StoryboardRejected) as e:
        await script.stage(profile, lib, ["dra_nova", "leo"], sc, demo.sheet(), Ledger(db, None, 2.0), "ep-1")
    assert "objeto no registrado: dragon" in e.value.problems[0]
    # Too few scenes for the channel's format is a problem too.
    profile.format.min_scenes = 3
    answers[:] = [staging("matraz"), staging("matraz")]
    with pytest.raises(storyboard.StoryboardRejected, match="hay 1 escenas"):
        await script.stage(profile, lib, ["dra_nova", "leo"], sc, demo.sheet(), Ledger(db, None, 2.0), "ep-1")


# ---------------------------------------------------------------- voice and lip sync

def test_voice_is_cached_retried_and_stops_on_a_provider_that_keeps_failing(tmp_path, monkeypatch):
    monkeypatch.setattr(voice.time, "sleep", lambda s: None)
    calls = []

    def flaky(v, text, out_dir, name):
        calls.append(text)
        if len(calls) < 3:
            raise RuntimeError("503 from provider")
        return {**voice._tone(v, text, out_dir, name), "usd": 0.012}

    v = Voice(provider="elevenlabs", voice_id="abc")
    first = voice.speak(v, "Hola,  mundo.", tmp_path, attempts=3, providers={"elevenlabs": flaky})
    assert first["usd"] == 0.012 and not first["cached"] and len(first["failures"]) == 2 and len(first["words"]) == 2
    again = voice.speak(v, "Hola, mundo.", tmp_path, attempts=3, providers={"elevenlabs": flaky})
    assert again["cached"] and again["usd"] == 0.0 and len(calls) == 3 and again["path"] == first["path"]
    assert voice.cached(v, "Hola, mundo.", tmp_path) and not voice.cached(v, "Otra línea.", tmp_path)
    # Another voice saying the same words is another recording.
    assert voice.line_key(v, "Hola") != voice.line_key(Voice(provider="elevenlabs", voice_id="xyz"), "Hola")

    def dead(v, text, out_dir, name):
        raise RuntimeError("401 invalid api key")

    with pytest.raises(voice.VoiceError, match="falló 2 veces"):
        voice.speak(v, "Nunca sale.", tmp_path, attempts=2, providers={"elevenlabs": dead})
    assert not list(tmp_path.glob("tmp-*"))
    with pytest.raises(voice.VoiceError, match="proveedor"):
        voice.speak(Voice(provider="otra", voice_id="x"), "Hola.", tmp_path)


def test_mouth_follows_the_voice_and_closes_between_sentences(tmp_path):
    r = voice.speak(Voice(provider="tono", voice_id="x"), "Hola amigos. Esto es una prueba.", tmp_path)
    fps = 30
    mouth = lipsync.mouth_track(r["path"], fps, r["words"])
    assert len(mouth) == pytest.approx(r["duration"] * fps, abs=1.5) and set(mouth) <= {0, 1, 2, 3} and max(mouth) == 3
    pause = int((r["words"][1]["end"] + 0.13) * fps)      # the gap after "amigos."
    assert mouth[pause] == 0 and mouth[0] == 0 and mouth[-1] == 0
    for w in r["words"]:
        mid = int((w["start"] + w["end"]) / 2 * fps)
        assert mouth[mid] >= 1
    # No state lasts a single frame.
    assert all(not (mouth[i - 1] == mouth[i + 1] != mouth[i]) for i in range(1, len(mouth) - 1))
    # Without word times it still works from the loudness alone.
    assert max(lipsync.mouth_track(r["path"], fps)) == 3


def test_mouth_shapes_follow_the_sounds_of_the_words(tmp_path):
    shapes = lambda w: [s for s, _ in lipsync.word_shapes(w)]
    assert shapes("mamá") == [0, 3, 0, 3] and shapes("Hola,") == [4, 1, 3]              # h is silent, punctuation ignored
    assert shapes("¿Qué") == [1, 2] and shapes("guitarra") == [1, 5, 1, 3, 1, 1, 3]       # que / gui: the u is not said
    assert shapes("muy") == [0, 4, 5] and shapes("año") == [3, 1, 4] and shapes("42") == [1]
    assert sum(share for _, share in lipsync.word_shapes("gravedad")) == pytest.approx(1.0)
    r = voice.speak(Voice(provider="tono", voice_id="x"), "Papá mira un oso. Sí.", tmp_path)
    fps = 30
    track = lipsync.track(r["path"], fps, r["words"])
    assert set(track) <= {0, 1, 2, 3, 4, 5} and {4, 5} & set(track)
    oso, si = r["words"][3], r["words"][4]
    assert 4 in track[int(oso["start"] * fps):int(oso["end"] * fps) + 1] and 5 in track[int(si["start"] * fps):int(si["end"] * fps) + 1]
    assert track[0] == 0 and track[-1] == 0 and track[int((oso["end"] + 0.12) * fps)] == 0     # shut in the pauses
    assert all(not (track[i - 1] == track[i + 1] != track[i]) for i in range(1, len(track) - 1))
    assert lipsync.track(r["path"], fps, []) == lipsync.mouth_track(r["path"], fps)            # no word times: loudness


# ---------------------------------------------------------------- timing

def test_scenes_last_what_their_audio_lasts_and_lines_never_overlap(lib, tmp_path):
    sb = demo_board()
    voices = tone_voices(sb, lib, tmp_path)
    sims = {s["id"]: s for s in demo.sheet()["simulations"]}
    timeline = plan.compile_episode(sb, lib, voices, sims)
    assert [s["id"] for s in timeline["scenes"]] == ["s1", "s2", "s3", "s4"]
    assert timeline["duration"] == pytest.approx(sum(s["duration"] for s in timeline["scenes"]), abs=1e-3)
    for scene, model in zip(timeline["scenes"], sb.scenes):
        events = scene["plan"]["events"]
        assert all(e["type"] in ("action", "emotion", "mouth", "look", "face", "camera", "effect", "base") for e in events)
        assert all(e["t"] < scene["duration"] for e in events)
        # Whole frames, and at least as long as everything said and done in it.
        assert scene["duration"] * lib.fps == pytest.approx(round(scene["duration"] * lib.fps))
        spoken = sum(voices[f"{sb.scenes.index(model)}:{i}"]["duration"] for i, b in enumerate(model.beats) if b.text)
        assert scene["duration"] > spoken + sum(b.seconds for b in model.beats if not b.text)
    lines = timeline["lines"]
    assert len(lines) == 12 and all(a["start"] + a["duration"] < b["start"] for a, b in zip(lines, lines[1:]))
    assert len(timeline["words"]) == sb.words() and timeline["words"][0]["word"] == "¿Qué"
    # Each mouth track starts with its line.
    s1 = timeline["scenes"][0]["plan"]
    mouths = [e for e in s1["events"] if e["type"] == "mouth"]
    assert [round(m["t"], 2) for m in mouths] == [round(l["start"], 2) for l in lines[:3]]
    # The simulation draws the engine's numbers, whatever the storyboard said.
    sim = timeline["scenes"][2]["plan"]["props"][0]
    assert sim["params"]["accel"] == pytest.approx(0.0339, abs=1e-4) and sim["params"]["seconds"] == 5
    # Gravity went off in s2 and returns in s4: s4 opens with everything already floating.
    s2, s4 = timeline["scenes"][1]["plan"], timeline["scenes"][3]["plan"]
    assert s2["warmup"] == 0 and s4["warmup"] == plan.WARMUP
    assert {"t": -plan.WARMUP, "type": "base", "character": "leo", "action": "float"} in s4["events"]
    assert any(e["type"] == "effect" and e["effect"] == "gravity_on" and e["t"] > 0 for e in s4["events"])


def test_a_retake_changes_only_that_scene_and_an_engine_change_changes_all(lib, tmp_path):
    sb = demo_board()
    voices = tone_voices(sb, lib, tmp_path)
    sims = {s["id"]: s for s in demo.sheet()["simulations"]}
    base = [s["key"] for s in plan.compile_episode(sb, lib, voices, sims)["scenes"]]
    assert base == [s["key"] for s in plan.compile_episode(sb, lib, voices, sims)["scenes"]]        # deterministic
    retaken = [s["key"] for s in plan.compile_episode(sb, lib, voices, sims, retakes={"s2": 1})["scenes"]]
    assert [a == b for a, b in zip(base, retaken)] == [True, False, True, True]
    other = type(lib)(**{**lib.__dict__, "fingerprint": "otro"})
    assert all(a != b for a, b in zip(base, [s["key"] for s in plan.compile_episode(sb, other, voices, sims)["scenes"]]))


# ---------------------------------------------------------------- Godot

def test_render_fails_clearly_without_godot_or_with_a_broken_one(lib, tmp_path, monkeypatch):
    scene_plan = {"scene": "s1", "fps": 30, "duration": 1.0, "set": "laboratorio", "characters": [], "props": [], "events": []}
    monkeypatch.setattr(godot, "find_godot", lambda: None)
    with pytest.raises(RenderFailed, match="GODOT_BIN"):
        godot.render_scene(scene_plan, "k1", tmp_path, lib)
    # Something that runs but is not Godot: no result file, no video.
    with pytest.raises(RenderFailed, match="no pudo dibujar"):
        godot.render_scene(scene_plan, "k1", tmp_path, lib, godot=sys.executable)
    assert not list(tmp_path.glob("tmp-*")) and not list(tmp_path.glob("*.mp4"))
    with pytest.raises(RenderFailed, match="no se pudo ejecutar"):
        godot.render_scene(scene_plan, "k1", tmp_path, lib, godot=str(tmp_path / "no-existe.exe"))
    # A scene already drawn with this key is not drawn again (Godot is not even looked for).
    (tmp_path / "s1-k2.mp4").write_bytes(b"video")
    assert godot.render_scene(scene_plan, "k2", tmp_path, lib) == (tmp_path / "s1-k2.mp4", True)
    # A library with a script missing never reaches Godot.
    broken = type(lib)(**{**lib.__dict__, "actions": {**lib.actions, "wave": {"script": "res://actions/wave.gd", "desc": ""}}})
    with pytest.raises(RenderFailed, match="wave.gd"):
        godot.render_scene(scene_plan, "k3", tmp_path, broken, godot=sys.executable)


@needs_godot
def test_godot_draws_a_scene_to_an_mp4_of_the_exact_length(lib, tmp_path):
    sb = storyboard.parse({**demo.storyboard(), "scenes": [demo.storyboard()["scenes"][1]]})
    sb.scenes[0].beats = sb.scenes[0].beats[:1] + [storyboard.Beat(seconds=0.6, effects=["gravity_on"], action="idle")]
    timeline = plan.compile_episode(sb, lib, {}, {}, font=pipeline.FONT)
    scene = timeline["scenes"][0]
    path, cached = godot.render_scene(scene["plan"], scene["key"], tmp_path, lib, godot=GODOT)
    info = quality.probe(path)
    assert not cached and (info["width"], info["height"], info["fps"]) == (1080, 1920, 30.0)
    assert info["duration"] == pytest.approx(scene["duration"], abs=0.04) and not quality.black_spans(path)
    assert godot.render_scene(scene["plan"], scene["key"], tmp_path, lib, godot=GODOT) == (path, True)


@needs_godot
def test_godot_refuses_a_plan_that_names_something_unregistered(lib, tmp_path):
    scene_plan = {"version": 1, "scene": "s1", "fps": 30, "duration": 0.5, "seed": 1, "set": "laboratorio", "font": "", "characters": [],
                  "props": [{"uid": "x", "id": "dragon", "x": 100, "y": 100, "params": {}}],
                  "events": [{"t": 0, "type": "effect", "effect": "explosion"}]}
    with pytest.raises(RenderFailed) as e:
        godot.render_scene(scene_plan, "bad", tmp_path, lib, godot=GODOT)
    assert "props no registrado: dragon" in str(e.value) and "efecto no registrado: explosion" in str(e.value)


# ---------------------------------------------------------------- the pipeline (drawing and editing faked)

class Fakes:
    """Godot and Remotion replaced by files, so the pipeline's own behaviour is what is tested."""

    def __init__(self, monkeypatch):
        self.rendered: list[str] = []
        self.composed = 0
        self.fail_scene: str | None = None
        self.cancel_at: str | None = None
        monkeypatch.setattr(godot, "render_scene", self.render_scene)
        monkeypatch.setattr(compose, "render", self.compose)
        monkeypatch.setattr(quality, "check", self.check)

    def render_scene(self, scene_plan, key, out_dir, lib, godot_bin=None, cancelled=None, timeout=0):
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{scene_plan['scene']}-{key}.mp4"
        if path.is_file():
            return path, True
        if self.cancel_at == scene_plan["scene"] and cancelled is not None:
            assert not cancelled()
            con = sqlite3.connect(out_dir.parents[2] / "animation.db")
            con.execute("update episodes set cancel_requested = 1")
            con.commit()
            con.close()
            assert cancelled()
            raise Cancelled()
        if self.fail_scene == scene_plan["scene"]:
            raise RenderFailed(f"Godot no pudo dibujar la escena {scene_plan['scene']}: se cerró")
        path.write_bytes(b"mp4")
        self.rendered.append(scene_plan["scene"])
        return path, False

    async def compose(self, props, media, dialogue, out_dir, renderer=None):
        self.composed += 1
        assert dialogue.is_file() and all(Path(p).is_file() for p in media.values())
        (out_dir / "short.mp4").write_bytes(b"final")
        (out_dir / "miniatura.png").write_bytes(b"png")
        return RenderOutput(out_dir / "short.mp4", out_dir / "miniatura.png")

    def check(self, profile, video, sb, sheet, timeline, videos, spent, previous=None, tail=0.0):
        return {"passed": True, "checks": [], "human": [], "duration": timeline["duration"] + tail, "spent_usd": spent,
                "demo": bool(sheet.get("demo"))}


async def test_demo_episode_runs_every_stage_and_stops_at_review(profile, db, monkeypatch):
    fakes = Fakes(monkeypatch)
    ep = pipeline.new_episode(db, profile, mode="demo")
    assert ep.status == PENDIENTE
    done = await pipeline.produce(profile, db, ep.id)
    assert done.status == LISTO and done.title == demo.TOPIC and Path(done.output_path).is_file()
    assert fakes.rendered == ["s1", "s2", "s3", "s4"] and fakes.composed == 1
    folder = pipeline.episode_dir(profile, ep.id)
    assert {"investigacion.json", "guion.json", "storyboard.json", "plan_s1.json", "props.json", "dialogo.wav", "calidad.md"} <= {p.name for p in folder.iterdir()}
    # Real progress: one event per line recorded and per scene drawn, in the order of the stages.
    events = db.query(Event).filter(Event.episode_id == ep.id).order_by(Event.id).all()
    stages = list(dict.fromkeys(e.stage for e in events))
    assert stages == [s for s, _ in pipeline.STAGES] + [LISTO]
    assert [(e.done, e.total) for e in events if e.stage == "GENERANDO_VOZ" and e.total] == [(i, 12) for i in range(1, 13)]
    assert [(e.done, e.total) for e in events if e.stage == "ANIMANDO" and e.total] == [(i, 4) for i in range(1, 5)]
    # The demo never reaches a paid service, and nothing was published.
    assert db.query(Cost).count() == 0 and db.query(Publication).count() == 0
    # The composition gets every scene, the captions and the labels.
    props = json.loads((folder / "props.json").read_text(encoding="utf-8"))
    assert len(props["scenes"]) == 4 and props["scenes"][2]["label"] == "Simulación simplificada" and len(props["words"]) == 109
    assert props["speakers"]["dra_nova"]["name"] == "Dra. Nova" and props["scenes"][1]["start"] == pytest.approx(props["scenes"][0]["duration"], abs=1e-3)
    assert {s["src"] for s in props["shots"]} == {"sonido/pop.wav", "sonido/flotar.wav", "sonido/caer.wav", "sonido/cierre.wav"}
    # The panel reads the finished episode: script, storyboard, resources used, scenes and costs.
    with TestClient(create_app(profile, start_worker=False)) as client:
        seen = client.get(f"/api/episodes/{ep.id}").json()
        assert seen["status"] == LISTO and seen["progress"]["percent"] == 100 and seen["has_video"] and seen["costs"] == []
        assert seen["resources"]["sets"] == ["laboratorio", "simulacion"] and "sim_tangente" in seen["resources"]["props"]
        assert seen["resources"]["characters"] == ["dra_nova", "leo"] and [s["id"] for s in seen["scenes"]] == ["s1", "s2", "s3", "s4"]
        assert client.get(f"/api/episodes/{ep.id}/video").content == b"final"
        assert client.post(f"/api/episodes/{ep.id}/scenes/s2/retake").json()["status"] == "PENDIENTE"


async def test_running_an_episode_again_repeats_nothing(profile, db, monkeypatch):
    fakes = Fakes(monkeypatch)
    spoken = []
    real = voice.PROVIDERS["tono"]
    monkeypatch.setitem(voice.PROVIDERS, "tono", lambda *a: (spoken.append(a[1]), real(*a))[1])
    ep = pipeline.new_episode(db, profile, mode="demo")
    await pipeline.produce(profile, db, ep.id)
    assert len(spoken) == 12
    events_before = db.query(Event).count()
    await pipeline.produce(profile, db, ep.id)
    assert len(spoken) == 12 and fakes.rendered == ["s1", "s2", "s3", "s4"]          # no new voice, no new drawing
    stages_again = {e.stage for e in db.query(Event).filter(Event.id > events_before)}
    assert not stages_again & {"INVESTIGANDO", "ESCRIBIENDO", "STORYBOARD", "GENERANDO_VOZ"}
    # A second episode with the same lines reuses the channel's recordings.
    other = pipeline.new_episode(db, profile, mode="demo")
    await pipeline.produce(profile, db, other.id)
    assert len(spoken) == 12
    # Asking for one scene again draws that one only.
    fakes.rendered.clear()
    pipeline.retake_scene(db, ep, "s2")
    await pipeline.produce(profile, db, ep.id)
    assert fakes.rendered == ["s2"] and len(spoken) == 12
    assert len(list((pipeline.episode_dir(profile, ep.id) / "escenas").glob("*.mp4"))) == 4      # the old take is gone
    with pytest.raises(ValueError):
        pipeline.retake_scene(db, ep, "s9")


async def test_a_failed_render_stops_the_episode_and_resuming_continues_from_there(profile, db, monkeypatch):
    fakes = Fakes(monkeypatch)
    fakes.fail_scene = "s3"
    ep = pipeline.new_episode(db, profile, mode="demo")
    with pytest.raises(RenderFailed):
        await pipeline.produce(profile, db, ep.id)
    assert ep.status == ERROR and ep.error.startswith("ANIMANDO:") and "s3" in ep.error and ep.output_path is None
    assert db.query(ErrorLog).filter(ErrorLog.stage == "ANIMANDO").count() == 1 and fakes.rendered == ["s1", "s2"]
    fakes.fail_scene = None
    await pipeline.produce(profile, db, ep.id)
    assert ep.status == LISTO and ep.error is None and fakes.rendered == ["s1", "s2", "s3", "s4"]


async def test_cancel_stops_safely_and_the_episode_can_be_resumed(profile, db, monkeypatch):
    fakes = Fakes(monkeypatch)
    fakes.cancel_at = "s2"
    ep = pipeline.new_episode(db, profile, mode="demo")
    with pytest.raises(Cancelled):
        await pipeline.produce(profile, db, ep.id)
    assert ep.status == PENDIENTE and "Cancelado durante ANIMANDO" in ep.error and ep.cancel_requested == 0
    assert fakes.rendered == ["s1"] and fakes.composed == 0 and ep.voice_json          # what was done is kept
    fakes.cancel_at = None
    await pipeline.produce(profile, db, ep.id)
    assert ep.status == LISTO and fakes.rendered == ["s1", "s2", "s3", "s4"]
    # A cancel asked before a stage starts is honoured at the next unit of work.
    other = pipeline.new_episode(db, profile, mode="demo")
    monkeypatch.setattr(pipeline.Run, "cancelled", lambda self: self.episode.status == "ESCRIBIENDO")
    with pytest.raises(Cancelled):
        await pipeline.produce(profile, db, other.id)
    assert other.status == PENDIENTE and other.storyboard_json is None


async def test_budget_stops_before_paying_and_voice_errors_stop_the_episode(profile, db, monkeypatch):
    Fakes(monkeypatch)
    monkeypatch.setattr(voice.time, "sleep", lambda s: None)
    paid = []

    def provider(v, text, out_dir, name):
        paid.append(text)
        return {**voice._tone(v, text, out_dir, name), "usd": voice.estimate_usd(v, text)}

    def start() -> Episode:
        ep = pipeline.new_episode(db, profile, mode="demo")
        ep.mode = "ia"      # paid voices, with the demo's research, script and storyboard already in place
        ep.research_json, ep.script_json = json.dumps(demo.sheet()), json.dumps(demo.script())
        ep.storyboard_json = json.dumps(demo.storyboard())
        db.commit()
        return ep

    profile.limits.max_usd_per_video = 0.05
    ep = start()
    with pytest.raises(BudgetExceeded):
        await pipeline.produce(profile, db, ep.id, voice_providers={"elevenlabs": provider})
    spent = Ledger(db, ep.id, 0.05).spent()
    assert ep.status == ERROR and "límite" in ep.error and 0 < spent <= 0.05 and 0 < len(paid) < 12
    assert db.query(Cost).filter(Cost.service == "elevenlabs").count() == len(paid)
    # With room in the budget the same episode goes on, and the lines already paid are not paid again.
    profile.limits.max_usd_per_video = 2.0
    before = len(paid)
    await pipeline.produce(profile, db, ep.id, voice_providers={"elevenlabs": provider})
    assert ep.status == LISTO and len(paid) == 12 and len(set(paid)) == 12 and before < 12

    def down(v, text, out_dir, name):
        raise RuntimeError("ElevenLabs 429: quota exceeded")

    shutil.rmtree(profile.data_dir / "cache")
    ep2 = start()
    with pytest.raises(voice.VoiceError):
        await pipeline.produce(profile, db, ep2.id, voice_providers={"elevenlabs": down})
    assert ep2.status == ERROR and ep2.error.startswith("GENERANDO_VOZ:") and "quota" in ep2.error
    assert db.query(ErrorLog).filter(ErrorLog.episode_id == ep2.id, ErrorLog.stage == "voz").count() == profile.limits.max_attempts


async def test_a_stored_storyboard_is_validated_again_before_it_is_drawn(profile, db, monkeypatch):
    fakes = Fakes(monkeypatch)
    ep = pipeline.new_episode(db, profile, mode="demo")
    await pipeline.produce(profile, db, ep.id)
    tampered = json.loads(ep.storyboard_json)
    tampered["scenes"][0]["beats"][0]["action"] = "os_system"
    ep.storyboard_json, ep.voice_json = json.dumps(tampered), None
    db.commit()
    fakes.rendered.clear()
    with pytest.raises(storyboard.StoryboardRejected):
        await pipeline.produce(profile, db, ep.id)
    assert ep.status == ERROR and "acción no registrada: os_system" in ep.error and fakes.rendered == []


# ---------------------------------------------------------------- approval and publishing

class FakeYouTube:
    def __init__(self, connected=True):
        self.connected, self.uploads = connected, []

    def is_connected(self):
        return self.connected

    async def upload_video(self, path, title, description, tags, privacy="private", category_id="27"):
        self.uploads.append((Path(path).name, title, privacy, category_id))
        return f"yt{len(self.uploads)}"


async def test_nothing_is_published_without_approval_and_never_twice(profile, db, tmp_path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"x")
    ep = Episode(topic="t", title="¿Por qué el cielo es azul?", status=LISTO, output_path=str(video),
                 metadata_json=json.dumps({"title": "¿Por qué el cielo es azul?", "description": "d", "tags": ["ciencia"]}),
                 quality_json=json.dumps({"passed": True, "demo": False}))
    db.add(ep)
    db.commit()
    yt = FakeYouTube()
    for status in (PENDIENTE, "ANIMANDO", LISTO, ERROR):
        ep.status = status
        db.commit()
        with pytest.raises(PublishRejected, match="aprobado"):
            await publish(profile, db, ep.id, client=yt)
    assert yt.uploads == [] and db.query(Publication).count() == 0
    ep.status = APROBADO
    db.commit()
    with pytest.raises(PublishRejected, match="conectado"):
        await publish(profile, db, ep.id, client=FakeYouTube(connected=False))
    with pytest.raises(PublishRejected, match="privacidad"):
        await publish(profile, db, ep.id, privacy="viral", client=yt)
    row = await publish(profile, db, ep.id, client=yt)
    assert row.external_id == "yt1" and ep.status == PUBLICADO and yt.uploads == [("short.mp4", "¿Por qué el cielo es azul?", "private", "27")]
    again = await publish(profile, db, ep.id, client=yt)
    assert again.id == row.id and len(yt.uploads) == 1
    # A demo episode has no sources: it cannot be published even if somebody approves it.
    demo_ep = Episode(topic="t", status=APROBADO, output_path=str(video), metadata_json=json.dumps({"title": "Demo de prueba"}),
                      quality_json=json.dumps({"demo": True}))
    db.add(demo_ep)
    db.commit()
    with pytest.raises(PublishRejected, match="demostración"):
        await publish(profile, db, demo_ep.id, client=yt)
    assert len(yt.uploads) == 1


async def test_analytics_reads_the_channels_own_numbers_and_says_nothing_without_enough(profile, db, monkeypatch):
    class Stats:
        def __init__(self):
            self.report = True

        async def public_stats(self, ids):
            return {vid: {"views": 1000 * (i + 1), "likes": 10 * (i + 1), "comments": i} for i, vid in enumerate(ids)}

        async def video_stats(self, ids):
            if not self.report:
                raise RuntimeError("analytics scope missing")
            return {vid: {"averageViewPercentage": 60.0 + 10 * i, "averageViewDuration": 30.0, "subscribersGained": i, "shares": 1}
                    for i, vid in enumerate(ids)}

    client = Stats()
    assert await analytics.collect(db, client) == 0 and analytics.summary(db) == []
    assert not analytics.lessons(db)["enough"] and "Sin datos de demanda observada" in analytics.lessons(db)["text"]

    def published(n: int, privacy: str = "public") -> Episode:
        board = demo.storyboard()
        if n % 2:
            board["scenes"] = [s for s in board["scenes"] if s["set"] != "simulacion"]
        ep = Episode(topic=f"t{n}", title=f"Pregunta {n}", status=PUBLICADO, duration=50.0 + n, script_json=json.dumps(demo.script()),
                     storyboard_json=json.dumps(board))
        db.add(ep)
        db.flush()
        db.add(Publication(episode_id=ep.id, external_id=f"yt{n}", status="publicado", privacy=privacy, published_at=datetime(2026, 11, n)))
        db.commit()
        return ep

    published(1), published(2), published(3, privacy="private")
    assert await analytics.collect(db, client) == 3
    rows = analytics.summary(db)
    assert [r["video_id"] for r in rows] == ["yt3", "yt2", "yt1"] and rows[2]["metrics"]["views"] == 1000
    assert rows[1]["simulation"] and not rows[2]["simulation"] and rows[1]["hook"] == demo.LINES[0][1] and rows[1]["scenes"] == 4
    # Two public episodes are not enough to compare, and a private one does not count.
    assert not analytics.lessons(db)["enough"]
    published(4), published(5)
    client.report = False            # without the analytics report the public counters are still read
    assert await analytics.collect(db, client) == 5
    said = analytics.lessons(db)
    assert said["enough"] and said["episodes"] == 4 and "Más visto: «Pregunta 5»" in said["text"] and "Menos visto: «Pregunta 1»" in said["text"]
    assert "retención" not in said["text"].casefold()
    client.report = True
    await analytics.collect(db, client)
    said = analytics.lessons(db)["text"]
    assert "Mejor retención: «Pregunta 5»" in said and "pista, no de regla" in said
    # The topic chooser is told what the channel's data says, and the panel shows it.
    seen = {}

    async def fake_ask(model, system, user, schema, ledger, detail, effort="medium"):
        seen["system"] = system
        return {"candidates": [{"question": "¿Por qué el cielo es azul de día?", "angle": "a", "curiosity": 8, "narrative": 7, "visual": 9,
                                "differentiation": 5, "sources": 9, "cost": 8, "why": "w"},
                               {"question": "¿Por qué soñamos cuando dormimos?", "angle": "a", "curiosity": 10, "narrative": 10, "visual": 10,
                                "differentiation": 10, "sources": 10, "cost": 10, "why": "ya hecha"}]}

    monkeypatch.setattr(research.llm, "ask", fake_ask)
    chosen = await research.choose_topic(profile, "CATÁLOGO", ["¿Por qué soñamos cuando dormimos?"], Ledger(db, None, 2.0), observed=said)
    assert chosen["topic"] == "¿Por qué el cielo es azul de día?" and "Mejor retención" in seen["system"] and chosen["demand"] == said
    assert chosen["candidates"][1]["repeated"] and chosen["candidates"][0]["score"] == pytest.approx(77.0)
    with TestClient(create_app(profile, start_worker=False)) as http:
        view = http.get("/api/analytics").json()
        assert view["lessons"]["enough"] and len(view["episodes"]) == 5
        assert http.post("/api/analytics/refresh").status_code == 409          # no YouTube account connected


def test_panel_queues_work_shows_real_progress_and_guards_approval(profile, monkeypatch):
    app = create_app(profile, start_worker=False)
    with open_db(profile.data_dir) as db:
        stuck = Episode(topic="a medias", status="ANIMANDO")
        db.add(stuck)
        db.commit()
        stuck_id = stuck.id
    with TestClient(app) as client:
        page = client.get("/").text
        assert "Estudio de Animación IA" in page and "Generar animación con IA" in page and "__" not in page
        studio = client.get("/api/studio").json()
        assert {c["id"] for c in studio["characters"]} == {"dra_nova", "leo"} and studio["states"][0] == "PENDIENTE" and "ERROR" in studio["states"]
        # The episode the last shutdown caught mid-stage is marked, not left "running" for ever.
        interrupted = client.get(f"/api/episodes/{stuck_id}").json()
        assert interrupted["status"] == "ERROR" and "Interrumpido durante ANIMANDO" in interrupted["error"]
        made = client.post("/api/generate", json={"topic": "¿Por qué soñamos?", "characters": ["dra_nova", "leo"]}).json()
        assert app.state.queue.qsize() == 1
        ep = client.get(f"/api/episodes/{made['id']}").json()
        assert ep["status"] == "PENDIENTE" and ep["queued"] and ep["progress"]["percent"] == 0 and ep["script"] is None
        assert client.post("/api/generate", json={"characters": ["capitan_x"]}).status_code == 422
        assert client.post("/api/generate", json={"format": "largo"}).status_code == 422
        for action in ("approve", "reject"):
            assert client.post(f"/api/episodes/{made['id']}/{action}").status_code == 409        # not ready for review
        assert client.post(f"/api/episodes/{made['id']}/publish", json={"privacy": "private"}).status_code == 409
        assert client.get(f"/api/episodes/{made['id']}/video").status_code == 404
        # Progress is read from what the pipeline recorded.
        with open_db(profile.data_dir) as db:
            row = db.get(Episode, made["id"])
            row.status = "GENERANDO_VOZ"
            db.add(Event(episode_id=row.id, stage="GENERANDO_VOZ", message="Leo: «…»", done=6, total=12))
            db.commit()
        p = client.get(f"/api/episodes/{made['id']}").json()["progress"]
        assert [s["state"] for s in p["stages"]] == ["done", "done", "done", "current", "pending", "pending", "pending"]
        assert (p["stages"][3]["done"], p["stages"][3]["total"]) == (6, 12) and p["percent"] == round(100 * 3.5 / 7)
        assert client.post(f"/api/episodes/{made['id']}/resume").status_code == 409             # it is being produced
        assert client.post(f"/api/episodes/{made['id']}/cancel").json()["status"] == "GENERANDO_VOZ"
        with open_db(profile.data_dir) as db:
            row = db.get(Episode, made["id"])
            assert row.cancel_requested == 1
            row.status = LISTO
            db.commit()
        assert client.post(f"/api/episodes/{made['id']}/approve").json()["status"] == "APROBADO"
        assert client.post(f"/api/episodes/{made['id']}/resume").status_code == 409             # approved work is not redone
        assert client.post(f"/api/episodes/{made['id']}/publish", json={"privacy": "private"}).status_code == 409   # no video file
        assert client.get("/api/episodes").json()["episodes"][0]["id"] == made["id"]


# ---------------------------------------------------------------- end to end, for real

@needs_godot
@pytest.mark.skipif(os.environ.get("ANIMATION_E2E") != "1" or not shutil.which("npx"),
                    reason="episodio completo con Godot y Remotion: ANIMATION_E2E=1 (tarda varios minutos)")
def test_end_to_end_demo_episode_becomes_an_mp4(profile, db):
    ep = pipeline.new_episode(db, profile, mode="demo")
    done = asyncio.run(pipeline.produce(profile, db, ep.id, godot_bin=GODOT))
    info = quality.probe(Path(done.output_path))
    assert done.status == LISTO and (info["width"], info["height"]) == (1080, 1920) and info["fps"] == 30 and info["audio"]
    assert 45 <= info["duration"] <= 60 and Path(done.thumbnail_path).stat().st_size > 10_000
    result = json.loads(done.quality_json)
    failed = [c["name"] for c in result["checks"] if not c["ok"]]
    assert failed == ["Hechos con cita literal de su fuente"]          # the demo has no sources, and says so
