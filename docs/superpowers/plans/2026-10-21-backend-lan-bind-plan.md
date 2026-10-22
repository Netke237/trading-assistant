# BACKEND-LAN-BIND — plan r1 (2026-10-21)

Status: PLAN r1, unaudited. Claim `BACKEND-LAN-BIND` on
`claude/backend-lan-bind-66ab3139`. Audit per `PROJECT_STATE.json`
`audit_rule` (fresh independent gate-briefed reviewer per round, cap 3 rounds
per stage). Requested by Kenneth in chat on 2026-10-21.

## 1. The incident

On 2026-10-21 every page of the live app (http://localhost:3001) showed
"Backend not running" / "Config health unknown" while the backend was healthy.

- The live frontend is a production build (`next build`) whose
  `frontend/.env.production.local` (gitignored, machine-local) bakes
  `NEXT_PUBLIC_API_URL=http://192.168.55.60:8000`. The browser calls the
  backend by the PC's LAN address, even on the PC itself.
- The backend was restarted at 06:22 through `start-bamendjou-backend.bat` →
  repo `start-backend.bat`, which hard-codes `--host 127.0.0.1`. Nothing
  listened on 192.168.55.60:8000, so every fetch failed.
- Until then it had run on `0.0.0.0` (started by hand on 2026-10-15, and the
  `TradingAssistant-Backend` scheduled task also runs uvicorn on `0.0.0.0`).
- The root `.env` (gitignored) already contains `BAMENDJOU_BACKEND_BIND` and
  `CORS_EXTRA_ORIGINS`: an earlier session wrote the support for them but never
  committed it (git stash `local-lan-and-session-start`, `c857febc`). The keys
  are therefore read by nothing on `main`.

Second, latent defect: `start-backend.bat`'s kill loop only matches
`127.0.0.1:8000`. A backend listening on `0.0.0.0:8000` (scheduled task, or a
hand start) is not stopped, so the new uvicorn either fails to bind or a stale
backend keeps serving old code after an update.

## 2. Change (one ticket, one PR)

Taken from stash `c857febc` (five files only; its `session-start.sh` and
`strategy_params.yaml` hunks are out of scope and stay in the stash), plus two
small additions marked NEW.

### 2.1 `start-backend.bat`
1. `BIND_HOST` defaults to `127.0.0.1`. If the root `.env` exists, the line
   `BAMENDJOU_BACKEND_BIND=<value>` (case-insensitive key, `#` lines skipped)
   overrides it. NEW: `%%~B` strips surrounding quotes.
2. Kill loop matches listeners on `127.0.0.1:8000 `, `0.0.0.0:8000 ` and
   `%BIND_HOST%:8000 ` (trailing space so `:80001` never matches), still
   filtered to `LISTENING`.
3. uvicorn starts with `--host %BIND_HOST%`.
4. Default behaviour with no key in `.env` is byte-for-byte today's
   (`127.0.0.1`). LAN binding stays opt-in because the API has no
   authentication and exposes broker order endpoints.

### 2.2 CORS (`backend/app/config.py`, `backend/app/main.py`)
1. `Settings.CORS_EXTRA_ORIGINS: str = ""`.
2. `cors_origins(settings) -> list[str]`: the three localhost origins, then
   each comma-separated extra origin trimmed, trailing `/` stripped, empties
   skipped, duplicates dropped. `*` raises `ValueError` (with
   `allow_credentials=True` a wildcard would let any web page a user visits
   drive the unauthenticated API, including order endpoints).
3. `create_app` passes `allow_origins=cors_origins(settings)`; nothing else in
   the middleware changes.
4. The value reaches `Settings` because `app/main.py` runs `load_dotenv()`
   (root `.env`, found by walking up from `app/`) before `create_app` calls
   `get_settings()`; `Settings` itself reads `backend/.env`, which does not
   exist.

### 2.3 Docs and hygiene
1. `.env.example`: commented LAN block (both keys, firewall note, warning that
   the API has no auth). NEW: names both `frontend/.env.development.local` and
   `frontend/.env.production.local`, and states that a frontend built with a
   LAN `NEXT_PUBLIC_API_URL` cannot reach a `127.0.0.1` backend (today's
   incident).
2. `.gitignore`: ignore `.env.development.local`, `.env.production.local`,
   `.env.test.local` (machine-local; they hold the LAN IP).
   `frontend/.env.local` stays tracked.

## 3. Tests and evidence

1. `backend/tests/test_cors_origins.py` (from the same earlier session, kept
   untracked until now): default is localhost-only; extras trimmed / slash-
   stripped / de-duplicated; `*` refused; a CORS preflight from the configured
   LAN origin and from `localhost:3001` is allowed and one from an unlisted
   LAN origin is not.
2. Existing backend suites touching app creation and CORS headers stay green
   (`pytest -q` on Python 3.11).
3. `.bat` evidence (no live restart): a scratch harness runs the exact
   `.env`-parsing lines of `start-backend.bat` against fixtures — key absent,
   unquoted `0.0.0.0`, quoted `"0.0.0.0"`, commented `# BAMENDJOU_BACKEND_BIND=…`,
   empty value, lower-case key — and prints `BIND_HOST`; and runs the kill-loop
   `findstr` pipeline over recorded `netstat -ano` lines (listeners on
   127.0.0.1:8000, 0.0.0.0:8000, 0.0.0.0:80001, an ESTABLISHED client to
   127.0.0.1:8000) and prints which PIDs it would kill.

## 4. Out of scope

- Authentication for the API (the real fix for LAN exposure).
- The machine-local launchers in `C:\GitHub\` (`start-bamendjou-backend.bat`,
  guard script) — not in the repo; they call `start-backend.bat` and the guard
  probes 127.0.0.1, which a 0.0.0.0 listener answers.
- The `TradingAssistant-Backend` scheduled task (already binds 0.0.0.0).
- Deploying: after merge Kenneth pulls `main` into `C:\GitHub\trading-assistant`;
  the next shortcut restart then binds per `.env`.

## 5. Gate relevance

No numeric or persistence code changes. Gate exposure is via the broker order
endpoints: a CORS allow-list that admits an unintended origin, or a bind that
exposes the API more widely than configured, could let a third party place a
broker order. The reviewer should treat those as gate-level.

## 6. Ratings

`size:S` (small diff, mostly recovered work, plus evidence and two audits);
`complexity:2` (startup script + CORS config, no state or persistence).
