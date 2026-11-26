"""The channel's database (data/channels/<key>/animation.db): episodes, what happened to each
one, what it cost, where it was published and how it did.
"""
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

# The states of an episode, in order. The working ones are the pipeline's stages.
PENDIENTE, INVESTIGANDO, ESCRIBIENDO, STORYBOARD, GENERANDO_VOZ, ANIMANDO, COMPONIENDO, VALIDANDO = (
    "PENDIENTE", "INVESTIGANDO", "ESCRIBIENDO", "STORYBOARD", "GENERANDO_VOZ", "ANIMANDO", "COMPONIENDO", "VALIDANDO")
LISTO, APROBADO, PUBLICADO, ERROR = "LISTO_PARA_REVISIÓN", "APROBADO", "PUBLICADO", "ERROR"
WORKING = (INVESTIGANDO, ESCRIBIENDO, STORYBOARD, GENERANDO_VOZ, ANIMANDO, COMPONIENDO, VALIDANDO)
STATES = (PENDIENTE, *WORKING, LISTO, APROBADO, PUBLICADO, ERROR)


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Episode(Base):
    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # What the owner asked for ("" = let the engine choose) and what it became.
    topic: Mapped[str] = mapped_column(Text, nullable=False, default="")
    title: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default=PENDIENTE)
    cast_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # "demo": fixed script and synthetic voices, no paid call (for tests and for trying the renderer).
    mode: Mapped[str] = mapped_column(Text, nullable=False, default="ia")
    # Each stage's result. A stage whose result is here is not run (or paid) again.
    research_json: Mapped[str | None] = mapped_column(Text)
    script_json: Mapped[str | None] = mapped_column(Text)
    storyboard_json: Mapped[str | None] = mapped_column(Text)
    voice_json: Mapped[str | None] = mapped_column(Text)
    timeline_json: Mapped[str | None] = mapped_column(Text)
    quality_json: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    # Scenes the owner asked to draw again: {scene id: how many times}. Changes that scene's render key.
    retakes_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    output_path: Mapped[str | None] = mapped_column(Text)
    thumbnail_path: Mapped[str | None] = mapped_column(Text)
    duration: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now, onupdate=now)


class Event(Base):
    """Something the pipeline really did, when it did it. The panel's progress is read from here."""
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"), nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Units finished and units in the stage (voice lines, scenes), when the stage has them.
    done: Mapped[int | None] = mapped_column(Integer)
    total: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)


class Cost(Base):
    __tablename__ = "costs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_id: Mapped[int | None] = mapped_column(ForeignKey("episodes.id"))
    service: Mapped[str] = mapped_column(Text, nullable=False)
    usd: Mapped[float] = mapped_column(Float, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)


class ErrorLog(Base):
    __tablename__ = "errors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_id: Mapped[int | None] = mapped_column(ForeignKey("episodes.id"))
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)


class Publication(Base):
    __tablename__ = "publications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"), nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False, default="youtube")
    external_id: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="subiendo")
    privacy: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)


class Metric(Base):
    """One dated reading of a published episode's numbers (see analytics.py)."""
    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id"), nullable=False)
    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    likes: Mapped[int | None] = mapped_column(Integer)
    comments: Mapped[int | None] = mapped_column(Integer)
    shares: Mapped[int | None] = mapped_column(Integer)
    avg_view_percentage: Mapped[float | None] = mapped_column(Float)
    avg_view_seconds: Mapped[float | None] = mapped_column(Float)
    subscribers_gained: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=now)


def open_db(data_dir: Path) -> Session:
    data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{data_dir / 'animation.db'}")
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)
