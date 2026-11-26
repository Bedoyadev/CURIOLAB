"""The voice call: ElevenLabs with character timings turned into word timings, brought to a
broadcast level, with the Whisper aligner as fallback when the timings do not match the text.

Copied from the repository this engine was born in (the Shorts factory and the documentary
engine it shared code with), so that this project stands on its own.
"""
import base64
import logging
import subprocess
from pathlib import Path

from animation.shared.settings import secret

logger = logging.getLogger("animation.narration")
STYLE_MODEL = 'eleven_multilingual_v2'
# Broadcast chain for a voice: it changes level and tone, not timing.
NARRATION_LOUDNESS_FILTER = (
    'highpass=f=80,equalizer=f=140:t=q:w=1:g=2.5,equalizer=f=3500:t=q:w=1.2:g=3,equalizer=f=9000:t=q:w=1.5:g=1.5,acompressor=threshold=-20dB:ratio=3.5:attack=5:release=120:makeup=2,loudnorm=I=-14:TP=-1.5:LRA=7'
)


class NarrationError(Exception):
    pass

def words_from_characters(chars: list[str], starts: list[float], ends: list[float]) -> list[dict]:
    """Character timings to word timings: a word is a run of characters between spaces."""
    words, current, begin, finish = [], "", 0.0, 0.0
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if current:
                words.append({"word": current, "start": round(begin, 3), "end": round(finish, 3)})
            current = ""
            continue
        if not current:
            begin = s
        current, finish = current + ch, e
    if current:
        words.append({"word": current, "start": round(begin, 3), "end": round(finish, 3)})
    return words

def _duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, timeout=20)
    return float(out.stdout.strip())

def _to_wav(mp3: Path, wav: Path) -> None:
    # The broadcast chain (it changes level and tone, not timing).
    run = subprocess.run(["ffmpeg", "-y", "-i", str(mp3), "-af", NARRATION_LOUDNESS_FILTER, "-ar", "44100", str(wav)],
                         capture_output=True, text=True, timeout=180)
    if run.returncode != 0:
        raise NarrationError(f"ffmpeg no pudo convertir la narración: {run.stderr[-300:]}")

def _elevenlabs(profile, text: str, mp3: Path) -> list[dict]:
    from elevenlabs import ElevenLabs, VoiceSettings

    v = profile.voice
    key = secret(v.key_env)
    if not key:
        raise NarrationError(f"falta la clave de ElevenLabs del canal ({v.key_env}) en backend/.env")
    client = ElevenLabs(api_key=key)
    request = {"voice_id": v.voice_id, "text": text, "model_id": v.model}
    if v.model == STYLE_MODEL:
        # Delivery controls only exist on this older model; the newer ones take the voice as it is
        # and get their expression from how the text is written.
        request["voice_settings"] = VoiceSettings(stability=v.stability, similarity_boost=v.similarity, style=v.style,
                                                  use_speaker_boost=True, speed=v.speed)
    response = client.text_to_speech.convert_with_timestamps(**request)
    audio = getattr(response, "audio_base_64", None) or getattr(response, "audio_base64", None)
    if not audio:
        raise NarrationError("ElevenLabs no devolvió audio")
    mp3.write_bytes(base64.b64decode(audio))
    alignment = getattr(response, "alignment", None)
    if alignment is None:
        return []
    return words_from_characters(list(alignment.characters), list(alignment.character_start_times_seconds),
                                 list(alignment.character_end_times_seconds))

def narrate(profile, text: str, out_dir: Path, name: str = "narracion") -> dict:
    """Blocking. Returns {"path", "duration", "words", "chars", "timing", "usd"}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    mp3, wav = out_dir / f"{name}.mp3", out_dir / f"{name}.wav"
    if profile.voice.provider != "elevenlabs":
        raise NarrationError(f"proveedor de voz no disponible: {profile.voice.provider}")
    words = _elevenlabs(profile, text, mp3)
    _to_wav(mp3, wav)
    timing = "elevenlabs"
    if len(words) != len(text.split()):
        # No timings, or they do not match the script word for word: align from the audio.
        from animation.shared.whisper import WordAligner

        logger.warning("Word timings from the provider do not match the script (%s vs %s); aligning from audio",
                       len(words), len(text.split()))
        words, timing = WordAligner().align(str(wav)), "whisper"
    return {"path": wav, "duration": _duration(wav), "words": words, "chars": len(text), "timing": timing,
            "usd": len(text) / 1000 * profile.voice.usd_per_1k_chars}
