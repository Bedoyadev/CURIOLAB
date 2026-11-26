"""From «Generar animación con IA» to a finished MP4 waiting for approval.

    PENDIENTE → INVESTIGANDO → ESCRIBIENDO → STORYBOARD → GENERANDO_VOZ → ANIMANDO → COMPONIENDO
              → VALIDANDO → LISTO_PARA_REVISIÓN          (then the owner: APROBADO → PUBLICADO)

How it holds up:
- Idempotent: each stage keeps its result (in the episode's row and folder). Running an episode
  again skips every stage whose result is there, so nothing is paid or drawn twice. Voices and
  scenes have their own caches by content, below the stage level.
- Resumable: an episode that stopped (an error, the budget, a cancel, the server going down) is
  continued by calling produce() on it again.
- Cancellable: a cancel request is honoured between units of work (a line, a scene) and stops a
  Godot render in progress. What was finished stays.
- Observable: every unit writes an Event; the panel's progress is those rows, not a timer.
- It ends at LISTO_PARA_REVISIÓN. Nothing here approves or publishes.
"""
import asyncio
import json
import logging
import sqlite3
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from animation import analytics, compose, demo, godot, lipsync, plan, quality, research, script, sound, storyboard, voice
from animation.db import (
    ANIMANDO, APROBADO, COMPONIENDO, ERROR, ESCRIBIENDO, GENERANDO_VOZ, INVESTIGANDO, LISTO, PENDIENTE, PUBLICADO,
    STORYBOARD, VALIDANDO, Episode, Event,
)
from animation.godot import Cancelled
from animation.ledger import BudgetExceeded, Ledger
from animation.library import Library, default_library
from animation.profile import AnimationProfile
from animation.research import NeedsReview  # noqa: F401  (part of what produce() raises)
from animation.shared.settings import Voice
from animation.shared.settings import REPO_ROOT

logger = logging.getLogger("animation.pipeline")
FONT = REPO_ROOT / "renderer" / "public" / "fonts" / "Inter.ttf"
# The stages in order, with what each one's result is called on the episode.
STAGES = [(INVESTIGANDO, "Investigando el tema"), (ESCRIBIENDO, "Escribiendo el guion"), (STORYBOARD, "Planificando las escenas"),
          (GENERANDO_VOZ, "Grabando las voces"), (ANIMANDO, "Animando las escenas"), (COMPONIENDO, "Montando el video"),
          (VALIDANDO, "Comprobando la calidad")]
# What "regenerate from here" clears, by stage name.
FIELDS_FROM = {
    "investigacion": ["research_json", "script_json", "storyboard_json", "voice_json", "timeline_json"],
    "guion": ["script_json", "storyboard_json", "voice_json", "timeline_json"],
    "storyboard": ["storyboard_json", "voice_json", "timeline_json"],
}


