# COMPOSITE-WATCH-STRATEGY-KEY-CRASH — plan

Date: 2026-09-25. Picked by Kenneth as the next task (`open_questions[0]`, logged by
the A4f build). Backend only, one layer, well under 500 lines.

## Problem

`StrategyWatchStore.add_composite_watch` (`backend/app/services/strategy_watch_store.py`)
creates rows with `watch_type: "composite"` and **no `strategy_key`**. Two code paths
subscript `w["strategy_key"]` on every row, composite ones included:

1. `strategy_watch_evaluator.evaluate_all`, strategy loop (`key = w["strategy_key"]`,
   ~:99) — runs for every enabled row before any `watch_type` check. One enabled
   composite watch raises `KeyError` mid-loop. Strategy rows listed **before** it have
   already been evaluated and their new state saved (`update_state`, e.g. idle →
   armed), but the `events` list is discarded with the exception, so those
   notifications are lost for good while the watch sits armed. Rows after it and the
   whole composite loop are never reached. The failing run is retried on every tick in
   both modes: eod never sets `_last_eod_run_date` (`strategy_watch_scheduler.py:65-67`),
   poll never sets `_last_run_at` (`:78-79`). The manual `POST /api/strategy-watch/evaluate` (`run_now` →
   `evaluate_and_notify` → `evaluate_all`, no guard) returns 500. Consequence for A4f:
   migrated HMM_intraday composite watches are not live either.
2. `StrategyWatchStore.add_watch` duplicate check (`w["symbol"] == symbol and
   w["strategy_key"] == strategy_key`, ~:147) — raises `KeyError` whenever the new
   strategy watch's symbol already has a composite watch. The router catches only
   `ValueError`, so `POST /api/strategy-watch/` returns 500. `add_watches_bulk`
   catches only `ValueError` too, so `POST /api/strategy-watch/bulk` returns 500
   **after** having saved every symbol before the offending one (partial add).

Reproduced on main (scratch script, real store in a temp dir): all three raise
`KeyError: 'strategy_key'`. The existing tests hide it because every composite
fixture is a hand-built dict carrying `strategy_key: "composite"`, which no real
composite row has.

A sweep (`grep -rn '\[.strategy_key.\]' backend/app backend/scripts`) finds only these
two subscripts. Every other backend `strategy_key` use is a request body field or a
`WatchEvent` field.

## Change

### C1. Evaluator strategy loop skips composite rows (`strategy_watch_evaluator.py`)

Directly after the `enabled` check in the strategy loop:

```python
if w.get("watch_type") == "composite":
    continue  # evaluated by the composite loop below; has no strategy_key
```

This mirrors the composite loop's own filter (`!= "composite"` there → `continue`), so
the two loops partition the rows by `watch_type`. `key = w["strategy_key"]` stays a
subscript: a strategy row without a key is corrupt data, not a case to hide.

### C2. `add_watch` duplicate check ignores composite rows (`strategy_watch_store.py`)

```python
if (w.get("watch_type") != "composite" and w["symbol"] == symbol
        and w["strategy_key"] == strategy_key
        and w.get("direction", "Bullish") == direction):
```

