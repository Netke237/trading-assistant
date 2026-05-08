# LLM Context — Test Infrastructure Setup (Workstream 19)

> **Self-contained.** Read this document fully before touching any code.
> Do not read any other file unless something is genuinely ambiguous after reading this document.
> Project root: `F:\Git\GitHub\Trading assistant`.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream creates new test files only. It does not modify any existing source file in `frontend/` or `backend/`. It modifies `frontend/package.json` (add jest deps) and `backend/requirements.txt` (add pytest deps).

**Goal:**
Set up the baseline test suites for both layers so future workstreams can land with tests:
- **Backend:** pytest with FastAPI TestClient, covering all 9 existing REST routes and the candle RNG determinism.
- **Frontend:** Jest + React Testing Library, covering the `statusForScore` utility and the `exportToXlsx` helper.

**What NOT to touch:**
- Any existing source file in `backend/app/` (routers, fixtures, schemas, models, main.py)
- Any existing source file in `frontend/` (pages, components, stores, lib files other than what's being tested)
- Alembic migration files

---

## Section 2 — Owned files

### Backend (create only)

| File path | Create / Modify | Purpose |
|---|---|---|
| `backend/tests/__init__.py` | **Create** | Empty package init |
| `backend/tests/conftest.py` | **Create** | FastAPI TestClient fixture |
| `backend/tests/test_routes.py` | **Create** | 200 + shape tests for all 9 routes |
| `backend/tests/test_candles.py` | **Create** | Mulberry32 RNG determinism test |
| `backend/requirements.txt` | **Modify** | Add `pytest==8.1.1`, `httpx==0.27.0` |

### Frontend (create only)

| File path | Create / Modify | Purpose |
|---|---|---|
| `frontend/jest.config.ts` | **Create** | Jest configuration |
| `frontend/__tests__/status.test.ts` | **Create** | `statusForScore` unit tests |
| `frontend/__tests__/export.test.ts` | **Create** | `exportToXlsx` smoke test |
| `frontend/package.json` | **Modify** | Add jest + testing-library deps |

---

## Section 3 — Read-only references

| File | Reason |
|---|---|
| `backend/app/main.py` | App factory — import for TestClient |
| `backend/app/fixtures/candles.py` | Mulberry32 RNG implementation — copy seed params for determinism test |
| `frontend/lib/status.ts` | `statusForScore` function — import in test |
| `frontend/lib/export.ts` | `exportToXlsx` function — import in smoke test (WS-15 must be done first; skip this test file if export.ts does not exist yet) |

---

## Section 4 — Backend implementation

### 4.1 `backend/tests/__init__.py`

```python
# empty
```

### 4.2 `backend/tests/conftest.py`

```python
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
def client():
    """Synchronous TestClient for simple route tests."""
    from fastapi.testclient import TestClient
    return TestClient(app)
```

### 4.3 `backend/tests/test_routes.py`

```python
"""Baseline route tests — all 9 trading endpoints must return HTTP 200 with correct shape."""

import pytest


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_watchlist_length_and_shape(client):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 10
    first = data[0]
    assert first["symbol"] == "AAPL"
    assert first["score"] == 82
    assert first["status"] == "PASS"
    assert "breakdown" in first


def test_watchlist_last_row(client):
    r = client.get("/api/watchlist")
    last = r.json()[-1]
    assert last["symbol"] == "INTC"
    assert last["status"] == "REJECT"


def test_regime_shape(client):
    r = client.get("/api/regime")
    assert r.status_code == 200
    data = r.json()
    assert data["overall"] == "PASS"
    assert len(data["metrics"]) == 8


def test_sectors_length(client):
    r = client.get("/api/sectors")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 11
    assert data[0]["key"] == "XLK"


def test_contracts_length_and_id(client):
    r = client.get("/api/contracts")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 6
    assert data[0]["id"] == "AAPL|190|2026-05-15|C"


def test_portfolio_length(client):
    r = client.get("/api/portfolio")
    assert r.status_code == 200
    assert len(r.json()) == 5


def test_alerts_length(client):
    r = client.get("/api/alerts")
    assert r.status_code == 200
    assert len(r.json()) == 5


def test_events_length(client):
    r = client.get("/api/events")
    assert r.status_code == 200
    assert len(r.json()) == 36


def test_tradecards_length(client):
    r = client.get("/api/tradecards")
    assert r.status_code == 200
    assert len(r.json()) == 10


def test_candles_aapl(client):
    r = client.get("/api/candles/AAPL")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 120
    first = data[0]
    assert set(first.keys()) == {"time", "open", "high", "low", "close", "volume"}


def test_candles_unknown_symbol(client):
    r = client.get("/api/candles/XXXXINVALID")
    assert r.status_code == 200
    assert len(r.json()) == 120
```

### 4.4 `backend/tests/test_candles.py`

```python
"""Mulberry32 RNG determinism test — same seed must produce identical output."""

from app.fixtures.candles import make_candles


def test_candles_are_deterministic():
    a = make_candles(seed=11, base=172, bars=5, drift=0.0008)
    b = make_candles(seed=11, base=172, bars=5, drift=0.0008)
    assert a == b, "Same seed must produce identical candle bars"


def test_candles_different_seeds_differ():
    a = make_candles(seed=11, base=172, bars=5, drift=0.0008)
    b = make_candles(seed=22, base=820, bars=5, drift=0.0015)
    assert a != b


def test_candle_bar_shape():
    bars = make_candles(seed=11, base=172, bars=3, drift=0.0008)
    assert len(bars) == 3
    for bar in bars:
        assert set(bar.keys()) == {"time", "open", "high", "low", "close", "volume"}
        assert bar["high"] >= bar["open"]
        assert bar["high"] >= bar["close"]
        assert bar["low"] <= bar["open"]
        assert bar["low"] <= bar["close"]
```

### 4.5 `backend/requirements.txt` additions

Add after the existing entries:
```
pytest==8.1.1
httpx==0.27.0
```

`httpx` is required by FastAPI's `TestClient` in recent versions.

---

## Section 5 — Frontend implementation

### 5.1 Install jest dependencies

```bash
cd frontend
npm install --save-dev \
  jest@29.7.0 \
  ts-jest@29.1.2 \
  @types/jest@29.5.12 \
  @testing-library/react@16.0.0 \
  @testing-library/jest-dom@6.4.2 \
  jest-environment-jsdom@29.7.0
```

### 5.2 `frontend/jest.config.ts`

```typescript
import type { Config } from 'jest';

const config: Config = {
  preset: 'ts-jest',
  testEnvironment: 'jsdom',
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/$1',
  },
  setupFilesAfterFramework: ['@testing-library/jest-dom'],
  testPathPattern: ['__tests__'],
  transform: {
    '^.+\\.tsx?$': ['ts-jest', { tsconfig: { jsx: 'react-jsx' } }],
  },
};

export default config;
```

### 5.3 `frontend/__tests__/status.test.ts`

```typescript
import { statusForScore } from '@/lib/status';

describe('statusForScore', () => {
  it('returns PASS for score >= 75', () => {
    expect(statusForScore(75)).toBe('PASS');
    expect(statusForScore(100)).toBe('PASS');
    expect(statusForScore(82)).toBe('PASS');
  });

  it('returns CAUTION for score 50–74', () => {
    expect(statusForScore(50)).toBe('CAUTION');
    expect(statusForScore(74)).toBe('CAUTION');
    expect(statusForScore(61)).toBe('CAUTION');
  });

  it('returns REJECT for score < 50', () => {
    expect(statusForScore(0)).toBe('REJECT');
    expect(statusForScore(49)).toBe('REJECT');
    expect(statusForScore(42)).toBe('REJECT');
  });
});
```

> **Note:** If `statusForScore` uses different thresholds than 75/50, read `frontend/lib/status.ts` first and adjust the test values to match the actual implementation. The test must reflect the real logic, not invented thresholds.

### 5.4 `frontend/__tests__/export.test.ts`

> **Prerequisite:** This test requires `frontend/lib/export.ts` (created by WS-15). If that file does not exist yet, create a stub test that just passes:
> ```typescript
> it.todo('exportToXlsx smoke test — requires WS-15 to be merged first');
> ```

If WS-15 is already merged:

```typescript
// Mock the xlsx module — we're testing that exportToXlsx calls it, not the xlsx internals
jest.mock('xlsx', () => ({
  utils: {
    aoa_to_sheet: jest.fn(() => ({})),
    book_new:     jest.fn(() => ({})),
    book_append_sheet: jest.fn(),
  },
  writeFile: jest.fn(),
}));

import { exportToXlsx } from '@/lib/export';
import type { WatchlistRow } from '@/types/domain';
import * as XLSX from 'xlsx';

const MOCK_ROWS: WatchlistRow[] = [
  {
    symbol: 'AAPL', company: 'Apple Inc', price: 185.2,
    direction: 'Bullish', horizon: 'Swing',
    score: 82, rankDelta: 2, scoreDelta: 3, status: 'PASS',
    breakdown: { trend: 88, pullback: 78, trigger: 85, event: 72, volatility: 74 },
    nextEventDays: 8, nextEventLabel: 'Earnings',
  },
];

describe('exportToXlsx', () => {
  it('calls XLSX.writeFile without throwing', () => {
    expect(() => exportToXlsx(MOCK_ROWS, 'test.xlsx')).not.toThrow();
    expect(XLSX.writeFile).toHaveBeenCalledWith(expect.anything(), 'test.xlsx');
  });

  it('passes headers as first row', () => {
    exportToXlsx(MOCK_ROWS, 'test.xlsx');
    const aoaCall = (XLSX.utils.aoa_to_sheet as jest.Mock).mock.calls[0][0];
    expect(aoaCall[0][0]).toBe('Rank');
    expect(aoaCall[0][1]).toBe('Symbol');
  });
});
```

---

## Section 6 — Task spec

### Acceptance criteria

**Backend:**
1. `cd backend && python -m pytest tests/ -q` passes with all tests green (12+ tests).
2. `test_candles_are_deterministic` passes — same seed produces identical output.
3. All 9 route tests return HTTP 200 with the expected shape.

**Frontend:**
1. `cd frontend && npx jest --passWithNoTests` exits 0.
2. `statusForScore` tests pass (3 tests).
3. `exportToXlsx` smoke test passes (or is marked `todo` if WS-15 is not yet merged).

### Verify

```bash
# Backend
cd backend
pip install pytest==8.1.1 httpx==0.27.0
python -m pytest tests/ -v
# Expected: all PASSED

# Frontend
cd ../frontend
npm install
npx jest
# Expected: passed (or 1 todo)
```

---

## Section 7 — Hard rules

1. Do NOT modify any existing source file in `backend/app/` or `frontend/app/`, `frontend/lib/`, `frontend/components/`.
2. Tests must import from the actual source — no duplication of implementation code.
3. If `statusForScore` thresholds differ from 75/50 in the actual implementation, adjust the test values to match — do not change the source.
4. Do NOT add `pytest-asyncio` or `anyio` — all backend tests are synchronous using `TestClient`.
5. `npm run typecheck` must remain clean after frontend test file additions.

---

## Section 8 — Dev workflow

```bash
# Backend
cd backend
pip install pytest==8.1.1 httpx==0.27.0
python -m pytest tests/ -v

# Frontend
cd frontend
npm install
npx jest
npm run typecheck
```

---

## Section 9 — Copy/paste prompt

```
Use the superpowers:using-git-worktrees skill to create your worktree first,
branching from feature/1-api-integration, branch name feature/ws-19-test-infra.

Read `llm-contexts/19-test-infrastructure.md` fully before writing any code.
It is your single source of truth.

You are setting up the baseline test suites for the Bamendjou options screener
(FastAPI backend with pytest, Next.js frontend with Jest).

Your owned files:
  Backend:
  - backend/tests/__init__.py               (CREATE — empty)
  - backend/tests/conftest.py               (CREATE)
  - backend/tests/test_routes.py            (CREATE)
  - backend/tests/test_candles.py           (CREATE)
  - backend/requirements.txt               (MODIFY — add pytest + httpx)

  Frontend:
  - frontend/jest.config.ts                 (CREATE)
  - frontend/__tests__/status.test.ts       (CREATE)
  - frontend/__tests__/export.test.ts       (CREATE — stub if export.ts absent)
  - frontend/package.json                   (MODIFY — add jest deps)

Do not modify any existing source file.

Before writing status.test.ts, read frontend/lib/status.ts to verify
the actual thresholds — adjust test values to match the real implementation.

Run verification in Section 6 after implementation.
Commit after all checks pass.
```
