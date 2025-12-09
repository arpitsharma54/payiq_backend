#!/bin/bash
set -e

echo "Fixing static directory permissions..."
mkdir -p /app/static
chown -R appuser:appgroup /app/static

# Wait for PostgreSQL to be ready
wait_for_postgres() {
    echo "Waiting for PostgreSQL..."
    while ! python -c "import psycopg2; psycopg2.connect(
        dbname='${POSTGRES_DB}',
        user='${POSTGRES_USER}',
        password='${POSTGRES_PASSWORD}',
        host='${POSTGRES_HOST}',
        port='${POSTGRES_PORT}'
    )" 2>/dev/null; do
        echo "PostgreSQL is unavailable - sleeping"
        sleep 2
    done
    echo "PostgreSQL is up!"
}

# Wait for Redis to be ready
wait_for_redis() {
    echo "Waiting for Redis..."
    while ! python -c "import redis; redis.Redis(host='${REDIS_HOST:-redis}', port=${REDIS_PORT:-6379}).ping()" 2>/dev/null; do
        echo "Redis is unavailable - sleeping"
        sleep 2
    done
    echo "Redis is up!"
}

case "$1" in
    web)
        wait_for_postgres
        wait_for_redis

        echo "Running migrations..."
        python manage.py migrate --noinput

        echo "Collecting static files..."
        python manage.py collectstatic --noinput

        echo "Starting Daphne server..."
        exec daphne -b 0.0.0.0 -p 8000 payiq.asgi:application
        ;;

    celery-worker)
        wait_for_postgres
        wait_for_redis

        echo "Starting Celery worker..."
        exec celery -A payiq worker --loglevel=info
        ;;

    celery-beat)
        wait_for_postgres
        wait_for_redis

        echo "Starting Celery beat..."
        exec celery -A payiq beat --loglevel=info
        ;;

    migrate)
        wait_for_postgres
        echo "Running migrations..."
        exec python manage.py migrate --noinput
        ;;

    createsuperuser)
        wait_for_postgres
        echo "Creating superuser..."
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
