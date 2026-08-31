# StreamVerse

Self-hosted video-sharing platform — upload, multi-rendition HLS transcoding, adaptive-bitrate playback, creator studio. French-first bilingual UI (FR default, EN secondary).

> **Delivery status: Phases 1–6 of 7 — feature-complete.**
> Every feature in the spec is built: the VOD pipeline with the public/private delivery split, engagement + discovery, live streaming, monetization, and the moderation queue with admin dashboards. **Phase 7 is the only one outstanding**, and it is by design: replacing the payment simulator with real providers requires merchant credentials that do not exist yet. It slots in behind the same interface without touching a call site. Section [Phase status](#phase-status) is the honest inventory.

---

## Table of contents

- [Quick start](#quick-start)
- [Demo credentials](#demo-credentials)
- [Accounts & sign-in](#accounts--sign-in)
- [Architecture](#architecture)
- [The transcoding pipeline](#the-transcoding-pipeline)
- [Public vs private HLS delivery](#public-vs-private-hls-delivery)
- [Engagement & discovery](#engagement--discovery)
- [Live streaming](#live-streaming)
- [Testing live streaming with OBS or ffmpeg](#testing-live-streaming-with-obs-or-ffmpeg)
- [Monetization](#monetization)
- [Moderation](#moderation)
- [Library: history, bookmarks, likes, following](#library-history-bookmarks-likes-following)
- [Security & SEO](#security--seo)
- [Roles](#roles)
- [Ports](#ports)
- [Environment variables](#environment-variables)
- [Performance & scaling](#performance--scaling)
- [Verifying the pipeline end to end](#verifying-the-pipeline-end-to-end)
- [Phase status](#phase-status)
- [Scope notes (what this does not do)](#scope-notes-what-this-does-not-do)
- [Version choices](#version-choices)

---

## Quick start

```bash
cp .env.example .env
# Generate a real secret key:
python3 -c "import secrets; print('DJANGO_SECRET_KEY=' + secrets.token_urlsafe(64))"
# ...and paste it into .env

docker compose up --build
```

Then open **http://localhost:8110**.

No manual steps are needed. The backend entrypoint runs migrations, `collectstatic`, MinIO bucket provisioning (with explicit access policies), and the demo seed.

The seed **generates ~15 real video clips with FFmpeg and pushes them through the actual transcoding pipeline**, so they appear as `processing` first and turn `ready` over the following minute or two. Watch the queue drain at **http://localhost:5574** (Flower, `admin` / `admin`).

It also creates real engagement — roughly 1 700 `View` rows spread over 30 days, plus likes, threaded comments and two pending reports — and then derives the counters on `Video` from those rows using the same reconciliation task that runs in production.

To seed synchronously instead:

```bash
docker compose exec backend python manage.py seed --reset --wait
```

---

## Demo credentials

Shared password for every demo account: **`StreamVerse2026!`**

| Role | Email | Name |
|---|---|---|
| admin | `admin@streamverse.local` | Administrateur |
| moderator | `moderator@streamverse.local` | Awa Moderation |
| user | `fatou@streamverse.local` | Fatou Diallo |
| user | `ibrahim@streamverse.local` | Ibrahim Sawadogo |
| user | `nadia@streamverse.local` | Nadia Kabore |
| user | `koffi@streamverse.local` | Koffi Mensah |

Other consoles:

| Service | URL | Credentials |
|---|---|---|
| Django admin (Jazzmin) | http://localhost:8110/admin/ | `admin@streamverse.local` |
| API docs (Swagger) | http://localhost:8110/api/docs/ | — |
| Flower (Celery queue) | http://localhost:5574 | `admin` / `admin` |
| Live demo channel | http://localhost:8110/live/fatou | see [live testing](#testing-live-streaming-with-obs-or-ffmpeg) |
| Subscription plans | http://localhost:8110/premium | sandbox payments |
| My library | http://localhost:8110/library | signed in |
| Subscriptions feed | http://localhost:8110/subscriptions | signed in |
| Ad campaign manager | http://localhost:8110/manage/ads | admin only |
| Moderation queue | http://localhost:8110/manage/moderation | moderator or admin |
| Admin dashboard | http://localhost:8110/manage/dashboard | admin only |
| MinIO console | http://localhost:9011 | `streamverse` / `streamverse-secret` |

Accounts created through the public signup flow require email activation. That email is sent over real SMTP — see [Accounts & sign-in](#accounts--sign-in) for what to configure, and for the one-line alternative that prints the activation link to the log instead.

---

## Accounts & sign-in

Two ways in: an email and a password, or a Google account. Both end at the same
place — a SimpleJWT access/refresh pair in `localStorage`, rotated and
blacklisted on use — so nothing downstream knows or cares which one was used.

### Sign in with Google

Optional, and off until you give it credentials. With none configured,
`GET /api/auth/providers/` reports `{"google": {"enabled": false}}` and the
frontend renders no button rather than one that can only fail.

To turn it on, create an **OAuth client ID** of type *Web application* in
[console.cloud.google.com](https://console.cloud.google.com) → APIs & Services →
Credentials, and register the callback:

```
Authorized JavaScript origins:  http://localhost:8110
Authorized redirect URIs:       http://localhost:8110/auth/google/callback
```

```dotenv
GOOGLE_OAUTH_CLIENT_ID=<...>.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-<...>
```

Google compares the redirect URI as an exact string — a trailing slash, `http`
against `https`, or a different port is a rejected sign-in, not a warning. The
client secret starts with `GOCSPX-`; pasting the client id into both fields
fails the exchange with `invalid_client`.

**Why the redirect flow and not Google's button script.** The obvious
alternative is `gsi/client`, which renders Google's own button and hands the
browser an ID token. It costs a third-party script tag and an iframe, which
means widening the CSP with `script-src https://accounts.google.com` — and that
CSP is the one thing standing between an injected script and the JWTs in
`localStorage` (see [Known accepted risks](#known-accepted-risks)). So this
takes a redirect instead, and loads **no Google JavaScript at all**. The G mark
on the button is an inline SVG.

What happens, end to end:

```
SPA ──GET /api/auth/google/authorize/?next=/studio──► backend
        mints state + PKCE verifier, parks them in Redis (10 min, single use),
        returns the URL. Only the URL reaches the browser.
   ◄───────────────────────────────────────────────────
browser ──full-page navigation──► accounts.google.com  (the user sees the real
                                                        address bar)
   ◄──redirect to /auth/google/callback?code&state──
SPA ──POST /api/auth/google/callback/ {code, state}──► backend
        redeems the state, exchanges the code server-to-server with the client
        secret + PKCE verifier, verifies the ID token's signature, issuer,
        audience and expiry, resolves the user
   ◄──{access, refresh, created, next}───────────────
```

Four things that decide who the sign-in is *for*:

- **Identity is the Google `sub`, never the email.** The address on a Google
  account can be changed by its owner; `sub` cannot. Links live in
  `accounts_socialaccount`, one row per `(provider, subject)`.
- **An unverified address is rejected outright.** Anyone can attach an address
  to a Google account; only `email_verified` is evidence, and without it a
  stranger could claim the StreamVerse account that already owns it.
- **A verified address that matches an existing account links to it**, password
  signup included — Google vouching for the address is exactly the proof the
  activation email would have asked for. Refusing instead would make "Sign in
  with Google" a dead end for every user who signed up the normal way. An
  account that never clicked its activation link is activated on the spot.
- **A suspended account is refused here**, not one request later by
  `SuspensionAwareJWTAuthentication` — otherwise a moderation decision would
  look like a broken login.

New accounts get a handle derived from the email's local part
(`j.p+news@gmail.com` → `jpnews`), disambiguated with a random suffix rather
than a counter, since `alice-2` advertises that `alice` exists. They also get no
password: `/account` then offers **Set a password** without asking for a current
one, and the API applies the same rule.

`next` survives the round trip on the server, parked with the OAuth state — it
never travels through the URL the browser carries to Google, and it is
re-validated on the way back, so `//evil.example` and friends collapse to `/`.

### Activation and password-reset email

Real SMTP, in every environment. There is no dev mail catcher: these two
messages are the only mail the platform sends, both are worthless undelivered,
and a container that accepts everything is a good way to ship a configuration
nobody has ever exercised.

```dotenv
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=1
EMAIL_HOST_USER=you@example.com
EMAIL_HOST_PASSWORD=<16-character App Password>
```

For Gmail that password is an **App Password**, not the account password —
Google stopped accepting those over SMTP in May 2022 and refuses them with a
bare `535` that explains nothing. Create one at *myaccount.google.com → Security
→ App passwords*; it requires 2-Step Verification. `DEFAULT_FROM_EMAIL` defaults
to `EMAIL_HOST_USER`, because Gmail rewrites or rejects a `From` that is not the
authenticated mailbox.

No account to hand? `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend`
prints each message, activation link included, to the backend log.

Sending happens in the **Celery worker**, not in the request: a real provider's
handshake and delivery is seconds, all of it otherwise spent holding the signup
open, and a provider hiccup used to turn a created account into a 500 with no
way to resend. So an SMTP failure appears here, never in the API response:

```bash
docker compose logs -f celery-worker | grep -i send_email
```

The task retries three times over 30/60/120 seconds. `EMAIL_ASYNC=0` sends
inline instead, which is easier to follow while debugging a new configuration.

---

## Architecture

```
                                 ┌──────────────────────────────┐
   Browser                       │  nginx :8110  (edge proxy)   │
      │                          │  /api/ /admin/ /ws/  →  ASGI │
      ├─────────── HTTP ────────►│  /            →  SPA         │
      │                          └───────────┬──────────────────┘
      │                                      │
      │                     ┌────────────────┴───────────────┐
      │                     │                                │
      │            ┌────────▼─────────┐            ┌─────────▼────────┐
      │            │  frontend        │            │  backend (ASGI)  │
      │            │  React + Vite    │            │  Django+Channels │
      │            │  served by nginx │            │  uvicorn :8000   │
      │            └──────────────────┘            └────┬────────┬────┘
      │                                                 │        │
      │                              ┌──────────────────┘        │
      │                              │                           │
      │                     ┌────────▼───────┐          ┌────────▼───────┐
      │                     │  PostgreSQL    │          │  Redis         │
      │                     │  :5459         │          │  :6402         │
      │                     └────────────────┘          │ channels/cache │
      │                                                 │ celery broker  │
      │                                                 └───┬────────────┘
      │                                                     │
      │                                    ┌────────────────▼──────────────┐
      │                                    │  celery worker  (queue:       │
      │                                    │  transcode, default)          │
      │                                    │  ┌─────────────────────────┐  │
      │                                    │  │  FFmpeg / ffprobe       │  │
      │                                    │  └─────────────────────────┘  │
      │                                    │  celery beat (maintenance)    │
      │                                    └────────────────┬──────────────┘
      │                                                     │ writes HLS
      │                                                     ▼
      │                                    ┌───────────────────────────────┐
      └────────── HLS manifests ──────────►│  MinIO  :9010 (S3 API)        │
                 + segments                │  ┌─────────────────────────┐  │
                 (never through Django)    │  │ streamverse-public      │  │
                                           │  │  anonymous GetObject    │  │
                                           │  ├─────────────────────────┤  │
                                           │  │ streamverse-private     │  │
                                           │  │  signed requests only   │  │
                                           │  └─────────────────────────┘  │
                                           └───────────────────────────────┘
```

**The key structural fact:** the arrow from the browser to MinIO bypasses Django entirely. Django serves the API, the upload endpoint and — for private videos only — small text manifests. It is never in the request path for a video byte.

### Monorepo layout

```
streamverse/
├── backend/                 Django + DRF + Channels (ASGI)
│   ├── config/              settings, urls, asgi, celery, routing, jazzmin
│   └── apps/
│       ├── core/            storage (MinIO), ws auth, permissions, seed
│       ├── accounts/        User model, roles, profile + images, Djoser wiring
│       ├── catalog/         Category, Tag
│       ├── videos/          Video/Rendition/Thumbnail, tus, tasks, playback
│       ├── engagement/      View, Like, Comment, Report + counter services
│       ├── search/          PostgreSQL FTS, related videos (no models)
│       ├── live/            LiveChannel/Recording/Chat, MediaMTX hooks, consumers
│       ├── monetization/    plans, payments (provider abstraction), ads
│       ├── moderation/      decisions, sanctions, queue + admin dashboard
│       ├── library/         watch history, bookmarks, follows
│       └── audit/           append-only AuditLog
├── frontend/                React 19 + Vite 8 + Tailwind 4 (JSX, not TS)
│   └── src/
│       ├── components/      Layout, VideoCard, player/, ui/
│       ├── features/        auth, videos, upload, studio, account,
│       │                    engagement, channel, search, live,
│       │                    monetization, moderation, library, admin
│       ├── stores/          zustand: auth, ui, player, upload queue
│       └── lib/             api (axios + JWT refresh), i18n, format
├── mediamtx/                RTMP + WebRTC ingest, HLS repackaging, bridge.sh
├── nginx/                   edge reverse proxy
├── docker-compose.yml
├── .env.example
└── README.md
```

### Django apps present in this phase

All of them, plus `library`: `accounts`, `catalog`, `videos`, `engagement`, `search`, `live`, `monetization`, `moderation`, `library`, `audit`, `core`.

---

## The transcoding pipeline

Everything after "bytes arrived" runs in Celery. Nothing transcodes inside a request.

### 1. Resumable upload (tus 1.0.0)

`frontend/src/stores/useUploadStore.js` → `backend/apps/videos/tus.py`

The browser uploads in 8 MiB chunks over the tus protocol. The server tracks the byte offset in an `UploadSession` row, so a dropped connection resumes from the last committed byte instead of restarting. `tus-js-client` also fingerprints the file in `localStorage`, so a page reload resumes too.

Implemented verbs: `OPTIONS` (capabilities), `POST` (create), `HEAD` (current offset), `PATCH` (append), `DELETE` (abort). Extensions: `creation`, `expiration`, `termination`.

The tus protocol is implemented directly rather than via a library — the maintained Django tus packages either target older Django releases or hard-wire storage assumptions that conflict with the MinIO layout here, and the core protocol is four verbs and an offset counter.

### 2. Validation gate

`backend/apps/videos/services/validation.py`

Before anything enters the queue:

- declared size checked at **creation** time, before a single byte is accepted;
- real MIME sniffed from the leading bytes with `python-magic` (the browser-declared `Content-Type` and the filename extension are both attacker-controlled);
- `ffprobe` must successfully parse it — a file can carry a valid MP4 magic number and contain nothing decodable;
- duration and resolution sanity-checked.

A rejection is immediate and synchronous, so the uploader is told at once rather than after watching a progress bar for a minute.

### 3. The Celery chain

`backend/apps/videos/tasks.py`

```
start_transcoding_pipeline
        │
        ▼
  probe_source ──────────► ffprobe: duration, resolution, codecs, rotation
        │                  archives the original to the private bucket
        ▼
  transcode_renditions ──► one FFmpeg process per ladder rung
        │                  → HLS segments + variant playlist → MinIO
        ▼
  build_master_playlist ─► #EXT-X-STREAM-INF entries with BANDWIDTH/
        │                  RESOLUTION/CODECS → adaptive switching
        ▼
  generate_thumbnails ───► poster frame + sprite sheet + WebVTT index
        │
        ▼
  finalize_video ────────► verifies every artefact exists in object storage,
                           then and only then sets status = ready
```

Any stage raising drops the whole chain into `on_pipeline_failure`, which sets `status=failed`, stores the real FFmpeg error where the uploader can read it, purges the half-written objects, and leaves a retry path. **There is no state in which a video is `ready` with a missing rendition** — `finalize_video` re-checks every rendition manifest in object storage before flipping the status.

### 4. The ladder — never upscales

`backend/apps/videos/services/ladder.py`

| Rung | Short side | Video bitrate | Audio |
|---|---|---|---|
| 240p | 240 | 400 kbps | 64 kbps |
| 360p | 360 | 800 kbps | 96 kbps |
| 480p | 480 | 1400 kbps | 128 kbps |
| 720p | 720 | 2800 kbps | 128 kbps |
| 1080p | 1080 | 5000 kbps | 192 kbps |

A 480p source produces 240p/360p/480p and stops. Fabricating a "1080p" rung from a 480p master would cost 4× the storage and encode time to deliver a blurrier picture at a higher bitrate, and would lie to the player's bandwidth estimator.

The rung applies to the **short side**, so a 1080×1920 phone recording yields 720×1280 for the "720p" rung rather than a letterboxed 1280×720. A source below 240p is encoded once at its native size, so playback still works.

The ladder tops out at 1080p on purpose — 4K transcoding on commodity CPU is hours per video. Add higher rungs in `ladder.py` if you deploy on GPU-encoding hardware.

The seed data deliberately includes a 1920×1080 source, a 320×180 source and a 720×1280 portrait source so all three ladder behaviours are visible on first boot.

### 5. Live progress over WebSocket

`ws/uploads/<video_id>/` — `backend/apps/videos/consumers.py`

Each pipeline task publishes to a per-video Channels group. The uploader sees `queued → probing → transcoding 360p (2/4) → packaging → thumbnails → publishing → ready`, not a blind poll.

- The bar is **weighted** across stages (transcoding is 76% of the span) so it advances at a rate that roughly matches wall-clock, rather than sitting at 40% for ten minutes and then sprinting.
- Frames are rate-limited server-side; FFmpeg emits progress per frame and forwarding all of it would flood the channel layer for no visual benefit.
- The current state is pushed **immediately on connect**, so a page opened or refreshed mid-encode shows the real percentage.
- JWT travels in the handshake query string (browsers cannot set headers on a WebSocket handshake), and **ownership is re-checked after authentication** — a valid token for user A cannot join user B's progress group.
- A REST polling fallback exists at `GET /api/studio/videos/<id>/progress/` for clients behind a proxy that strips WebSocket upgrades.

---

## Public vs private HLS delivery

`backend/apps/videos/services/playback.py`

The invariant: **Django is never in the request path for a video byte.** A 20-minute video is several hundred segments per rendition; proxying those through Django would mean hundreds of authenticated round-trips through the ASGI worker pool *per viewer*.

### Public and unlisted → public-read bucket, direct

Renditions, manifests and thumbnails are written to `streamverse-public`. `POST /api/videos/<id>/playback/` returns a plain MinIO URL and Django steps out entirely. Every manifest and every segment is fetched browser → MinIO.

Unlisted content is protected by the unguessable UUID in the path. The bucket policy grants `s3:GetObject` **only** — never `ListBucket` — so the key space cannot be enumerated.

### Private → private bucket, presigned

Renditions live in `streamverse-private`, which has no bucket policy at all: signed requests only.

1. `POST /api/videos/<id>/playback/` authorises the viewer **once**, then issues a short-lived signed session token.
2. The player fetches the master playlist from Django. Django generates it on the fly; its variant entries point back at Django.
3. Each variant playlist is generated by Django by reading the stored `.m3u8` from MinIO and **rewriting every segment line into a presigned MinIO URL**.
4. The player fetches every segment straight from MinIO.

Django serves 2–3 text responses of a few kilobytes per playback session. MinIO serves 100% of the media bytes. Presigning is local HMAC work with no network round-trip, so signing several hundred segment URLs is sub-millisecond.

### Two S3 clients, deliberately

`backend/apps/core/storage.py` builds two boto3 clients:

- **internal** — `http://minio:9000`, used by Django and the workers for PUT/GET/COPY/DELETE inside the compose network;
- **public** — `http://localhost:9010`, used *only* to generate presigned and public URLs.

SigV4 signs the `Host` header. A URL presigned against `minio:9000` would fail signature validation the moment the browser sent `Host: localhost:9010`. If you deploy behind a real domain, set `MINIO_PUBLIC_ENDPOINT` accordingly or private playback will break.

### Visibility changes move the objects

Flipping a video between private and public/unlisted crosses the bucket line, so `relocate_assets` moves the whole `videos/<id>/` prefix server-side. Without this, making a public video private would leave its segments anonymously readable in the public bucket — the manifest would be gated while the media stayed wide open.

### Other delivery notes

- **CDN caching in front of MinIO** is the production scaling path (Nginx as a caching layer, or a real CDN). Not built by default — noted rather than assumed.
- HLS segments are uploaded with `Cache-Control: immutable, max-age=1y` (their names are stable); manifests get 60 s.
- Django-served signed manifests are `Cache-Control: private, max-age=60` — caching past the presigned TTL would hand the player dead links.

---

## Engagement & discovery

### View counting that does not lie

`backend/apps/engagement/services.py`

A view is not a page load. Two rules, both enforced **server-side** — the client only reports honest elapsed watch time and cannot talk a counter up:

1. **Minimum watch time.** 30 seconds, or 30% of the video for anything shorter. A flat 30s threshold would make a 10-second clip permanently uncountable, so short videos scale down instead.
2. **Deduplication.** One `View` row per (video, identity, 12-hour bucket). Refreshing a page fifteen times is one view. Signed-in users dedupe on their user id; anonymous viewers on an opaque browser-generated id, falling back to the Django session key, then to a **salted IP hash**. The raw IP is never stored, and none of it is enough to build a profile.

The player only accumulates time while actually playing and while the tab is visible, so a paused tab left open overnight contributes nothing.

Counters on `Video` are denormalised for read speed, written with `F()` expressions so concurrent updates cannot lose an increment, and **reconciled hourly** from the source rows by `engagement.reconcile_counters` — a crash between a row write and its counter update self-heals rather than drifting forever.

### Likes, comments, reports

- **Likes** are one row per (video, user) with an `is_like` boolean, not two tables — switching from like to dislike is an update, so the two counters can never both count the same person.
- **Comments** are threaded exactly one level deep; a reply-to-a-reply is rejected rather than silently accepted and then rendered wrongly. Deletion is **soft**: replies keep their context, and a moderator retains the original text to justify an action. Deleting a parent removes its replies too. A deleted node's content and author are stripped server-side, never merely hidden by CSS.
- **Reports** use a generic FK so the moderation queue is one list regardless of target type. A DB-level partial unique constraint allows one *pending* report per user per target, so hammering the button cannot flood the queue. Self-reporting is refused.

### Search

`backend/apps/search/services.py`

PostgreSQL full-text search. No external search service. `Video.search_vector` is a stored `tsvector` with a **GIN index**, weighted:

| Weight | Field | Why |
|---|---|---|
| A | title | a title match should beat a match anywhere else |
| B | tags | curated, high-signal |
| C | description | long and noisy, so it ranks lowest |

The vector is *stored*, not computed per query: `to_tsvector(title \|\| description)` at query time forces a sequential scan over the whole table because no index can cover it.

Queries use `websearch` parsing, so `"exact phrase"` and `-excluded` mean what they mean everywhere else. When full-text returns nothing, a **trigram word-similarity** fallback runs — word-level, not whole-string, because comparing `concrt` against the whole title `Concert live a Ouagadougou` scores near zero while the closest *word* scores well. The API returns a `mode` field (`fulltext` / `fuzzy` / `none`) and the UI shows a badge, so an approximate match is never presented as an exact one.

**Scope limit, stated plainly:** this is stemming plus a typo fallback, not true fuzzy search. Meilisearch or Elasticsearch is the upgrade path — a genuinely different capability, not a tuning knob.

The vector is refreshed inline whenever a video's metadata changes and when it becomes `ready`, with `engagement.rebuild_search_index` as a periodic safety net for rows that changed through a path that did not update it.

### Related videos

Ranked by **shared tags first**, then shared category, then popularity. A video tagged the same way is a closer match than one that merely shares a broad category like "Music".

**This is not a recommendation engine.** No collaborative filtering, no watch-history modelling, no personalisation — two different viewers get the same list for the same video. The API returns `strategy: "content_based"` and the UI says so under the rail.

### Channel pages

`/c/<username>` — the creator's public identity (banner, avatar, bio, location, website) plus aggregates over their **public, ready** videos only, so a private upload never leaks its existence through a count. The page has a follow button but **no new-video notifications**: following changes the follower's own feed and nothing else, and the page says so rather than leaving users wondering why nothing arrived. See [Scope notes](#scope-notes-what-this-does-not-do).

### Profiles: avatar, banner, bio

A user owns the header of their own channel page. `/account` edits the text — display name, bio, location, website — and the two images:

| Field | Endpoint | Limit |
|---|---|---|
| avatar | `PUT` / `DELETE /api/accounts/me/avatar/` | 5 MiB, 2048 px per side |
| banner | `PUT` / `DELETE /api/accounts/me/banner/` | 10 MiB, 6000 px per side |
| text fields | `PATCH /api/accounts/me/` | bio 1000 chars |

Four things are worth knowing about how the images are handled:

- **They live in the public bucket**, like ad creatives. The private default would sign each URL with a six-hour expiry against the internal `minio:9000` host, which no browser can resolve — every avatar would render as a broken image.
- **The type is decided by decoding the file**, never by the `Content-Type` header or the filename: both are client-supplied. The stored name is generated server-side, with the extension of whatever Pillow actually opened.
- **Replacing an image deletes the one it supersedes**, so the bucket does not grow by one object per edit. That delete is best-effort and runs after the row is saved — an orphaned object is a cleanup problem, not a failed request.
- **The browser's checks are a courtesy.** The upload form rejects an oversized file before spending the user's bandwidth on it; the server repeats every check on the bytes that actually arrive.

`website_url` is rendered as an anchor on a public page, so it is restricted to `http`/`https` and emitted with `rel="noopener noreferrer nofollow ugc"` — a profile link is neither a free ranking boost nor a handle on the tab that opened it.

Both images are optional. With none uploaded the channel header falls back to the gradient and an initials tile, which is also what a viewer sees if an object ever goes missing from the bucket.

## Live streaming

Two ways in, one way out. A phone or a laptop goes live from the browser with
nothing installed; OBS still publishes over RTMP for anyone with a real setup.
Both land on the same path, so everything downstream — HLS, chat, recording,
the VOD conversion — cannot tell them apart.

```
  OBS / ffmpeg                          browser (phone or computer)
       │  RTMP  rtmp://localhost:1936/live     │  WHIP  /live-webrtc/webrtc/<slug>/whip
       │  Stream Key: <slug>?key=<secret>      │  short-lived publish ticket
       │                                       │  H264 + Opus, media over UDP :8189
       ▼                                       ▼
  ┌──────────────────────────────────────────────────────────┐
  │  MediaMTX 1.20                                           │
  │                                     webrtc/<slug>        │
  │                                          │  ffmpeg bridge│
  │                                          │  audio → AAC  │
  │   :1935 RTMP in                          │  video copied │
  │   :8889 WHIP in                          ▼               │
  │   :8189 WebRTC media (UDP)          live/<slug>          │   ┌──────────────┐
  │   :8888 HLS out ────────────────────────────────────────►│──►│ nginx        │──► viewer
  │   :9997 control API                                      │   │ /live-hls/   │
  │                                                          │   └──────────────┘
  │   auth hook ──────► Django: validate key / ticket        │
  │   runOnAvailable ─► Django: session opens                │
  │   runOnUnavailable► Django: session closes               │
  │   record ─────────► fMP4 on shared volume                │
  └──────────────────────────┬───────────────────────────────┘
                             │  Celery
                             ▼
                   the SAME VOD pipeline as an upload
                   (probe → ladder → package → thumbs)
                             │
                             ▼
                     a normal, private Video
```

### Going live from a phone or a laptop

**Studio → Mon direct → Diffuser depuis cet appareil.** Pick camera or screen,
check the preview, press *Passer en direct*. No stream key, no OBS, no install.
On a phone the front/back camera toggle is there too.

Under it, three things are worth knowing.

**The browser publishes to a staging path, not to the broadcast path.** A
browser can only send Opus audio over WebRTC, and the MPEG-TS HLS every viewer
plays cannot carry Opus. So `webrtc/<slug>` is bridged into `live/<slug>` by an
ffmpeg that re-encodes *only the audio* — the H264 video is copied through
frame-for-frame. That is one audio encode per broadcast; a video transcode would
cost roughly fifty times as much. The alternative, moving the whole platform to
fMP4 HLS, would have broken audio on every iPhone in the audience.

The channel flips to `live` when the **bridged** stream arrives, never when the
browser connects — so viewers are never pointed at a path that has no playlist
yet. `mediamtx/bridge.sh` is the whole bridge, comments included.

**H264 is required of the browser, not merely preferred.** The WHIP client
filters its codec preferences down to H264 and fails loudly if the browser has
none, because a VP8 offer would silently turn the cheap audio-only bridge into a
full transcode. Every current Chrome, Edge, Safari and Firefox can send H264.

**The camera is authorised by a ticket, not by the stream key.** Pressing *go
live* mints a credential that is bound to one channel and expires in five
minutes (`LIVE_WHIP_TICKET_TTL_SECONDS`). The permanent stream key never reaches
the browser, never lands in a URL, and never appears in MediaMTX's access log.
The OBS path still uses the key — it has no way to hold a ticket.

> **HTTPS is not optional for this.** Browsers only grant camera and microphone
> access in a secure context, which means HTTPS or `localhost`. Reached over
> plain HTTP on a LAN address, a phone reports no camera at all — the studio
> detects this and says so rather than letting it look like a broken device.
> `LIVE_WEBRTC_HOST` must also name a host the *browser* can reach, or ICE never
> connects.

### The path/key split

OBS is configured with:

| OBS field | Value |
|---|---|
| Server | `rtmp://localhost:1936/live` |
| Stream Key | `<channel-slug>?key=<secret>` |

The **slug is the RTMP path; the secret rides in the query string.** That split is the point: the path is what appears in the HLS URL every viewer fetches, so putting the key there would hand a publishing credential to the entire audience.

Django validates the key with `hmac.compare_digest` — a plain `==` on a secret leaks its prefix through timing to anyone who can measure the endpoint.

### Session lifecycle

`runOnAvailable` and `runOnUnavailable` post to Django, which opens and closes a `LiveRecording` (which doubles as the session record, so chat starts clean each broadcast). `start_session` is idempotent: MediaMTX re-fires the hook after a brief publisher reconnect, and that must not spawn a second session or reset an ongoing broadcast's viewer count.

Hooks are best-effort — if MediaMTX is killed, `runOnUnavailable` never runs and a channel would advertise a stream nobody can watch. A beat task every 2 minutes reconciles against MediaMTX's control API, which is the source of truth for what is actually publishing. It deliberately does nothing when the API is unreachable, rather than mass-ending channels over a network blip.

### Viewer counts and chat

One WebSocket per viewer at `ws/live/<slug>/` carries chat, the viewer count and status changes — the same audience, so two sockets per viewer would double connections for nothing.

Counts come from **our own socket connections**, not MediaMTX's reader count: that measures people watching *on this site*, which is what a viewer badge means, and it needs no polling. Anonymous viewers may connect and read (they are part of the audience); posting requires authentication, enforced in the consumer. A per-connection interval guard rate-limits chat, because DRF throttles never see a WebSocket frame.

### Recording → VOD

When a broadcast ends, the recording is queued through the **standard VOD pipeline** — not a second parallel transcoder. It becomes an ordinary `Video` and runs the same probe → ladder → package → thumbnails → publish chain as a user upload. One pipeline to keep correct instead of two.

The result is created **private**. A stream that captured something the broadcaster did not intend is not republished automatically; publishing stays an explicit choice.

### Two security notes worth reading

**Read authorization does not use MediaMTX's HTTP auth.** MediaMTX completes read-auth with a `Secure` cookie, which browsers refuse over plain HTTP — on an `http://` deployment the handshake can never complete. Rather than require TLS for a local demo, reads are excluded in `mediamtx.yml` and enforced one layer out: nginx `auth_request`s Django on every **playlist** fetch. That is a real enforcement point — a player cannot keep playing without refreshing the playlist every couple of seconds, so disabling a channel stops in-flight playback within one segment duration (verified: 403 within ~5s). Segments are not individually authorised; per-segment auth would put Django back in the media path, which is exactly what this architecture avoids.

**The stream key is never rendered in the Django admin** — not even read-only. An admin page is one shoulder-surf from a channel takeover, and the owner can always rotate the key from their studio. Rotation is refused mid-broadcast, because it would not kill the RTMP session MediaMTX already authorised, and the user would believe they had revoked access when they had not.

## Testing live streaming with OBS or ffmpeg

A live stream cannot be seeded — it needs a real push. The seed provisions the channel and key so this works immediately.

**The quickest test needs neither OBS nor ffmpeg:** open
http://localhost:8110/studio/live, press *Activer la camera*, then *Passer en
direct*, and watch yourself at http://localhost:8110/live/&lt;your-slug&gt;. That
exercises the WebRTC path. The RTMP instructions below exercise the other one.

**Demo credentials** (owner: `fatou@streamverse.local`):

| | |
|---|---|
| OBS **Server** | `rtmp://localhost:1936/live` |
| OBS **Stream Key** | `fatou?key=sv-demo-stream-key-do-not-use-in-production` |
| Watch page | http://localhost:8110/live/fatou |
| Studio page | http://localhost:8110/studio/live |

### With ffmpeg (no OBS needed)

```bash
ffmpeg -re \
  -f lavfi -i "testsrc2=size=1280x720:rate=25" \
  -f lavfi -i "sine=frequency=440" \
  -c:v libx264 -preset ultrafast -tune zerolatency -g 50 -pix_fmt yuv420p \
  -c:a aac -b:a 128k -f flv \
  "rtmp://localhost:1936/live/fatou?key=sv-demo-stream-key-do-not-use-in-production"
```

Then open **http://localhost:8110/live/fatou**. Within a few seconds the channel flips to `live`, the player starts, and the viewer count reflects everyone on the page.

### Browser ingest, without a browser

ffmpeg 7.1+ can speak WHIP, which is a way to exercise the whole WebRTC path —
ticket, bridge, HLS — on a machine with no camera. Mint a ticket first:

```bash
TOKEN=$(curl -s -X POST http://localhost:8110/api/auth/jwt/create/ \
  -H 'Content-Type: application/json' \
  -d '{"email":"fatou@streamverse.local","password":"StreamVerse2026!"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access"])')

WHIP=$(curl -s -X POST http://localhost:8110/api/live/me/webrtc-ticket/ \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["publish_url"])')

ffmpeg -re \
  -f lavfi -i "testsrc2=size=1280x720:rate=30" \
  -f lavfi -i "sine=sample_rate=48000" \
  -c:v libx264 -preset ultrafast -pix_fmt yuv420p -g 60 \
  -c:a libopus -ar 48000 -ac 2 \
  -f whip "http://localhost:8110${WHIP}"
```

Note the codecs: **H264 and Opus**, exactly what a browser sends. The ffmpeg
inside the MediaMTX container can run this too, which is how the path is tested
from a host that has no ffmpeg of its own:

```bash
docker compose exec mediamtx sh -c "ffmpeg ... -f whip 'http://nginx${WHIP}'"
```

### With OBS

Settings → Stream → Service: **Custom…**, then paste the Server and Stream Key above. Start Streaming.

### What to check

```bash
# The channel flipped to live, and the playback URL is now offered
curl -s http://localhost:8110/api/live/fatou/ | python3 -m json.tool | head -8

# The HLS manifest is served through nginx (not from MinIO — MediaMTX is the origin)
curl -sL http://localhost:8110/live-hls/live/fatou/index.m3u8

# A wrong key is refused at the RTMP handshake
ffmpeg -re -f lavfi -i "testsrc2=size=320x240:rate=15" -c:v libx264 -t 3 -f flv \
  "rtmp://localhost:1936/live/fatou?key=WRONG"     # -> Broken pipe
```

**Chat and viewer count:** open the watch page in two browser windows. The count updates in both, messages appear in both, and a signed-out window can read but not post.

**Takedown enforcement**, mid-broadcast:

```bash
docker compose exec backend python manage.py shell -c "
from apps.live.models import LiveChannel
LiveChannel.objects.filter(slug='fatou').update(is_enabled=False)"
# the playlist starts returning 403 within ~5 seconds and playback stops
```

**Recording → VOD:** stop the stream, wait ~30 s, then check the studio at `/studio/live` — the session shows the converted video once the pipeline finishes. Or:

```bash
docker compose exec backend python manage.py shell -c "
from apps.live.models import LiveRecording
s = LiveRecording.objects.order_by('-started_at').first()
print(s.duration_seconds, 's |', round(s.recorded_size_bytes/1048576, 1), 'MiB |',
      'video:', s.converted_video_id, '|', s.conversion_error or 'no error')"
```

## Monetization

### Money is an integer

Every amount is a whole number of FCFA, in the database and on the wire. XOF has
no minor unit so there is nothing to round — but the reason for integers is the
general one: floats silently lose value, and a ledger that disagrees with the
provider by a rounding error is worse than one that fails loudly. The API returns
both `price` (int) and `price_display` (`"2 000 FCFA"`) so the client never does
arithmetic or guesses a locale's grouping rules.

### The payment flow is genuinely asynchronous

`backend/apps/monetization/providers/`

A mock that flips a transaction to `completed` inside the request proves nothing.
The hard parts of payments are *asynchronous confirmation*, *signature
verification*, *replay* and *out-of-order delivery* — and a synchronous stub
tests none of them. So the mock provider:

```
POST /api/monetization/checkout/
      │
      ├─► Transaction created  status=pending      ← returned to the client
      │
      └─► Celery task, N seconds later
              │
              └─► HTTP POST to our own public webhook endpoint
                    with an HMAC signature over "timestamp.body"
                          │
                          ├─ signature verified BEFORE the payload is read
                          ├─ WebhookEvent recorded, unique per (provider, event_id)
                          └─ transaction → completed | failed, subscription activated
```

The client polls the transaction until it settles. That waiting state is not
padding: a mobile-money push has to be approved on the payer's handset, and
pretending the payment is instant is a lie the user discovers when their
subscription does not appear.

`MOCK_PAYMENT_FAILURE_PERCENT` (default 15) makes a share of payments fail, so
the failure path is exercised by the demo rather than only by a hand-written
test.

### Idempotency and replay, enforced by the database

| Risk | Guard |
|---|---|
| Double-clicked checkout, retried request | `Transaction.idempotency_key` is **UNIQUE**. Same key → the existing transaction is returned, not a second charge. |
| Provider retries a callback until it gets a 2xx | `WebhookEvent` is **UNIQUE on (provider, event_id)**. A duplicate is answered `200 {"duplicate": true}` — an error would make the provider retry forever. |
| Replay of an old captured callback | The timestamp is inside the signed material and rejected outside a 5-minute window. |
| Late `failed` after a `completed` | Terminal states are final; a subscription already paid for is never revoked by a straggling callback. |
| Provider confirms a different amount | Treated as a reconciliation failure, not a subscription to activate. |
| A price sent by the client | There is no amount field in the checkout request. The price is read from the plan server-side. |

One subtlety worth calling out: **the idempotency lookup runs before the
"already subscribed" guard.** A client retrying after a lost response sends the
same key, and by then its own pending subscription exists — guarding first would
reject the retry with "a payment is already in progress" instead of returning the
transaction it is asking about. (This was a real bug caught in testing.)

### Cancellation keeps what was paid for

Cancelling turns off auto-renewal and keeps access to the end of the current
period. Revoking immediately would be taking money for nothing.

### Ads

`backend/apps/monetization/services/ads.py`

**The rule that must never be got wrong: an ad-free subscriber sees no ads** —
checked server-side at selection time, not in the player, which the user
controls. The endpoint returns `reason: "subscriber_ad_free"` and the watch page
shows an *Ad-free* badge because of it.

Selection is **weighted rotation** over eligible campaigns (active, in date
range, under cap, category-matched). Weight 3 serves three times as often as
weight 1 — not an auction, and not dressed up as one. Impressions are counted at
**serve** time, not completion: an ad delivered and then abandoned still consumed
inventory, and counting only completions would let a campaign blow past its cap.

Mid-rolls are skipped entirely on videos shorter than `ADS_MIN_DURATION_FOR_MIDROLL`
(default 120 s) and fire at most once per session, never on a seek backwards.

Campaign management is a **dedicated React view at `/manage/ads`**, not Django
admin CRUD — approving, pausing and capping campaigns against their delivery is a
decision workflow, and those actions are one click there versus buried in a
generic model form. (It lives under `/manage/` because `/admin/` belongs to
Django; nginx proxies that prefix.)

### Trying it

```bash
# Plans and payment methods
curl -s http://localhost:8110/api/monetization/plans/ | python3 -m json.tool
curl -s http://localhost:8110/api/monetization/providers/ | python3 -m json.tool
```

In the UI: **/premium** → pick a plan → choose Orange Money / Moov / Wave / card
→ watch the pending state resolve on its own a few seconds later.

Ad behaviour is easiest to see by comparing two accounts on the same video:
`koffi@streamverse.local` (no subscription — gets a pre-roll) against
`nadia@streamverse.local` (subscribed — gets the *Ad-free* badge and no ads).

To watch the whole payment path in the logs:

```bash
docker compose logs -f celery-worker | grep -i "mock payment\|webhook"
```

## Moderation

`backend/apps/moderation/` · UI at **`/manage/moderation`**

The queue is `engagement.Report` — reports are what moderators work through, and
a second copy of them here would mean two sources of truth for one workflow.
What the moderation app owns is the record of what was **decided**.

### A removal always carries a reason

Validated in the serializer *and* again in the service, because the service is
also reachable from management commands and the admin. Ten characters minimum,
and the text is what gets communicated to the author. Content that vanishes with
nobody able to say why is how a moderation system loses the trust of the people
it moderates.

`take_down`, not delete: the uploader is owed an explanation, an appeal needs the
original, and a DMCA-style process needs a record of what was removed. Restoring
is a first-class action.

### The decision screen shows the history first

Opening a report loads, on one screen: the reported content, its author, how many
*other* people reported the same thing, and that author's prior record over the
last 90 days — with a repeat-offender flag at three upheld actions. Four actions
are one click each:

| Action | Effect |
|---|---|
| Dismiss | Report closed as unfounded. Reason optional. |
| Remove | Content taken down. **Reason required.** |
| Remove and warn | …plus a warning on record (restricts nothing, counts toward escalation). |
| Remove and suspend | …plus a suspension for N days, or a permanent ban. |

Resolving a report also closes every other pending report about the same content
— otherwise a moderator reviews the same thing three times.

This is a dedicated React view rather than Django admin CRUD for exactly that
reason: a generic model form gives you none of that context, and the four actions
would be buried in a field list.

### Suspension takes effect on the next request

Not the next login. `SuspensionAwareJWTAuthentication` rejects a suspended
account even while it still holds an unexpired access token — verified: a token
that worked a second earlier returns 401 immediately after the suspension, and
works again after reinstatement.

A moderator cannot sanction another moderator or an admin from the queue; that is
an admin decision, not a click in a worklist.

### Everything is audited twice over

Each decision writes a `ModerationAction` (the moderator-facing history, with the
stated reason) and an `AuditLog` entry (the append-only platform trail). Both are
read-only in the Django admin — a moderation record an admin can edit is not a
record.

### Admin dashboard

**`/manage/dashboard`** (admin only): users, videos by status, total views,
rendition storage, live channels, revenue, active subscriptions, pending reports,
and 30-day uploads-vs-signups. The moderation queue has its own health panel —
including **the age of the oldest pending report**, which is the first sign a
queue is failing long before the total count looks bad.

### Trying it

Sign in as `moderator@streamverse.local` and open **/manage/moderation**. The
seed leaves two pending reports. Report something yourself from any video's
**Report** button to add a third, then work it through the queue.

```bash
# Try to remove content without a reason — refused
curl -s -X POST http://localhost:8110/api/moderation/reports/1/ \
  -H "Authorization: Bearer $MOD_TOKEN" -H 'Content-Type: application/json' \
  -d '{"action":"remove","reason":"short"}'
# -> 400, "Un motif d'au moins 10 caracteres est obligatoire"
```

## Library: history, bookmarks, likes, following

`backend/apps/library/` · UI at **`/library`** and **`/subscriptions`**

Four features that share one shape — a row per (user, thing) — and one audience:
the signed-in viewer's own stuff. All six endpoints are scoped to `request.user`
at the queryset level and return **401 to anonymous callers**; there is no path
by which one user reads another's library.

### Watch history is deliberately not derived from `View`

`engagement.View` and `library.WatchHistoryEntry` look redundant. They are not —
they answer different questions and have different lifetimes:

| | `View` | `WatchHistoryEntry` |
|---|---|---|
| Purpose | analytics | the viewer's own record |
| Granularity | one row per 12-hour bucket | one row per video, ever |
| Anonymous viewers | yes | no |
| Feeds | `Video.view_count` | "recently viewed" / "continue watching" |
| Lifetime | pruned at 180 days | until the user deletes it |
| User can delete | no | **yes** |

Deriving history from `View` would mean **clearing your history silently
decrements the creator's view count** — a privacy action that quietly falsifies
someone else's stats. Verified: removing an entry leaves `view_count` unchanged.

History is written from the **existing view heartbeat**, so "recently viewed"
costs no extra request per playback. Two rules make it useful rather than noisy:

- Under 3 seconds is a misclick, not history — nothing is recorded.
- `progress_seconds` is the **furthest point reached**, not the last position, so
  seeking backwards near the end does not lose the fact you nearly finished.
  "Continue watching" then offers only entries between 5% and 95% — resuming a
  video at 98% is noise.

### Bookmarks and likes

Bookmarks are a plain toggle with a unique constraint per (user, video). The
liked shelf reads the existing `Like` rows where `is_like=True`, ordered by *when
you liked it* — via a correlated subquery, because joining on `likes` would
multiply each video by its like count and repeat rows in the page.

Dislikes are deliberately not listed. Nobody wants a browsable shelf of things
they disliked.

### Following

A plain social graph: `Follow(follower, channel)` with a unique constraint, and a
**database-level check constraint** forbidding self-follows — your own uploads in
your own "new from channels you follow" feed is noise, not a feature.

Counters on `User` are **recomputed from the rows** inside the toggle transaction
rather than incremented, so they cannot drift.

The `/subscriptions` feed is strictly chronological. The platform has no
recommendation model and this feed does not pretend to be one; the page says so.

**There are still no notifications.** Following changes only the follower's own
feed — nobody is emailed or pushed when a channel uploads. That was the part of
the original "no follow graph" scope decision that carried the real cost, and it
stands.

### N+1 avoidance

Grid endpoints attach the caller's bookmark/reaction state to a whole page in
**two queries**, not two per card — 48 queries on a 24-item grid is the naive
version of this feature.

### Trying it

```bash
# The library is private
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8110/api/library/history/   # 401

# Watching for 1s does not enter history; 40s does
curl -s -X POST http://localhost:8110/api/videos/$V/view/ -H "Authorization: Bearer $T" \
  -H 'Content-Type: application/json' -d '{"watched_seconds":1,"client_id":"demo"}'
curl -s -X POST http://localhost:8110/api/videos/$V/view/ -H "Authorization: Bearer $T" \
  -H 'Content-Type: application/json' -d '{"watched_seconds":40,"client_id":"demo"}'
curl -s http://localhost:8110/api/library/history/ -H "Authorization: Bearer $T"
```

In the UI: **/library** has four tabs (History with a *Continue watching* rail,
Bookmarks, Liked, Following). **/subscriptions** is the feed. Follow buttons are
on the channel page and under the player; the bookmark toggle sits beside the
like buttons.

## Security & SEO

### Response headers

Every SPA response carries a Content-Security-Policy, which matters here
specifically because JWTs are held in `localStorage`: without a CSP, a single
injected script can read them. With one, there is no origin an injected script
may load code from or exfiltrate to.

| Header | Where | Value |
| --- | --- | --- |
| `Content-Security-Policy` | SPA + preview routes | `default-src 'self'`, `object-src 'none'`, `frame-ancestors 'none'`, `script-src 'self'` (no `unsafe-inline`, no `unsafe-eval`) |
| `X-Content-Type-Options` | everywhere | `nosniff` |
| `X-Frame-Options` | SPA, API, admin | `DENY` |
| `Referrer-Policy` | SPA / API | `strict-origin-when-cross-origin` / `same-origin` |
| `Permissions-Policy` | SPA + API | camera, microphone, geolocation, payment, USB all denied; autoplay/fullscreen/PiP/EME kept for the player |
| `Cross-Origin-Opener-Policy` | SPA | `same-origin` |
| `Cross-Origin-Resource-Policy` | API | `same-origin` |
| `X-Permitted-Cross-Domain-Policies` | API | `none` |

Three CSP relaxations are deliberate and each has a reason:

- `worker-src 'self' blob:` — hls.js spawns its demuxer worker from a Blob URL.
- `style-src 'unsafe-inline'` — React writes inline `style=""` attributes
  (progress bars, poster backgrounds). CSP counts those as inline styles, and
  nonces cannot cover attributes.
- `img-src` / `media-src` / `connect-src` include `MINIO_PUBLIC_ENDPOINT` —
  posters, manifests and segments are fetched straight from object storage,
  which is the entire point of keeping Django out of the byte path.

The API sets its own headers in `apps.core.middleware.SecurityHeadersMiddleware`
rather than relying only on the edge, so it stays safe if it is ever exposed
without the reverse proxy in front of it. `server_tokens off` stops nginx
advertising its exact build.

HSTS, HTTPS redirect and `Secure` cookies are env-gated and **off by default**,
because the demo runs on plain HTTP. `SECURE_HSTS_SECONDS` in particular is
effectively irreversible for its duration once a browser has seen it — set it
only when TLS is permanent.

### Known accepted risks

These are real and deliberately not addressed in this build:

- **JWTs live in `localStorage`**, so any successful XSS reads them. The CSP is
  the mitigation. Moving to `httpOnly` cookies would need CSRF handling on every
  mutating endpoint — a larger change than a header pass.
- **The WebSocket access token is passed in the query string** (browsers cannot
  set headers on a WebSocket handshake), so it lands in nginx and uvicorn access
  logs. Short access-token lifetimes limit the window.
- `ALLOWED_HOSTS` defaults to `*` for the demo. Set it to real hostnames in
  production.
- `LIVE_HOOK_SECRET` and `MOCK_PAYMENT_WEBHOOK_SECRET` fall back to slices of
  `DJANGO_SECRET_KEY`. Set them explicitly so rotating one does not rotate all.
- The public MinIO bucket is anonymous-read **by design** — that is what makes
  public HLS delivery work without Django in the path.

### SEO

A single-page app serves the same empty shell for every URL, which breaks
indexing and link previews in two different ways, so there are two fixes.

**For search engines**, which do execute JavaScript: `useDocumentMeta` rewrites
title, description, canonical, Open Graph, Twitter Card and JSON-LD per route.
Watch pages emit `VideoObject` (the schema that earns a video-rich result),
channels emit `ProfilePage`, and the home page emits `WebSite` + `SearchAction`.

**For link unfurlers** — Facebook, Slack, WhatsApp, Discord, LinkedIn — which do
not run scripts at all: nginx matches their user agents and routes `/watch/<id>`,
`/shorts/<id>` and `/c/<username>` to server-rendered previews from `apps.seo`
carrying the same title, description and poster the user sees, with
`Vary: User-Agent` so no cache serves one to the other. Googlebot is
deliberately **not** in that list: it renders JS, and serving it different HTML
than a person gets is the definition of cloaking.

The logo ships as one transparent, pre-cropped PNG (`src/assets/images/logo.png`,
26 KB) rendered through `components/Logo.jsx`, plus a favicon set, an iOS touch
icon on a brand plate (iOS composites onto white) and a 1200x630 `og-image.png`
used as the social card for any page without art of its own.

`robots.txt` and `sitemap.xml` are generated by Django, not shipped as static
files — the sitemap has to enumerate the live catalogue, and both need the
deployment's real origin (`SITE_URL`) rather than a value baked in at build
time. The sitemap covers public videos, Shorts, channels and categories;
unlisted videos are excluded, because listing them would undo exactly what
"unlisted" means. `/search` is disallowed and marked `noindex`: one indexable
page per query string is unbounded crawl space with no content of its own.

The sitemap is deliberately **not** cached. An hour-old copy keeps advertising a
video that has since been taken down or made private, and a takedown has to stop
pointing crawlers at the video immediately; the queries behind it are indexed and
column-limited, and crawlers fetch it rarely.

## Roles

Enforced server-side via DRF permission classes **and** queryset scoping. Studio endpoints filter on `uploader=request.user` at the database level, so an object-permission bug cannot expose someone else's row.

| Capability | user | moderator | admin |
|---|:--:|:--:|:--:|
| Upload / transcode / retry own video | ✅ | ✅ | ✅ |
| Edit, delete, publish own video | ✅ | ✅ | ✅ |
| Own creator dashboard & stats | ✅ | ✅ | ✅ |
| Own live channel, stream key, go live | ✅ | ✅ | ✅ |
| Chat in a live stream | ✅ | ✅ | ✅ |
| Disable **any** live channel (takedown) | ❌ | ❌ | ✅ |
| Subscribe to a paid plan, cancel it | ✅ | ✅ | ✅ |
| Manage ad campaigns (`/manage/ads`) | ❌ | ❌ | ✅ |
| Moderation queue (`/manage/moderation`) | ❌ | ✅ | ✅ |
| Take down / restore any video | ❌ | ✅ | ✅ |
| Warn, suspend or ban an account | ❌ | ✅ | ✅ |
| Sanction a moderator or admin | ❌ | ❌ | ✅ (Django admin) |
| Admin dashboard (`/manage/dashboard`) | ❌ | ❌ | ✅ |
| Watch public / unlisted content | ✅ | ✅ | ✅ |
| Watch **any** private video | ❌ | ✅ | ✅ |
| Delete any comment on **own** video | ✅ | ✅ | ✅ |
| Delete **any** comment platform-wide | ❌ | ✅ | ✅ |
| Edit any video / force takedown | ❌ | ❌ | ✅ |
| Django admin (Jazzmin) | ❌ | ❌ | ✅ |
| Read full audit log | ❌ | ❌ | ✅ |
| Comment, like, report | ✅ | ✅ | ✅ |
| Watch history, bookmarks, follow channels | ✅ | ✅ | ✅ |
| *Phase 6:* review report queue, suspend accounts | ❌ | ✅ | ✅ |
| *Phase 5:* ad campaigns, subscription plans | ❌ | ❌ | ✅ |

Suspension is enforced on **every request**, not just at login: `SuspensionAwareJWTAuthentication` rejects a suspended account even while it still holds an unexpired access token.

---

## Ports

Deliberately non-default so this stack can share a server with other projects.

| Service | Host port | Notes |
|---|---|---|
| App (nginx) | **8110** | the only port you normally need |
| PostgreSQL | 5459 | |
| Redis | 6402 | |
| Flower | 5574 | Celery queue monitor |
| MinIO S3 API | **9010** | the browser fetches HLS from here |
| MinIO console | 9011 | |
| RTMP ingest (MediaMTX) | **1936** | OBS publishes here |
| WebRTC media (MediaMTX) | **8189/udp** | browser broadcasts land here. UDP, and it cannot be proxied — the WHIP handshake goes through nginx, the media does not |

---

## Environment variables

Everything is in `.env.example` with comments. The ones that matter most:

| Variable | Default | Why you would change it |
|---|---|---|
| `DJANGO_SECRET_KEY` | — | **Required.** No working default. |
| `MINIO_PUBLIC_ENDPOINT` | `http://localhost:9010` | Must match the host the **browser** uses, or presigned URLs fail signature validation. |
| `CELERY_WORKER_CONCURRENCY` | `2` | Match to real CPU cores — see below. |
| `FFMPEG_PRESET` | `veryfast` | `medium`/`slow` give better quality per bit at multiples of the wall-clock cost. |
| `FFMPEG_VIDEO_ENCODER` | `libx264` | `h264_nvenc` on an NVIDIA-runtime host. |
| `MINIO_PRESIGN_TTL_SECONDS` | `21600` (6 h) | Private playback session lifetime. |
| `MAX_UPLOAD_BYTES` | 5 GiB | |
| `MAX_AVATAR_BYTES` / `MAX_BANNER_BYTES` | 5 MiB / 10 MiB | Profile image ceilings, enforced by decoding the upload. |
| `MAX_AVATAR_DIMENSION` / `MAX_BANNER_DIMENSION` | 2048 / 6000 px | Longest side accepted for each. |
| `SEED_ON_START` | `1` | Set `0` to skip demo seeding. |
| `LIVE_RTMP_PUBLIC_URL` | `rtmp://localhost:1936` | What broadcasters type into OBS. Change the host for a real domain. |
| `LIVE_HOOK_SECRET` | — | Shared secret for the MediaMTX lifecycle hooks. **Change it.** |
| `LIVE_RECORDING_RETENTION_DAYS` | `7` | Raw recordings are deleted this long after conversion. |
| `PAYMENTS_USE_MOCK` | `1` | The single switch between the simulator and real providers. Turning it off with none implemented raises at startup. |
| `MOCK_PAYMENT_WEBHOOK_SECRET` | — | HMAC secret the mock signs callbacks with. **Change it.** |
| `MOCK_PAYMENT_FAILURE_PERCENT` | `15` | Share of simulated payments that fail, so the failure path is exercised. |
| `ADS_ENABLED` | `1` | Master switch for ad selection. |
| `ADS_MIN_DURATION_FOR_MIDROLL` | `120` | Videos shorter than this get no mid-roll. |
| `JWT_ACCESS_MINUTES` / `JWT_REFRESH_DAYS` | 15 / 7 | Refresh tokens rotate and blacklist on use. |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | — | Both blank turns Google sign-in off, button included. |
| `GOOGLE_OAUTH_REDIRECT_URI` | `FRONTEND_URL` + `/auth/google/callback` | Must match the Google credential byte for byte. |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | — | Without these no activation email is delivered. Gmail needs an App Password. |
| `EMAIL_BACKEND` | SMTP | `…console.EmailBackend` prints mail to the log instead of sending it. |
| `EMAIL_ASYNC` | `1` | `0` sends inline, so SMTP errors surface in the API response. |

---

## Performance & scaling

**Transcoding is the expensive thing this platform does.** Each Celery slot can saturate a CPU core for the entire length of an encode.

- `CELERY_WORKER_CONCURRENCY` defaults to **2**, which suits a laptop demo. On a real deployment, size it to actual cores — roughly `cores - 1`, leaving headroom for Postgres and the ASGI workers. Setting it higher than the core count does not increase throughput; it just makes every encode slower and every progress bar less useful.
- `CELERY_WORKER_PREFETCH_MULTIPLIER=1` and `acks_late` are set so a worker cannot hoard a queue of hour-long jobs it will not get to.
- Transcoding runs on a **separate `transcode` queue** from bookkeeping tasks, so a burst of uploads never starves cleanup or mail.
- **Hardware-accelerated encoding is an optional upgrade, not assumed available.** On a GPU host, set `FFMPEG_VIDEO_ENCODER=h264_nvenc` and give the worker container the NVIDIA runtime. Expect roughly an order of magnitude speed-up at slightly worse quality per bit.
- The `minio_data` volume grows fast — a 1080p source produces five renditions, so plan for roughly 1.5–2× the original file size across the ladder, plus the archived original.
- The **archived original** is kept in the private bucket so a retry does not depend on the scratch volume. Delete `originals/` if storage matters more than retry capability.

Beat tasks that keep the disk honest:

- `cleanup_abandoned_uploads` (every 30 min) — expires tus sessions nobody finished and deletes their scratch files.
- `cleanup_stale_workdirs` (every 6 h) — removes FFmpeg work directories left by a worker that was killed mid-encode.

---

## Verifying the pipeline end to end

This is the acceptance test for Phase 2. It takes about two minutes.

```bash
# 1. Bring the stack up
docker compose up --build

# 2. Confirm every service is healthy
curl -s http://localhost:8110/api/health/ | python3 -m json.tool
# {"status": "ok", "checks": {"database": "ok", "redis": "ok", "object_storage": "ok"}}
```

**3. Watch a real upload go through.**

1. Sign in at http://localhost:8110/login as `fatou@streamverse.local` / `StreamVerse2026!`
2. Go to **Televerser** (`/upload`), drop any MP4/MOV/MKV in, give it a title, start.
3. Watch the upload bar, then the **transcoding** card that replaces it — stage names and percentage arrive over WebSocket.
4. When it reports `ready`, open the studio (`/studio`) and the video row shows `N × HLS`.

**4. Confirm multiple renditions actually exist:**

```bash
docker compose exec backend python manage.py shell -c "
from apps.videos.models import Video
v = Video.objects.filter(status='ready').latest('uploaded_at')
print(v.title, v.source_resolution, v.storage_bucket)
for r in v.renditions.all():
    print(f'  {r.label:>6}  {r.width}x{r.height}  {r.video_bitrate_kbps}kbps  {r.segment_count} segments')
print('master:', v.hls_master_path)
"
```

Or browse the buckets directly in the MinIO console at http://localhost:9011.

**5. Confirm adaptive playback.** Open the video, click the gear icon in the player — the quality list is populated from the master playlist's `#EXT-X-STREAM-INF` entries. Leave it on **Auto** and throttle the network in devtools; hls.js switches rungs at segment boundaries.

**6. Confirm the delivery split.** Open devtools → Network while playing:

- a **public** video: `.m3u8` and `.ts` requests all go to `localhost:9010` (MinIO). Nothing hits Django.
- a **private** video (set visibility to Private in the studio first): the `.m3u8` requests go to `localhost:8110/api/videos/.../hls/...` and every `.ts` goes to `localhost:9010` with `X-Amz-Signature` in the query string.

**7. Confirm failure handling is honest.** Upload a non-video file renamed to `.mp4` — it is rejected synchronously at the validation gate with a specific reason, and never reaches the queue.

### Phase 3: engagement & search

**8. View counting cannot be gamed.** Open a video and watch it briefly, then reload a few times. The count rises by **one**, not by the number of reloads:

```bash
V=$(curl -s "http://localhost:8110/api/videos/?page_size=1" | python3 -c "import sys,json;print(json.load(sys.stdin)['results'][0]['id'])")

# 1 second watched -> not counted
curl -s -X POST "http://localhost:8110/api/videos/$V/view/" \
  -H 'Content-Type: application/json' -d '{"watched_seconds":1,"client_id":"demo"}'

# past the threshold -> counted once, and only once
curl -s -X POST "http://localhost:8110/api/videos/$V/view/" \
  -H 'Content-Type: application/json' -d '{"watched_seconds":500,"client_id":"demo"}'
curl -s -X POST "http://localhost:8110/api/videos/$V/view/" \
  -H 'Content-Type: application/json' -d '{"watched_seconds":900,"client_id":"demo"}'
```

**9. Search reports its own confidence.** Compare an exact hit with a typo:

```bash
curl -s "http://localhost:8110/api/search/?q=django"  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['mode'], d['count'])"
curl -s "http://localhost:8110/api/search/?q=djngo"   | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['mode'], d['count'])"
curl -s "http://localhost:8110/api/search/?q=zzzqqq"  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['mode'], d['count'])"
# -> fulltext 3   /   fuzzy 1   /   none 0
```

The UI shows the same distinction as a badge on `/search`.

**10. Comments nest exactly one level.** On any video, reply to a comment — then try to reply to the reply. The API refuses it (`400`) rather than accepting a depth the UI cannot render. Deleting a parent as a moderator blanks it *and* its replies, and the deleted node's text never appears in the response payload.

**11. Counters self-heal.** Corrupt one on purpose and let the reconciliation task fix it:

```bash
docker compose exec backend python manage.py shell -c "
from apps.videos.models import Video
v = Video.objects.filter(status='ready').first()
Video.objects.filter(pk=v.pk).update(view_count=999999)
from apps.engagement.tasks import reconcile_counters
print(reconcile_counters())
v.refresh_from_db(); print('restored to', v.view_count)
"
```

---

### A note on `manage.py check --deploy`

The stack passes `check --deploy` with **four remaining warnings**, all of the
same kind and all expected for a demo published over plain HTTP on `localhost`:
`SECURE_HSTS_SECONDS`, `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`,
`CSRF_COOKIE_SECURE`. They are not silenced, because silencing them would hide a
real finding on the day this is deployed behind TLS.

To clear them on a real deployment, terminate TLS at your proxy and set:

```bash
SESSION_COOKIE_SECURE=1
CSRF_COOKIE_SECURE=1
# plus SECURE_SSL_REDIRECT / SECURE_HSTS_SECONDS in config/settings.py
```

There are **zero** schema, model or configuration errors — `/api/schema/`
generates cleanly with no drf-spectacular warnings.

## Phase status

| # | Phase | Status |
|---|---|---|
| 1 | Foundation — accounts, roles, catalogue, dashboards | ✅ **in this build** |
| 2 | Video upload & transcoding pipeline, adaptive playback | ✅ **in this build** |
| 3 | Engagement & search — views, likes, comments, reports, PostgreSQL full-text search, related videos, channel pages | ✅ **in this build** |
| 4 | Live streaming — RTMP *and* in-browser WebRTC ingest, HLS live playback, live chat, recording→VOD | ✅ **in this build** |
| 5 | Monetization — mock payment provider, subscriptions, first-party ad rotation | ✅ **in this build** |
| 6 | Moderation, admin dashboards, polish | ✅ **in this build** |
| 7 | Real payment provider integration | ⬜ blocked on merchant credentials — see [Monetization](#monetization) |

### What is deliberately present but inert

- The `live_start` throttle scope now rate-limits stream-key rotation; it will also gate session starts if per-user broadcast limits are added.
- `/api/studio/stats/` still returns an `engagement_available` flag. It became `true` in Phase 3; the field stays in the contract so the dashboard can always tell the user whether the numbers are live rather than assuming.

Engagement counters were seeded as bare numbers in the Phase 2 drop. They are now backed by real `View` / `Like` / `Comment` rows, and the seed derives the counters from those rows using the **same reconciliation task that runs in production** — so the demo numbers and the production maths agree.

### Deferred design decisions, recorded

- **MediaMTX over nginx-rtmp-module**, as agreed before the build. `arut/nginx-rtmp-module` has had no release in years and does not build cleanly against current Nginx; MediaMTX 1.20 is actively maintained, does RTMP→HLS natively, records without an external process, and exposes HTTP hooks that validate a stream key against Django. It runs as its own container, keeping the Nginx image standard.
- **Search** shipped in Phase 3 as PostgreSQL `tsvector` + GIN with a trigram fallback. The `/browse` page keeps a simple title filter for category browsing and says so; weighted full-text lives on `/search`.

---

## Scope notes (what this does not do)

Stated plainly rather than approximated:

- **No ML recommendations.** Related videos are content-based (shared tags, then category). No collaborative filtering, no watch-history modelling, no personalisation — two viewers get the same list. The API says `strategy: "content_based"` and the UI repeats it under the rail.
- **Search is not typo-tolerant in the Meilisearch sense.** PostgreSQL FTS with stemming, plus a trigram fallback for near-misses. The response carries the match `mode` so approximate results are labelled as such.
- **Ads are first-party rotation, not VAST/VPAID/programmatic.** There is no ad exchange, no auction, no header bidding and no third-party script in the viewer's browser. The server picks one of *our own* campaign rows by weighted rotation. Real ad-network integration is its own substantial project and is not equivalent.
- **Payments are simulated.** `PAYMENTS_USE_MOCK=1` by default and the checkout UI shows a sandbox banner because of it. The mock is genuinely asynchronous — signed HTTP callbacks, replay guard, idempotency — but no money moves. Turning the flag off with no real provider implemented raises at startup rather than silently pretending to take payments.
- **No automated copyright / content-ID detection.** This is a real gap for production use. The report flow (live since Phase 3, with a `copyright` reason) plus Phase 6's review queue provides a *manual* DMCA-style takedown path, which is not the same thing as automated content matching. The report dialog says so to the user filing it.
- **Live streaming cannot be seeded.** Demonstrating it needs an actual RTMP push from OBS or `ffmpeg`; a seed script cannot fabricate a live stream. The seed provisions the channel and a documented stream key so the walkthrough below works with zero setup.
- **Following exists, but notifications do not.** The original scope was follow-less browsing; a follow graph was added later at the product owner's request. A follow affects **only the follower's own feed** — nobody is emailed or pushed when a channel uploads, which was the part of "no follow graph" that carried the real cost. The subscriptions feed is strictly chronological, not ranked.
- **This is not a CDN.** Single-node MinIO with no edge caching. Fine for a demo or a small deployment; a real audience needs the caching layer noted above.

---

## Version choices

Versions were resolved against PyPI/npm at build time, not from memory, and pinned in `requirements.txt` / `package.json`.

**One deliberate exception: Django 5.2.17 LTS, not the latest 6.1.** `django-celery-beat` 2.9.0 declares a hard `Django<6.1` pin, and `djoser` 2.3.4 declares support only through 5.2. Django 5.2.17 is the newest release every required dependency actually supports, and it is an LTS with security support to April 2028. Revisit once those two publish 6.x support.

MinIO is pinned to `RELEASE.2025-04-22T22-12-26Z` rather than latest: later community releases stripped the embedded web Console, and the demo relies on the bucket browser for inspecting the public/private split by hand.

Other pins: DRF 3.18, Channels 4.3.2, Celery 5.6.3, React 19.2.8, Vite 8.2.1, Tailwind 4.3.3 (CSS-first config — the design tokens are in `src/styles/index.css`, there is no `tailwind.config.js`), hls.js 1.6.17, tus-js-client 4.3.1, PostgreSQL 18, Redis 8.10.
