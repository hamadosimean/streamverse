"""HLS packaging: master playlist and the WebVTT thumbnail index.

ffmpeg writes each *variant* playlist; the master that ties them together is
written here so the ordering, bandwidth advertisement and codec strings are
under our control rather than a side effect of encoder flags.
"""
from __future__ import annotations

from pathlib import Path

from apps.videos.services.ladder import Rendition


def _bandwidth(rendition: Rendition) -> int:
    """Peak bits/s the player should budget for this rung.

    8% over the nominal video+audio bitrate covers TS container overhead. Getting
    this wrong in the low direction makes the player over-select a rung it cannot
    sustain and stall.
    """
    return int((rendition.video_bitrate_kbps + rendition.audio_bitrate_kbps) * 1000 * 1.08)


def build_master_playlist(renditions: list[tuple[Rendition, str]]) -> str:
    """Render the master `.m3u8`.

    `renditions` is a list of `(rendition, relative_playlist_path)`, ordered
    lowest-quality first so a player that cannot measure bandwidth yet starts on
    something that will actually play.
    """
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-INDEPENDENT-SEGMENTS", ""]

    for rendition, rel_path in renditions:
        bandwidth = _bandwidth(rendition)
        lines.append(
            "#EXT-X-STREAM-INF:"
            f"BANDWIDTH={bandwidth},"
            f"AVERAGE-BANDWIDTH={int(bandwidth * 0.9)},"
            f"RESOLUTION={rendition.width}x{rendition.height},"
            f'CODECS="{rendition.codecs}"'
        )
        lines.append(rel_path)

    return "\n".join(lines) + "\n"


def _timestamp(seconds: float) -> str:
    hours, rem = divmod(max(seconds, 0), 3600)
    minutes, secs = divmod(rem, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{secs:06.3f}"


def build_thumbnail_vtt(sprite_filename: str, geometry: dict,
                        duration_seconds: float) -> str:
    """WebVTT index over the sprite sheet, using media fragment `#xywh=`.

    Emitted for interoperability with third-party players. Our own player uses
    `Video.sprite_meta` instead, because a private video's sprite is reached via a
    presigned URL and rewriting every cue in the VTT for that case would be pure
    overhead.
    """
    tiles = geometry["tiles"]
    interval = geometry["interval"]
    columns = geometry["columns"]
    tw = geometry["tile_width"]
    th = geometry["tile_height"]

    lines = ["WEBVTT", ""]
    for index in range(tiles):
        start = index * interval
        end = min((index + 1) * interval, duration_seconds)
        if end <= start:
            break
        x = (index % columns) * tw
        y = (index // columns) * th
        lines.append(f"{_timestamp(start)} --> {_timestamp(end)}")
        lines.append(f"{sprite_filename}#xywh={x},{y},{tw},{th}")
        lines.append("")

    return "\n".join(lines)


def sprite_tile_positions(geometry: dict, duration_seconds: float):
    """Yield `(timestamp, x, y)` for each tile — used to create VideoThumbnail rows."""
    tiles = geometry["tiles"]
    interval = geometry["interval"]
    columns = geometry["columns"]
    tw = geometry["tile_width"]
    th = geometry["tile_height"]

    for index in range(tiles):
        timestamp = min(index * interval, duration_seconds)
        yield timestamp, (index % columns) * tw, (index // columns) * th, tw, th


def rewrite_variant_playlist(playlist_text: str, url_for_segment) -> str:
    """Replace relative segment names with absolute (presigned) URLs.

    Used for private videos: Django hands the player a manifest whose segment
    lines point straight at MinIO, so Django serves kilobytes of text once and
    never touches a media byte.

    Comment lines (`#EXTINF`, `#EXT-X-*`) are passed through untouched — except
    `#EXT-X-KEY`/`#EXT-X-MAP`, which carry URIs and would otherwise be left
    dangling. They are not produced by our current encode settings, but rewriting
    them keeps this correct if fMP4 or encryption is enabled later.
    """
    out: list[str] = []
    for raw in playlist_text.splitlines():
        line = raw.strip()
        if not line:
            out.append(raw)
            continue
        if line.startswith("#"):
            if 'URI="' in line:
                head, _, rest = line.partition('URI="')
                uri, _, tail = rest.partition('"')
                out.append(f'{head}URI="{url_for_segment(uri)}"{tail}')
            else:
                out.append(raw)
            continue
        out.append(url_for_segment(line))
    return "\n".join(out) + "\n"
