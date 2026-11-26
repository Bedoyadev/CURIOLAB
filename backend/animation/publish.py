"""Publishing Engine: an approved episode to the channel's own YouTube account. The channel's
session (the token) and its Google application file live in its data directory.

Two rules, both enforced here and not only in the panel:
- only an episode the owner approved is uploaded;
- never twice: an episode with a finished upload returns that upload.
"""
import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from animation.db import APROBADO, PUBLICADO, Episode, Publication, now
from animation.profile import AnimationProfile
from animation.shared.youtube import MAX_TITLE, PRIVACY_VALUES, ChannelYouTube, PublishRejected

__all__ = ["ChannelYouTube", "PublishRejected", "publish"]
logger = logging.getLogger("animation.publish")


async def publish(profile: AnimationProfile, db: Session, episode_id: int, privacy: str | None = None, client=None) -> Publication:
    episode = db.get(Episode, episode_id)
    if episode is None:
        raise PublishRejected("no existe el episodio")
    done = db.execute(select(Publication).where(Publication.episode_id == episode_id,
                                                Publication.external_id.is_not(None))).scalars().first()
    if done is not None:
        return done
    if episode.status != APROBADO:
        raise PublishRejected(f"solo se publica un episodio aprobado (está en: {episode.status})")
    if db.execute(select(Publication).where(Publication.episode_id == episode_id, Publication.status == "subiendo")).scalars().first():
        raise PublishRejected("ya hay una subida de este episodio en curso")
    if not episode.output_path or not Path(episode.output_path).is_file():
        raise PublishRejected("no existe el archivo de video")
    if json.loads(episode.quality_json or "{}").get("demo"):
        raise PublishRejected("un episodio de demostración no se publica: sus hechos no tienen fuente")
    meta = json.loads(episode.metadata_json or "{}")
    title = " ".join(str(meta.get("title") or "").split())[:MAX_TITLE]
    if not title:
        raise PublishRejected("el episodio no tiene título")
    privacy = privacy or profile.publishing.privacy
    if privacy not in PRIVACY_VALUES:
        raise PublishRejected(f"privacidad no válida: {privacy}")
    client = client or ChannelYouTube(profile)
    if not client.is_connected():
        raise PublishRejected("el canal de YouTube no está conectado")
    row = Publication(episode_id=episode_id, title=title, status="subiendo", privacy=privacy)
    db.add(row)
    db.commit()
    try:
        video_id = await client.upload_video(Path(episode.output_path), title, meta.get("description") or "",
                                             meta.get("tags") or [], privacy=privacy, category_id=profile.publishing.category_id)
    except Exception as e:
        row.status, row.error = "fallido", str(e)[:500]
        db.commit()
        raise
    row.external_id, row.status, row.published_at = video_id, "publicado", now()
    episode.status = PUBLICADO
    db.commit()
    logger.info("Episode %s published as %s (%s)", episode_id, video_id, privacy)
    return row