`load()` already backfills `watch_type` to `"strategy"` on legacy rows, and
`add_watch` rows have no `watch_type` key at all (they are strategy rows by default,
the same reading the evaluator's composite loop uses), so `.get(...) != "composite"`
is true for every strategy row. `add_watches_bulk` needs no change: it calls
`add_watch`.

### Not changed (by decision)

- **No `strategy_key` added to composite rows** (neither in `add_composite_watch` nor
  as a `load()` backfill). That would also stop the crash, but only through the
  evaluator's implicit `_SIGNAL_FNS.get("composite") is None` skip, and it writes a
  fake key into persisted data. Filtering on `watch_type` states the intent.
- **No per-watch `try/except` around the whole strategy-loop body.** That the
  scheduler loses the whole tick on any one watch's exception is a wider robustness
  question; the only known trigger is this bug. Logged, not widened.
- **Frontend.** `GET /api/strategy-watch/` returns composite rows too, so the
  Strategy Watch page lists them as if they were strategy rows (empty Strategy cell at
  `strategy-watch/page.tsx:158`, `w.strategy_key` undefined). They can be toggled and
  removed from there. Nothing crashes. Observation, not in scope.

## Tests (real `StrategyWatchStore` in `tmp_path`, never hand-built composite dicts)

- **T1** `test_strategy_watch_evaluator.py`: a real store holding, **in this order**,
  an enabled composite watch (AAPL, `add_composite_watch`) then an enabled strategy
  watch (MSFT `pullback_ema`, `add_watch`). Patch the evaluator's
  `strategy_watch_store` with it, `get_bars` → bars, `_SIGNAL_FNS["pullback_ema"]` →
  a signal, and `composite_trigger_evaluator.evaluate_scheduled` → `False`.
  `evaluate_all()` does not raise and returns exactly one `entry` event, for MSFT.
  The composite-first order matters: on main the crash lands before MSFT is reached.
- **T1b** same file: the order reversed (strategy MSFT first, composite AAPL second).
  `evaluate_all()` returns the MSFT `entry` event. On main that event is lost after its
  armed state was already saved.
- **T2** `test_strategy_watch_evaluator.py`: same store, `evaluate_scheduled` → `True`
  and `describe_match` patched (both at `app.services.composite_trigger_evaluator.*`,
  since the evaluator imports them inside the function; `describe_match` returns a
  realistic detail dict so the real `format_composite_reason` runs, no fallback)
  → the composite event is emitted as well (the strategy-loop skip does not starve
  the composite loop) — two events, MSFT `pullback_ema` entry and AAPL `composite`.
- **T3** `test_strategy_watch_store.py`: `add_composite_watch("AAPL", …)` then
  `add_watch("AAPL", "pullback_ema")` succeeds; a second identical `add_watch` still
  raises `ValueError("… already watched")` (the dedup is not disabled).
- **T3b** `test_strategy_watch_store.py`: strategy rows only — a second identical
  `add_watch` raises `ValueError` (pins the dedup itself, independent of composite
  rows).
- **T4** `test_strategy_watch_store.py`: composite AAPL, then
  `add_watches_bulk(["AAPL", "MSFT"], "breakout_base")` returns 2 rows.
- **T5** `test_strategy_watch_router.py`: seed the composite watch **directly on the
  reloaded store** (`import app.services.strategy_watch_store as sws;
  sws.strategy_watch_store.add_composite_watch(...)` after the fixture ran) — never
  through `POST /api/composite-watches/`, whose router the fixture does not reload, so
  on main that write lands in the stale store and the test passes vacuously. Assert
  the store holds the composite row, then `POST /api/strategy-watch/` for the same
  symbol → 201, not 500, and the store holds 2 rows.
- **T6** `test_strategy_watch_router.py`: same seeding, plus
  `app.services.strategy_watch_evaluator.strategy_watch_store` patched to the
  reloaded store (the evaluator also holds the pre-reload object), `get_bars` and
  `evaluate_scheduled` patched **→ `False`** with an **OMM** `trigger_def` (no intraday
  fetch), and `notify_enabled_channels` patched in the evaluator so nothing can be sent;
  `POST /api/strategy-watch/evaluate` → 200.

## Review log

- Round 1 (plan): NOT CLEAN — 1 major (T5 would pass vacuously on main if seeded via
  the composite router), 3 minor (tick-consequence described wrongly; `/evaluate`
  500 missed; M4 kill reason wrong), 2 nits (patch `describe_match`; frontend
  observation understated). All six taken into this amendment.
- Round 2 (plan): **CLEAN**. The reviewer prototyped all 8 tests (7 red on main with
  `KeyError`; T3b green on main by design; all green with C1+C2) and ran M1–M5: each
  one is killed. Five nits taken: T6 pins `evaluate_scheduled → False` + OMM + a
  notify patch; T2's `describe_match` returns a real dict; the fixture drops its fake
  `strategy_key`; the retry claim covers poll mode as well; the config check is in
  Verification.
- Code round 1 (3f0c680): **CLEAN**. Pre-fix, 7 new tests go red with `KeyError`, and
  the fixture fix turns 2 existing composite tests red too. M1–M5 are killed, as are
  the reviewer's own non-equivalent mutations. T6 makes no network call (checked with
  sockets blocked). The suite gives 3274 passed, 1 skipped. Three nits:
  - The malformed-strategy-row `KeyError` is left unpinned on purpose, because pinning
    it would lock in the whole-run abort.
  - The state record was missing; it is now added.
  - M5 is not killed by T1b, which is expected.
- Side effect seen after round 1: the reviewer's probe seeded through
  `POST /api/composite-watches/`, whose un-reloaded store still points at the real
  `backend/config/strategy_watches.yaml`, and wrote a row there (reverted). This is
  more evidence for the round-1 major finding. Implementation check: after the backend
  suite runs, `git status --short backend/config` must be empty.

- **Fixture fix:** `_composite_watch()` in `test_strategy_watch_evaluator.py` drops its
  `"strategy_key": "composite"`, which no real row has and which hid this bug. The
  existing composite tests then run on the real row shape.

## Mutation plan (each must turn a test red)

| # | Mutation | Expected killer |
|---|---|---|
| M1 | delete C1's composite skip | T1, T1b, T2, T6 |
| M2 | C1 skip on `== "strategy"` instead | T1 |
| M3 | delete C2's `watch_type` clause | T3, T4, T5 |
| M4 | C2 clause `== "composite"` (inverted) | T3 (composite row raises `KeyError` again), T3b (duplicate accepted) |
| M5 | C1 `break` instead of `continue` | T1 (MSFT after AAPL never evaluated) |

## Verification

- `cd backend && .venv/bin/python -m pytest tests/test_strategy_watch_*.py tests/test_composite_watch_router.py`
  then the full backend suite; the scratch repro prints no `KeyError`.
- `git status --short backend/config` is empty after the suite runs.
- `python3 scripts/state.py` exits 0 after the state record is added.

## State record

`PROJECT_STATE.json`: new phase entry `COMPOSITE-WATCH-STRATEGY-KEY-CRASH` (probe:
the composite skip line in the evaluator), `open_questions[0]` moved to
`closed_questions.items`, `active_phase_note` updated. Log the two "not changed"
items above as open observations.
