# Contributing to StreamVerse

Thank you for contributing! This guide covers setup, conventions, and the workflow for getting changes merged.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Local Development Setup](#2-local-development-setup)
3. [Project Layout](#3-project-layout)
4. [Backend Conventions](#4-backend-conventions)
5. [Frontend Conventions](#5-frontend-conventions)
6. [Running Tests](#6-running-tests)
7. [Database Migrations](#7-database-migrations)
8. [Celery Tasks](#8-celery-tasks)
9. [Environment Variables](#9-environment-variables)
10. [Pull Request Checklist](#10-pull-request-checklist)

---

## 1. Prerequisites

| Tool | Minimum version |
|---|---|
| Docker | 26+ |
| Docker Compose v2 | 2.24+ |
| Node.js (for local frontend dev) | 20 LTS |
| Python (for local backend dev) | 3.12+ |
| ffmpeg (optional, for local transcoding tests) | 6+ |

---

## 2. Local Development Setup

### Full stack (recommended for most work)

```bash
# 1. Clone the repo
git clone <repo-url>
cd streamverse

# 2. Copy and configure the environment
cp .env.example .env
# Edit .env — at minimum set DJANGO_SECRET_KEY.
# Signup sends a real activation email, so also set EMAIL_HOST_USER and
# EMAIL_HOST_PASSWORD, or set
#   EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
# to have the links printed to the backend log instead.

# 3. Start everything
docker compose up --build

# 4. The app is now at http://localhost:8110
#    Django Admin:   http://localhost:8110/admin/   (admin / admin123)
#    Flower:         http://localhost:5574
#    MinIO console:  http://localhost:9011
```

The `SEED_ON_START=1` environment variable (default) automatically:
- Runs migrations
- Creates a superuser (`admin` / `admin123`)
- Seeds categories, sample videos and subscription plans

### Backend only (hot-reload)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Start the dependency services via Docker
docker compose up db redis minio

# Run Django
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

### Frontend only (hot-reload with Vite HMR)

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173 — proxied to the running backend
```

---

## 3. Project Layout

```
streamverse/
├── backend/
│   ├── apps/          Django applications (one directory per domain)
│   ├── config/        Django project settings, ASGI, Celery, routing
│   ├── Dockerfile
│   ├── entrypoint.sh  Dispatches: asgi | worker | beat | flower
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── features/  Page-level components (one directory per route domain)
│   │   ├── components/  Shared UI components
│   │   ├── hooks/     Shared React hooks
│   │   ├── stores/    Zustand stores
│   │   ├── lib/       Axios instance, utility functions
│   │   └── locales/   i18n JSON (fr.json, en.json)
│   ├── Dockerfile
│   └── vite.config.js
├── nginx/
│   └── templates/     nginx config (envsubst-processed at container start)
├── mediamtx/
│   └── mediamtx.yml   MediaMTX configuration
├── docs/              ← You are here
└── docker-compose.yml
```

---

## 4. Backend Conventions

### New Django app

```bash
cd backend
python manage.py startapp <name> apps/<name>
# Add 'apps.<name>' to INSTALLED_APPS in config/settings.py
```

Each app should have:
- `models.py` — data layer only; no business logic
- `serializers.py` — DRF serializers
- `views.py` — thin views; delegate to `services.py` for logic
- `services.py` — pure functions; can be called from views and tasks alike
- `tasks.py` — Celery tasks; call services, not views
- `urls.py` — URL patterns; include from `config/urls.py`
- `admin.py` — register models
- `migrations/` — auto-generated

### Code style

- **Black** for formatting (line length 100)
- **isort** for import order
- **Type hints** on all function signatures
- **Docstrings** on models, service functions and non-trivial methods
- Never put business logic in serializers or views; put it in `services.py`

### Model conventions

- UUID PKs for user-facing resources (use `UUIDPrimaryKeyModel` from `apps.core.models`)
- Always inherit `TimeStampedModel` from `apps.core.models` for `created_at` / `updated_at`
- Monetary amounts: always `PositiveIntegerField`, never `FloatField` or `DecimalField`
- Denormalised counters: use `F()` expressions; never `.save()` on the counter field directly

### API conventions

- REST + JSON only (no GraphQL, no SOAP)
- Use `drf-spectacular` `@extend_schema` decorator on non-obvious views
- Pagination required on all list endpoints (default 20 items)
- Error responses follow DRF defaults: `{"detail": "..."}` or `{"field": ["error"]}`
- 401 = unauthenticated, 403 = authenticated but unauthorised

---

## 5. Frontend Conventions

### Code style

- **ESLint** + **Prettier** (config in `package.json`)
- Functional components + hooks only; no class components
- File naming: `PascalCase.jsx` for components, `camelCase.js` for utilities

### Feature structure

Each feature directory under `src/features/` should be self-contained:

```
features/videos/
├── HomePage.jsx       Route-level page component
├── WatchPage.jsx
├── components/        Sub-components used only by this feature
│   ├── VideoCard.jsx
│   └── PlayerControls.jsx
├── hooks/             Feature-specific hooks
│   └── useVideoPlayer.js
└── api.js             TanStack Query hooks + Axios calls for this feature
```

### i18n

All user-visible strings must use `useTranslation()`:
```js
const { t } = useTranslation()
return <h1>{t('video.watchPage.title')}</h1>
```

Add the key to both `src/locales/fr.json` and `src/locales/en.json`.

Both files must stay at exact key parity — same keys, same nesting, no
locale-only extras. After editing, check it:
```bash
python3 - <<'EOF'
import json
fr = json.load(open('frontend/src/locales/fr.json'))
en = json.load(open('frontend/src/locales/en.json'))
flat = lambda d, p='': {k for key, v in d.items()
                        for k in (flat(v, f'{p}{key}.') if isinstance(v, dict) else {p + key})}
print('only in fr:', flat(fr) - flat(en) or 'none')
print('only in en:', flat(en) - flat(fr) or 'none')
EOF
```

### Copy conventions

French is the default locale and English the secondary; write both when you
add a key.

**French strings are written without accents.** The whole locale file is
accent-free, and mixing the two conventions looks like a bug rather than a
choice. `televerser`, not `téléverser`.

**Name what the viewer experiences, not how it is built.** Implementation
vocabulary belongs in these docs, not in the product. The user does not know
what a rendition, a manifest, a tsvector or ffprobe is, and does not need to.

| Instead of | Write |
| --- | --- |
| Rendus disponibles / Available renditions | Qualites disponibles / Available qualities |
| Diffusion directe depuis le stockage objet | Lecture adaptative |
| Assemblage du manifeste / Building manifest | Assemblage des qualites / Assembling qualities |
| analyse (ffprobe) - transcodage HLS multi-qualite | analyse du fichier, encodage en plusieurs qualites |
| Recherche plein texte PostgreSQL (tsvector + index GIN) | Recherche sur les titres, les tags et les descriptions |

The exception is copy whose audience is an operator rather than a viewer —
`admin.*`, `billing.sandbox*`, `live.streamKeyHint`. Those are read by someone
configuring the system, and being precise there is the point. Keep them
technical.

**Do not advertise what has not shipped, and delete the claim once it has.**
`home.heroSubtitle` promised "et bientot le direct" long after live streaming
went live; `studio.engagementNotice` told users that counters were "alimentes
en phase 3", quoting the build plan back at them. A string that describes a
roadmap will go stale, and nothing in CI will catch it. Describe the current
behaviour instead.

**Keep it short.** These strings sit in hints, tooltips and empty states. If a
sentence needs a subordinate clause to survive, it is explaining too much.

### State management rules

- **Zustand** only for global client state (auth, player, live connection)
- **TanStack Query** for all server data (lists, detail pages, mutations)
- Never store server data in Zustand

---

## 6. Running Tests

### Backend

```bash
cd backend
# With Docker services running:
python manage.py test apps --keepdb

# Or with pytest:
pytest apps/ -x
```

### Frontend

```bash
cd frontend
npm run test      # Vitest unit tests
npm run lint      # ESLint
```

---

## 7. Database Migrations

```bash
# After changing models.py:
python manage.py makemigrations <app_name>

# Apply:
python manage.py migrate

# Check for issues:
python manage.py migrate --check   # exits non-zero if unapplied migrations exist
```

**Rules:**
- Never edit an applied migration. Create a new one.
- Give migrations meaningful names: `python manage.py makemigrations --name add_is_short_to_video`
- If a migration is data-only (no schema change), put it in a `migrations/data_migrations/` directory and document it in the PR.

---

## 8. Celery Tasks

```python
# apps/<name>/tasks.py
from config.celery import app

@app.task(bind=True, max_retries=3, default_retry_delay=60)
def my_task(self, arg):
    try:
        ...
    except SomeTransientError as exc:
        raise self.retry(exc=exc)
```

**Rules:**
- Tasks must be idempotent: re-running the same task with the same args must be safe.
- Never pass ORM objects to tasks; pass PKs.
- Use `@app.task(acks_late=True)` for tasks that touch money or storage.
- Periodic tasks are registered in `config/celery.py` under `app.conf.beat_schedule`.

To run a task locally:
```bash
# Trigger directly (bypasses the queue):
python manage.py shell -c "from apps.videos.tasks import transcode_video; transcode_video.apply(args=[str(video.id)])"

# Or queue it and let a worker pick it up:
celery -A config.celery worker -l info
```

---

## 9. Environment Variables

All configuration is environment-driven. See [`.env.example`](../.env.example) for the full list with descriptions.

Key groups:

| Prefix | Purpose |
|---|---|
| `DJANGO_*` | Core Django settings |
| `POSTGRES_*` | Database connection |
| `REDIS_*` | Redis / channel layer / cache / broker |
| `MINIO_*` | Object storage |
| `LIVE_*` | RTMP / MediaMTX configuration |
| `PAYMENTS_*` | Payment provider selection and secrets |
| `ADS_*` | Advertising feature flags |
| `FFMPEG_*` | Transcode quality settings |

For local development, copy `.env.example` to `.env` and set at minimum:
- `DJANGO_SECRET_KEY` — any random string

---

## 10. Pull Request Checklist

Before opening a PR, confirm:

- [ ] `docker compose up --build` succeeds from a clean state
- [ ] New migrations are included for any model changes
- [ ] Migrations are reversible (test with `python manage.py migrate <app> <prev>`)
- [ ] No raw SQL; use the ORM
- [ ] Monetary amounts use `INTEGER`, not `float`
- [ ] New API endpoints have `@extend_schema` if the auto-generated schema is wrong
- [ ] New user-visible strings have i18n keys in both `fr.json` and `en.json`
- [ ] No secrets or `.env` values hardcoded in source files
- [ ] `SEED_ON_START=0` works (no fixture dependency in production paths)
- [ ] Tests pass: `python manage.py test apps`
- [ ] ESLint passes: `npm run lint` (frontend changes)
