#!/bin/sh
# Bridge one browser broadcast (WebRTC/WHIP) into the normal RTMP ingest path.
#
# Run by MediaMTX as `runOnAvailable` on `webrtc/<slug>`, with MTX_PATH in the
# environment. MediaMTX kills it when the publisher disconnects.
#
# Why this exists: a browser can only send Opus audio over WebRTC, and the HLS
# output every viewer plays is MPEG-TS, which cannot carry Opus. So the audio is
# re-encoded to AAC and the video — H264, which the WHIP client insists on when
# it negotiates — is copied through without touching a single frame. The cost is
# one audio encode per live broadcast; a video transcode would cost fifty times
# that.
#
# The output is an ordinary RTMP publish to `live/<slug>`, so from here on a
# browser broadcast is indistinguishable from an OBS one: same publish auth,
# same ready hook, same recording, same VOD conversion.
set -eu

SLUG="${MTX_PATH#webrtc/}"

if [ -z "$SLUG" ] || [ "$SLUG" = "$MTX_PATH" ]; then
    echo "[bridge] refusing to bridge unexpected path: ${MTX_PATH}" >&2
    exit 1
fi

echo "[bridge] ${MTX_PATH} -> live/${SLUG}"

# `-bridge=1` is not decoration: Django only accepts the hook secret as a
# publish credential for a request that also identifies itself as the bridge,
# and only from inside this container.
exec ffmpeg -hide_banner -loglevel warning -nostdin \
    -rtsp_transport tcp -i "rtsp://127.0.0.1:8554/${MTX_PATH}" \
    -c:v copy \
    -c:a aac -ar 48000 -ac 2 -b:a 128k \
    -f flv "rtmp://127.0.0.1:1935/live/${SLUG}?key=${MTX_HOOK_SECRET}&bridge=1"
