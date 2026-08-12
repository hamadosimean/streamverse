#!/usr/bin/env bash
# StreamVerse backend entrypoint.
#
# One image, several roles. `$1` selects the role so docker-compose can reuse
# the same build for the ASGI server, the Celery worker, beat and Flower.
set -euo pipefail

ROLE="${1:-asgi}"

wait_for() {
    local host="$1" port="$2" label="$3"
    echo "[entrypoint] waiting for ${label} (${host}:${port})..."
    for _ in $(seq 1 60); do
        if nc -z "${host}" "${port}" 2>/dev/null; then
            echo "[entrypoint] ${label} is up."
            return 0
        fi
        sleep 2
    done
    echo "[entrypoint] ERROR: ${label} never became reachable." >&2
    exit 1
}

wait_for "${POSTGRES_HOST:-db}" "${POSTGRES_PORT:-5432}" "postgres"
wait_for "${REDIS_HOST:-redis}" "${REDIS_PORT:-6379}" "redis"
wait_for "${MINIO_HOST:-minio}" "${MINIO_PORT:-9000}" "minio"

case "${ROLE}" in
    asgi)
        echo "[entrypoint] applying migrations..."
        python manage.py migrate --noinput

        echo "[entrypoint] collecting static files..."
        python manage.py collectstatic --noinput --clear

        echo "[entrypoint] provisioning MinIO buckets + policies..."
        python manage.py init_minio

        if [ "${SEED_ON_START:-1}" = "1" ]; then
            echo "[entrypoint] seeding demo data..."
            python manage.py seed
        fi

        echo "[entrypoint] starting ASGI server (uvicorn) on :8000"
        exec uvicorn config.asgi:application \
            --host 0.0.0.0 --port 8000 \
            --workers "${UVICORN_WORKERS:-2}" \
            --proxy-headers --forwarded-allow-ips='*'
        ;;

    worker)
        # The worker must not race the ASGI container's migrate step.
        python manage.py wait_for_migrations
        echo "[entrypoint] starting celery worker (concurrency=${CELERY_WORKER_CONCURRENCY:-2})"
        exec celery -A config worker \
            --loglevel="${CELERY_LOG_LEVEL:-info}" \
            --concurrency="${CELERY_WORKER_CONCURRENCY:-2}" \
            -Q "${CELERY_QUEUES:-transcode,default}"
        ;;

    beat)
        python manage.py wait_for_migrations
        echo "[entrypoint] starting celery beat"
        exec celery -A config beat \
            --loglevel="${CELERY_LOG_LEVEL:-info}" \
            --scheduler django_celery_beat.schedulers:DatabaseScheduler
        ;;

    flower)
        exec celery -A config flower \
            --address=0.0.0.0 --port=5555 \
            --basic-auth="${FLOWER_USER:-admin}:${FLOWER_PASSWORD:-admin}"
        ;;

    *)
        exec "$@"
        ;;
esac
