"""«Estudio de Animación IA»: the channel's panel.

    python -m animation.server --channel curiolab --port 8200

One button makes an episode; the rest is for looking at what was made (script, storyboard,
resources, costs, quality report, the video), asking for a scene again, and approving. Approving
does not publish: uploading is a separate, explicit action on an approved episode.

Work is queued and done one episode at a time by a single worker. If the server stops in the
middle of an episode, the next start marks it as interrupted; resuming continues from the last
finished stage without paying again for what is already done.
"""
import argparse
import asyncio
import json
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from animation import analytics, godot, pipeline
from animation.db import APROBADO, ERROR, LISTO, PENDIENTE, PUBLICADO, STATES, WORKING, Cost, Episode, ErrorLog, Event, Publication, open_db
from animation.library import default_library
from animation.profile import AnimationProfile, load_profile
from animation.publish import ChannelYouTube, PublishRejected, publish
from animation.shared.text import words as slug_words
from animation.shared.youtube import MAX_TITLE, PRIVACY_VALUES, YouTubeError

logger = logging.getLogger("animation.server")
PANEL = Path(__file__).with_name("panel.html")
_PAGE = """<!doctype html><meta charset="utf-8"><title>{name}</title>
<body style="font-family:system-ui;background:#15161C;color:#fff;padding:48px">
<h2>{title}</h2><p>{body}</p><p><a style="color:#FFD23F" href="/">Volver al estudio</a></p></body>"""


class Generate(BaseModel):
    # "" lets the engine choose the question.
    topic: str = Field(default="", max_length=300)
    characters: list[str] = Field(default_factory=list, max_length=4)
    format: str = "short"
    demo: bool = False


class Edit(BaseModel):
    title: str = Field(min_length=10, max_length=MAX_TITLE)
    description: str = Field(min_length=20, max_length=5000)


class PublishIn(BaseModel):
    privacy: str = "private"


class Redo(BaseModel):
    stage: str


def _load(text: str | None):
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def progress(db, ep: Episode) -> dict:
    """Where the episode is, from its state and the events the pipeline wrote: which stages are
    done, and how many units of the current one (lines recorded, scenes drawn)."""
    order = [s for s, _ in pipeline.STAGES]
    finished = ep.status in (LISTO, APROBADO, PUBLICADO)
    current = order.index(ep.status) if ep.status in order else (len(order) if finished else -1)
    unit = None
    if 0 <= current < len(order):
        unit = db.execute(select(Event).where(Event.episode_id == ep.id, Event.stage == ep.status, Event.total.is_not(None))
                          .order_by(Event.id.desc())).scalars().first()
    fraction = unit.done / unit.total if unit is not None and unit.total else 0.0
    last = db.execute(select(Event).where(Event.episode_id == ep.id).order_by(Event.id.desc())).scalars().first()
    return {
        "stages": [{"key": key, "label": label, "state": "done" if i < current else "current" if i == current else "pending",
                    "done": unit.done if unit is not None and i == current else None,
                    "total": unit.total if unit is not None and i == current else None}
                   for i, (key, label) in enumerate(pipeline.STAGES)],
        "percent": 100 if finished else round(100 * (max(current, 0) + fraction) / len(order)) if current >= 0 else 0,
        "message": last.message if last else "",
    }


