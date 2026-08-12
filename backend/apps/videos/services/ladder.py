"""ABR rendition ladder.

Rule that matters: **never upscale**. A 480p source yields 240p/360p/480p and
stops there. Fabricating a "1080p" rung from a 480p master would cost 4x the
storage and encode time to deliver a blurrier picture at a higher bitrate, and
would lie to the player's bandwidth estimator.

Portrait video is handled by applying the rung to the *short* side, so a
1080x1920 phone recording produces 720x1280 for the "720p" rung rather than a
letterboxed 1280x720.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rung:
    label: str
    short_side: int          # 240, 360, 480, 720, 1080
    video_bitrate_kbps: int
    audio_bitrate_kbps: int
    codecs: str              # RFC 6381, for the master playlist


# Ladder tops out at 1080p on purpose: 4K transcoding on commodity CPU is hours
# per video. Add 1440p/2160p rungs here if you deploy on GPU-encoding hardware.
LADDER: tuple[Rung, ...] = (
    Rung("240p", 240, 400, 64, "avc1.4d400d,mp4a.40.2"),
    Rung("360p", 360, 800, 96, "avc1.4d401e,mp4a.40.2"),
    Rung("480p", 480, 1400, 128, "avc1.4d401e,mp4a.40.2"),
    Rung("720p", 720, 2800, 128, "avc1.4d401f,mp4a.40.2"),
    Rung("1080p", 1080, 5000, 192, "avc1.4d4028,mp4a.40.2"),
)


@dataclass(frozen=True)
class Rendition:
    """A concrete, resolved encode target with even pixel dimensions."""

    label: str
    width: int
    height: int
    video_bitrate_kbps: int
    audio_bitrate_kbps: int
    codecs: str


def _even(value: int) -> int:
    """H.264 4:2:0 requires even dimensions; round down so we never upscale."""
    value = int(value)
    return value - (value % 2) if value % 2 else value


def _scaled(src_w: int, src_h: int, target_short: int) -> tuple[int, int]:
    short = min(src_w, src_h)
    ratio = target_short / short
    return max(_even(src_w * ratio), 2), max(_even(src_h * ratio), 2)


def build_ladder(src_width: int, src_height: int) -> list[Rendition]:
    """Resolve the encode targets for a given source resolution.

    Always returns at least one rendition: a source too small for even the
    bottom rung is encoded once at its native size, so playback still works.
    """
    if src_width <= 0 or src_height <= 0:
        raise ValueError("Source resolution is unknown; cannot build a ladder.")

    short_side = min(src_width, src_height)
    renditions: list[Rendition] = []

    for rung in LADDER:
        if rung.short_side > short_side:
            break  # would upscale — stop climbing
        width, height = _scaled(src_width, src_height, rung.short_side)
        renditions.append(
            Rendition(
                label=rung.label,
                width=width,
                height=height,
                video_bitrate_kbps=rung.video_bitrate_kbps,
                audio_bitrate_kbps=rung.audio_bitrate_kbps,
                codecs=rung.codecs,
            )
        )

    if not renditions:
        # Source shorter than 240p (e.g. a 176x144 clip). Encode it as-is.
        bottom = LADDER[0]
        renditions.append(
            Rendition(
                label=f"{short_side}p",
                width=_even(src_width),
                height=_even(src_height),
                video_bitrate_kbps=bottom.video_bitrate_kbps,
                audio_bitrate_kbps=bottom.audio_bitrate_kbps,
                codecs=bottom.codecs,
            )
        )

    return renditions
