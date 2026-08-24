/**
 * WHIP publisher — the browser half of "go live from this device".
 *
 * WHIP (RFC 9725) is deliberately small: POST an SDP offer, get an SDP answer,
 * DELETE the returned resource to hang up. No signalling socket, no library.
 *
 * Two decisions worth knowing about:
 *
 * 1. **H264 is required, not preferred.** The server copies the video track
 *    through to RTMP without re-encoding it, which is what keeps a broadcast
 *    cheap enough to run several at once. VP8 would force a full transcode per
 *    stream. Every current browser can send H264, so asking for it outright and
 *    failing loudly beats silently costing fifty times the CPU.
 *
 * 2. **ICE is gathered fully before the offer is sent** (no trickle). It costs
 *    a second at startup and saves implementing the PATCH half of the protocol
 *    plus its own failure modes. There are no STUN servers to wait on: the
 *    media port is reachable directly.
 */

const SDP_HEADERS = { 'Content-Type': 'application/sdp' }

export class WhipError extends Error {
  constructor(code, detail) {
    super(detail || code)
    this.code = code
  }
}

/** Wait until ICE gathering finishes, or the timeout elapses. */
function iceGathered(pc, timeoutMs = 3000) {
  if (pc.iceGatheringState === 'complete') return Promise.resolve()

  return new Promise((resolve) => {
    const done = () => {
      pc.removeEventListener('icegatheringstatechange', onChange)
      clearTimeout(timer)
      resolve()
    }
    const onChange = () => {
      if (pc.iceGatheringState === 'complete') done()
    }
    // A timeout rather than a hang: gathering can stall on an interface that
    // never answers, and the candidates already collected are usually enough.
    const timer = setTimeout(done, timeoutMs)
    pc.addEventListener('icegatheringstatechange', onChange)
  })
}

/** Pin a transceiver to H264, or say why we cannot. */
function requireH264(transceiver) {
  const capabilities = RTCRtpSender.getCapabilities?.('video')
  if (!capabilities) return // Older browser: let the negotiation decide.

  const h264 = capabilities.codecs.filter((codec) =>
    codec.mimeType.toLowerCase() === 'video/h264',
  )
  if (h264.length === 0) throw new WhipError('no_h264')

  // setCodecPreferences is not universal; where it is missing the SDP order is
  // whatever the browser chose, which in practice still offers H264.
  transceiver.setCodecPreferences?.(h264)
}

/**
 * Publish `stream` to a WHIP endpoint.
 *
 * Returns a handle with `stop()` and the peer connection, so the caller can
 * watch connection state without owning the protocol details.
 */
export async function publish({ url, stream, onStateChange }) {
  if (!window.RTCPeerConnection) throw new WhipError('unsupported')

  const pc = new RTCPeerConnection({
    // No STUN: the server publishes a reachable host candidate itself, and a
    // public STUN lookup would only add a round trip to every broadcast.
    iceServers: [],
    bundlePolicy: 'max-bundle',
  })

  pc.addEventListener('connectionstatechange', () => {
    onStateChange?.(pc.connectionState)
  })

  try {
    for (const track of stream.getTracks()) {
      const transceiver = pc.addTransceiver(track, {
        direction: 'sendonly',
        streams: [stream],
      })
      if (track.kind === 'video') requireH264(transceiver)
    }

    await pc.setLocalDescription(await pc.createOffer())
    await iceGathered(pc)

    const response = await fetch(url, {
      method: 'POST',
      headers: SDP_HEADERS,
      body: pc.localDescription.sdp,
    })

    if (!response.ok) {
      // 400/409 from MediaMTX is nearly always "somebody is already publishing
      // to this path" — worth separating from a credential that expired.
      const code = response.status === 401 || response.status === 403
        ? 'rejected'
        : response.status === 400 || response.status === 409
          ? 'busy'
          : 'failed'
      throw new WhipError(code, `HTTP ${response.status}`)
    }

    const answer = await response.text()
    await pc.setRemoteDescription({ type: 'answer', sdp: answer })

    // nginx rewrites this back under the same-origin WHIP prefix; resolving it
    // against the request URL covers a server that answers with a relative one.
    const location = response.headers.get('Location')
    const resource = location ? new URL(location, window.location.origin + url).href : null

    return {
      pc,
      resource,
      async stop() {
        // Tell the server first: closing the connection alone leaves MediaMTX
        // waiting out its own timeout, and the channel stays `live` meanwhile.
        if (resource) {
          try {
            await fetch(resource, { method: 'DELETE' })
          } catch {
            /* The connection close below ends the session either way. */
          }
        }
        pc.close()
      },
    }
  } catch (error) {
    pc.close()
    throw error
  }
}
