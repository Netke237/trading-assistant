# Bamendjou — Stock & Options Screener

A Next.js + FastAPI screener for discretionary swing trading, with three scan modes: **Options**,
**Stocks**, and **Pre-Breakout**.

- `frontend/` — Next.js 15 App Router UI (TypeScript, CSS Modules, Zustand)
- `backend/` — FastAPI + PostgreSQL backend (scoring, backtesting, broker integrations)
- `docs/` — design references and historical planning documents
- `llm-contexts/` — historical LLM task specs from earlier development phases
- `tests/` — stub only; real test coverage lives in `backend/tests/` and `frontend/__tests__/` /
  `frontend/lib/__tests__/`

For architecture, conventions, and the full component/store/backend map, see
[`CLAUDE.md`](./CLAUDE.md) — the authoritative, actively-maintained reference for this repo.

## Running it

```bash
# Frontend dev server (localhost:3001)
cd frontend && npm run dev

# Full backend + database (FastAPI on :8001, Postgres on :5433)
docker-compose up

# Backend test suite (does not start the service — see docker-compose above for that)
cd backend && pytest
```

See `CLAUDE.md`'s "Dev workflow" section for typecheck/test commands and other day-to-day details.
