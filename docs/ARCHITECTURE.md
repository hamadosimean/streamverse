# StreamVerse — Architecture

> A full-stack video-streaming platform: VOD + live, subscriptions, ads, moderation.  
> One command to run everything: `docker compose up --build`

**Companion documents**

| Document | Answers |
|---|---|
| [DATABASE_SCHEMA.md](./DATABASE_SCHEMA.md) | What are the entities, how do they relate, what rules must the data obey? |
| [DATABASE.md](./DATABASE.md) | What are the actual tables, columns, indexes and constraints? |
| [CONFIGURATION.md](./CONFIGURATION.md) | What is every environment variable, and what breaks if it is wrong? |
| [DEPLOYMENT.md](./DEPLOYMENT.md) | How does this go to a production server? |
| [API.md](./API.md) | What are the HTTP and WebSocket endpoints? |
| [CONTRIBUTING.md](./CONTRIBUTING.md) | How do I set up and work on this locally? |

---

## Table of Contents

1. [High-Level Overview](#1-high-level-overview)
2. [Service Topology](#2-service-topology)
3. [Backend (Django)](#3-backend-django)
4. [Frontend (React + Vite)](#4-frontend-react--vite)
5. [Media Pipeline](#5-media-pipeline)
6. [Authentication & Authorization](#6-authentication--authorization)
7. [Monetization](#7-monetization)
8. [Search](#8-search)
9. [Infrastructure & DevOps](#9-infrastructure--devops)
10. [Key Design Decisions](#10-key-design-decisions)

---

## 1. High-Level Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser / OBS                                                  │
└────────┬──────────────────────────────────────┬────────────────┘
         │ HTTP / WS                            │ RTMP
         ▼                                      ▼
┌────────────────┐                   ┌─────────────────────┐
│   nginx :8110  │                   │  MediaMTX :1936     │
│  (reverse proxy│                   │  RTMP ingest +      │
│   + HLS proxy) │                   │  HLS repackaging    │
└──┬─────┬───────┘                   └──────────┬──────────┘
   │     │                                      │
   │  /live-hls/                    hooks (/api/live/*)
   │     │                                      │
   ▼     ▼                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Django / Uvicorn ASGI :8000                   │
│  REST API  ·  Django Admin  ·  Django Channels (WebSocket)      │
└──────┬───────────────┬──────────────────────┬───────────────────┘
       │               │                      │
       ▼               ▼                      ▼
  PostgreSQL        MinIO S3              Redis
  (primary DB)    (object store)      (cache / broker /
                                       channel layer)
       ▲
       │
  Celery Workers  ·  Celery Beat
  (transcode, live→VOD, ad-caps, cleanups)
```

---

## 2. Service Topology

| Service | Image | Role |
|---|---|---|
| `nginx` | `nginx:1.30-trixie` | TLS termination, SPA serving, API proxy, HLS proxy |
| `frontend` | custom (Vite/React build) | SPA served by nginx |
| `backend` | custom Django/Uvicorn | REST API + Django Admin + WebSocket |
| `celery-worker` | same image as backend | Background tasks (transcode, etc.) |
| `celery-beat` | same image as backend | Periodic tasks scheduler |
| `flower` | same image as backend | Celery task monitor UI |
| `db` | `postgres:18-trixie` | Primary relational store |
| `redis` | `redis:8.10-trixie` | Cache / channel layer / Celery broker |
| `minio` | `minio/minio:2025-04-22` | S3-compatible object store (HLS, thumbnails, ad creatives) |
| `mailpit` | `axllent/mailpit:v1.30` | Dev SMTP server + web UI |
| `mediamtx` | `bluenviron/mediamtx:1.20.0-ffmpeg` | RTMP ingest + HLS repackaging + lifecycle hooks |

> **Single image, four roles.** `backend`, `celery-worker`, `celery-beat` and `flower` all use `streamverse-backend:local`. The entrypoint dispatches on the `command` argument (`asgi | worker | beat | flower`). This avoids the classic failure mode where `docker compose build backend` leaves the worker running stale code.

---

## 3. Backend (Django)

**Stack:** Django 5.2 LTS · DRF · Djoser (auth) · SimpleJWT · Django Channels · Celery · drf-spectacular (OpenAPI)

### 3.1 App Map

```
backend/apps/
├── core/          Base models (TimeStampedModel, UUIDPrimaryKeyModel),
│                  middleware, health endpoint, custom storage backend
├── accounts/      Custom User model (email login), roles, suspension,
│                  profile: bio, location, website, avatar + banner uploads
├── catalog/       Category and Tag taxonomy
├── videos/        Video model, renditions, thumbnails, tus upload sessions,
│                  transcode pipeline, Shorts classification
├── engagement/    Views, Likes, Comments, Reports (analytics + social layer)
├── library/       WatchHistory, Bookmarks, Follow graph (viewer personal data)
├── live/          LiveChannel, LiveRecording, LiveChatMessage; MediaMTX hooks
├── monetization/  SubscriptionPlan, UserSubscription, Transaction,
│                  WebhookEvent, AdCampaign, AdImpression
├── moderation/    ModerationAction, UserSanction (decisions & sanctions)
├── search/        Postgres full-text search (tsvector, GIN index)
├── audit/         Append-only AuditLog
└── seo/           robots.txt, sitemap.xml, Open Graph crawler renderers
```

### 3.2 Request Lifecycle

```
Browser
  │
  │  HTTPS → nginx :80
  │    ├─ /api/*         → proxy_pass backend:8000   (DRF views)
  │    ├─ /ws/*          → proxy_pass backend:8000   (Django Channels)
  │    ├─ /admin/*       → proxy_pass backend:8000   (Django Admin)
  │    ├─ /live-hls/*    → proxy_pass mediamtx:8888  + auth_request /api/live/authz/
│    │                    (playlists only; segments are not individually gated)
  │    └─ everything else → frontend SPA (index.html)
  │
  │  DRF request pipeline
  │    SecurityHeadersMiddleware → CorsMiddleware → SessionMiddleware
  │    → LocaleMiddleware → CsrfViewMiddleware → AuthenticationMiddleware
  │
  └─ JWT auth via SimpleJWT (access + refresh tokens with rotation + blacklist)
```

### 3.3 Async Workers

Two queues. `videos.transcode.*` and `live.convert_recording_to_vod` are routed to **`transcode`**; everything else runs on **`default`**, so a burst of uploads never starves the cheap bookkeeping tasks.

| Task | Queue | Trigger |
|---|---|---|
| `videos.transcode.start_pipeline` → `probe_source` → `transcode_renditions` → `build_master_playlist` → `generate_thumbnails` → `finalize_video` | transcode | Last upload chunk lands |
| `videos.transcode.on_pipeline_failure` | transcode | Any stage raises |
| `videos.transcode.relocate_assets` | transcode | Visibility crosses the public/private line |
| `videos.transcode.delete_assets` | transcode | Video deleted |
| `live.convert_recording_to_vod` | transcode | `runOnUnavailable` MediaMTX hook |
| `monetization.deliver_mock_webhook` | default | `MOCK_PAYMENT_CONFIRM_DELAY_SECONDS` after a mock checkout |
| `videos.maintenance.*`, `engagement.*`, `live.reconcile_live_state`, `monetization.*` | default | Beat — full schedule in [CONFIGURATION.md §20](./CONFIGURATION.md#20-scheduled-jobs) |

### 3.4 WebSockets (Django Channels + Redis channel layer)

| Consumer | Path | Purpose |
|---|---|---|
| `UploadProgressConsumer` | `/ws/uploads/<video_id>/` | Streams transcode stage + progress to the uploader. Owner-only. |
| `LiveChatConsumer` | `/ws/live/<slug>/` | Live chat **and** viewer-count fan-out on one socket. Anonymous read, authenticated write. |

Browsers cannot set headers on a WebSocket handshake, so the access token
travels as `?token=`. It is still a short-lived access token, and every consumer
re-checks ownership or membership after authentication — the token alone never
grants access to a group.

---

## 4. Frontend (React + Vite)

**Stack:** React 19 · React Router 7 · Zustand · TanStack Query 5 · Tailwind CSS 4 · hls.js · tus-js-client · i18next (FR/EN) · Vite 8

Routes are lazily code-split: the watch page pulls in hls.js and the studio pulls in recharts, neither of which the home feed needs.

### 4.1 Route Map

| Path | Page | Auth |
|---|---|---|
| `/` | Home feed | Public |
| `/browse` | Category browser | Public |
| `/watch/:videoId` | Video player + comments | Public |
| `/search` | Full-text search results | Public |
| `/c/:username` | Channel page | Public |
| `/shorts[/:videoId]` | Vertical Shorts feed | Public |
| `/live` | Live directory | Public |
| `/live/:slug` | Live watch + chat | Public |
| `/premium` | Subscription plans | Public |
| `/login` | Login | Guest only |
| `/register` | Registration | Guest only |
| `/activate/:uid/:token` | Email activation | — |
| `/password/forgot` | Password reset request | — |
| `/password/reset/:uid/:token` | Password reset confirm | — |
| `/library` | Watch history + bookmarks | Auth |
| `/subscriptions` | Followed channels feed | Auth |
| `/upload` | Video upload (tus resumable) | Auth |
| `/studio` | Creator studio | Auth |
| `/studio/live` | Live streaming studio | Auth |
| `/studio/videos/:videoId` | Video editor | Auth |
| `/account` | Profile + account settings | Auth |
| `/manage/moderation` | Moderation queue | Moderator+ |
| `/manage/dashboard` | Admin dashboard | Admin |
| `/manage/ads` | Ad campaign manager | Admin |

> `/admin/` is reserved for Django Admin (nginx proxies that prefix). React admin views live under `/manage/` to avoid the collision.

### 4.2 State Management

| Store (Zustand) | Responsibility |
|---|---|
| `useAuthStore` | Current user, JWT tokens, boot-time `/accounts/me/` call |
| `usePlayerStore` | Player preferences (volume, quality, autoplay) persisted across pages |
| `useUploadStore` | In-flight tus upload state, so navigating away does not lose it |
| `useUIStore` | UI language and the two sidebar states (mobile drawer, desktop rail) |

Server state (lists, pagination, mutations) is managed by **TanStack Query** with optimistic updates for likes/bookmarks.

---

## 5. Media Pipeline

### 5.1 VOD Upload & Transcode

```
Browser
  │  tus resumable upload → /api/videos/upload/
  │  chunks land in upload_scratch volume
  ▼
UploadSession row (tracks offset, expires_at)
  │  last chunk received
  ▼
Video row created (status=processing, visibility=private)
  ▼
Celery task: transcode_video
  1. ffprobe   → fill source_* fields, detect Shorts eligibility
  2. Build ABR ladder (240p … 1080p, never upscale past source)
  3. ffmpeg    → HLS segments in transcode_work volume
  4. Package master.m3u8
  5. Extract poster + sprite sheet + thumbnails.vtt
  6. Upload all assets to MinIO (public or private bucket by visibility)
  7. Video.status = ready
  │  WebSocket progress events pushed at each stage
  ▼
VideoRendition rows, VideoThumbnail rows
```

**Processing stages:** `queued → probing → transcoding → packaging → thumbnails → publishing → done`

**Shorts auto-classification:** A video qualifies as a Short only if its duration ≤ `SHORTS_MAX_DURATION_SECONDS` **AND** its aspect ratio ≤ `SHORTS_MAX_ASPECT_RATIO` (portrait/square). This cannot be set manually, preventing cheap clips from flooding the main feed.

### 5.2 Live Streaming

```
OBS/encoder
  │  RTMP  rtmp://host:1936/live/<slug>?key=<secret>
  ▼
MediaMTX :1935
  ├─ AUTH hook   GET  /api/live/auth/              Django validates stream key
  ├─ READY hook  POST /api/live/hooks/ready/       Django: status=live, LiveRecording created
  ├─ HLS output  :8888/live/<slug>/                proxied by nginx at /live-hls/
  │                                                nginx auth_request on every playlist
  └─ NOT-READY   POST /api/live/hooks/not-ready/   Django: status=ended,
                                                   Celery: publish_live_recording
                                                       → VOD pipeline on fMP4
                                                       → creates normal Video row
```

### 5.3 Object Storage Layout

```
streamverse-public bucket          streamverse-private bucket
────────────────────────────────   ────────────────────────────
videos/<uuid>/hls/master.m3u8      originals/<uuid>/source.<ext>
videos/<uuid>/hls/<label>/         (uploaded file, worker-only)
  index.m3u8
  seg_0000.ts …
videos/<uuid>/thumbs/
  poster.jpg
  sprite.jpg
  thumbnails.vtt
ads/<year>/<month>/<creative>
avatars/<year>/<month>/<image>
banners/<year>/<month>/<image>
```

Private videos have their HLS assets in `streamverse-private`. Visibility changes trigger a bucket migration of the entire `videos/<uuid>/` prefix. The **original file** always stays private.

Profile images (`avatars/`, `banners/`) and ad creatives are public by nature — they are rendered for every visitor — so they are written straight to the public bucket through a Django `FileField` rather than the direct-S3 path the transcoder uses. Object names are generated server-side, and replacing an image deletes the one it supersedes.

---

## 6. Authentication & Authorization

| Mechanism | Details |
|---|---|
| **Login** | Email + password → Djoser + SimpleJWT (`/api/auth/jwt/create/`) |
| **Tokens** | Short-lived access + longer refresh with rotation |
| **Blacklist** | `rest_framework_simplejwt.token_blacklist` — revoked refresh tokens cannot be reused |
| **Registration** | `/api/auth/users/` → confirmation email → `/activate/:uid/:token` |
| **Roles** | `user` / `moderator` / `admin` stored as a `role` field on User |
| **Suspension** | `is_suspended` flag; suspended users' public content is hidden from all feeds |

DRF permission classes: `IsAuthenticated`, `IsOwnerOrStaff`, `IsModerator`, `IsAdmin`.

---

## 7. Monetization

```
User → /premium → choose plan → POST /api/monetization/checkout/
  creates Transaction (idempotency_key UNIQUE in DB)
  creates UserSubscription (status=pending)
  │
  ├─ MOCK provider (dev): Celery fires after 8 s (15 % chance of failure)
  └─ Real provider: redirect → webhook POST /api/monetization/webhooks/<provider>/
                      WebhookEvent row written first (replay guard)
                      Transaction updated → UserSubscription activated
```

**Advertising:** `AdCampaign` rows define creatives, placement (pre/mid-roll), date range, impression cap, and category targeting. Subscribers with `plan.ad_free=True` are excluded from ad selection.

---

## 8. Search

Full-text search runs on **PostgreSQL's native tsvector/tsquery** — no Elasticsearch.

```
Video.search_vector (SearchVectorField, GIN index)
  Weights: title=A  tags=B  description=C
  Language: SEARCH_LANGUAGE_CONFIG (default: french)
  Updated by: post_save signal + Tag M2M change signal
```

---

## 9. Infrastructure & DevOps

### 9.1 Port Map

| Host port | Container port | Service |
|---|---|---|
| **8110** | 80 | nginx (main entry point) |
| **5459** | 5432 | PostgreSQL |
| **6402** | 6379 | Redis |
| **5574** | 5555 | Flower (Celery monitor) |
| **8045** | 8025 | Mailpit UI |
| **9010** | 9000 | MinIO S3 API |
| **9011** | 9001 | MinIO web console |
| **1936** | 1935 | MediaMTX RTMP ingest |

### 9.2 Named Volumes

| Volume | Purpose |
|---|---|
| `postgres_data` | PostgreSQL data directory |
| `redis_data` | Redis AOF persistence |
| `minio_data` | MinIO object blobs |
| `static` | Django collected static files (shared with nginx) |
| `upload_scratch` | tus chunks + source files (backend ↔ worker) |
| `transcode_work` | ffmpeg intermediates (swept by beat task) |
| `live_recordings` | MediaMTX fMP4 session files (mediamtx ↔ worker) |

### 9.3 Redis Databases

| DB | URL env var | Usage |
|---|---|---|
| `0` | `REDIS_URL` | General / default |
| `1` | `CHANNEL_REDIS_URL` | Django Channels layer |
| `2` | `CACHE_REDIS_URL` | Django cache |
| `3` | `CELERY_BROKER_URL` | Celery broker |

---

## 10. Key Design Decisions

| Decision | Rationale |
|---|---|
| **Single backend image, multiple roles** | Prevents stale-code bugs from partial rebuilds |
| **tus resumable upload** | Survives network interruptions; required for mobile and large files |
| **Shorts auto-classification** | Prevents manual gaming; requires both portrait AND short duration |
| **Separate `WatchHistory` from `View`** | Deleting your history must not decrement the creator's view count |
| **Postgres FTS instead of Elasticsearch** | Eliminates an extra service for this platform's search workload |
| **Private-first default visibility** | New videos are `private` until explicitly published — nothing leaks by accident |
| **Integer FCFA amounts** | XOF has no minor unit; float rounding errors in payment ledgers are unacceptable |
| **DB-unique idempotency keys on payments** | Double-clicks and retried requests converge on one row — enforced by the database, not application logic |
| **MediaMTX `-ffmpeg` alpine image** | Provides `wget` and `sh` needed for lifecycle hooks |
| **nginx `auth_request` for HLS playlists** | Players re-fetch the playlist every few seconds; cutting off a channel stops in-flight playback within one segment duration without putting Django in the media path for every segment |
