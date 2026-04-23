# Ritter Nroetschen - Infrastructure Setup

Complete self-hosted Docker Compose infrastructure for the Ritter Nroetschen project.

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
- PostgreSQL 15 (port 5432)
- FastAPI backend (port 8000)

### 3. Verify Services

```bash
# Check container status
docker compose ps

# View logs
docker compose logs -f

# Test API
curl http://localhost:8000/
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
docker volume rm ritter_postgres_data

# Restart (init scripts will re-run)
docker compose up -d
```

## Security Considerations

- **Never commit `.env` file** - contains secrets
- Change all default passwords in production
- Use strong `JWT_SECRET_KEY` (32+ random characters)
- Database runs as dedicated non-superuser (`ritter_app`)
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
# Find process using port 8000 or 5432
sudo lsof -i :8000
sudo lsof -i :5432

# Use different ports in .env if needed
```

## Maintenance

### Backup Database

```bash
# Create backup
docker compose exec db pg_dump -U ritter_admin ritter_nroetschen > backup.sql

# Restore backup
docker compose exec -T db psql -U ritter_admin ritter_nroetschen < backup.sql
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
