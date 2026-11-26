"""Shared loader for faster-whisper models: GPU when it actually works, CPU otherwise."""
import importlib.util
import logging
import os

try:
    from faster_whisper import WhisperModel
except ImportError:  # pragma: no cover - optional heavy dependency
    WhisperModel = None

logger = logging.getLogger("animation.whisper")

# "auto" (default) tries the GPU first; "cpu" or "cuda" force one.
DEVICE_ENV = "ANIMATION_WHISPER_DEVICE"


def _cuda_library_dirs() -> list[str]:
    """Folders that may hold the cuBLAS/cuDNN DLLs: the nvidia-* pip wheels and a CUDA build of PyTorch."""
    dirs: list[str] = []
    try:
        import nvidia  # namespace package created by the nvidia-* wheels

        for base in getattr(nvidia, "__path__", []):
            dirs += [os.path.join(base, name, "bin") for name in ("cublas", "cudnn")]
    except ImportError:
        pass
    spec = importlib.util.find_spec("torch")  # located without importing it
    if spec is not None and spec.origin:
        dirs.append(os.path.join(os.path.dirname(spec.origin), "lib"))
    return [d for d in dirs if os.path.isdir(d)]


def _register_cuda_dlls() -> None:
    """Let ctranslate2 find the CUDA libraries on Windows, where they are not on the DLL path."""
    if os.name != "nt":
        return
    for lib_dir in _cuda_library_dirs():
        os.add_dll_directory(lib_dir)
        os.environ["PATH"] = lib_dir + os.pathsep + os.environ.get("PATH", "")


def load_model(model_size: str):
    """Load a Whisper model on the GPU if one is usable, falling back to the CPU."""
    if WhisperModel is None:
        raise RuntimeError("faster-whisper is not installed")
    device = os.environ.get(DEVICE_ENV, "auto").lower()
    if device in ("auto", "cuda"):
        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0:
                _register_cuda_dlls()
                # int8_float16 keeps VRAM use low enough to share a 6 GB card with the renderer.
                model = WhisperModel(model_size, device="cuda", compute_type="int8_float16")
                logger.info("Whisper %s loaded on the GPU", model_size)
                return model
        except Exception as e:  # missing CUDA libraries, out of memory, driver problems...
            if device == "cuda":
                raise
            logger.warning("Whisper could not use the GPU (%s); falling back to the CPU", e)
    return WhisperModel(model_size, device="cpu", compute_type="int8")


class WordAligner:
    def __init__(self, model_size: str = "small"):
        self._model_size = model_size
        self._model = None

    def _get_model(self):
        if self._model is None:
            self._model = load_model(self._model_size)
        return self._model

    def align(self, audio_path: str) -> list[dict]:
        segments, _ = self._get_model().transcribe(audio_path, language="es", word_timestamps=True, beam_size=5)
        words = []
        for seg in segments:
            for w in seg.words or []:
                text = w.word.strip()
                if text:
                    words.append({"word": text, "start": round(w.start, 3), "end": round(w.end, 3)})
        return words
