# StreamVerse — Configuration Reference

Every knob in the stack, where it is read, what it defaults to, and what breaks
if it is wrong.

**Principle:** nothing secret is hardcoded. All runtime configuration is
environment-driven; `backend/config/settings.py` is the single reader.

---

## Table of Contents

1. [How Configuration Flows](#1-how-configuration-flows)
2. [Required Before First Boot](#2-required-before-first-boot)
3. [Django Core](#3-django-core)
4. [Public Identity & SEO](#4-public-identity--seo)
5. [Security & TLS](#5-security--tls)
6. [Authentication](#6-authentication)
7. [Database](#7-database)
8. [Redis, Cache, Channels, Celery](#8-redis-cache-channels-celery)
9. [Object Storage (MinIO / S3)](#9-object-storage-minio--s3)
10. [Upload & Transcoding](#10-upload--transcoding)
11. [Shorts](#11-shorts)
12. [Engagement & Search](#12-engagement--search)
13. [Live Streaming](#13-live-streaming)
14. [Monetization](#14-monetization)
15. [Rate Limits](#15-rate-limits)
16. [Email](#16-email)
17. [Host Ports](#17-host-ports)
18. [Frontend Build-Time Configuration](#18-frontend-build-time-configuration)
19. [Non-Environment Configuration Files](#19-non-environment-configuration-files)
20. [Scheduled Jobs](#20-scheduled-jobs)
21. [Secrets Inventory](#21-secrets-inventory)
22. [Known Gaps](#22-known-gaps)

---

## 1. How Configuration Flows

```
 .env  (repo root, gitignored)
   │
   │  read by docker compose for ${VAR} substitution
   ▼
docker-compose.yml
   ├─ x-backend-env anchor  ──► backend · celery-worker · celery-beat · flower
   ├─ service environment:  ──► db · minio · mailpit · mediamtx · nginx
   └─ build args:           ──► frontend (baked into the JS bundle)
        │
        ▼
   container environment variables
        │
        ▼
backend/config/settings.py   (django-environ)
```

Two things follow from this that catch people out:

**1. Inside a container, `.env` is never read by Django.** `settings.py` calls
`environ.Env.read_env(BASE_DIR.parent / ".env")`, and `BASE_DIR` is `/app`, so it
looks for `/.env` — which does not exist in the image. Every value therefore
arrives as a real environment variable placed there by compose. **A variable that
compose does not forward has no effect in Docker, no matter what `.env` says.**
See [§22](#22-known-gaps) for the current list.

That same call *does* work for a bare-metal run (`python manage.py runserver`
from `backend/`), where `BASE_DIR.parent` is the repo root.

**2. An unset variable becomes an empty string, not a default.** Compose
substitutes `${VAR}` with `""` when it is missing from the env file, and
django-environ treats a present-but-empty variable as a value — so the default in
`settings.py` is *not* used. Every entry in the `x-backend-env` anchor that could
be omitted therefore carries a compose-level fallback (`${VAR:-default}`). When
you add a new variable, give it one too.

### Environment files

| File | Tracked | Purpose |
|---|---|---|
| `.env.example` | yes | The documented template. Copy it to `.env`. |
| `.env` | **no** (gitignored) | What compose actually reads. |
| `.env.prod` | **not currently gitignored** — see [§22](#22-known-gaps) | Production values. Use with `docker compose --env-file .env.prod up -d`. |

```bash
cp .env.example .env
python3 -c "import secrets; print('DJANGO_SECRET_KEY=' + secrets.token_urlsafe(64))"
# paste the result into .env
docker compose up --build
```

Legend for the tables below — **Fwd** = forwarded to the backend containers by
`docker-compose.yml`:

| Symbol | Meaning |
|---|---|
| ✅ | Forwarded; setting it in `.env` works. |
| ➖ | Not forwarded — the `settings.py` default always applies under Docker. |
| 🔒 | Secret. Never commit a real value. |

---

## 2. Required Before First Boot

| Variable | Why |
|---|---|
| `DJANGO_SECRET_KEY` 🔒 | Compose refuses to start without it (`${DJANGO_SECRET_KEY:?}`). It also seeds several derived secrets — see [§21](#21-secrets-inventory). |

Everything else has a working default. For production, [§22](#22-known-gaps) and
[DEPLOYMENT.md §2](./DEPLOYMENT.md) list what must additionally change.

---

## 3. Django Core

| Variable | Default | Fwd | Effect |
|---|---|---|---|
| `DEBUG` | `False` | ✅ | Never `1` in production — it disables the security block at the bottom of `settings.py` and serves media from the app. |
| `DJANGO_SECRET_KEY` 🔒 | `dev-insecure-change-me` | ✅ | Signs sessions, tokens, password-reset links, view dedup keys and IP hashes. **Rotating it invalidates every active session and every unexpired reset link, and changes view-dedup hashes.** |
| `ALLOWED_HOSTS` | `*` | ✅ | Comma-separated. Also gates WebSocket origins via `AllowedHostsOriginValidator`. |
| `CORS_ALLOWED_ORIGINS` | *(empty)* | ✅ | Comma-separated origins. Credentials are allowed, so this cannot be `*`. |
| `CSRF_TRUSTED_ORIGINS` | *(empty)* | ✅ | Needed for the Django admin behind a proxy. Must include the scheme. |
| `FRONTEND_URL` | `http://localhost:8110` | ✅ | Base for activation and password-reset links in outgoing email. |
| `LOG_LEVEL` | `INFO` | ✅ | Applies to the root logger and the `apps` logger. |
| `TIME_ZONE` | `UTC` | ✅ | Also becomes `CELERY_TIMEZONE`, so beat schedules follow it. Storage is always UTC (`USE_TZ = True`). |

Language is fixed in code, not by environment: `LANGUAGE_CODE = "fr"`, with
`fr` and `en` available. French is the default UI language; per-user preference
lives on `User.preferred_language`.

---

## 4. Public Identity & SEO

These exist because sitemaps, `robots.txt` and Open Graph tags must emit
**absolute** URLs and often have no request to derive them from.

| Variable | Default | Fwd | Effect |
|---|---|---|---|
| `SITE_URL` | `http://localhost:8110` | ✅ | Origin for canonical URLs, `og:url`, `og:image` and the sitemap protocol. Must be the origin users actually type, including the port. |
| `SITE_NAME` | `StreamVerse` | ✅ | `og:site_name`, JSON-LD publisher name. |
| `SITE_DESCRIPTION` | French one-liner | ✅ | Default meta description for the site preview. |

> Set `SITE_URL` explicitly for any deployment that is not on `localhost:8110`.
> The compose fallback keeps it from arriving empty, but a fallback pointing at
> localhost is still wrong for a real host: link previews would emit `og:url`
> and `og:image` that no crawler can fetch.

---

## 5. Security & TLS

All default to off, because the demo runs on plain HTTP. Turn them on together
with real TLS.

| Variable | Default | Fwd | Effect |
|---|---|---|---|
| `SECURE_SSL_REDIRECT` | `0` | ✅ | Django-level HTTP→HTTPS redirect. Only applies when `DEBUG=0`. |
| `SESSION_COOKIE_SECURE` | `0` | ✅ | Only applies when `DEBUG=0`. |
| `CSRF_COOKIE_SECURE` | `0` | ✅ | Only applies when `DEBUG=0`. |
| `SECURE_HSTS_SECONDS` | `0` | ✅ | **Effectively irreversible for its duration.** A browser that has seen it refuses plain HTTP to the host even if the certificate later lapses. Set `31536000` only once TLS is permanent. |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | `True` | ➖ | |
| `SECURE_HSTS_PRELOAD` | `False` | ➖ | |

Hardcoded and not configurable: `SECURE_PROXY_SSL_HEADER` (trusts
`X-Forwarded-Proto` from nginx), `X_FRAME_OPTIONS = DENY`,
`SECURE_CONTENT_TYPE_NOSNIFF`, `SECURE_REFERRER_POLICY = same-origin`,
`SESSION_COOKIE_HTTPONLY`, and `SameSite=Lax` on both cookies.

The Content-Security-Policy and Permissions-Policy headers are **not** Django
settings — they are built in `nginx/templates/default.conf.template`
([§19](#19-non-environment-configuration-files)).

---

## 6. Authentication

| Variable | Default | Fwd | Effect |
|---|---|---|---|
| `JWT_ACCESS_MINUTES` | `15` | ✅ | Access-token lifetime. Also bounds how long a WebSocket `?token=` stays valid. |
| `JWT_REFRESH_DAYS` | `7` | ✅ | Refresh-token lifetime. |

Fixed in code: refresh-token rotation with blacklist-after-rotation, `Bearer`
header type, `UPDATE_LAST_LOGIN`, email as the login field, activation email
required on signup, and `SuspensionAwareJWTAuthentication` — which re-checks
suspension on **every** request, not just at login.

---

## 7. Database

| Variable | Default | Fwd | Effect |
|---|---|---|---|
| `POSTGRES_DB` | `streamverse` | ✅ | |
| `POSTGRES_USER` | `streamverse` | ✅ | |
| `POSTGRES_PASSWORD` 🔒 | `streamverse` | ✅ | Change for any deployment reachable from outside the host. |
| `POSTGRES_HOST` | `db` | ✅ (pinned to `db`) | |
| `POSTGRES_PORT` | `5432` | ✅ (pinned to `5432`) | Container port — the host port is `POSTGRES_HOST_PORT`. |

`CONN_MAX_AGE` is fixed at 60 s in `settings.py`. Raising it (or adding
PgBouncer) is a code change, not an env change.

---

## 8. Redis, Cache, Channels, Celery

One Redis instance, four logical databases — separated so flushing the cache
cannot drop queued tasks.

| Variable | Value in compose | Fwd | Used for |
|---|---|---|---|
| `REDIS_URL` | `redis://redis:6379/0` | ✅ | General / default |
| `CHANNEL_REDIS_URL` | `redis://redis:6379/1` | ✅ | Channels layer (WebSocket fan-out) |
| `CACHE_REDIS_URL` | `redis://redis:6379/2` | ✅ | Django cache (trending rails, health probe) |
| `CELERY_BROKER_URL` | `redis://redis:6379/3` | ✅ | Celery broker |

| Variable | Default | Fwd | Effect |
|---|---|---|---|
| `CELERY_WORKER_CONCURRENCY` | `2` | ✅ (worker only) | **Match to physical cores, not threads.** Each slot can saturate a core for the length of an encode. |
| `CELERY_TASK_TIME_LIMIT` | `21600` (6 h) | ➖ | Hard kill for a transcode. |
| `CELERY_TASK_SOFT_TIME_LIMIT` | `21300` | ➖ | Raises inside the task so it can clean up. |
| `CELERY_QUEUES` | `transcode,default` | ➖ (entrypoint) | Which queues this worker consumes. |
| `CELERY_LOG_LEVEL` | `info` | ➖ (entrypoint) | |
| `UVICORN_WORKERS` | `2` | ✅ | ASGI worker processes. |
| `FLOWER_USER` / `FLOWER_PASSWORD` 🔒 | `admin` / `admin` | ✅ | Basic auth on the Flower UI. **Change or firewall it** — Flower can inspect and revoke tasks. |

Results are stored in PostgreSQL (`django-celery-results`), and the beat
schedule in PostgreSQL (`django-celery-beat` `DatabaseScheduler`), so a
schedule edited in the admin survives a restart.

**Queue routing** — `videos.transcode.*` and `live.convert_recording_to_vod` go
to the `transcode` queue; everything else to `default`. A burst of uploads
therefore never starves the cheap bookkeeping tasks. `CELERY_ACKS_LATE = True`
and `prefetch_multiplier = 1` are fixed: long jobs must not be hoarded or lost.

---

## 9. Object Storage (MinIO / S3)

Two endpoints exist on purpose:

- **internal** (`MINIO_ENDPOINT`) — what Django and Celery use inside the compose network;
- **public** (`MINIO_PUBLIC_ENDPOINT`) — what the **browser** uses.

Presigned URLs must be signed against the *public* host, or the SigV4 signature
will not match the `Host` header the browser actually sends.

| Variable | Default | Fwd | Effect |
|---|---|---|---|
| `MINIO_ENDPOINT` | `http://minio:9000` | ✅ (pinned) | Internal S3 API. |
| `MINIO_PUBLIC_ENDPOINT` | `http://localhost:9010` | ✅ | **The one people get wrong.** Change it when the stack moves off localhost or private playback fails signature validation. Also interpolated into the nginx CSP, so posters, manifests and segments are only loadable from this origin. |
| `MINIO_ROOT_USER` → `MINIO_ACCESS_KEY` | `streamverse` | ✅ | |
| `MINIO_ROOT_PASSWORD` → `MINIO_SECRET_KEY` 🔒 | `streamverse-secret` | ✅ | |
| `MINIO_PUBLIC_BUCKET` | `streamverse-public` | ✅ | Anonymous read. Holds public + unlisted HLS, posters, avatars, channel banners, ad creatives. |
| `MINIO_PRIVATE_BUCKET` | `streamverse-private` | ✅ | Presigned access only. Holds private HLS **and every uploaded original**, whatever the visibility. |
| `MINIO_PRESIGN_TTL_SECONDS` | `21600` (6 h) | ✅ | Lifetime of a presigned playback session. Shorter is safer; too short and a long viewing session dies mid-playback. |
| `MINIO_REGION` | `us-east-1` | ➖ | Signature region. |

Buckets and their access policies are provisioned on first boot by
`manage.py init_minio`, run from the backend entrypoint. Path-style addressing
is fixed (`addressing_style: path`) because MinIO does not do virtual-host
buckets by default.

---

## 10. Upload & Transcoding

| Variable | Default | Fwd | Effect |
|---|---|---|---|
| `UPLOAD_SCRATCH_DIR` | `/data/uploads` | ✅ (pinned) | tus chunks + source files. Shared volume between backend and worker. |
| `TRANSCODE_WORK_DIR` | `/data/work` | ✅ (pinned) | ffmpeg scratch space, swept by a beat task. |
| `MAX_UPLOAD_BYTES` | `5368709120` (5 GiB) | ✅ | Server-side cap. nginx separately caps a single request body at `128m`. |
| `MAX_VIDEO_DURATION_SECONDS` | `14400` (4 h) | ✅ | Rejected after probing. |
| `UPLOAD_SESSION_TTL_HOURS` | `24` | ✅ | Abandoned tus sessions swept after this. |
| `FFMPEG_BIN` / `FFPROBE_BIN` | `ffmpeg` / `ffprobe` | ➖ | Both ship in the backend image. |
| `FFMPEG_VIDEO_ENCODER` | `libx264` | ✅ | Set `h264_nvenc` (NVIDIA) or `h264_vaapi` (Intel/AMD) for hardware encoding — the host needs the driver and the container the device. |
| `FFMPEG_PRESET` | `veryfast` | ✅ | `medium`/`slow` give better quality per bit at multiples of the wall-clock cost. |
| `HLS_SEGMENT_SECONDS` | `4` | ✅ | VOD segment length. Shorter = faster start-up, more requests. (Live segment length is set in `mediamtx.yml`, not here.) |

Accepted upload MIME types are fixed in `settings.py`: MP4, QuickTime,
Matroska, WebM, AVI, MPEG, 3GPP, FLV.

The ABR ladder itself (240p–1080p, bitrates, RFC 6381 codec strings) is code,
not configuration: `backend/apps/videos/services/ladder.py`. It never upscales
past the source, and applies each rung to the **short** side so portrait video
is not letterboxed.

### Profile images

Avatars and channel banners are a separate path from the video pipeline: an
ordinary multipart `PUT`, no tus, no Celery, straight into the **public** bucket.

| Variable | Default | Fwd | Effect |
|---|---|---|---|
| `MAX_AVATAR_BYTES` | `5242880` (5 MiB) | ✅ | Rejected before decoding. |
| `MAX_BANNER_BYTES` | `10485760` (10 MiB) | ✅ | |
| `MAX_AVATAR_DIMENSION` | `2048` | ✅ | Longest side, in pixels. |
| `MAX_BANNER_DIMENSION` | `6000` | ✅ | Wider than an avatar: a banner is a strip. |

Accepted formats are fixed in `settings.py` (`ALLOWED_IMAGE_MIME_TYPES`): JPEG,
PNG, WebP, GIF. Which one a file *is* comes from decoding it with Pillow — the
`Content-Type` header and the filename are client-supplied strings and neither
is trusted. The frontend applies the same size limits before uploading, but only
to save the user a transfer they were going to lose anyway.

Raising these means every viewer of a channel page pays the difference, so the
ceilings are about page weight rather than disk.

---

## 11. Shorts

| Variable | Default | Fwd | Effect |
|---|---|---|---|
| `SHORTS_MAX_DURATION_SECONDS` | `90` | ➖ | |
| `SHORTS_MAX_ASPECT_RATIO` | `1.0` | ➖ | Width ÷ height. `1.0` admits square; anything wider is landscape. |

A video becomes a Short only when it satisfies **both** — derived from ffprobe
output at transcode time, never accepted from the uploader. Otherwise any video
could declare itself a Short to jump into the full-screen feed.

---

## 12. Engagement & Search

| Variable | Default | Fwd | Effect |
|---|---|---|---|
| `VIEW_MIN_SECONDS` | `30` | ✅ | Watch time before a view counts — or 30 % of the duration when that is smaller, so short clips stay countable. Enforced server-side. |
| `VIEW_DEDUP_WINDOW_SECONDS` | `43200` (12 h) | ✅ | Repeat views from one identity inside this window collapse into one row. |
| `SEARCH_LANGUAGE_CONFIG` | `french` | ✅ | PostgreSQL text-search dictionary. Use `simple` for a mixed-language catalogue where stemming does more harm than good. **Changing it requires a reindex** — run the `engagement.rebuild_search_index` task, or wait for its 4-hourly beat. |

---

## 13. Live Streaming

| Variable | Default | Fwd | Effect |
|---|---|---|---|
| `LIVE_RTMP_APP` | `live` | ✅ | RTMP application segment. Full path is `<app>/<channel-slug>`. |
| `LIVE_RTMP_PUBLIC_URL` | `rtmp://localhost:1936` | ✅ | What broadcasters type into OBS's **Server** field. Change the host when you move off localhost. |
| `LIVE_HLS_PUBLIC_PATH` | `/live-hls` | ✅ | Same-origin path where nginx proxies MediaMTX's HLS output. Changing it means editing the nginx template too. |
| `LIVE_MEDIAMTX_API` | `http://mediamtx:9997` | ✅ (pinned) | Control API used to reconcile channels stuck in `live`. Never published. |
| `LIVE_HOOK_SECRET` 🔒 | first 32 chars of `DJANGO_SECRET_KEY` | ✅ | Shared secret for the ready / not-ready hooks, sent as `X-Live-Hook-Secret`. Also injected into MediaMTX as `MTX_HOOK_SECRET`. |
| `LIVE_RECORDINGS_DIR` | `/data/recordings` | ✅ | Shared volume: MediaMTX writes, the Celery worker reads. Present in `.env`, absent from `.env.example`. |
| `LIVE_RECORDING_SETTLE_SECONDS` | `20` | ✅ | Grace period before touching a recording — MediaMTX is still flushing when the hook fires. |
| `LIVE_RECORDING_RETENTION_DAYS` | `7` | ✅ | Raw recordings deleted this long after conversion to VOD. |
| `LIVE_CHAT_MIN_INTERVAL_SECONDS` | `1.0` | ✅ | Per-socket message spacing. DRF throttles never see a WebSocket frame, so the consumer enforces this itself. |

**Two auth paths, on purpose.** *Publishing* is authorised by MediaMTX calling
`/api/live/auth/`, which compares the stream key in constant time. *Playback* is
authorised one layer out: nginx `auth_request`s `/api/live/authz/` for every
**playlist** fetch — MediaMTX's own read-auth completes with a `Secure` cookie
that browsers refuse over plain HTTP. Segments are not individually authorised;
a player cannot keep playing without refreshing the playlist every couple of
seconds, so that is where a takedown actually bites, while the bulk of the bytes
never touch Django.

Both `/api/live/auth/`, `/api/live/authz/` and `/api/live/hooks/*` are **404'd
by nginx at the edge** and reachable only from inside the compose network.

---

## 14. Monetization

| Variable | Default | Fwd | Effect |
|---|---|---|---|
| `PAYMENTS_USE_MOCK` | `True` | ✅ | The single switch between the simulator and real providers. While on, the checkout UI shows a sandbox banner. |
| `MOCK_PAYMENT_WEBHOOK_SECRET` 🔒 | first 40 chars of `DJANGO_SECRET_KEY` | ✅ | HMAC secret the mock signs callbacks with and the verifier checks. |
| `MOCK_PAYMENT_CONFIRM_DELAY_SECONDS` | `8` | ✅ | How long the simulated payer takes to confirm. |
| `MOCK_PAYMENT_FAILURE_PERCENT` | `15` | ✅ | Share of simulated payments that fail, so the failure path is exercised by the demo and not only by a test. |
| `PAYMENT_PENDING_TIMEOUT_MINUTES` | `30` | ✅ | A pending payment nobody confirmed is failed after this. Without it the open-subscription constraint would block the user from ever retrying. |
| `RENEWAL_LEAD_HOURS` | `24` | ✅ | How far ahead of period end renewals are attempted. |
| `INTERNAL_API_BASE_URL` | `http://backend:8000` | ✅ (pinned) | Where Celery delivers simulated webhooks — inside the compose network, so they never leave the host. |
| `ADS_ENABLED` | `True` | ✅ | Master switch for ad selection. |
| `ADS_MIN_DURATION_FOR_MIDROLL` | `120` | ✅ | Mid-roll on a 20-second clip is user-hostile. |

Prices, billing periods and benefits are **data**, not configuration —
`SubscriptionPlan` rows, editable in the admin. All amounts are integer FCFA.

---

## 15. Rate Limits

DRF scoped throttles. Format is DRF's own (`<n>/<period>`).

| Variable | Default | Fwd | Applies to |
|---|---|---|---|
| `THROTTLE_UPLOAD` | `20/hour` | ✅ | Upload session creation |
| `THROTTLE_AUTH` | `30/hour` | ✅ | Login / registration / password reset |
| `THROTTLE_COMMENT` | `60/hour` | ✅ | Comment creation |
| `THROTTLE_LIVE_START` | `10/hour` | ✅ | Live session start / key rotation |
| `THROTTLE_CHECKOUT` | `20/hour` | ✅ | Payment checkout |

WebSocket traffic is **not** covered by these — throttles never see a frame.
Live chat is rate-limited by `LIVE_CHAT_MIN_INTERVAL_SECONDS` in the consumer.

---

## 16. Email

| Variable | Default | Fwd | Effect |
|---|---|---|---|
| `EMAIL_HOST` | `mailpit` | ✅ (pinned) | |
| `EMAIL_PORT` | `1025` | ✅ (pinned) | |
| `EMAIL_USE_TLS` | `False` | ➖ | |
| `DEFAULT_FROM_EMAIL` | `no-reply@streamverse.local` | ✅ | |

Mailpit is a development catcher — it accepts anything and delivers nothing.
Activation emails land at http://localhost:8045. Pointing at a real SMTP
provider requires forwarding `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` and
`EMAIL_USE_TLS` in `docker-compose.yml`, which the file does not do today; see
[DEPLOYMENT.md §6](./DEPLOYMENT.md).

---

## 17. Host Ports

Deliberately non-default so the stack can share a server with other projects.
These affect only the host side of the mapping; container ports are fixed.

| Variable | Host | Container | Service |
|---|---|---|---|
| `APP_HOST_PORT` | `8110` | 80 | nginx — the only port a user needs |
| `POSTGRES_HOST_PORT` | `5459` | 5432 | PostgreSQL |
| `REDIS_HOST_PORT` | `6402` | 6379 | Redis |
| `FLOWER_HOST_PORT` | `5574` | 5555 | Flower |
| `MAILPIT_HOST_PORT` | `8045` | 8025 | Mailpit UI |
| `MINIO_API_HOST_PORT` | `9010` | 9000 | MinIO S3 API — **the browser fetches HLS here** |
| `MINIO_CONSOLE_HOST_PORT` | `9011` | 9001 | MinIO console |
| `RTMP_HOST_PORT` | `1936` | 1935 | MediaMTX RTMP ingest |

Not published at all: MediaMTX HLS (`:8888`, proxied at `/live-hls/`), MediaMTX
control API (`:9997`), and the frontend container (`:80`, proxied by nginx).

Changing `MINIO_API_HOST_PORT` means changing `MINIO_PUBLIC_ENDPOINT` to match,
or every presigned URL will point at a port that does not answer.

---

## 18. Frontend Build-Time Configuration

Vite bakes these into the bundle at **build** time. Changing them requires
`docker compose build frontend` — restarting the container does nothing.

| Variable | Default | Effect |
|---|---|---|
| `VITE_API_BASE_URL` | `/api` | Same-origin by default, so there is no CORS preflight on ordinary API calls. |
| `VITE_WS_BASE_URL` | `/ws` | WebSocket base. The access token travels as `?token=` because browsers cannot set headers on a WS handshake. |

Never put a secret in a `VITE_*` variable — it ships to every visitor.

---

## 19. Non-Environment Configuration Files

| File | Configures | Notable contents |
|---|---|---|
| `nginx/templates/default.conf.template` | The edge proxy | Content-Security-Policy and Permissions-Policy (built with `map`), the social-crawler split for link previews, the `auth_request` gate on live playlists, the 404 on `/api/live/(auth\|authz\|hooks)/`, 128 MiB body cap, 1-hour WebSocket read timeout. `${MINIO_PUBLIC_ENDPOINT}` is substituted at container start; `NGINX_ENVSUBST_FILTER` restricts substitution to that one name so nginx's own `$host`/`$request_uri` survive. |
| `frontend/nginx-spa.conf` | The SPA container | History-API fallback to `index.html`. |
| `mediamtx/mediamtx.yml` | RTMP ingest | `authHTTPAddress` → Django; reads excluded from MediaMTX auth on purpose; `hlsVariant: mpegts` (most reliable across browsers), 2 s segments × 7, `hlsAlwaysRemux`, fMP4 recording to `/recordings/%path/...`, and the `runOnAvailable` / `runOnUnavailable` hooks that call Django. |
| `backend/entrypoint.sh` | Container role dispatch | `asgi \| worker \| beat \| flower` from `$1`. The `asgi` role runs migrate → collectstatic → `init_minio` → optional seed before serving. Worker and beat call `wait_for_migrations` so they cannot race it. |
| `backend/config/celery.py` | Queues and beat schedule | See [§20](#20-scheduled-jobs). |
| `backend/config/jazzmin.py` | Django admin theme | Branding only. |
| `docker-compose.yml` | Service topology | The `x-backend-env` anchor is the definitive list of what reaches the backend containers. |

| Variable | Default | Effect |
|---|---|---|
| `SEED_ON_START` | `1` | Runs `manage.py seed` on backend boot. **Set to `0` in production.** The seed generates ~15 real clips with ffmpeg and pushes them through the actual pipeline. |

---

## 20. Scheduled Jobs

Defined in `backend/config/celery.py`, stored in PostgreSQL by
`django-celery-beat` — so a schedule edited in the Django admin overrides the
code default and survives restarts.

| Task | Schedule | Purpose |
|---|---|---|
| `videos.maintenance.cleanup_abandoned_uploads` | every 30 min | Sweep unfinished tus sessions + scratch files |
| `videos.maintenance.cleanup_stale_workdirs` | every 6 h | Remove work dirs left by crashed workers |
| `engagement.reconcile_counters` | hourly (:20) | Re-derive denormalised counters from source rows |
| `engagement.refresh_trending_cache` | every 10 min | Pre-aggregate the homepage rails |
| `engagement.rebuild_search_index` | every 4 h (:45) | Safety net for search vectors changed out-of-band |
| `engagement.prune_view_rows` | daily 04:00 | Drop raw view rows past retention |
| `live.reconcile_live_state` | every 2 min | Poll MediaMTX; the not-ready hook is best-effort |
| `live.cleanup_old_recordings` | daily 04:30 | Delete raw recordings already converted to VOD |
| `monetization.sweep_stale_payments` | every 10 min | Fail payments nobody confirmed, so the user can retry |
| `monetization.process_renewals` | every 6 h | Create renewal transactions |
| `monetization.expire_subscriptions` | hourly (:05) | |
| `monetization.expire_campaigns` | hourly (:25) | |
| `monetization.aggregate_ad_stats` | hourly (:40) | Re-derive campaign counters from impressions |
| `monetization.revenue_snapshot` | hourly (:50) | Admin dashboard aggregate |

---

## 21. Secrets Inventory

| Secret | Default | Risk if left at default |
|---|---|---|
| `DJANGO_SECRET_KEY` | none — boot fails | Forgeable sessions and tokens. Also the fallback seed for the two secrets below and the salt for view-dedup + IP hashes. |
| `POSTGRES_PASSWORD` | `streamverse` | Full database access via the published host port. |
| `MINIO_ROOT_PASSWORD` | `streamverse-secret` | Full object-store access, including every private original. |
| `LIVE_HOOK_SECRET` | derived from the secret key | Forged stream lifecycle events. |
| `MOCK_PAYMENT_WEBHOOK_SECRET` | derived from the secret key | Forged payment confirmations — a free subscription. |
| `FLOWER_PASSWORD` | `admin` | Task inspection and revocation. |

Per-row secrets not covered by environment: `LiveChannel.stream_key` (32-byte
URL-safe token per channel, rotatable by its owner) and
`Transaction.idempotency_key`.

---

## 22. Known Gaps

The five wiring defects previously listed here have been fixed. What follows is
what remains.

**Resolved** (verified with `docker compose config` — the backend service now
resolves every variable in the anchor to a non-empty value):

| Was | Fix |
|---|---|
| `docker-compose.yml` interpolated `${MOCK_PAYMENT_WEBHOOK_SECRETt}` — a stray trailing `t` — so the setting was always empty and silently fell back to a slice of `DJANGO_SECRET_KEY` | Typo corrected |
| 17 documented variables were never forwarded to the containers | Added to the `x-backend-env` anchor, each with a fallback mirroring `settings.py` |
| `SITE_URL` / `SITE_NAME` were forwarded without a fallback, so omitting them overrode the `settings.py` defaults with empty strings | Compose fallbacks added; both keys added to `.env` and `.env.prod` |
| `.env.prod` was not gitignored despite holding a real secret key and passwords | `.gitignore` now ignores `.env` and `.env.*`, re-admitting `.env.example` |
| `LIVE_RECORDINGS_DIR` was required by compose but absent from `.env.example` | Documented in `.env.example`, and given a `/data/recordings` fallback |

**Still open**

**1. Real SMTP needs three more variables wired.** `EMAIL_HOST_USER`,
`EMAIL_HOST_PASSWORD` and `EMAIL_USE_TLS` are read by `settings.py` but are not
in the `x-backend-env` anchor, and `EMAIL_HOST` / `EMAIL_PORT` are pinned to
`mailpit:1025`. Moving off Mailpit means editing `docker-compose.yml`, not just
`.env`. See [DEPLOYMENT.md §6](./DEPLOYMENT.md).

**2. A handful of settings are reachable only by editing `settings.py`.** They
are read from the environment but appear in neither `.env.example` nor the
compose anchor, so under Docker their defaults always apply:
`SHORTS_MAX_DURATION_SECONDS` · `SHORTS_MAX_ASPECT_RATIO` · `MINIO_REGION` ·
`FFMPEG_BIN` · `FFPROBE_BIN` · `CELERY_TASK_TIME_LIMIT` ·
`CELERY_TASK_SOFT_TIME_LIMIT` · `SECURE_HSTS_INCLUDE_SUBDOMAINS` ·
`SECURE_HSTS_PRELOAD`. Add them to both files if you need to tune them.

**3. Defaults are now stated twice.** Each forwarded variable carries a fallback
in `docker-compose.yml` *and* a default in `settings.py`. That is the price of
closing the empty-string hole; when you change one, change the other.

---

## See also

- [DEPLOYMENT.md](./DEPLOYMENT.md) — production values, TLS, backups
- [ARCHITECTURE.md](./ARCHITECTURE.md) — what each service does with these settings
- [DATABASE_SCHEMA.md](./DATABASE_SCHEMA.md) — the rules these thresholds enforce
- [CONTRIBUTING.md](./CONTRIBUTING.md) — local development setup
