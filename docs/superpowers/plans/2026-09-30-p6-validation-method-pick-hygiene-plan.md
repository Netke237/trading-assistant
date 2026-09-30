# P6 — Validation, method-pick & state-tool hygiene (plan)

Phase: `P6-VALIDATION-METHOD-PICK-HYGIENE`. Branch `ccr-55258cbe-hpvjcf`, off main `5b027e2`.
Package: `docs/superpowers/plans/2026-09-25-work-packages.md` § P6 (+ the dispatch.py item added by
decision `P4B-FOLLOWUPS-2026-09-26`, item 7). Every entry below was re-verified OPEN against
`5b027e2` on 2026-09-30 before this plan was written.

Kenneth's decisions this plan implements:

- `BACKLOG-DECISIONS-2026-09-25` Q3 (document the state-probe rename hole, no code change) and Q22
  (stale comments/tests folded into the owning package).
- `P4B-FOLLOWUPS-2026-09-26` item 7 (dispatch.py).
- `P6-SCOPE-2026-09-30` (new, asked this session): G5-1 → `extra='forbid'` on `ArmRequest`;
  G4-1 → a specific refusal message, NOT a plan/estimate cache; G1-6 residual → P6 may add one
  `RequestValidationError` handler to `backend/app/main.py` (not a P6-owned file; authorised).

Split into FOUR units, one layer each, each audited on its own (audit_rule: batch size). Order:
A → B → C → D; each is independently shippable.

---

## Unit A — backend request validation (schemas, portfolio PATCH, ArmRequest, main.py)

### A1. Non-finite prices are refused (G1-6)

Evidence: `PortfolioPositionCreate.entryPrice` / `pickedRowStockPrice` / `pickedRowOptionPrice`
(`schemas/__init__.py:954,1029-1030`) are `gt=0` only. Measured 2026-09-30: posting
`"entry_price": Infinity` validates (inf > 0), and the handler's response then fails to encode,
so the client sees a 500. On the real `POST /api/portfolio` the row is COMMITTED before the
response is built — a stored `entry_price = inf` is CORRUPT PERSISTED DATA behind a 500.
`ArmRequest.picked_row_stock_price` / `picked_row_option_price` (`routers/auto_trade.py:164-165`)
have the same hole, and `auto_trade_booking.py:210-214` maps them 1:1 into
`PortfolioPositionCreate` at fire time.

Change: add `allow_inf_nan=False` to those five `Field(...)`s, and to
`PortfolioPositionUpdate.resolvedTpPrice` (A4 touches that field; `_floor_stop(inf)` returns inf,
so TP_HIT never fires — the same defect on the PATCH path).

NOT in scope, logged against main: other float fields without the flag (stop, structuralStop,
premiumStopDollar, portfolioValue, ...). The package names the picked prices and entryPrice.

### A2. The 422 for a non-finite input stops turning into a 500 (G1-6 residual; main.py authorised)

Evidence: measured 2026-09-30 — `"entry_price": NaN` is refused by pydantic, then FastAPI's default
handler JSON-encodes `exc.errors()`, whose `input` is the NaN; Starlette's `JSONResponse` uses
`allow_nan=False` → `ValueError` → 500. After A1 the same happens for Infinity.

Change: one `@app.exception_handler(RequestValidationError)` in `backend/app/main.py` that returns
EXACTLY the default shape — `JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})`
— where `errors` is `exc.errors()` with every non-finite float, at any depth (`input`, `ctx`),
replaced by its string form (`"nan"`, `"inf"`, `"-inf"`). Nothing else changes: same status, same
`detail` list, same `loc`/`msg`/`type` (frontend `apiError` in `lib/api.ts` reads `loc` and `msg`).

