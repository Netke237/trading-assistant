# EXACT-STRIKE — plan r2 (2026-10-09)

Status: PLAN r2. Plan stage CLOSED CLEAN at round 2 (round 1: 1 gate finding, R1-1, fixed in r2; round 2: zero). Nothing here is built; the code stage (cap 3 rounds) starts after the build. Claim: `EXACT-STRIKE` on
`claude/intelligent-merkle-ba9f03`. Audit per `PROJECT_STATE.json` `audit_rule`
(fresh independent gate-briefed adversarial reviewer per round, cap 3 rounds per
stage).

## 1. The defect (pre-existing, found by the NO-LIVE-QUOTE NLQ-1 code audit)

Both option-chain builders in `backend/app/data/market.py`
(`fetch_option_chain`, the dead sync twin, and `fetch_option_chain_async`)
write the strike as an integer:

```python
strike = float(c.get("strike") or 0)
"id": f"{symbol}|{int(strike)}|{target_exp}|{option_type}",
"strike": int(strike),
```

`fetch_contract_quote_async` matches with `int(float(strike_str))`. A
fractional strike (AAPL monthlies list 2.5-wide strikes such as 182.5; names
under $25 list 0.5/2.5 strikes) is therefore truncated everywhere. Measured
consequences, each a wrong number or a wrong order:

| # | Path | What goes wrong |
|---|---|---|
| D1 | Chain dedup (`seen` set on `c["id"]`, end of both builders) | 22 and 22.5 share id `XYZ\|22\|…`; the second row in Tradier order is **dropped**, so one of the two contracts silently vanishes from the scan, Step 6 and the Watchlist. |
| D2 | yfinance IV backfill (`yf_iv.get(float(c["strike"]))`) | A 22.5 row looks up the 22.0 key: wrong IV, or none. |
| D3 | `routers/scan.py` `strike = float(contract.get("strike", price))` → Black–Scholes / Heston pricing, breakeven, targets, `ContractDetails.strike=int(strike)` | All computed with 22 instead of 22.5: wrong breakeven/targets/R:R on the trade card. |
| D4 | `routers/scan.py` `contract=f"{symbol}\|{int(strike)}\|…"` → broker send (`option_symbol.pipe_to_occ`) | A card built from a 22.5 row sends OCC `…C00022000`: **the broker order is for the 22 contract**. |
| D5 | `fetch_contract_quote_async` | Any stored id is matched by truncation; consumers `routers/portfolio.py` `get_portfolio` (marks + equity snapshot), `services/position_writer.py`, `routers/alerts.py`, `services/portfolio_alert_monitor.py`, `services/auto_trade_booking.py`, `routers/contracts.py` `GET /api/quote/option`. A stored `XYZ\|22.5\|…` (only reachable by hand today) gets the 22 row's price. |
| D6 | `routers/contracts.py` `_parse_strikes` (`strikes=` integers only) and `GET /api/quote/option` (`strike: int`) | A fractional strike is a 422; the Watchlist cannot grade a fractional star. |
| D7 | `frontend/lib/contractGrading.ts` `truncStrike` and `frontend/lib/step6CardContract.ts` `missingCardContracts` (`Math.trunc`) | Both mirror the backend truncation on purpose. Once the backend sends 22.5 rows, a `XYZ\|22.5\|…` star would request `strikes=22` and be graded with the 22 row's score/price unless this changes **in the same release** as the backend. |

`services/daily_risk_hooks.py` `opening_price` already avoids these helpers
(quotes the exact OSI symbol) for this reason; it is not changed.
`data/option_symbol.py` `pipe_to_occ` is already exact
(`round(float(strike_str) * 1000)`) and is not changed.

## 2. Target representation

One module, `backend/app/data/strike.py`, owns the representation:

```python
STRIKE_DP = 3  # OCC resolution: strike * 1000 is an integer

def canonical_strike(raw) -> int | float:
    """Finite positive strike rounded to 3 dp; an integral value is returned as
    int (185.0 -> 185) so JSON and f-strings stay byte-identical to today for
    integer strikes. Raises ValueError for non-finite, <= 0 or bool input."""

def format_strike(raw) -> str:
    """The strike text inside a contract id: str(canonical_strike(raw)).
    185 / 185.0 / '185' / '185.0' -> '185';  22.5 / '22.50' -> '22.5'."""

def parse_strike_text(text: str) -> int | float:
    """Strike text from an id or query param -> canonical_strike. Accepts
    ^\\d{1,5}(\\.\\d{1,3})?$ only (no sign, exponent, underscore, whitespace)."""
```

