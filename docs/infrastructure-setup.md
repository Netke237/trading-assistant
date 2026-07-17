# Bamendjou (Trading Assistant) - Infrastructure Setup

Complete self-hosted Docker Compose infrastructure for the Bamendjou project.

## Prerequisites

- Docker Engine 20.10+
- Docker Compose 2.20+
- Git

## Quick Start

### 1. Configure Environment

Copy the example environment file and update values:

```bash
cp .env.example .env
```

Edit `.env` and set secure passwords:
- `POSTGRES_PASSWORD`: Strong database password
- `JWT_SECRET_KEY`: Random 32+ character string

### 2. Start the Environment

```bash
docker compose up -d
```

This starts:
- PostgreSQL 15 (host port 5433 → container 5432, database `TradingAssistantDB`)
- FastAPI backend (host port 8001 → container 8000)

Note: non-default host ports (5433, 8001) are intentional — they avoid colliding with
containers from other, unrelated projects on this machine. This only affects the
Dockerized backend; local dev via `python -m uvicorn` (see backend/.env) still uses
port 8000 directly and is unaffected.

### 3. Verify Services

```bash
# Check container status
docker compose ps

# View logs
docker compose logs -f

# Test API
curl http://localhost:8001/
```

## Running Migrations

### Automatic Migrations (Alembic)

```bash
# Run migrations inside backend container
docker compose exec backend alembic upgrade head

# Create new migration
docker compose exec backend alembic revision --autogenerate -m "description"
```

### Manual SQL Migrations

Init scripts in `backend/migrations/init-scripts/` run automatically on first database startup:

1. `01-extensions.sql` - Enable PostgreSQL extensions
2. `02-app-user.sql` - Create application user
3. `03-permissions.sql` - Grant proper permissions

## Viewing Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f db
docker compose logs -f backend

# Last 100 lines
docker compose logs --tail=100 backend
```

## Resetting the Database

**Warning: This destroys all data!**

```bash
# Stop services
docker compose down

# Remove named volume
docker volume rm tradingassistant_postgres_data

# Restart (init scripts will re-run)
docker compose up -d
```

## Security Considerations

- **Never commit `.env` file** - contains secrets
- Change all default passwords in production
- Use strong `JWT_SECRET_KEY` (32+ random characters)
- A dedicated non-superuser role (`bamendjou_app`) exists with least-privilege grants
  on `TradingAssistantDB` — but the backend currently connects as `bamendjou`
  (the `POSTGRES_USER`, which Postgres always makes a superuser). Switching
  `DATABASE_URL` to run as `bamendjou_app` instead is a deliberate follow-up, not
  yet done — don't assume the app is running least-privilege today.
- Backend runs as non-root user inside container
- PostgreSQL only accessible via Docker network (not exposed externally in production)

## Troubleshooting

### Database Connection Failed

```bash
# Check if PostgreSQL is healthy
docker compose ps

# Check PostgreSQL logs
docker compose logs db

# Verify environment variables
docker compose exec backend env | grep DATABASE
```

### Port Already in Use

```bash
# Find process using port 8001 or 5433
sudo lsof -i :8001
sudo lsof -i :5433

# Use different ports in .env if needed
```

## Maintenance

### Backup Database

```bash
# Create backup
docker compose exec db pg_dump -U bamendjou TradingAssistantDB > backup.sql

# Restore backup
docker compose exec -T db psql -U bamendjou TradingAssistantDB < backup.sql
```

### Update Images

```bash
# Pull latest images
docker compose pull

# Rebuild backend
docker compose build --no-cache backend

# Restart
docker compose up -d
```
