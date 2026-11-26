"""An animated channel's profile: its name, look, cast, voices, format and limits. The engine reads
it; nothing about a particular channel is written in the engine's code."""
import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from animation.shared.settings import BACKEND, PROFILES_DIR, Limits, Publishing, Voice


class Brand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ink: str = "#15161C"        # text on light, outlines
    paper: str = "#FFFFFF"      # caption text
    accent: str = "#FFD23F"     # the word being spoken, the title pill
    accent2: str = "#18B7A6"
    font_title: str = "Archivo Black"
    font_body: str = "Inter"


class Format(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_seconds: int = 45
    max_seconds: int = 60
    # Spoken words of the whole script. Dialogue runs slower than narration: with the pauses between
    # lines and the silent beats it comes to about half a second per word, and the closing card
    # takes its own seconds of the minute.
    words_min: int = 85
    words_max: int = 110
    min_scenes: int = 3
    max_scenes: int = 7


class Research(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_sources: int = Field(default=2, ge=1)
    min_facts: int = Field(default=5, ge=1)


class AnimationProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # What kind of channel the profile describes: this engine only loads its own.
    engine: Literal["animation"]
    key: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    slogan: str
    about: str
    language: str = "es"
    brand: Brand = Field(default_factory=Brand)
    # Characters every episode starts from (ids in animator/library/characters/).
    cast: list[str] = Field(min_length=1)
    # Voice of each character, by the "voice" name in its definition.
    voices: dict[str, Voice]
    format: Format = Field(default_factory=Format)
    research: Research = Field(default_factory=Research)
    limits: Limits = Field(default_factory=Limits)
    publishing: Publishing = Field(default_factory=Publishing)
    claude_model: str = "claude-sonnet-5-5"
    subscribe: str = "SUSCRÍBETE"
    closing_line: str = ""
    editorial: list[str] = Field(default_factory=list)

    @property
    def data_dir(self) -> Path:
        """Everything this channel owns: database, voice cache, episodes, sound, credentials."""
        root = Path(os.environ.get("ANIMATION_DATA_DIR") or BACKEND / "data" / "channels")
        return root / self.key

    def rules(self) -> str:
        return "\n".join(f"- {r}" for r in self.editorial)


def load_profile(key: str, profiles_dir: Path | None = None) -> AnimationProfile:
    path = (profiles_dir or PROFILES_DIR) / f"{key}.json"
    if not path.is_file():
        raise FileNotFoundError(f"no hay perfil para el canal '{key}' en {path.parent}")
    return AnimationProfile(**json.loads(path.read_text(encoding="utf-8")))