Invariants (each pinned by a test):

- **I1 Byte identity for integer strikes.** For every integer strike every id
  string and every JSON response is byte-identical to today: `"strike":185`,
  never `185.0`; id `AAPL|185|2025-05-16|C`. Persisted ids, stars, alerts,
  positions and armed auto-trade symbols keep matching with no migration.
- **I2 Python/JS parity.** `format_strike(x)` equals JS `` `${x}` `` for every
  wire value `x` the backend emits. Both use shortest round-trip decimal for
  values in (0, 100000) at 3 dp, so `frontend/types/domain.ts` `contractId`
  needs no change. A shared golden file
  `backend/tests/fixtures/strike_format_golden.json`
  (`[{"wire": 22.5, "text": "22.5"}, {"wire": 185, "text": "185"}, 7.125,
  0.5, 1, 99999.999, …]`) is asserted by a pytest and by a Jest test that reads
  the same file with `fs` (no copy of the table).
- **I3 Exact matching.** Quote lookup and strike filtering compare
  `canonical_strike` values; 22.5 never matches 22, `187.0` matches 187.
- **I4 Wire type.** A shared Pydantic type
  `Strike = Annotated[Union[int, float], AfterValidator(canonical_strike)]`
  (smart-mode union keeps an int an int) replaces `strike: int` on
  `OptionContract`, `ContractDetails` and `AlternativeContract`. Old persisted
  `scan_sessions.last_result_json` (integer strikes) still validates.

Chain rows whose strike is missing, non-finite or <= 0 are **dropped** (today
they become strike 0, id `X|0|…`; Tradier has never been observed sending one,
and `format_strike` must never emit `nan`).

## 3. Tickets (one phase, one PR; built after NO-LIVE-QUOTE merges)

All four land in one PR because D7 must ship with the backend (section 1).
Estimated size: ES-1 ~150 lines + tests, ES-2 ~120 + tests, ES-3 ~40 + tests,
ES-4 ~200 (script) + tests.

### ES-1 Backend data layer (`backend/app/data/`)

1. Add `strike.py` (section 2) + `tests/test_strike.py` (golden file, rejects
   `-5`, `+5`, `1_000`, `1e3`, `nan`, `inf`, `0`, `True`, 6+ integer digits, 4+
   decimals).
2. Both chain builders: `strike = canonical_strike(c.get("strike"))` inside a
   `try/except (TypeError, ValueError): continue`; `"id"` uses
   `format_strike(strike)`; `"strike": strike`. Fixes D1, D2 (yfinance key
   `float(c["strike"])` is now the exact value; `_yf_iv_for_chain` keys stay
   `float(row["strike"])`, so 22.5 == 22.5).
3. `fetch_contract_quote_async`: `target_strike = parse_strike_text(strike_str)`
   (a malformed strike returns None, as any parse failure does today); match
   `c["strike"] == target_strike and c["expiry"] == expiry` (the expiry clause
   comes from NO-LIVE-QUOTE). Rewrite NLQ's docstring paragraph "STRIKE after
   integer truncation … Callers must not use this helper to authorize money on
   a fractional strike" to state exact matching. `daily_risk_hooks` keeps its
   OSI quote (it needs `ask`, which the chain row does not carry).
4. Tests (`tests/test_exact_strike_chain.py`): a mocked Tradier chain with
   strikes 22, 22.5, 23 → three rows, ids `X|22|…`, `X|22.5|…`, `X|23|…`,
   `strike` values `22`, `22.5`, `23` (types int, float, int); quote for
   `X|22.5|…` returns the 22.5 row's price, for `X|22|…` the 22 row's; a chain
   with only 22.5 returns None for `X|22|…`; `X|22.0|…` returns the 22 row.
   yfinance backfill test: a 22.5 row with no Tradier IV gets the 22.5 key.

### ES-2 Backend wire + routers

