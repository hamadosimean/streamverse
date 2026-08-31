# StreamVerse — Deployment Guide

This guide covers deploying StreamVerse to a production server. Development (`docker compose up --build`) is documented in the README and [CONTRIBUTING.md](./CONTRIBUTING.md).

---

## Table of Contents

1. [Minimum Server Requirements](#1-minimum-server-requirements)
2. [Environment Configuration](#2-environment-configuration)
3. [TLS / HTTPS](#3-tls--https)
4. [DNS and Ports](#4-dns-and-ports)
5. [Object Storage (MinIO)](#5-object-storage-minio)
6. [Email](#6-email)
7. [Payment Providers](#7-payment-providers)
8. [First Boot](#8-first-boot)
9. [Performance & Scaling](#9-performance--scaling)
10. [Backups](#10-backups)
11. [Updating](#11-updating)
12. [Pre-Flight Checklist](#12-pre-flight-checklist)

---

## 1. Minimum Server Requirements

| Resource | Development | Production (small) | Production (medium) |
|---|---|---|---|
| CPU | 2 cores | 4 cores | 8+ cores |
| RAM | 4 GB | 8 GB | 16 GB |
| Disk | 20 GB | 200 GB SSD | 500 GB+ SSD |
| Network | — | 100 Mbps | 1 Gbps |

Transcoding is CPU-bound. Set `CELERY_WORKER_CONCURRENCY` to the number of **physical** CPU cores, not threads.

Live streaming adds sustained bandwidth: plan for each concurrent RTMP stream at ~3–6 Mbps ingest and the same outbound per viewer × viewer count.

---

## 2. Environment Configuration

```bash
cp .env.example .env
```

The repo also carries a `.env.prod` for production values. Compose does not pick
it up automatically — select it explicitly:

```bash
docker compose --env-file .env.prod up -d --build
```

> `.gitignore` ignores `.env` and `.env.*`, re-admitting only `.env.example`.
> Keep it that way — `.env.prod` holds a real secret key plus database and
> object-store passwords.

Two mechanics are worth knowing — both are documented in
[CONFIGURATION.md §1](./CONFIGURATION.md#1-how-configuration-flows):

1. **Inside a container, Django never reads `.env`.** Values arrive as
   environment variables placed there by compose, so anything absent from the
   `x-backend-env` anchor in `docker-compose.yml` has no effect however you set
   it. Real SMTP credentials are the notable remaining case —
   [CONFIGURATION.md §22](./CONFIGURATION.md#22-known-gaps).
2. **An unset variable becomes an empty string, not a default** — compose
   substitutes `""`, and django-environ treats that as a value. Every forwarded
   variable therefore carries a `${VAR:-default}` fallback. Add one when you add
   a variable.

Confirm what a given env file actually produces before deploying:

```bash
docker compose --env-file .env.prod config | less
```

**Required for production** (must be changed from defaults):

```dotenv
DEBUG=0
DJANGO_SECRET_KEY=<256-bit random string>
ALLOWED_HOSTS=streamverse.example.com
CORS_ALLOWED_ORIGINS=https://streamverse.example.com
CSRF_TRUSTED_ORIGINS=https://streamverse.example.com
FRONTEND_URL=https://streamverse.example.com
SITE_URL=https://streamverse.example.com

POSTGRES_PASSWORD=<strong random password>
MINIO_ROOT_PASSWORD=<strong random password>

LIVE_HOOK_SECRET=<random string>
MOCK_PAYMENT_WEBHOOK_SECRET=<random string>
FLOWER_PASSWORD=<strong random password>

# Must match the origin the BROWSER uses to fetch HLS, or every presigned
# playback URL fails signature validation.
MINIO_PUBLIC_ENDPOINT=https://cdn.streamverse.example.com

# Required by docker-compose.yml but absent from .env.example.
LIVE_RECORDINGS_DIR=/data/recordings

# Where broadcasters point OBS.
LIVE_RTMP_PUBLIC_URL=rtmp://streamverse.example.com:1936

# Disable seed data in production
SEED_ON_START=0

# Match to PHYSICAL cores on the worker host.
CELERY_WORKER_CONCURRENCY=4

# HTTPS hardening
SECURE_HSTS_SECONDS=31536000
SECURE_SSL_REDIRECT=1
SESSION_COOKIE_SECURE=1
CSRF_COOKIE_SECURE=1
```

---

## 3. TLS / HTTPS

nginx is the TLS termination point. Recommended approach: put nginx behind **Certbot** or use a cloud load balancer for TLS offload.

### With Let's Encrypt (Certbot)

1. Add a Certbot container to your compose file or run it on the host.
2. Mount the certificates into the nginx container:
   ```yaml
   nginx:
     volumes:
       - /etc/letsencrypt:/etc/letsencrypt:ro
       - ./nginx/templates:/etc/nginx/templates:ro
   ```
3. Update `nginx/templates/default.conf.template` to add HTTPS server blocks and redirect HTTP → HTTPS.

### MinIO public endpoint

When using HTTPS, `MINIO_PUBLIC_ENDPOINT` must use HTTPS too:
```dotenv
MINIO_PUBLIC_ENDPOINT=https://cdn.streamverse.example.com
```
Or, point a subdomain at MinIO and configure its own TLS.

---

## 4. DNS and Ports

For production, publish **only port 443** (and 80 for redirect) from nginx to the public internet. All other service ports should be firewalled.

Only **RTMP ingest** (`1936`) needs to be public if your streamers are external.

Recommended DNS setup:

| Record | Value | Purpose |
|---|---|---|
| `streamverse.example.com` | Server IP | Main app |
| `cdn.streamverse.example.com` | MinIO IP / CDN | Object storage public endpoint |

---

## 5. Object Storage (MinIO)

The default MinIO setup is suitable for a single-server deployment. For higher availability:

- Replace MinIO with **AWS S3** or **Cloudflare R2** by setting the `MINIO_*` variables to point at the S3-compatible API.
- Create two buckets: one public (static-website hosting enabled) and one private.
- Set `MINIO_PUBLIC_BUCKET` and `MINIO_PRIVATE_BUCKET` accordingly.

**Bucket CORS policy for the public bucket** (required for HLS playback from the browser):
```json
[{
  "AllowedOrigins": ["https://streamverse.example.com"],
  "AllowedMethods": ["GET", "HEAD"],
  "AllowedHeaders": ["*"],
  "MaxAgeSeconds": 3600
}]
```

---

## 6. Email

SMTP is configured from `.env` alone — every `EMAIL_*` variable is forwarded to
the containers, and there is no local catcher to switch off.

```dotenv
# Gmail / Google Workspace
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=1
EMAIL_HOST_USER=you@yourdomain.com
EMAIL_HOST_PASSWORD=<16-character App Password>
DEFAULT_FROM_EMAIL=you@yourdomain.com
```

`EMAIL_HOST_PASSWORD` is an **App Password**, not the account password: Google
stopped accepting those over SMTP in May 2022 and refuses them with a bare
`535`. Create one at *myaccount.google.com → Security → App passwords* (2-Step
Verification must be on first). Gmail also rewrites or rejects a `From` that is
not the authenticated mailbox, so keep `DEFAULT_FROM_EMAIL` equal to
`EMAIL_HOST_USER` or one of its verified aliases.

Any other provider works the same way — port 587 with `EMAIL_USE_TLS=1`, or port
465 with `EMAIL_USE_SSL=1` instead. Never both.

Mail is sent by the **Celery worker**, not in the request, so a failure never
reaches the API response. Verify a deployment by signing up and watching:

```bash
docker compose logs -f celery-worker | grep -i send_email
```

`530 Authentication Required` means the credentials are empty; `535` means the
password is not an App Password. Sending three times over 30/60/120 seconds
before giving up is the task's own retry.

---

## 7. Payment Providers

The stack ships with a **mock payment provider** (`PAYMENTS_USE_MOCK=1`) for development. To enable real providers:

```dotenv
PAYMENTS_USE_MOCK=0
```

Then configure each provider's credentials in `.env`. Real provider integrations are implemented as subclasses of `BasePaymentProvider` in `backend/apps/monetization/providers/`.

Webhook endpoints must be publicly reachable. Register each provider's callback URL:
- `https://streamverse.example.com/api/monetization/webhooks/orange_money/`
- `https://streamverse.example.com/api/monetization/webhooks/wave/`
- etc.

---

## 8. First Boot

**The backend entrypoint already bootstraps itself.** With `command: ["asgi"]` it
waits for Postgres, Redis and MinIO, then runs `migrate`, `collectstatic`,
`init_minio` (bucket creation + access policies) and — unless `SEED_ON_START=0` —
the demo seed, before starting uvicorn. The worker and beat containers call
`wait_for_migrations` so they cannot race it. There is no separate migration
step to run by hand.

```bash
# 1. Build and start everything.
docker compose --env-file .env.prod up -d --build

# 2. Watch the bootstrap.
docker compose logs -f backend

# 3. Create a real administrator (the demo seed is off in production).
docker compose exec backend python manage.py createsuperuser

# 4. Verify. Expect {"status":"ok"} with database, redis and
#    object_storage all "ok" — it returns 503 if any check fails.
curl -s http://localhost:8110/api/health/

# 5. Confirm the workers are consuming both queues.
docker compose exec celery-worker celery -A config inspect active_queues
```

Then check, in a browser:

| Check | URL | Expect |
|---|---|---|
| SPA loads | `https://your-domain/` | Home feed renders |
| API docs | `/api/docs/` | Swagger UI |
| Admin | `/admin/` | Jazzmin login |
| Crawler preview | `curl -A facebookexternalhit https://your-domain/` | Server-rendered OG tags with **absolute** `og:url` and `og:image` — relative values mean `SITE_URL` is empty |
| Sitemap | `/sitemap.xml` | Public, ready, long-form videos only — no unlisted ones |
| Buckets | MinIO console | `streamverse-public` (anonymous read) and `streamverse-private` both present |

---

## 9. Performance & Scaling

### Transcoding

```dotenv
# Set to number of physical CPU cores on the worker host
CELERY_WORKER_CONCURRENCY=4

# Encoding preset (veryfast → veryslow = smaller files, more CPU)
FFMPEG_PRESET=fast

# Use hardware encoding if available (requires host driver support)
FFMPEG_VIDEO_ENCODER=h264_nvenc   # NVIDIA
FFMPEG_VIDEO_ENCODER=h264_vaapi   # Intel/AMD
```

### Web workers

```dotenv
UVICORN_WORKERS=4   # 2× CPU cores is a common starting point
```

### Celery workers

Run multiple `celery-worker` containers for parallel transcoding:
```bash
docker compose up -d --scale celery-worker=4
```

### Redis

For high traffic, switch to Redis Cluster or Redis Sentinel by updating `REDIS_URL`, `CHANNEL_REDIS_URL`, `CACHE_REDIS_URL`, and `CELERY_BROKER_URL`.

### Database

Enable connection pooling (PgBouncer) between Django and PostgreSQL for high-concurrency deployments. Django's `CONN_MAX_AGE` setting also helps:
```python
# In settings.py (set via env var):
"CONN_MAX_AGE": 600,
```

---

## 10. Backups

### PostgreSQL

```bash
# Dump
docker exec streamverse-db-1 pg_dump -U streamverse streamverse | gzip > backup.sql.gz

# Restore
gunzip -c backup.sql.gz | docker exec -i streamverse-db-1 psql -U streamverse streamverse
```

### MinIO

Use `mc mirror` (MinIO client) to sync the data bucket to a remote location:
```bash
mc mirror minio/streamverse-public s3/my-s3-backup/public
mc mirror minio/streamverse-private s3/my-s3-backup/private
```

Or use MinIO's built-in **replication** for continuous backup to a secondary bucket.

### What to back up

| Data | Location | Backup method |
|---|---|---|
| Database | `postgres_data` volume | `pg_dump` |
| Video assets | MinIO `streamverse-public` | `mc mirror` |
| Originals | MinIO `streamverse-private` | `mc mirror` |
| `.env` | Host filesystem | Secure secret store |

`redis_data` (channel layer + cache) does not need backup — it is ephemeral state.

---

## 11. Updating

```bash
# 1. Pull new code
git pull

# 2. Rebuild images
docker compose build

# 3. Run migrations (with zero-downtime if migrations are backward-compatible)
docker compose run --rm backend python manage.py migrate

# 4. Restart services
docker compose up -d --force-recreate

# 5. Verify health
curl http://localhost:8110/api/health/
```

For breaking migrations or major version upgrades, perform a maintenance window:
```bash
docker compose stop
docker compose run --rm backend python manage.py migrate
docker compose up -d
```

---

## 12. Pre-Flight Checklist

Run through this before exposing the stack. Each item links to the detail.

**Secrets** — every default here is public knowledge:

- [ ] `DJANGO_SECRET_KEY` generated fresh (64+ random chars)
- [ ] `POSTGRES_PASSWORD` changed
- [ ] `MINIO_ROOT_PASSWORD` changed
- [ ] `LIVE_HOOK_SECRET` set explicitly (otherwise derived from the secret key)
- [ ] `MOCK_PAYMENT_WEBHOOK_SECRET` set explicitly
- [ ] `FLOWER_PASSWORD` changed — Flower can inspect and revoke tasks
- [ ] `.env.prod` still covered by `.gitignore` (`git check-ignore -v .env.prod`)

See [CONFIGURATION.md §21](./CONFIGURATION.md#21-secrets-inventory).

**Origins** — all four must agree with the URL users actually type, including port:

- [ ] `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, `FRONTEND_URL`
- [ ] `SITE_URL` and `SITE_NAME` present and non-empty
- [ ] `MINIO_PUBLIC_ENDPOINT` matches the host the browser fetches HLS from — a
      mismatch fails SigV4 validation on every private playback **and** blocks
      media through the nginx CSP, which is built from this value
- [ ] `LIVE_RTMP_PUBLIC_URL` points at the real ingest host

**Hardening:**

- [ ] `DEBUG=0`
- [ ] `SEED_ON_START=0`
- [ ] `SESSION_COOKIE_SECURE=1`, `CSRF_COOKIE_SECURE=1`, `SECURE_SSL_REDIRECT=1`
- [ ] `SECURE_HSTS_SECONDS` set **only** once TLS is permanent — it is
      effectively irreversible for its duration
- [ ] Only 80/443 (and 1936 if streamers are external) reachable from the
      internet; 5459, 6402, 5574, 9010 and 9011 firewalled
- [ ] `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` set and a real signup verified
      in the worker log — §6
- [ ] If Google sign-in is on: the production redirect URI registered on the
      Google credential byte for byte, and `GOOGLE_OAUTH_CLIENT_SECRET` holding
      the secret (`GOCSPX-…`) rather than a second copy of the client id

**Capacity:**

- [ ] `CELERY_WORKER_CONCURRENCY` = physical cores on the worker host
- [ ] `UVICORN_WORKERS` sized for the web host
- [ ] Disk sized for multi-rendition HLS. A full 1080p ladder encodes five
      renditions totalling ~10.4 Mbps of video (400 + 800 + 1400 + 2800 + 5000
      kbps, per `services/ladder.py`), so budget roughly
      `duration × 10.4 Mbps` per video, **plus** the uploaded original, which is
      retained in the private bucket forever

---

## See also

- [CONFIGURATION.md](./CONFIGURATION.md) — every variable, its default, and whether it is actually forwarded
- [ARCHITECTURE.md](./ARCHITECTURE.md) — service topology, ports and volumes
- [DATABASE_SCHEMA.md](./DATABASE_SCHEMA.md) — retention windows and what the maintenance tasks prune
