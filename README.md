# payiq_backend

## Database Setup

This project uses PostgreSQL running in Docker.

### Prerequisites
- Docker and Docker Compose installed on your system

### Starting PostgreSQL

1. Start the PostgreSQL container:
   ```bash
   docker-compose up -d
   ```

2. The database will be available at `localhost:5432` with the following default credentials:
   - Database: `payiq_db`
   - User: `payiq_user`
   - Password: `payiq_password`

3. To customize these settings, create a `.env` file in the project root (see `.env.example` for reference).

### Stopping PostgreSQL

```bash
docker-compose down
```

### Viewing PostgreSQL Logs

```bash
docker-compose logs -f postgres
```

### Running Migrations

After starting the PostgreSQL container, run Django migrations:

```bash
python manage.py migrate
```