def create_app(profile: AnimationProfile, start_worker: bool = True) -> FastAPI:
    queue: asyncio.Queue[int] = asyncio.Queue()
    state = {"current": None}
    pending_states: set[str] = set()

    async def worker() -> None:
        while True:
            episode_id = await queue.get()
            state["current"] = episode_id
            try:
                with open_db(profile.data_dir) as db:
                    ep = db.get(Episode, episode_id)
                    # Cancelled or changed while it waited in the queue: not this turn's work any more.
                    if ep is not None and ep.status == PENDIENTE and ep.error is None:
                        await pipeline.produce(profile, db, episode_id)
            except asyncio.CancelledError:
                raise
            except Exception as e:   # the pipeline already left the episode in its state with the reason
                logger.info("Episode %s stopped: %s", episode_id, e)
            finally:
                state["current"] = None
                queue.task_done()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        with open_db(profile.data_dir) as db:
            # An episode caught mid-stage by the last shutdown is not running any more.
            for ep in db.execute(select(Episode).where(Episode.status.in_(WORKING))).scalars():
                ep.error, ep.status = f"Interrumpido durante {ep.status}. Se puede reanudar.", ERROR
            waiting = [ep.id for ep in db.execute(select(Episode).where(Episode.status == PENDIENTE, Episode.error.is_(None))
                                                  .order_by(Episode.id)).scalars()]
            db.commit()
        for episode_id in waiting:
            queue.put_nowait(episode_id)
        task = asyncio.create_task(worker()) if start_worker else None
        yield
        if task is not None:
            task.cancel()

    app = FastAPI(title=f"{profile.name} · Estudio de Animación IA", lifespan=lifespan)
    app.state.queue = queue

    def summary(db, ep: Episode) -> dict:
        spent = db.execute(select(func.coalesce(func.sum(Cost.usd), 0.0)).where(Cost.episode_id == ep.id)).scalar_one()
        quality = _load(ep.quality_json)
        return {"id": ep.id, "status": ep.status, "topic": ep.topic, "title": ep.title or ep.topic or "(el motor elegirá el tema)",
                "mode": ep.mode, "working": state["current"] == ep.id, "queued": ep.status == PENDIENTE and ep.error is None and state["current"] != ep.id,
                "duration": ep.duration, "spent_usd": round(float(spent), 3), "error": ep.error,
                "has_video": bool(ep.output_path and Path(ep.output_path).is_file()),
                "quality_passed": quality.get("passed") if quality else None,
                "created_at": ep.created_at.isoformat() if ep.created_at else None, "progress": progress(db, ep)}

    def get(db, episode_id: int) -> Episode:
        ep = db.get(Episode, episode_id)
        if ep is None:
            raise HTTPException(404, "Episodio no encontrado")
        return ep

    @app.get("/", response_class=HTMLResponse)
    def panel():
        b = profile.brand
        page = PANEL.read_text(encoding="utf-8")
        for key, value in {"__NAME__": profile.name, "__SLOGAN__": profile.slogan, "__INK__": b.ink, "__ACCENT__": b.accent,
                           "__ACCENT2__": b.accent2, "__LIMIT__": f"{profile.limits.max_usd_per_video:.2f}"}.items():
            page = page.replace(key, value)
        return page

    @app.get("/api/studio")
    def studio():
        """What the studio has: the cast to choose from, the formats, and whether it can render."""
        lib = default_library()
        return {"channel": profile.name, "states": list(STATES), "formats": [{"key": "short", "label": f"Short vertical · {profile.format.min_seconds}-{profile.format.max_seconds} s"}],
                "characters": [{"id": cid, "name": c["name"], "role": c["role"], "default": cid in profile.cast,
                                "has_voice": c["voice"] in profile.voices, "art": c.get("art", "")} for cid, c in lib.characters.items()],
                "library": {"version": lib.version, "actions": list(lib.actions), "sets": list(lib.sets), "props": list(lib.props),
                            "cameras": list(lib.cameras), "effects": list(lib.effects)},
                "godot": bool(godot.find_godot()), "limit_usd": profile.limits.max_usd_per_video}

    @app.get("/api/episodes")
    def episodes():
        with open_db(profile.data_dir) as db:
            rows = db.execute(select(Episode).order_by(Episode.id.desc())).scalars().all()
            total = db.execute(select(func.coalesce(func.sum(Cost.usd), 0.0))).scalar_one()
            return {"spent_usd": round(float(total), 2), "busy": state["current"], "episodes": [summary(db, e) for e in rows]}

    @app.get("/api/episodes/{episode_id}")
    def episode(episode_id: int):
        with open_db(profile.data_dir) as db:
            ep = get(db, episode_id)
            sb = _load(ep.storyboard_json)
            timeline = _load(ep.timeline_json) or {}
            lib = default_library()
            resources = None
            if sb:
                scenes = sb["scenes"]
                resources = {
                    "characters": sorted({m["character"] for s in scenes for m in s["cast"]} | {b["speaker"] for s in scenes for b in s["beats"] if b["speaker"]}),
                    "sets": sorted({s["set"] for s in scenes}), "props": sorted({p["prop"] for s in scenes for p in s["props"]}),
                    "actions": sorted({b["action"] for s in scenes for b in s["beats"]} | {r["action"] for s in scenes for b in s["beats"] for r in b["reactions"]}),
                    "cameras": sorted({b["camera"] for s in scenes for b in s["beats"]}),
                    "effects": sorted({e for s in scenes for b in s["beats"] for e in b["effects"]}),
                    "provisional_art": sorted(c for c in lib.characters if lib.characters[c].get("art") == "provisional"),
                }
            return {
                **summary(db, ep), "research": _load(ep.research_json), "script": _load(ep.script_json), "storyboard": sb,
                "scenes": timeline.get("scenes", []), "resources": resources, "retakes": _load(ep.retakes_json) or {},
                "metadata": _load(ep.metadata_json), "quality": _load(ep.quality_json),
                "publication": next(({"status": p.status, "video_id": p.external_id, "privacy": p.privacy, "error": p.error} for p in db.execute(
                    select(Publication).where(Publication.episode_id == ep.id).order_by(Publication.id.desc())).scalars()), None),
                "costs": [{"service": c.service, "usd": round(c.usd, 4), "detail": c.detail}
                          for c in db.execute(select(Cost).where(Cost.episode_id == ep.id).order_by(Cost.id)).scalars()],
                "events": [{"id": e.id, "stage": e.stage, "message": e.message, "done": e.done, "total": e.total, "at": e.created_at.isoformat()}
                           for e in db.execute(select(Event).where(Event.episode_id == ep.id).order_by(Event.id.desc()).limit(40)).scalars()],
                "errors": [{"stage": e.stage, "message": e.message[:400]}
                           for e in db.execute(select(ErrorLog).where(ErrorLog.episode_id == ep.id).order_by(ErrorLog.id.desc()).limit(5)).scalars()],
            }

    def enqueue(episode_id: int) -> None:
        queue.put_nowait(episode_id)

    @app.post("/api/generate")
    async def generate(body: Generate):
        """The button. The episode is queued; it ends waiting for review and is never published."""
        if body.format != "short":
            raise HTTPException(422, "Formato no disponible todavía")
        with open_db(profile.data_dir) as db:
            try:
                ep = pipeline.new_episode(db, profile, topic=body.topic, cast=body.characters or None, mode="demo" if body.demo else "ia")
            except ValueError as e:
                raise HTTPException(422, str(e))
            enqueue(ep.id)
            return {"id": ep.id}

    def _requeue(episode_id: int, change) -> dict:
        with open_db(profile.data_dir) as db:
            ep = get(db, episode_id)
            if state["current"] == episode_id or ep.status in WORKING:
                raise HTTPException(409, "El episodio se está produciendo; cancélalo antes")
            try:
                change(db, ep)
            except ValueError as e:
                raise HTTPException(409, str(e))
            ep.status, ep.error = PENDIENTE, None
            db.commit()
            enqueue(ep.id)
            return summary(db, ep)

    @app.post("/api/episodes/{episode_id}/resume")
    async def resume(episode_id: int):
        def change(db, ep):
            if ep.status in (APROBADO, PUBLICADO):
                raise ValueError("Un episodio aprobado no se vuelve a producir")
        return _requeue(episode_id, change)

    @app.post("/api/episodes/{episode_id}/scenes/{scene_id}/retake")
    async def retake(episode_id: int, scene_id: str):
        """Draw one scene again; the others keep their renders, the voices their recordings."""
        return _requeue(episode_id, lambda db, ep: pipeline.retake_scene(db, ep, scene_id))

    @app.post("/api/episodes/{episode_id}/redo")
    async def redo(episode_id: int, body: Redo):
        return _requeue(episode_id, lambda db, ep: pipeline.regenerate_from(db, ep, body.stage))

    @app.post("/api/episodes/{episode_id}/cancel")
    def cancel(episode_id: int):
        with open_db(profile.data_dir) as db:
            ep = get(db, episode_id)
            if state["current"] != episode_id and ep.status not in WORKING:
                if ep.status == PENDIENTE and ep.error is None:
                    ep.error = "Cancelado antes de empezar. Se puede reanudar."
                    db.commit()
                    return summary(db, ep)
                raise HTTPException(409, "El episodio no se está produciendo")
            ep.cancel_requested = 1
            db.commit()
            return summary(db, ep)

    def _decide(episode_id: int, approve: bool) -> dict:
        with open_db(profile.data_dir) as db:
            ep = get(db, episode_id)
            if ep.status != LISTO:
                raise HTTPException(409, f"Solo se decide un episodio listo para revisión (está en: {ep.status})")
            ep.status, ep.error = (APROBADO, None) if approve else (ERROR, "Rechazado en la revisión.")
            db.commit()
            return summary(db, ep)

    @app.post("/api/episodes/{episode_id}/approve")
    def approve(episode_id: int):
        """Records the owner's go-ahead. It does not publish."""
        return _decide(episode_id, True)

    @app.post("/api/episodes/{episode_id}/reject")
    def reject(episode_id: int):
        return _decide(episode_id, False)

    @app.patch("/api/episodes/{episode_id}/metadata")
    def edit_metadata(episode_id: int, body: Edit):
        with open_db(profile.data_dir) as db:
            ep = get(db, episode_id)
            if ep.status == PUBLICADO or not ep.metadata_json:
                raise HTTPException(409, "El episodio no tiene publicación que editar")
            meta = json.loads(ep.metadata_json)
            meta["title"], meta["description"] = " ".join(body.title.split()), body.description.strip()
            ep.metadata_json = json.dumps(meta, ensure_ascii=False)
            db.commit()
            return summary(db, ep)

    def _file(episode_id: int, attr: str, media_type: str, download: str | None = None) -> FileResponse:
        with open_db(profile.data_dir) as db:
            ep = db.get(Episode, episode_id)
            path = getattr(ep, attr) if ep else None
        if not path or not Path(path).is_file():
            raise HTTPException(404, "Archivo no encontrado")
        return FileResponse(path, media_type=media_type, filename=download)

    @app.get("/api/episodes/{episode_id}/video")
    def video(episode_id: int, download: bool = False):
        name = None
        if download:
            with open_db(profile.data_dir) as db:
                ep = db.get(Episode, episode_id)
                slug = "-".join(slug_words(ep.title or "")[:9]) if ep else ""
            name = f"{profile.key}-{slug or episode_id}.mp4"
        return _file(episode_id, "output_path", "video/mp4", name)

    @app.get("/api/episodes/{episode_id}/thumbnail")
    def thumbnail(episode_id: int):
        return _file(episode_id, "thumbnail_path", "image/png")

    @app.get("/api/youtube/status")
    async def youtube_status():
        client = ChannelYouTube(profile)
        out = {"configured": client.is_configured(), "connected": client.is_connected(), "channel_title": None,
               "default_privacy": profile.publishing.privacy, "error": None}
        if out["connected"]:
            try:
                out["channel_title"] = (await client.channel())["title"]
            except YouTubeError as e:
                out["error"] = str(e)[:300]
        return out

    @app.get("/api/youtube/connect")
    def youtube_connect(request: Request):
        client = ChannelYouTube(profile)
        if not client.is_configured():
            raise HTTPException(409, "Falta el archivo youtube_client_secret.json")
        token = secrets.token_urlsafe(24)
        pending_states.add(token)
        return {"url": client.auth_url(str(request.url_for("youtube_callback")), token)}

    @app.get("/api/youtube/callback", response_class=HTMLResponse, name="youtube_callback")
    async def youtube_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
        if error or not code or state not in pending_states:
            return HTMLResponse(_PAGE.format(name=profile.name, title="No se conectó el canal",
                                             body=error or "La respuesta de Google no corresponde a un inicio de sesión de este panel."), 400)
        pending_states.discard(state)
        try:
            await ChannelYouTube(profile).exchange_code(code, str(request.url_for("youtube_callback")))
        except YouTubeError as e:
            return HTMLResponse(_PAGE.format(name=profile.name, title="No se conectó el canal", body=str(e)[:300]), 400)
        return _PAGE.format(name=profile.name, title="Canal conectado", body="Ya puedes cerrar esta pestaña y volver al estudio.")

    @app.post("/api/youtube/disconnect")
    def youtube_disconnect():
        ChannelYouTube(profile).disconnect()
        return {"connected": False}

    @app.get("/api/analytics")
    def analytics_view():
        """The published episodes with their latest numbers, and what they say."""
        with open_db(profile.data_dir) as db:
            return {"episodes": analytics.summary(db), "lessons": analytics.lessons(db)}

    @app.post("/api/analytics/refresh")
    async def analytics_refresh():
        client = ChannelYouTube(profile)
        if not client.is_connected():
            raise HTTPException(409, "El canal de YouTube no está conectado")
        with open_db(profile.data_dir) as db:
            try:
                read = await analytics.collect(db, client)
            except YouTubeError as e:
                raise HTTPException(502, f"YouTube no devolvió los datos: {str(e)[:300]}")
            return {"read": read, "episodes": analytics.summary(db), "lessons": analytics.lessons(db)}

    @app.post("/api/episodes/{episode_id}/publish")
    async def publish_episode(episode_id: int, body: PublishIn):
        if body.privacy not in PRIVACY_VALUES:
            raise HTTPException(422, "Privacidad no válida")
        with open_db(profile.data_dir) as db:
            try:
                row = await publish(profile, db, episode_id, privacy=body.privacy)
            except PublishRejected as e:
                raise HTTPException(409, str(e))
            except YouTubeError as e:
                raise HTTPException(502, f"YouTube rechazó la subida: {str(e)[:300]}")
            return {"status": row.status, "video_id": row.external_id, "privacy": row.privacy, "error": row.error}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(prog="animation.server")
    parser.add_argument("--channel", required=True)
    parser.add_argument("--port", type=int, default=8200)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    uvicorn.run(create_app(load_profile(args.channel)), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
