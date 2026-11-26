"""The wrapper around the Remotion command line: prepares a job folder with the media, bundles
once, renders the video and the stills, and cleans up."""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RENDER_TIMEOUT_SECONDS = 900
_IS_WINDOWS = sys.platform == "win32"
# Flags for the video render: draw with the GPU (ANGLE) and encode with the hardware encoder
# (NVENC) when there is one; both fall back to software on their own. Hardware encoders ignore CRF,
# so the bitrate is set explicitly. Override with ANIMATION_REMOTION_FLAGS (space separated).
_GPU_RENDER_FLAGS = ["--gl=angle", "--hardware-acceleration=if-possible", "--video-bitrate=8M"]
DEFAULT_RENDER_FLAGS: list[str] = (
    os.environ["ANIMATION_REMOTION_FLAGS"].split() if "ANIMATION_REMOTION_FLAGS" in os.environ
    else _GPU_RENDER_FLAGS
)


class RenderError(Exception):
    pass


@dataclass
class RenderOutput:
    video: Path
    thumbnail: Path
    thumbnail_vertical: Path | None = None


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


TRIM_PADDING_SECONDS = 0.5
# GPU encoder first (NVENC), software x264 as the fallback when there is no usable GPU.
_TRIM_ENCODERS = (
    ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "19"],
    ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"],
)


def _trim_clip(src: Path, dst: Path, start: float, duration: float) -> bool:
    """Cut [start, start+duration] of src into dst (video only, every frame seekable). False if it fails."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    for encoder in _TRIM_ENCODERS:
        cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, start):.3f}", "-i", str(src),
               "-t", f"{duration + TRIM_PADDING_SECONDS:.3f}", "-an", *encoder,
               "-g", "15", "-pix_fmt", "yuv420p", str(dst)]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=180)
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0 and dst.is_file() and dst.stat().st_size > 0:
            return True
    dst.unlink(missing_ok=True)
    return False


class RemotionRenderer:
    def __init__(self, renderer_dir: Path | None = None, npx: str | None = None,
                 render_flags: list[str] | None = None, entry: str = "src/animation/index.ts"):
        """entry: the Remotion entry file, relative to the renderer folder."""
        self._dir = renderer_dir or REPO_ROOT / "renderer"
        self._entry = entry
        self._npx = npx or shutil.which("npx") or "npx"
        self._render_flags = list(DEFAULT_RENDER_FLAGS if render_flags is None else render_flags)

    def _prepare_job(self, props: dict, media: dict[str, Path], audio: Path) -> tuple[Path, Path]:
        job = self._dir / "jobs" / uuid.uuid4().hex
        public = job / "public"
        shutil.copytree(self._dir / "public", public)
        props = json.loads(json.dumps(props))  # private copy: clip offsets are rewritten below
        # A Short keeps its beats at the top level; the recap keeps them inside its chapters.
        all_beats = [*props.get("beats", []), *[b for ch in props.get("chapters", []) for b in ch.get("beats", [])]]
        clips = {b["clip"]["src"]: b["clip"] for b in all_beats if b.get("clip")}
        for rel, src in media.items():
            clip = clips.get(rel)
            # Seeking frame by frame into a 10-minute 1080p source is what makes renders slow: cut
            # each clip down to just the seconds used, so Remotion reads a tiny file from second 0.
            if clip is not None and _trim_clip(Path(src), public / rel, float(clip["from"]), float(clip["duration"])):
                clip["from"] = 0.0
            else:
                _link_or_copy(Path(src), public / rel)
        _link_or_copy(Path(audio), public / "audio" / "narration.wav")
        props_path = job / "props.json"
        props_path.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
        return job, props_path

    @staticmethod
    def _kill_tree(proc: subprocess.Popen) -> None:
        """Kill the whole process tree: `npx` spawns node/chrome children that outlive a plain kill()."""
        if _IS_WINDOWS:
            try:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=30)
            except (OSError, subprocess.SubprocessError):
                pass
        proc.kill()

    def _run(self, args: list[str], timeout: int = RENDER_TIMEOUT_SECONDS) -> None:
        cmd = [self._npx, "remotion", *args]
        try:
            proc = subprocess.Popen(
                cmd, cwd=self._dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
            )
        except OSError as e:  # includes FileNotFoundError (npx missing) and permission errors
            raise RenderError(f"could not run remotion via {self._npx!r}: {e}") from e
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as e:
            self._kill_tree(proc)
            try:
                proc.communicate(timeout=15)
            except (subprocess.SubprocessError, OSError):
                pass
            raise RenderError(
                f"remotion {args[0] if args else ''} timed out after {timeout}s"
            ) from e
        except BaseException:
            self._kill_tree(proc)
            raise
        if proc.returncode != 0:
            raise RenderError((stderr or stdout or "remotion failed")[-2000:])

    def _render_sync(self, props: dict, media: dict[str, Path], audio: Path, out_dir: Path,
                     composition: str = "Short", stills: dict[str, str] | None = None,
                     timeout: int = RENDER_TIMEOUT_SECONDS, video_name: str = "short.mp4") -> RenderOutput:
        """stills: {still composition id: output file name}; the first one is the main thumbnail.
        video_name: the rendered file's name (its extension has to suit the codec in the flags)."""
        stills = stills or {"Thumbnail": "thumb.png", "ThumbnailVertical": "thumb_vertical.png"}
        # Remotion runs with the renderer folder as its working directory, so a relative output
        # path (the default data dir is "./data") would land inside renderer/ instead.
        out_dir = Path(out_dir).resolve()
        job, props_path = self._prepare_job(props, media, audio)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            names = list(stills.values())
            out = RenderOutput(out_dir / video_name, out_dir / names[0],
                               out_dir / names[1] if len(names) > 1 else None)
            # Bundle once and reuse it for the video and both thumbnails; passing the entry file to
            # each command would re-bundle the project three times (~10 s each).
            bundle = job / "bundle"
            self._run(["bundle", self._entry, f"--public-dir={job / 'public'}", f"--out-dir={bundle}"])
            entry, common = str(bundle), [f"--props={props_path}"]
            render = ["render", entry, composition, str(out.video), *common, *self._render_flags]
            if timeout == RENDER_TIMEOUT_SECONDS:
                self._run(render)
            else:
                self._run(render, timeout)
            for still_id, name in stills.items():
                self._run(["still", entry, still_id, str(out_dir / name), *common])
            return out
        finally:
            shutil.rmtree(job, ignore_errors=True)

    async def render(self, props: dict, media: dict[str, Path], audio: Path, out_dir: Path,
                     composition: str = "Short", stills: dict[str, str] | None = None,
                     timeout: int = RENDER_TIMEOUT_SECONDS, video_name: str = "short.mp4") -> RenderOutput:
        return await asyncio.to_thread(self._render_sync, props, media, audio, out_dir, composition, stills, timeout, video_name)
