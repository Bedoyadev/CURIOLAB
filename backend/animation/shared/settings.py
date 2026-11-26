"""Where things are, the credentials, and the settings every channel profile has.

Copied from the repository this engine was born in (the Shorts factory and the documentary
engine it shared code with), so that this project stands on its own.
"""
import os
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

BACKEND = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND.parent
PROFILES_DIR = BACKEND / "channels"
# USD per million tokens (input, output), for the cost record.
PRICES_PER_MTOK = {"claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0), "claude-haiku-5-5": (0.1, 0.5)}


class Voice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = "elevenlabs"
    # Name of the environment variable (or backend/.env entry) holding this channel's own key.
    key_env: str = "ELEVENLABS_API_KEY"
    voice_id: str
    model: str = "eleven_multilingual_v2"
    stability: float = Field(default=0.5, ge=0, le=1)
    similarity: float = Field(default=0.8, ge=0, le=1)
    style: float = Field(default=0.2, ge=0, le=1)
    speed: float = Field(default=1.0, ge=0.7, le=1.2)
    usd_per_1k_chars: float = Field(default=0.3, ge=0)

class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_usd_per_video: float = Field(default=2.0, gt=0)
    max_attempts: int = Field(default=3, ge=1, le=6)

class Publishing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval: str = "manual"       # nothing leaves the machine without the owner's approval
    privacy: str = "private"
    category_id: str = "27"        # Education

def secret(name: str, env_file: Path | None = None) -> str:
    """A credential by name. backend/.env wins over the process environment: a shell opened before
    a key was changed still carries the old value, the file does not."""
    path = env_file or BACKEND / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(rf"\s*{re.escape(name)}\s*=\s*(.*)", line)
            if m and m.group(1).strip():
                return m.group(1).strip().strip('"').strip("'")
    return os.environ.get(name, "")


def anthropic_key() -> str:
    return secret("ANTHROPIC_API_KEY")
