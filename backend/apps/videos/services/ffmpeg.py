"""Thin, testable wrappers around ffprobe / ffmpeg.

Everything here is pure filesystem work — no Django models, no MinIO. That keeps
the encoder logic independently exercisable (`python -m apps.videos.services.ffmpeg`
is not needed; a plain unit test can call these with a fixture file).
"""
from __future__ import annotations

import json
import logging
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from django.conf import settings

from apps.videos.services.ladder import Rendition

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float], None]  # receives 0.0 - 1.0


class FFmpegError(RuntimeError):
    """Raised with the tail of stderr so the uploader sees a real reason."""


@dataclass
class ProbeResult:
    duration_seconds: float
    width: int
    height: int
    video_codec: str
    audio_codec: str
    has_audio: bool
    format_name: str
    bitrate: int

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"


def _run(cmd: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
    logger.debug("running: %s", shlex.join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def probe(source: str | Path) -> ProbeResult:
    """Extract duration, resolution and codec info with ffprobe.

    Also doubles as upload validation: a file that ffprobe cannot parse is not a
    video, whatever its extension or declared MIME type claimed.
    """
    cmd = [
        settings.FFPROBE_BIN,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(source),
    ]
    proc = _run(cmd, timeout=120)
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe a echoue: {proc.stderr.strip()[-800:]}")

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise FFmpegError(f"Sortie ffprobe illisible: {exc}") from exc

    streams = data.get("streams", [])
    fmt = data.get("format", {})

    video_stream = next((s for s in streams if s.get("codec_type") == "video"
                         and s.get("disposition", {}).get("attached_pic", 0) == 0), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if video_stream is None:
        raise FFmpegError("Le fichier ne contient aucune piste video exploitable.")

    # Duration can live on the stream or only on the container.
    duration = float(video_stream.get("duration") or fmt.get("duration") or 0)
    if duration <= 0:
        raise FFmpegError("Duree de la video indeterminee ou nulle.")

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise FFmpegError("Resolution de la video indeterminee.")

    # Rotation metadata means the displayed frame is transposed.
    rotation = 0
    for side_data in video_stream.get("side_data_list", []) or []:
        if "rotation" in side_data:
            rotation = abs(int(side_data["rotation"])) % 360
    if rotation in (90, 270):
        width, height = height, width

    return ProbeResult(
        duration_seconds=duration,
        width=width,
        height=height,
        video_codec=video_stream.get("codec_name", ""),
        audio_codec=(audio_stream or {}).get("codec_name", ""),
        has_audio=audio_stream is not None,
        format_name=fmt.get("format_name", ""),
        bitrate=int(fmt.get("bit_rate") or 0),
    )


def _parse_progress(line: str) -> float | None:
    """Pull elapsed seconds out of one `-progress pipe:1` key=value line."""
    if line.startswith("out_time_us="):
        raw = line.split("=", 1)[1].strip()
        return int(raw) / 1_000_000 if raw.isdigit() else None
    if line.startswith("out_time_ms="):
        raw = line.split("=", 1)[1].strip()
        # ffmpeg's out_time_ms is actually microseconds despite the name.
        return int(raw) / 1_000_000 if raw.isdigit() else None
    return None


def transcode_rendition(
    source: str | Path,
    out_dir: str | Path,
    rendition: Rendition,
    duration_seconds: float,
    has_audio: bool = True,
    progress_cb: ProgressCallback | None = None,
) -> dict:
    """Encode one ladder rung to HLS.

    One ffmpeg process per rung (rather than a single multi-output command) so a
    failure is attributable to a specific rendition and progress is reportable
    per rung.

    Returns `{"playlist": "index.m3u8", "segments": int, "bytes": int}`.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    playlist = out_dir / "index.m3u8"

    seg = settings.HLS_SEGMENT_SECONDS
    # Fixed GOP == segment length keeps every segment independently decodable, which
    # is what lets the player switch renditions at a segment boundary without artifacts.
    gop = max(int(seg * 25), 2)

    cmd = [
        settings.FFMPEG_BIN, "-hide_banner", "-nostdin", "-y",
        "-i", str(source),
        "-vf", f"scale={rendition.width}:{rendition.height}:flags=bicubic",
        "-c:v", settings.FFMPEG_VIDEO_ENCODER,
        "-preset", settings.FFMPEG_PRESET,
        "-profile:v", "main",
        "-crf", "23",
        "-maxrate", f"{rendition.video_bitrate_kbps}k",
        "-bufsize", f"{rendition.video_bitrate_kbps * 2}k",
        "-g", str(gop), "-keyint_min", str(gop),
        "-sc_threshold", "0",
        "-pix_fmt", "yuv420p",
    ]

    if has_audio:
        cmd += ["-c:a", "aac", "-b:a", f"{rendition.audio_bitrate_kbps}k", "-ac", "2"]
    else:
        cmd += ["-an"]

    cmd += [
        "-f", "hls",
        "-hls_time", str(seg),
        "-hls_playlist_type", "vod",
        "-hls_segment_type", "mpegts",
        "-hls_flags", "independent_segments",
        "-hls_segment_filename", str(out_dir / "seg_%05d.ts"),
        "-progress", "pipe:1", "-loglevel", "error",
        str(playlist),
    ]

    logger.info("transcoding %s -> %s", rendition.label, out_dir)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1)

    stderr_tail: list[str] = []
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            elapsed = _parse_progress(line.strip())
            if elapsed is not None and progress_cb and duration_seconds > 0:
                progress_cb(min(elapsed / duration_seconds, 1.0))
    finally:
        proc.stdout and proc.stdout.close()
        if proc.stderr is not None:
            stderr_tail = proc.stderr.read().splitlines()[-20:]
            proc.stderr.close()
        proc.wait()

    if proc.returncode != 0:
        raise FFmpegError(
            f"Echec du transcodage {rendition.label}: " + "\n".join(stderr_tail)[-1500:]
        )

    if not playlist.exists():
        raise FFmpegError(f"ffmpeg n'a produit aucun manifeste pour {rendition.label}.")

    segments = sorted(out_dir.glob("seg_*.ts"))
    if not segments:
        raise FFmpegError(f"Aucun segment genere pour {rendition.label}.")

    if progress_cb:
        progress_cb(1.0)

    return {
        "playlist": playlist.name,
        "segments": len(segments),
        "bytes": sum(p.stat().st_size for p in segments) + playlist.stat().st_size,
    }


def extract_poster(source: str | Path, dest: str | Path,
                   at_second: float, width: int = 1280) -> None:
    """Grab a single frame as the poster image."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        settings.FFMPEG_BIN, "-hide_banner", "-nostdin", "-y",
        "-ss", f"{max(at_second, 0):.3f}",
        "-i", str(source),
        "-frames:v", "1",
        "-vf", f"scale={width}:-2:flags=bicubic",
        "-q:v", "3",
        "-loglevel", "error",
        str(dest),
    ]
    proc = _run(cmd, timeout=180)
    if proc.returncode != 0 or not dest.exists():
        raise FFmpegError(f"Echec de l'extraction du poster: {proc.stderr.strip()[-800:]}")


def build_sprite_sheet(
    source: str | Path,
    dest: str | Path,
    duration_seconds: float,
    tile_width: int = 160,
    tile_height: int = 90,
    columns: int = 10,
    max_tiles: int = 100,
) -> dict:
    """Render evenly-spaced scrubbing previews into one sprite sheet.

    One sheet instead of N loose JPEGs: the seek bar needs every preview at once,
    and 100 separate requests would defeat the point of previewing.

    Returns the geometry the WebVTT index needs.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # One tile every `interval` seconds, capped so long videos stay one sheet.
    tiles = max(1, min(max_tiles, int(duration_seconds // 5) or 1))
    interval = duration_seconds / tiles
    rows = max(1, -(-tiles // columns))  # ceil division

    cmd = [
        settings.FFMPEG_BIN, "-hide_banner", "-nostdin", "-y",
        "-i", str(source),
        "-vf", (f"fps=1/{interval:.6f},"
                f"scale={tile_width}:{tile_height}:force_original_aspect_ratio=decrease,"
                f"pad={tile_width}:{tile_height}:(ow-iw)/2:(oh-ih)/2:color=black,"
                f"tile={columns}x{rows}"),
        "-frames:v", "1",
        "-q:v", "5",
        "-loglevel", "error",
        str(dest),
    ]
    proc = _run(cmd, timeout=900)
    if proc.returncode != 0 or not dest.exists():
        raise FFmpegError(f"Echec de la planche de miniatures: {proc.stderr.strip()[-800:]}")

    return {
        "tiles": tiles,
        "interval": interval,
        "columns": columns,
        "rows": rows,
        "tile_width": tile_width,
        "tile_height": tile_height,
    }
