#!/bin/sh
set -e

# ---- Playwright bootstrap (ONLY for celery-worker) ----
if [ "$1" = "celery-worker" ]; then
  if [ ! -d "/root/.cache/ms-playwright/chromium" ]; then
    echo "Installing Playwright Chromium (first run)..."
    playwright install chromium
  fi
fi

echo "Fixing static directory permissions..."
mkdir -p /app/static
chown -R appuser:appgroup /app/static || true

wait_for_postgres() {
  echo "Waiting for PostgreSQL..."
  while ! python - <<EOF 2>/dev/null
import psycopg2
psycopg2.connect(
  dbname="${POSTGRES_DB}",
  user="${POSTGRES_USER}",
  password="${POSTGRES_PASSWORD}",
  host="${POSTGRES_HOST}",
  port="${POSTGRES_PORT}"
)
EOF
  do
    echo "PostgreSQL is unavailable - sleeping"
    sleep 2
  done
  echo "PostgreSQL is up!"
}

wait_for_redis() {
  echo "Waiting for Redis..."
  while ! python - <<EOF 2>/dev/null
import redis
redis.Redis(
  host="${REDIS_HOST:-redis}",
  port=int("${REDIS_PORT:-6379}")
).ping()
EOF
  do
    echo "Redis is unavailable - sleeping"
    sleep 2
  done
  echo "Redis is up!"
}

case "$1" in
  web)
    wait_for_postgres
    wait_for_redis
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput
    exec uvicorn payiq.asgi:application --host 0.0.0.0 --port 8000
    ;;

  celery-worker)
    wait_for_postgres
    wait_for_redis
    exec celery -A payiq worker --loglevel=info
    ;;

  celery-beat)
    wait_for_postgres
    wait_for_redis
    exec celery -A payiq beat --loglevel=info
    ;;

  migrate)
    wait_for_postgres
    exec python manage.py migrate --noinput
    ;;

  createsuperuser)
    wait_for_postgres
    exec python manage.py createsuperuser
    ;;

  shell)
    wait_for_postgres
    exec python manage.py shell
    ;;

  *)
    exec "$@"
    ;;
esac