Test: NaN and Infinity bodies to `POST /api/portfolio` → 422 whose detail names `entry_price`; a
normal 422 (missing field) is byte-identical before and after (compare against
`fastapi.exception_handlers.request_validation_exception_handler`'s output for the same request).

### A3. `pickedAt` is a real timestamp (G1-9)

Evidence: `pickedAt: Optional[str]` (`schemas/__init__.py:1032`) and `picked_at: Optional[str]`
(`auto_trade.py:167`) accept any string of any length; stored in a plain String column.

Change: one shared annotated type in `schemas/__init__.py`, used by BOTH fields:
`Optional[PickedAt]` where `PickedAt` = str, `max_length=64`, and an `AfterValidator` that requires
`datetime.fromisoformat(v)` to succeed AND be timezone-aware (the only producer is the frontend's
`new Date().toISOString()`, e.g. `2026-09-30T12:00:00.000Z`, which Python 3.11 parses as UTC). The
string is stored AS SENT (no normalisation) — the column and every reader are unchanged. None stays
a real state ("nobody picked").

WHY BOTH FIELDS, AND IN THE SAME CHANGE: a fired auto-trade books through
`PortfolioPositionCreate` AFTER the broker order is placed. If only the create schema tightened, an
arm accepted with a bad `picked_at` would fire, place the order, then fail booking — an order with
no tracked position, the exact P1 failure. Mirroring the constraint on `ArmRequest` makes that
refusal happen at ARM, before anything is placed. The same argument applies to A1's two
`picked_row_*` fields and is why A1 changes `ArmRequest` too.

Residual, stated: an `ArmedStrategy` armed BEFORE deploy with a bad value would fail booking at
fire. Armed state is in-process memory (not persisted), so a deploy restart clears it.

### A4. The PATCH path can no longer write half of the method/price pair (G1-5)

Evidence: `routers/portfolio.py:270-279` — `activeTpMethod` and `resolvedTpPrice` are independent
ifs; a method alone leaves the price stale/NULL, which spec §2.7 names gate-level (the drawer shows
one basis while TP_HIT fires on the ladder). `activeTpMethod: null` is silently ignored.

Change, applied BEFORE any field is written (a malformed pair is a malformed request, not a partly
valid edit, so this is an early 422 — unlike `qty`, whose late raise exists to save OTHER valid
fields in the same debounced patch; the pair has no such companion case because the product's
writer, `tpMethodPatch`, always sends both):

- If exactly one of `activeTpMethod` / `resolvedTpPrice` is in `updates` → 422
  `"activeTpMethod and resolvedTpPrice must be sent together."`
- If both are present: `activeTpMethod` null → 422; a non-`ladder` method whose floored price is
  None → 422 (the §2.7 forbidden state). `ladder` with any price is accepted and stores the floored
  value (the product sends `null`, which is unchanged).

Client impact, checked: `tpMethodPatch` (`EditDrawer.tsx:1467-1469`) always emits both;
`portfolioStore.toUpdatePayload` copies each key through independently, and patches coalesce per
recId, so both keys still travel together. No other frontend writer of either key exists.

EXISTING TESTS THIS CHANGES (plan round 1, finding 1). `backend/tests/test_portfolio_update.py:83-110`
has three tests that PATCH `resolvedTpPrice` ALONE and expect 200; under A4 each becomes a 422.
They are rewritten, not deleted, so the round-8 floor stays pinned where it still applies:
- `…negative…` / `…zero…` → send `{"activeTpMethod": "ladder", "resolvedTpPrice": -50 | 0}` → 200,
  `resolvedTpPrice` null (the floor, on the ladder path where a null price is legal).
- `…when_positive` → `{"activeTpMethod": "monte_carlo", "resolvedTpPrice": 210.5}` → 200, 210.5.
- NEW: `{"activeTpMethod": "monte_carlo", "resolvedTpPrice": -50}` → 422 (a non-ladder method whose
  floored price is None — the §2.7 refusal; this REPLACES round 8's "store null" outcome for
  non-ladder methods, deliberately).
- NEW: `{"resolvedTpPrice": 210.5}` alone and `{"activeTpMethod": "monte_carlo"}` alone → 422, and
  the position is unchanged (nothing written before the refusal).
- NEW: `{"activeTpMethod": null, "resolvedTpPrice": 210.5}` → 422.
No other backend test PATCHes either key (round 1 grepped every `client.patch(`).

### A5. `ArmRequest` forbids unknown keys (G5-1; decided `P6-SCOPE-2026-09-30`)

Change: `model_config = ConfigDict(extra='forbid')` on `ArmRequest`. Verified 2026-09-30: every key
`AutoTradeArm/index.tsx:310-360` sends is a declared field (the `regimeGate` spread carries
`regime_headwind_*_pct`; `armPickedFieldsFrom`/`armBookingFieldsFrom` emit declared snake_case
keys). Update the two comments in `auto_trade.py` and `lib/api.ts` that describe the silent
`extra='ignore'` drop — the `lib/api.ts` comment is outside the owned list; it is a comment-truth
fix only, stated here so the auditor can reject it if unwanted.

Test: a body with `pickedMethod` (camelCase) → 422 naming the key; the product's own full arm body
(built from the existing arm tests' fixture) → 200.

### A6. `_rr_ratio_for_row` reports ambiguity (G1-8)

Change (`services/picked_method.py:149-165`): collect every row within `_PRICE_TOL`; choose the
CLOSEST; if two or more rows tie on distance with DIFFERENT ratios → return None (the documented
"unmappable → ladder" degrade). Identical ratios at a tie are not ambiguous. Below the gate by the
entry's own rating; included because the package lists it.

### A7. Stale comment (O4 step 1)

`picked_method.py:183-190`: the guard around the config load lives in
`services/position_writer.py`, not `routers/portfolio.py`. Pointer fix only.

---

## Unit B — backend notifications + a vacuous test

### B1. dispatch.py (P4B-FOLLOWUPS item 7)

Evidence: `notify_enabled_channels` does `cfg.get('gmail', {})` then `gmail.get('enabled')` — a
YAML `gmail:` with no body (None) raises `AttributeError` out of the function, so Telegram is never
tried. `load_notification_config` logs a corrupt/unreadable settings.yaml at DEBUG and returns `{}`,
and a top-level `notifications: null` returns None.

Change:
- `load_notification_config()` keeps its signature and `{}`-on-failure contract (chart_alerts.py
  calls it three times; not owned) but: logs read/parse failure at ERROR; returns `{}` when the
  `notifications` value is not a dict.
- A new `_read_notification_config() -> tuple[dict, bool]` (the bool: the file was readable) is
  what `load_notification_config` wraps. "Unreadable" = the file exists but opening/parsing raised,
  or its top level is not a mapping. A MISSING file is readable-and-empty (no channels configured —
  the documented fresh-install state), not unreadable.
- `notify_enabled_channels`: a non-dict channel block counts as disabled; each channel is still
  tried independently.

### B2. The watch evaluator treats an unreadable settings file as channels-enabled

`strategy_watch_evaluator._any_channel_enabled` calls the new `_read_notification_config()`; if
not readable → True (and logs at ERROR), so the watch gates its state on delivery, which
`notify_enabled_channels` then reports as failed → the transition retries next run
(WATCH-UNDELIVERED-EVENT-RESEND's path) instead of committing silently. Its docstring's "a corrupt
settings.yaml reads as no channel and transitions commit" is corrected.

### B3. test_alternatives.py asserts something (B3 finding)

Evidence: flat 30-bar fixture → pre-screen REJECT → `data["candidates"]` empty → every `for c in`
loop iterates nothing; the module reports green while checking nothing.

Change: use real OHLCV from `tests/fixtures/` that survives the pre-screen (with
`overrides={'min_stock_score': 40}` if needed, per the entry), and put
`assert data["candidates"], ...` before every loop. The test's assertions about alternatives are
otherwise unchanged; if one of them now FAILS against real candidates, that is a real finding and is
reported, not weakened. Mutation check: breaking `alternativesCount` in scan.py must fail the file.

BUILD DEVIATION (recorded at build, 2026-09-30): the entry's suggested remedy does not work.
Measured: real `tests/fixtures/AAPL_candles.json` scores 42 and is REJECTed at the stock score gate
with `min_stock_score` 40 or 0 alike, because that gate is on the card's STATUS, not the threshold.
Built instead with the module's own established pattern (`_process_symbol` driver below it, and
`test_scan_endpoint.py`'s `_force_passing_stock_score` / `_no_db_leak`): `score_stock` patched to a
PASS card with a measured trend rule, the DB pre-fetch patched out, and the chains given
`open_interest` and a RELATIVE expiry (the hardcoded 2026-06-20 had also gone stale). The
non-empty assertion before every loop is as planned. Mutant (`alternativesCount = 0` in scan.py)
now fails 2 tests, up from 1.

---

## Unit C — frontend (cardEdits, scanStore, StockPositionCard, MethodPickSelector)

### C1. `normalizeCardEdits` value-checks `picks` (G2-4-RESIDUAL)

`maxLossOverride` is no longer persisted (`persistableCardEdits` keeps only stamp + picks), so only
`picks` reaches rehydrate. New `isValidMethodPick(v)`: `method` in the four `PickedMethod`s;
`rowStockPrice`/`rowOptionPrice` each a finite number > 0 or null; `stopBasis` `'stock'|'premium'`;
`pickedAt` a non-empty string. An invalid entry is DROPPED (absent = not picked, which the send gate
refuses — the safe failure). `maxLossOverride` stays shape-only; its doc says why (not persisted).

### C2. Header documents the second key format (G2-7)

`cardEdits.ts` KEYING note: add the `SYMBOL|<display label>` fallback that `editKeyFor`
(`step-7-trade-card/page.tsx`) produces, and that `clearPicksForSymbol` is safe with it because it
reads only up to the first `|`. Doc only; the step-7 page is not owned and is not changed.

### C3. `clearPicksForSymbol` compares case-insensitively (G2-8)

Uppercase both the key prefix and `symbol` before comparing (`contractId()` uppercases keys).

### C4. `hasOwnProperty` instead of `in` (G2-10)

`writeCardEdit` (`:217`) and `clearCardPick` (`:371`): `Object.prototype.hasOwnProperty.call`.

### C5. scanStore storage survives QuotaExceededError (G2-12)

`createJSONStorage(() => ...)` returns a wrapper around `localStorage` whose `setItem` catches and
`console.warn`s (getItem/removeItem pass through). The prior blob survives (unchanged behaviour);
what changes is that `set()` no longer throws out of a React event handler. `lib/stockScan.ts`'s
own guard stays (not owned; harmless).

### C6. Name collision (step 3 below-gate)

`scanStore.ts` imports `clearCardPick` and defines a store action of the same name. Rename the
IMPORT (`clearCardPick as clearCardPickIn`); the store action's public name is unchanged, so no
caller outside the owned files moves.

### C7. Stale `pickSettled` comments

`StockPositionCard/index.tsx:488` and `MethodPickSelector/index.tsx:26` name a guard that no longer
exists; point them at TradeCard's current state-only comparison.

### C8. A lost Monte Carlo / Arithmetic pick says so (G4-1; decided: message, not cache)

Evidence: `StockPositionCard` holds `plan`/`estimate` in `useState(null)`; `step-4-stocks/page.tsx`
renders `{open && <StockPositionCard/>}`, so collapse+reopen remounts the card, the
`pickedMethodGone` effect clears the stored pick, and the user sees only the generic
`MISSING_METHOD_PICK_MESSAGE`.

Change (inside StockPositionCard only; the clear logic itself is NOT touched, so the note at
`:476-495` — "re-read this before adding a cache" — stays true):
- local `const [clearedPickMethod, setClearedPickMethod] = useState<PickedMethod | null>(null)`;
  the existing clear effect records `methodPick.method` just before calling
  `applyMethodPickRef.current(null)`. The clear fires in the REMOUNTED instance (store still holds
  the pick, `estimate` is null), so the record lives in the instance the user is looking at.
- while `pickMissing && clearedPickMethod`, the refusal line reads
  `Your ${label} pick was cleared because its ${estimate|plan} is no longer on screen — run
  ${Estimate|Arithmetic plan} again and re-pick before submitting.` instead of the generic message.
  Button `title` stays `MISSING_METHOD_PICK_TITLE`.
- any new pick (methodPick non-null) resets `clearedPickMethod` to null.

Test: pick Monte Carlo after an estimate, unmount, remount with the same store → the specific text
renders and Limit/Market stay disabled; a card never picked → generic text.

### C9. Test name (CONCENTRATION-FLAG)

`StockPositionCard.concentration.test.tsx:190`: rename so it no longer claims the flag "never
fires at a 100% cap" (it can, for notional > account). Assertion unchanged.

---

## Unit D — state tooling (scripts/state.py, STATE_TRACKING.md)

### D1. A failed `git log` warns instead of reading "No drift"

`_round_numbers_in_branch_subjects` returns a module sentinel `_GIT_FAILED` when the subprocess
raises or exits non-zero (the "no rounds found" None is unchanged). `audit_bookkeeping_drift` maps
it to `("warn", "Audit bookkeeping COULD NOT RUN: git log failed ...")`, the same tier and wording
family as the base-ref-unresolved branch. Test in `test_state_audit_bookkeeping.py`.

### D2. A string `audit_rounds` does not crash the SessionStart hook

`declared = target.get("audit_rounds") or 0` → coerce: an int (not bool) is used; a numeric string
is `int()`ed; anything else → return `("warn", "audit_rounds on <label> is not an integer (<repr>)
— bookkeeping not checked")`. Test with `"3"` and `"three"`.

### D3. STATE_TRACKING.md documents the audit-bookkeeping probe (+ Q3)

New section: what it reads (commit SUBJECTS, `round N`, since the target's entry was introduced),
base ref resolution (`origin/main` / `main`, merged history excluded), the warn/drift tiers and the
hard cap (round 3 unclean → drift), how it clears (go clean / merge), and — Kenneth's Q3 — the
accepted hole: renaming an `already_shipped` entry, moving an entry between `phases` and
`already_shipped`, or dropping and restoring it resets the scoping boundary to that commit.

---

## Verification (package rule 7)

Per unit: backend `cd backend && .venv/bin/python -m pytest -q`; frontend
`cd frontend && npx tsc --noEmit && npx jest`; `python3 scripts/state.py` exit 0. Each new test is
mutation-checked (revert the fix → the test fails). Tests never write `backend/config/*.yaml` or run
the real app lifespan (B1/B2 point `_SETTINGS_PATH` at a tmp file).

## PROJECT_STATE.json on completion

One phase entry (`P6-VALIDATION-METHOD-PICK-HYGIENE`, defect marker: dispatch.py's
`gmail = cfg.get('gmail', {})`). Each finished backlog entry moves to `closed_questions` with
evidence (commit + test name). Merge waits on Kenneth.
