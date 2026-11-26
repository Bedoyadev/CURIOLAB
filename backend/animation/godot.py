"""Animation Engine, backend side: runs the Godot director on one scene's plan and leaves an MP4.

    godot --path animator --write-movie escena.avi --fixed-fps 30 -- --plan=plan.json --result=r.json

Godot's Movie Maker mode renders every frame at a fixed time step whatever the machine's speed,
so the output is deterministic and never drops a frame. It needs a display (it opens a small
window while it draws); it does not work with --headless, which has no renderer.

One call per scene: a scene that fails or is asked again is drawn alone, and a scene whose plan
has not changed is not drawn at all (its MP4 is found by the plan's key).
"""
import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from animation.library import Library
from animation.shared.settings import secret

logger = logging.getLogger("animation.godot")
SCENE_TIMEOUT_SECONDS = 600
POLL_SECONDS = 0.3


class RenderFailed(Exception):
    pass


class Cancelled(Exception):
    pass


def find_godot() -> str | None:
    """The Godot 4 executable: GODOT_BIN (backend/.env or the environment), or one on the PATH."""
    configured = secret("GODOT_BIN")
    if configured:
        return configured if Path(configured).is_file() else None
    return shutil.which("godot4") or shutil.which("godot")


def _kill(proc: subprocess.Popen) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=30)
    proc.kill()


def _encode(avi: Path, mp4: Path, frames: int, fps: int) -> None:
    """Godot's MJPEG to H.264, cut to the plan's exact number of frames (the last one is held if
    Godot wrote one too few) and brought from JPEG's full colour range to the video range players
    expect. Short GOP: the cover is taken from a frame in the middle of one of these files."""
    tmp = mp4.with_suffix(".tmp.mp4")
    run = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(avi), "-an", "-vf", "tpad=stop_mode=clone:stop_duration=1,scale=in_range=pc:out_range=tv,format=yuv420p",
         "-color_range", "tv",
         "-frames:v", str(frames), "-r", str(fps), "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-g", "15",
         str(tmp)], capture_output=True, text=True, timeout=600)
    if run.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        raise RenderFailed(f"ffmpeg no pudo codificar la escena: {run.stderr[-400:]}")
    tmp.replace(mp4)


def render_scene(plan: dict, key: str, out_dir: Path, lib: Library, godot: str | None = None,
                 cancelled: Callable[[], bool] | None = None, timeout: int = SCENE_TIMEOUT_SECONDS) -> tuple[Path, bool]:
    """Blocking. (the scene's MP4, whether it was already there)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    mp4 = out_dir / f"{plan['scene']}-{key}.mp4"
    if mp4.is_file() and mp4.stat().st_size > 0:
        return mp4, True
    missing = lib.missing_files()
    if missing:
        raise RenderFailed(f"faltan archivos de la biblioteca de animación: {', '.join(missing)}")
    godot = godot or find_godot()
    if not godot:
        raise RenderFailed("no se encuentra Godot 4: define GODOT_BIN en backend/.env con la ruta del ejecutable")
    work = out_dir / f"tmp-{plan['scene']}-{key}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    plan_path, result_path, avi = work / "plan.json", work / "result.json", work / "scene.avi"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    cmd = [godot, "--path", str(lib.root), "--write-movie", str(avi), "--fixed-fps", str(plan["fps"]), "--disable-vsync",
           "--", f"--plan={plan_path}", f"--result={result_path}"]
    try:
        # Godot's output goes to a file: a pipe nobody reads while polling would fill up and hang it.
        log_path = work / "godot.log"
        try:
            with open(log_path, "w", encoding="utf-8", errors="replace") as log_file:
                proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
        except OSError as e:
            raise RenderFailed(f"no se pudo ejecutar Godot ({godot}): {e}") from e
        started = time.monotonic()
        while proc.poll() is None:
            if cancelled is not None and cancelled():
                _kill(proc)
                raise Cancelled()
            if time.monotonic() - started > timeout:
                _kill(proc)
                raise RenderFailed(f"Godot no terminó la escena {plan['scene']} en {timeout} s")
            time.sleep(POLL_SECONDS)
        log = log_path.read_text(encoding="utf-8", errors="replace")[-1500:] if log_path.is_file() else ""
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else None
        if result is None or not result.get("ok") or proc.returncode != 0:
            reason = "; ".join(result["errors"]) if result and result.get("errors") else log.strip() or "sin salida"
            raise RenderFailed(f"Godot no pudo dibujar la escena {plan['scene']}: {reason}")
        if not avi.is_file() or avi.stat().st_size == 0:
            raise RenderFailed(f"Godot no escribió el video de la escena {plan['scene']}")
        _encode(avi, mp4, int(round(plan["duration"] * plan["fps"])), plan["fps"])
        return mp4, False
    finally:
        shutil.rmtree(work, ignore_errors=True)