1. `schemas/__init__.py`: `Strike` type on the three models (I4).
2. `routers/contracts.py`: `_parse_strikes` → `set[int | float]` via
   `parse_strike_text` (422 message "strikes must be comma-separated
   strikes, e.g. 187 or 187.5"); `OptionContract(strike=…)` passes the row's
   value (no `int()`); `GET /api/quote/option` `strike: str = Query(...)` parsed
   with `parse_strike_text` (422 on bad text) and the id built with
   `format_strike`.
3. `scoring/contract_validator.py` `_contract_id`: `format_strike` (today it
   would emit `22.5` already but `185.0` if a float ever reached it).
4. `routers/scan.py`: the id at the card (`int(strike)` → `format_strike`),
   `ContractDetails(strike=…)`, alternative `strike=int(alt_strike)` and
   `int(float(_alt_sp.legs[0].strike))` → `canonical_strike`. The
   `contract.get("strike", price)` fallback is unreachable (every chain row now
   carries a valid strike or is dropped); replace it with `contract["strike"]`
   so a stock price can never become a strike.
5. Tests: integer-strike golden responses are byte-identical (I1) for
   `/api/contracts`, `/api/quote/option`, a scan card; a 22.5 chain produces a
   card whose `contract` is `X|22.5|…`, `contractDetails.strike == 22.5`,
   breakeven computed from 22.5, and `pipe_to_occ(card.contract)` ends
   `C00022500`; `strikes=22.5` returns only the 22.5 row; `strikes=22.5x` is
   422; old `last_result_json` with integer strikes reloads.

### ES-3 Frontend (`frontend/lib/contractGrading.ts`, `frontend/lib/step6CardContract.ts`)

1. Remove `truncStrike`; group strikes and match rows on the exact parsed
   `strike` (`Number(c.strike) === p.strike`). `STRIKE_RE` stays
   (`^\d+(\.\d+)?$`); `187.0` parses to 187 and matches the 187 row (I3).
2. `frontend/lib/step6CardContract.ts` (plan r2, audit R1-1):
   `missingCardContracts` sends `strike: cd.strike` exactly (no `Math.trunc`),
   so Step 6's rescue of a card contract cut by `max_price`/`limit` asks for
   `strikes=[182.5]`, not 182 (which, against the exact backend, returns the
   182 row or nothing, and `withCardContract`'s id gate then drops the card's
   own contract from Step 6). Correct the field comment ("Truncated as the
   backend truncates") and the `withCardContract` NOTE (ids carry
   `int(strike)`) to the exact mechanism.
3. Update `lib/__tests__/contractGrading.test.ts` ("keeps a fractional strike
   for the label and truncates it for matching" becomes exact matching) and
   `lib/__tests__/step3ParamReach.test.tsx` ("truncates a fractional strike as
   the backend does" now expects 182.5; add: a 182.5 card yields a request with
   `strike: 182.5`, and `withCardContract` appends a fetched row with id
   `XOM|182.5|…` but not one with id `XOM|182|…`). Add the I2 golden-file Jest
   test against `contractId`. After the change, no `Math.trunc` / `Math.floor`
   / `Math.round` is applied to a strike anywhere in `frontend/` outside tests
   (grep-checked at build end).
4. `EditDrawer.tsx` `optionStrikeFromContract` comment (says the id "rounds
   down any fractional strike"): correct the mechanism statement for new ids;
   legacy truncated ids still exist, so the fallback ordering it describes is
   kept.
5. `npm run typecheck` clean; Jest for touched files.

### ES-4 Persisted-id migration check (read-only)

`backend/scripts/check_contract_strikes.py` — **never writes**. Reads
`DATABASE_URL` (same resolution as the app). Scans every persisted contract
string:

| Table.column | Holds |
|---|---|
| `portfolio_positions.contract` (+ trade-card snapshot JSON `strike`) | open positions |
| `closed_positions.contract` | closed history |
| `watched_contracts.contract_id` | stars |
| `scan_sessions.last_result_json` (`contract`, `contractDetails.strike`, alternatives) | last scan |

Reports, per row:

- **NONCANONICAL** — strike text `!= format_strike(text)` (e.g. `187.0`,
  `0187`). After ES-1 these still quote correctly (I3), but a string compare
  against a new id (stars vs. Step 6 rows) would miss; listed for Kenneth.
- **UNPARSEABLE** — not `SYMBOL|STRIKE|YYYY-MM-DD|C/P` or `SYMBOL|STOCK`.
- **AMBIGUOUS (only with `--chain`, live Tradier, unexpired only)** — an
  integer-strike id `X|k|E|R` where the chain for E lists a fractional strike
  in `(k, k+1)`. Every chain-built id until now was truncated, so this row
  *may* have been meant as the fractional contract. Rows that reached a broker
  were ordered as `pipe_to_occ` of the truncated id, i.e. they **are** the k
  contract and are correct; the risk is only manual/booked-without-broker
  entries. The script cannot tell which; it lists them.
- Summary counts; exit 0 (report only).

Frontend `localStorage` (`bamendjou-auto-trade`, `bamendjou-alerts-v2`,
legacy `bamendjou-portfolio-v1`, `bamendjou-watched-contracts-v1`) cannot be
read by a backend script. Every producer of those ids was a truncating one, so
they are integer-form and stay byte-identical (I1); the only exposure is the
same AMBIGUOUS case, covered for stars and positions by the DB copy. Not
scanned; stated in the report footer.

**No automatic rewrite.** Changing a persisted id changes which contract is
marked, alerted or ordered; any correction is Kenneth's call per row (Q-1).

Where it runs: against the database the live app uses (Q-2). Tests use an
aiosqlite DB seeded with each category.

## 4. Coordination with NO-LIVE-QUOTE

NO-LIVE-QUOTE (claim reassigned 2026-10-09 to `codex/no-live-quote-resumed`,
not yet pushed; last pushed work is `claude/priceless-jennings-995ab7` @
`b6f2259e`, NLQ-1 clean, NLQ-2..4 open) edits the same builder loops,
`_quote_keys`, `fetch_contract_quote_async` (expiry clause + docstring),
`routers/portfolio.py`, `scoring/contract_validator.py` and
`schemas/__init__.py`. This plan was read against `b6f2259e`.

- Plan audit runs now. **ES-1/ES-2 code is not started until NO-LIVE-QUOTE is
  merged to main** (whichever branch carries it); then this branch rebases onto
  main and builds on NLQ's versions (dropped no-ask rows, `quoteState` keys,
  expiry clause kept). If NLQ's merged code differs from `b6f2259e` in these
  files, the affected ES steps are re-checked before building.
- ES-3 and ES-4 touch no NLQ file (NLQ edits `EditDrawer.tsx`; ES-3.3 is a
  comment edit there and is done after the rebase).
- AUTOTRADE-FIRE-HYGIENE (`claude/hopeful-rubin-64bowt`, #133-#137) H1 adds a
  scan-fire executor in `routers/scan.py`: a different region from ES-2.4's
  strike lines, textual merge only. Its H2 (booking) touches
  `auto_trade_booking.py`, which this plan does not change (that file already
  parses the strike with `float()`).
- The claim is renewed while waiting; if it lapses it is re-taken at build
  start.

## 5. Gate briefing for the auditor

Blocking only: a WRONG NUMBER shown to the user or sent on a broker order, or
CORRUPT PERSISTED DATA. In this plan that means: any path where a fractional
strike still truncates; any path where an integer strike's id/JSON changes
bytes (breaks persisted matches); any path where the plan's matching would pair
a contract with another contract's quote/score; any write to persisted data.
Wording, test hygiene, style and illustrative examples are not findings.

## 6. Open questions for Kenneth

- **Q-1** AMBIGUOUS rows: report only and you correct by hand (recommended), or
  should the plan add an explicit, per-row confirmed rewrite command?
- **Q-2** Which database does the live app use — the mini PC's
  `tradingassistant-db` container? ES-4 runs there, read-only, after you
  confirm.

## 7. Verification at build end

`pytest` (Python 3.11 venv) for the touched modules + the full backend suite;
`npm run typecheck`; Jest for touched files; `python3 scripts/state.py` no
drift; then the code audit stage (round 1 = whole integrated diff).

## 8. Audit log (plan stage)

- **Round 1** (fresh independent subagent, bmad-review-adversarial-general,
  gate-briefed; scope: whole plan r1 @ 646c6510 against code + NLQ b6f2259e):
  **1 gate finding.** R1-1 — `frontend/lib/step6CardContract.ts:41`
  `Math.trunc(cd.strike)` would drop a fractional card contract from Step 6's
  rescue once the backend is exact; the plan omitted the file while telling the
  implementer to edit its test. Fixed in r2 (ES-3.2/3.3, D7).
- Round 1 below-gate, logged NOT fixed (per `audit_rule`), for the build to
  consider: (a) ES-4 `DATABASE_URL` falls back to `sqlite+aiosqlite:///./dev.db`
  and `.env` is cwd-relative (`backend/app/config.py`), so a wrong cwd reports a
  false "clean" on an empty new file; (b) `parse_strike_text` is narrower than
  frontend `STRIKE_RE`, so an odd star like `X|22.5001|…` 422s its whole
  Watchlist group ("Could not load", no wrong number); (c) ES-4 omits
  `position_alert_history.contract` and daily-risk `instrument` (history);
  (d) D4's mechanism: Step 7 / AutoTradeArm build the order symbol from
  `contractDetails.strike` via `contractId`
  (`step-7-trade-card/page.tsx` ~1027-1033), not from `card.contract`; ES-2.4
  fixes `ContractDetails.strike`, so the outcome holds; (e) an old
  `last_result_json` with strike 0 would fail the `Strike` validator on
  `/scan/last-run` reload (never observed from Tradier).
- **Round 2** (fresh independent subagent, bmad-review-adversarial-general,
  gate-briefed; scope: `git diff 646c6510..6cc3f005` of this file, the R1-1 fix
  and its interactions): **CLEAN, zero gate findings.** Traced 182.5 from
  `ContractDetails.strike` through `missingCardContracts`, `api.ts`
  `strikes.join(',')`, `parse_strike_text`, `get_contracts` filtering and the
  `withCardContract` id gate: exactly the 182.5 row; integer strikes unchanged.
  Below gate, logged: (f) legacy saved-scan cards whose truncated id stood for
  a fractional contract now rescue the exact integer row (consistent with the
  order symbol; ES-4 AMBIGUOUS scope); (g) `step6CardContract.ts` lets strike 0
  through its guard, the backend 422s it and the rescue is silently empty.
- **Plan stage closed clean at round 2.**

## 9. Build-start re-check against current `main` (2026-10-22, plan §4)

Record only: no ES step, mechanism or invariant above is changed. Branch `board/exact-strike-41be05fa` = plan head `3669ecb5` + `git merge origin/main` (`bf0b3b54`, merged without conflicts). NO-LIVE-QUOTE is merged on `main`.

Every truncation site in §1/§3 was re-located on the merged code and is still present as described: `market.py` both chain builders (`"id": f"{symbol}|{int(strike)}|…"`, `"strike": int(strike)`, NLQ's `if not ask > 0: continue` now precedes them; dedup `seen` at the end of both; yfinance backfill `yf_iv.get(float(c["strike"]))`); `fetch_contract_quote_async` (`target_strike = int(float(strike_str))`, NLQ expiry clause kept, the docstring paragraph ES-1.3 rewrites is present); `schemas/__init__.py` `strike: int` on `OptionContract`, `ContractDetails`, `AlternativeContract` (`OptionLeg.strike` is already `float`); `routers/contracts.py` `_parse_strikes` (now also capped at 9 digits; superseded by `parse_strike_text`), `OptionContract(strike=int(c.get("strike", 0)))`, `GET /api/quote/option` `strike: int`; `routers/scan.py` card id `int(strike)`, `ContractDetails(strike=int(strike))`, alternatives `int(alt_strike)` and `int(float(_alt_sp.legs[0].strike))`; `contract_validator._contract_id`; frontend `contractGrading.ts` `truncStrike` and `step6CardContract.ts:41` `Math.trunc(cd.strike)` (both files unchanged since the plan).

Sweep for strike handling added since 2026-10-09 (all `split("|")` / id f-strings in `backend/app`, all strike-related `Math.*`/`parseInt` in `frontend/`): no new truncating site. `auto_trade_booking.py` parses the strike with `float()`; `alert_generator.py`, `routers/portfolio.py`, `portfolio_exposure.py`, `portfolioStore.ts` read only the symbol or expiry part; the Monte-Carlo / exit-plan seed keys in `routers/contracts.py` use `req.strike` (a float request field) and are not contract ids. `alt_c.get("strike", price)` in `routers/scan.py` is the alternatives' twin of the fallback ES-2.4 removes; it is unreachable for the same reason (every chain row carries a valid strike or is dropped) and ES-2.4 replaces it the same way.
