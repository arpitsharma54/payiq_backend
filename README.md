# PayIQ Backend

Django-based backend for PayIQ payment processing platform.

## Prerequisites

- Docker and Docker Compose installed
- Git

## Quick Start (Development)

1. Clone the repository and navigate to the backend directory:
   ```bash
   cd payiq_backend
   ```

2. Copy the environment file and configure:
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

3. Start all services:
   ```bash
   docker compose up -d
   ```

4. Access the application:
   - API: http://localhost:8000
   - Via Nginx: http://localhost

## Services Overview

| Service | Description | Port |
|---------|-------------|------|
| `web` | Django application (Gunicorn) | 8000 |
| `nginx` | Reverse proxy with SSL | 80, 443 |
| `db` | PostgreSQL 16 database | 5432 |
| `redis` | Cache and message broker | 6379 |
| `celery-worker` | Background task processor | - |
| `certbot` | SSL certificate management | - |

## Development Setup

### Using Docker Compose Watch (Hot Reload)

```bash
docker compose watch
```

This automatically syncs code changes to the container without rebuilding.

### Running Migrations

```bash
docker compose exec web python manage.py migrate
```

### Creating a Superuser

```bash
docker compose exec web python manage.py createsuperuser
```

### Collecting Static Files

```bash
docker compose exec web python manage.py collectstatic --noinput
```

### Viewing Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f web
docker compose logs -f celery-worker
```

## Production Setup with SSL

### 1. Configure Environment

Update your `.env` file:
```env
DEBUG=0
DOMAIN=yourdomain.com
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
SECRET_KEY=your-secure-secret-key
```

### 2. Obtain SSL Certificate

Run the initialization script to obtain Let's Encrypt certificates:

```bash
# Production
./init-letsencrypt.sh yourdomain.com admin@yourdomain.com

# Staging (for testing - avoids rate limits)
./init-letsencrypt.sh yourdomain.com admin@yourdomain.com 1
```

### 3. Start Services

```bash
docker compose up -d
```

### SSL Certificate Auto-Renewal

The `certbot` container automatically checks for certificate renewal every 12 hours. Certificates are renewed when they have less than 30 days until expiry.

To manually renew:
```bash
docker compose exec certbot certbot renew
docker compose exec nginx nginx -s reload
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Django secret key | (required) |
| `DEBUG` | Debug mode (0 or 1) | `0` |
| `ALLOWED_HOSTS` | Comma-separated allowed hosts | `localhost,127.0.0.1` |
| `DOMAIN` | Domain for SSL certificate | `localhost` |
| `POSTGRES_DB` | Database name | `payiq_db` |
| `POSTGRES_USER` | Database user | `payiq_user` |
| `POSTGRES_PASSWORD` | Database password | `payiq_password` |
| `REDIS_HOST` | Redis hostname | `redis` |
| `FRONTEND_BASE_URL` | Frontend URL for CORS | `http://localhost:5173` |
| `CORS_ALLOWED_ORIGINS` | Allowed CORS origins | `http://localhost:5173` |
| `WEB_PORT` | Django exposed port | `8000` |
| `NGINX_HTTP_PORT` | Nginx HTTP port | `80` |
| `NGINX_HTTPS_PORT` | Nginx HTTPS port | `443` |

See `.env.example` for a complete list.

## Common Commands

```bash
# Start all services
docker compose up -d

# Stop all services
docker compose down

# Rebuild and start
docker compose up -d --build

# View running containers
docker compose ps

# Execute command in container
docker compose exec web python manage.py <command>

# Access Django shell
docker compose exec web python manage.py shell

# Access database shell
docker compose exec db psql -U payiq_user -d payiq_db

# Restart a specific service
docker compose restart web

# View resource usage
docker compose stats
```

## Nginx Configuration

- **Production (SSL)**: `nginx/nginx.conf.template` - Automatically configured with your domain
- **Development (HTTP only)**: `nginx/nginx-http-only.conf` - Use for local development

To use HTTP-only config for development, update the nginx volume in `docker-compose.yml`:
```yaml
volumes:
  - ./nginx/nginx-http-only.conf:/etc/nginx/conf.d/default.conf:ro
```

## Troubleshooting

### Nginx fails to start (SSL certificates missing)

For first-time setup without SSL, use the HTTP-only nginx config or run the `init-letsencrypt.sh` script.

### Database connection refused

Ensure the database is healthy:
```bash
docker compose ps
docker compose logs db
```

### Permission denied errors

Ensure proper file permissions:
```bash
chmod +x init-letsencrypt.sh
chmod +x docker-entrypoint.sh
```

### Celery tasks not processing

Check celery worker logs:
```bash
docker compose logs -f celery-worker
```