def episode_dir(profile: AnimationProfile, episode_id: int) -> Path:
    path = profile.data_dir / "episodios" / f"{episode_id:04d}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save(folder: Path, name: str, data) -> None:
    (folder / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class Run:
    """One pass of the pipeline over one episode."""

    def __init__(self, profile: AnimationProfile, db: Session, episode: Episode, lib: Library | None = None,
                 godot_bin: str | None = None, renderer=None, voice_providers: dict | None = None):
        self.profile, self.db, self.episode = profile, db, episode
        self.lib = lib or default_library()
        self.godot_bin, self.renderer, self.voice_providers = godot_bin, renderer, voice_providers
        self.folder = episode_dir(profile, episode.id)
        self.ledger = Ledger(db, episode.id, profile.limits.max_usd_per_video)
        self.cast = json.loads(episode.cast_json) or list(profile.cast)

    # ------------------------------------------------------------ bookkeeping

    def event(self, message: str, done: int | None = None, total: int | None = None) -> None:
        self.db.add(Event(episode_id=self.episode.id, stage=self.episode.status, message=message, done=done, total=total))
        self.db.commit()
        logger.info("Episode %s [%s] %s%s", self.episode.id, self.episode.status, message,
                    f" ({done}/{total})" if total else "")

    def enter(self, status: str) -> None:
        self.check_cancel()
        self.episode.status = status
        self.db.commit()
        self.event(dict(STAGES)[status])

    def cancelled(self) -> bool:
        self.db.refresh(self.episode, ["cancel_requested"])
        return bool(self.episode.cancel_requested)

    def check_cancel(self) -> None:
        if self.cancelled():
            raise Cancelled()

    def cancelled_from_thread(self) -> bool:
        """The same question, asked from the thread that waits on Godot: it reads the flag on
        a connection of its own instead of sharing this run's session across threads."""
        with sqlite3.connect(self.profile.data_dir / "animation.db", timeout=5) as con:
            row = con.execute("select cancel_requested from episodes where id = ?", (self.episode.id,)).fetchone()
        return bool(row and row[0])

    def previous(self) -> list[dict]:
        """Earlier episodes of the channel, for the checks against repeating one."""
        out = []
        for ep in self.db.execute(select(Episode).where(Episode.id != self.episode.id, Episode.script_json.is_not(None))).scalars():
            s = json.loads(ep.script_json)
            out.append({"title": ep.title or s.get("title", ""), "text": script.script_text(s)})
        return out

    # ------------------------------------------------------------ stages

    async def do_research(self) -> dict:
        ep = self.episode
        if ep.research_json:
            return json.loads(ep.research_json)
        self.enter(INVESTIGANDO)
        if ep.mode == "demo":
            sheet = demo.sheet()
        else:
            topic, chosen = ep.topic.strip(), None
            if not topic:
                chosen = await research.choose_topic(self.profile, self.lib.catalog(self.cast),
                                                     [p["title"] for p in self.previous()], self.ledger,
                                                     observed=analytics.lessons(self.db)["text"])
                topic = chosen["topic"]
                self.event(f"Tema elegido: {topic}")
                _save(self.folder, "tema.json", chosen)
            sheet = await research.investigate(self.profile, topic, self.ledger)
            sheet["candidates"] = chosen["candidates"] if chosen else []
        ep.topic = sheet["topic"]
        ep.research_json = json.dumps(sheet, ensure_ascii=False)
        self.db.commit()
        _save(self.folder, "investigacion.json", sheet)
        self.event(f"{len(sheet['facts'])} hechos verificados de {len(sheet['sources'])} fuentes; "
                   f"{len(sheet['simulations'])} simulación(es)")
        return sheet

    async def do_script(self, sheet: dict) -> dict:
        ep = self.episode
        if ep.script_json:
            return json.loads(ep.script_json)
        self.enter(ESCRIBIENDO)
        if ep.mode == "demo":
            result = demo.script()
        else:
            result = await script.write_script(self.profile, self.lib, self.cast, sheet, self.ledger,
                                               [p["text"] for p in self.previous()])
        ep.script_json, ep.title = json.dumps(result, ensure_ascii=False), result["title"]
        sources = "\n".join(f"- {s['title'] or s['publisher']}: {s['url']}" for s in sheet["sources"])
        ep.metadata_json = json.dumps({
            "title": result["title"], "tags": result["tags"],
            "description": "\n\n".join(part for part in (result["description"], "Fuentes:\n" + sources if sources else "",
                                                         "Animación original. Las voces de los personajes son generadas con IA.") if part),
        }, ensure_ascii=False)
        self.db.commit()
        _save(self.folder, "guion.json", result)
        self.event(f"Guion de {result['checks']['words']} palabras; gancho elegido: «{result['hooks'][result['chosen_hook']]['text']}»")
        return result

    async def do_storyboard(self, sheet: dict, script_data: dict) -> storyboard.Storyboard:
        ep = self.episode
        known = research.support_ids(sheet)
        if not ep.storyboard_json:
            self.enter(STORYBOARD)
            if ep.mode == "demo":
                document, notes = demo.storyboard(f"{self.profile.key}-{ep.id:04d}"), []
            else:
                document, notes = await script.stage(self.profile, self.lib, self.cast, script_data, sheet, self.ledger,
                                                     f"{self.profile.key}-{ep.id:04d}")
            for note in notes:
                self.event(f"Corregido: {note}")
            # Stored complete (every field of the schema present), so whoever reads it needs no defaults.
            document = storyboard.parse(document).model_dump()
            ep.storyboard_json = json.dumps(document, ensure_ascii=False)
            self.db.commit()
            _save(self.folder, "storyboard.json", document)
        # Validated every time it is about to be used, wherever it came from (a cached row or a
        # file somebody edited by hand): nothing unregistered reaches the renderer.
        sb = storyboard.parse(json.loads(ep.storyboard_json))
        storyboard.repair(sb, self.lib)
        problems = storyboard.validate(sb, self.lib, known)
        if problems:
            raise storyboard.StoryboardRejected(problems)
        if ep.status == STORYBOARD:
            self.event(f"{len(sb.scenes)} escenas, {sum(len(s.beats) for s in sb.scenes)} beats, {sb.words()} palabras")
        return sb

    async def do_voices(self, sb: storyboard.Storyboard) -> dict[str, dict]:
        ep = self.episode
        lines = sb.lines()
        cache = self.profile.data_dir / "cache" / "voz"
        if ep.voice_json:
            kept = json.loads(ep.voice_json)
            if len(kept) == len(lines) and all(Path(v["path"]).is_file() for v in kept.values()):
                return kept
        self.enter(GENERANDO_VOZ)
        out: dict[str, dict] = {}
        for n, (si, bi, beat) in enumerate(lines, 1):
            self.check_cancel()
            character = self.lib.characters[beat.speaker]
            # The demo episode hums: it must never reach a paid voice.
            v = Voice(provider="tono", voice_id=character["voice"]) if ep.mode == "demo" else self.profile.voices.get(character["voice"])
            if v is None:
                raise voice.VoiceError(f"el canal no tiene voz para {beat.speaker} (voices.{character['voice']})")
            if not voice.cached(v, beat.text, cache):
                self.ledger.check(voice.estimate_usd(v, beat.text))   # refuse before paying, not after
            try:
                result = await asyncio.to_thread(voice.speak, v, beat.text, cache, self.profile.limits.max_attempts, self.voice_providers)
            except voice.VoiceError as e:
                for failure in e.failures:
                    self.ledger.error("voz", failure)
                raise
            for failure in result["failures"]:
                self.ledger.error("voz", failure)
            if result["usd"]:
                self.ledger.add(v.provider, result["usd"], f"voz:{beat.speaker}:{result['chars']} caracteres")
            mouth = lipsync.track(result["path"], self.lib.fps, result["words"])
            out[f"{si}:{bi}"] = {"speaker": beat.speaker, "path": str(result["path"]), "duration": result["duration"],
                                 "words": result["words"], "mouth": mouth, "timing": result["timing"], "cached": result["cached"]}
            self.event(f"{character['name']}: «{beat.text[:48]}»" + (" (en caché)" if result["cached"] else ""), n, len(lines))
        ep.voice_json = json.dumps(out, ensure_ascii=False)
        self.db.commit()
        return out

    async def do_animate(self, timeline: dict) -> list[Path]:
        self.enter(ANIMANDO)
        videos = []
        scenes = timeline["scenes"]
        for n, scene in enumerate(scenes, 1):
            self.check_cancel()
            _save(self.folder, f"plan_{scene['id']}.json", scene["plan"])
            path, cached = await asyncio.to_thread(godot.render_scene, scene["plan"], scene["key"], self.folder / "escenas",
                                                   self.lib, self.godot_bin, self.cancelled_from_thread)
            videos.append(path)
            self.event(f"Escena {scene['id']} ({scene['set']}, {scene['duration']:.1f} s)" + (" (ya dibujada)" if cached else ""), n, len(scenes))
        # Renders of plans that are no longer the episode's are not kept.
        for old in (self.folder / "escenas").glob("*.mp4"):
            if old not in videos:
                old.unlink(missing_ok=True)
        return videos

    async def do_compose(self, sb: storyboard.Storyboard, timeline: dict, videos: list[Path]) -> None:
        ep = self.episode
        self.enter(COMPONIENDO)
        sounds = sound.ensure_sounds(self.profile.data_dir / "sonido")
        dialogue = await asyncio.to_thread(compose.mix_dialogue, timeline["lines"], timeline["duration"], self.folder / "dialogo.wav")
        self.event(f"Diálogo mezclado: {len(timeline['lines'])} líneas en {timeline['duration']:.1f} s")
        props, media = compose.build_props(self.profile, self.lib, sb.title, timeline, videos, sounds)
        _save(self.folder, "props.json", props)
        self.check_cancel()
        output = await compose.render(props, media, dialogue, self.folder, self.renderer)
        ep.output_path, ep.thumbnail_path = str(output.video), str(output.thumbnail)
        self.db.commit()
        self.event("Video montado con subtítulos, música y efectos")

    async def do_validate(self, sb: storyboard.Storyboard, sheet: dict, timeline: dict, videos: list[Path]) -> dict:
        ep = self.episode
        self.enter(VALIDANDO)
        result = await asyncio.to_thread(quality.check, self.profile, Path(ep.output_path), sb.model_dump(), sheet, timeline, videos,
                                         self.ledger.spent(), self.previous(), compose.TAIL_SECONDS)
        ep.duration, ep.quality_json = result["duration"], json.dumps(result, ensure_ascii=False)
        self.db.commit()
        (self.folder / "calidad.md").write_text(quality.report(self.profile, sb.title, result), encoding="utf-8")
        failed = [c["name"] for c in result["checks"] if not c["ok"]]
        self.event("Pasa las comprobaciones automáticas" if result["passed"] else "No pasa: " + "; ".join(failed))
        return result


async def produce(profile: AnimationProfile, db: Session, episode_id: int, **kwargs) -> Episode:
    """Make (or continue) an episode. Returns it in LISTO_PARA_REVISIÓN, or raises with the
    episode left where it stopped: NeedsReview, BudgetExceeded, Cancelled, or the stage's error."""
    episode = db.get(Episode, episode_id)
    if episode is None:
        raise ValueError(f"no existe el episodio {episode_id}")
    if episode.status in (APROBADO, PUBLICADO):
        raise ValueError("un episodio aprobado no se vuelve a producir")
    # The flag may have been set from another connection (the panel): read it before clearing it.
    db.refresh(episode)
    episode.cancel_requested, episode.error = 0, None
    db.commit()
    run = Run(profile, db, episode, **kwargs)
    try:
        sheet = await run.do_research()
        script_data = await run.do_script(sheet)
        sb = await run.do_storyboard(sheet, script_data)
        voices = await run.do_voices(sb)
        timeline = plan.compile_episode(sb, run.lib, voices, {s["id"]: s for s in sheet["simulations"]},
                                        json.loads(episode.retakes_json), FONT)
        episode.timeline_json = json.dumps({**timeline, "scenes": [{k: v for k, v in s.items() if k != "plan"} for s in timeline["scenes"]]},
                                           ensure_ascii=False)
        videos = await run.do_animate(timeline)
        await run.do_compose(sb, timeline, videos)
        await run.do_validate(sb, sheet, timeline, videos)
        episode.status = LISTO
        db.commit()
        run.event(f"Listo para revisión · {run.ledger.spent():.2f} USD")
        return episode
    except Cancelled:
        # Not an error: it waits, and everything finished so far is kept for when it is resumed.
        db.refresh(episode, ["cancel_requested"])
        stage = episode.status
        episode.status, episode.cancel_requested = PENDIENTE, 0
        episode.error = f"Cancelado durante {stage}. Se puede reanudar."
        db.commit()
        run.event("Cancelado")
        raise
    except Exception as e:
        stage = episode.status
        run.ledger.error(stage, str(e))
        episode.status, episode.error = ERROR, f"{stage}: {str(e)[:900]}"
        db.commit()
        run.event(f"Detenido: {str(e)[:300]}")
        raise


def new_episode(db: Session, profile: AnimationProfile, topic: str = "", cast: list[str] | None = None, mode: str = "ia") -> Episode:
    lib = default_library()
    cast = cast or list(profile.cast)
    unknown = [c for c in cast if c not in lib.characters]
    if unknown:
        raise ValueError(f"personajes no registrados: {', '.join(unknown)}")
    episode = Episode(topic=" ".join(topic.split()), cast_json=json.dumps(cast), mode=mode)
    db.add(episode)
    db.commit()
    return episode


def retake_scene(db: Session, episode: Episode, scene_id: str) -> None:
    """Ask for one scene to be drawn again: its render key changes, the others keep theirs."""
    if episode.status in (APROBADO, PUBLICADO):
        raise ValueError("un episodio aprobado no se cambia")
    scenes = [s["id"] for s in json.loads(episode.storyboard_json or "{}").get("scenes", [])]
    if scene_id not in scenes:
        raise ValueError(f"el episodio no tiene la escena {scene_id}")
    retakes = json.loads(episode.retakes_json)
    retakes[scene_id] = retakes.get(scene_id, 0) + 1
    episode.retakes_json, episode.status = json.dumps(retakes), PENDIENTE
    db.commit()


def regenerate_from(db: Session, episode: Episode, stage: str) -> None:
    """Throw away a stage's result and everything built on it (voices already paid stay cached)."""
    if episode.status in (APROBADO, PUBLICADO):
        raise ValueError("un episodio aprobado no se cambia")
    if stage not in FIELDS_FROM:
        raise ValueError(f"etapa desconocida: {stage}")
    for field in FIELDS_FROM[stage]:
        setattr(episode, field, None)
    episode.status = PENDIENTE
    db.commit()

