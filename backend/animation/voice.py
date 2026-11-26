"""Voice Engine: one audio file per line of dialogue, in its character's voice, with the time of
every word.

- The paid call is shared.narration.narrate: ElevenLabs with character
  timings, turned into word timings, with the Whisper aligner as fallback.
- Cache: a line is identified by its voice, model, settings and exact text. The same line is never
  paid for twice, in this episode or in a later one (data/channels/<key>/cache/voz/).
- Budget: the caller checks a line's cost (estimate_usd) against the episode's limit before
  the call and records what was spent after it. Nothing here touches the database, so a line can
  be recorded in a worker thread.
- Errors: a failed call is retried a limited number of times, then the episode stops with the
  line that failed. Lines already recorded stay in the cache, so resuming continues from there.

The provider "tono" makes a synthetic placeholder (a hummed tone per word) without any network
call: it is what the demo episode and the tests use, and a way to try the renderer for free.
"""
import hashlib
import json
import logging
import shutil
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from animation.shared.settings import Voice

logger = logging.getLogger("animation.voice")
RATE = 44100
RETRY_WAIT_SECONDS = 2.0


class VoiceError(Exception):
    def __init__(self, message: str, failures: list[str] | None = None):
        super().__init__(message)
        # What each attempt answered, for the episode's error log.
        self.failures = failures or []


def line_key(voice: Voice, text: str) -> str:
    identity = json.dumps([voice.provider, voice.voice_id, voice.model, voice.stability, voice.similarity,
                           voice.style, voice.speed, text], ensure_ascii=False)
    return hashlib.sha1(identity.encode()).hexdigest()[:20]


def estimate_usd(voice: Voice, text: str) -> float:
    return 0.0 if voice.provider == "tono" else len(text) / 1000 * voice.usd_per_1k_chars


def _tone(voice: Voice, text: str, out_dir: Path, name: str) -> dict:
    """A hummed stand-in for a voice: one swelling tone per word, pauses at punctuation."""
    pitch = 150 + int(hashlib.sha1(voice.voice_id.encode()).hexdigest(), 16) % 110
    words, chunks, t = [], [], 0.12
    chunks.append(np.zeros(int(RATE * t)))
    for word in text.split():
        length = 0.07 + 0.036 * len(word)
        n = int(RATE * length)
        k = np.arange(n) / RATE
        tone = sum(a * np.sin(2 * np.pi * pitch * h * k * (1 + 0.01 * np.sin(2 * np.pi * 5 * k)))
                   for h, a in ((1, 1.0), (2, 0.5), (3, 0.25)))
        chunks.append(0.3 * tone * np.sin(np.pi * k / length) ** 0.6)
        words.append({"word": word, "start": round(t, 3), "end": round(t + length, 3)})
        gap = 0.26 if word[-1] in ".?!…" else 0.14 if word[-1] in ",;:" else 0.04
        chunks.append(np.zeros(int(RATE * gap)))
        t += length + gap
    data = np.concatenate(chunks)
    path = out_dir / f"{name}.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(data, -1, 1) * 32767).astype("<i2").tobytes())
    return {"path": path, "duration": len(data) / RATE, "words": words, "chars": len(text), "timing": "tono", "usd": 0.0}


def _elevenlabs(voice: Voice, text: str, out_dir: Path, name: str) -> dict:
    from animation.shared.narration import narrate

    return narrate(SimpleNamespace(voice=voice), text, out_dir, name)


PROVIDERS = {"elevenlabs": _elevenlabs, "tono": _tone}


def cached(voice: Voice, text: str, cache_dir: Path) -> bool:
    key = line_key(voice, " ".join(text.split()))
    return (cache_dir / f"{key}.wav").is_file() and (cache_dir / f"{key}.json").is_file()


def speak(voice: Voice, text: str, cache_dir: Path, attempts: int = 3, providers: dict | None = None) -> dict:
    """Blocking. {"path", "duration", "words", "chars", "timing", "usd", "cached", "failures"} of
    one line. usd: what this call cost (0 when it came from the cache)."""
    text = " ".join(text.split())
    if not text:
        raise VoiceError("línea vacía")
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = line_key(voice, text)
    wav, meta = cache_dir / f"{key}.wav", cache_dir / f"{key}.json"
    if wav.is_file() and meta.is_file():
        return {**json.loads(meta.read_text(encoding="utf-8")), "path": wav, "usd": 0.0, "cached": True, "failures": []}
    provider = (providers or PROVIDERS).get(voice.provider)
    if provider is None:
        raise VoiceError(f"proveedor de voz no disponible: {voice.provider}")
    work = cache_dir / f"tmp-{key}"
    result, last, failures = None, None, []
    for attempt in range(1, attempts + 1):
        work.mkdir(exist_ok=True)
        try:
            result = provider(voice, text, work, "linea")
            break
        except Exception as e:   # the provider's errors are its own types: network, quota, bad voice id...
            last = e
            logger.warning("Voice attempt %s/%s failed: %s", attempt, attempts, e)
            failures.append(f"intento {attempt}: {e}")
            if attempt < attempts:
                time.sleep(RETRY_WAIT_SECONDS * attempt)
    if result is None:
        shutil.rmtree(work, ignore_errors=True)
        raise VoiceError(f"la voz falló {attempts} veces en «{text[:60]}»: {last}", failures)
    shutil.move(str(result["path"]), wav)
    shutil.rmtree(work, ignore_errors=True)
    record = {"duration": result["duration"], "words": result["words"], "chars": result["chars"], "timing": result["timing"]}
    meta.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return {**record, "path": wav, "usd": result["usd"], "cached": False, "failures": failures}
