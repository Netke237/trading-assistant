# Wave 0 Implementation Plan - Agent Distribution

## Project
Ritter Nroetschen - Scaffold Phase (Wave 0)

## Objective
Create production-grade scaffold for FastAPI backend, PostgreSQL database, and Android apps (Child + Parent) with Docker Compose infrastructure.

## Agent Assignments

### Phase 1 (Parallel Execution)

#### 1. System Architect (Winston) - bmad-create-architecture
**Scope:** Backend structure, Docker architecture, database schema design
**Deliverables:**
- FastAPI app structure (main.py, config.py)
- SQLAlchemy model definitions (admin, child, quest, time_log, override_log)
- Alembic migration strategy
- Docker Compose architecture (PostgreSQL + backend)
- Environment variable schema (.env.example)

#### 2. DevOps/Infrastructure Agent
**Scope:** Docker Compose, environment setup, branch management
**Deliverables:**
- docker-compose.yml (PostgreSQL 15 + backend service)
- .env.example (JWT secrets, DB connection - no hardcoded values)
- Updated .gitignore (exclude .env)
- Branch `feature/0-scaffold` created from main
- PostgreSQL init scripts (uuid-ossp, pgcrypto, dedicated app user)
- Persistent volume configuration

### Phase 2 (Parallel Execution)

#### 3. Backend Developer
**Scope:** Implement scaffold code per architect's design
**Deliverables:**
- Working `/health` endpoint (200ms response, no DB dependency)
- All model files with proper SQLAlchemy definitions
- Alembic migration files
- requirements.txt with pinned versions
- Dockerfile

#### 4. Android Developer
**Scope:** Kotlin + Jetpack Compose skeleton for both apps
**Deliverables:**
- Child App: Compiles and launches to blank screen (API 26+)
- Parent App: Compiles and launches to blank screen (API 26+)
- Shared module (`:shared`) for common DTOs, network interfaces, JWT handling patterns, common UI components/theme

### Phase 3 (Sequential Execution)

#### 5. QA Verification Agent - bmad-check-implementation-readiness
**Scope:** Validate against acceptance criteria
**Tests:**
- `/health` responds in <100ms
- Docker Compose builds and starts successfully
- Backend container connects to PostgreSQL
- Both Android apps compile without errors
- No Wave 1+ features present
- No business logic in Android apps

#### 6. Devil's Advocate - bmad-review-adversarial-general
**Scope:** Spec drift detection
**Checks:**
- Confirm only scaffold exists (no auth, no quests, no state machines)
- Verify DGR compliance (no hardcoded secrets, positive framing prep)
- Confirm branch naming convention followed

### Phase 4

#### 7. Team Lead (Kimi Code)
**Scope:** Final review and merge
**Actions:**
- Review all deliverables
- Approve PR merge to main
- Update wave-status.md

## Technical Decisions

1. **Shared Android Library**: Yes - `:shared` module for API DTOs, network interfaces, JWT patterns, common UI components
2. **PostgreSQL Init**: Yes - uuid-ossp, pgcrypto, dedicated app user, persistent volumes
3. **Agent Dispatch Strategy**: Phase-based (not all at once) to prevent rework

## Constraints (MUST NOT Violate)
- No Wave 1+ features (auth, profiles, quest management, etc.)
- No business logic in Android apps - blank screens only
- No hardcoded secrets or connection strings
- No cloud-hosted database
- Must use Alembic migrations
- No state machine implementation yet
- Push to `feature/0-scaffold` branch only

## Acceptance Criteria
- [ ] `/health` endpoint returns `{status: "ok"}` in <100ms
- [ ] Docker Compose builds and starts without errors
- [ ] Backend connects to PostgreSQL
- [ ] Both Android apps compile and show blank screens
- [ ] All DGR rules followed
- [ ] No spec drift (Wave 0 scope only)

## Created
Date: 2026-04-23
Status: In Progress
