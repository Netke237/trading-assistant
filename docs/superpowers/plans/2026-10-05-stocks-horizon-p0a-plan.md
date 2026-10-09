# Stocks horizon P0A: exclusion list + confidence de-overlap — Implementation Plan (`STOCKS-HORIZON-P0A`)

> **For agentic workers:** built through `k-ticket-coordinator`. One ticket per task, one fresh implementer per
> ticket, test-first. The coordinator owns `PROJECT_STATE.json`, the tracking issue and the audits. Implementers never
> edit audit fields and never put `round N` in a commit subject.

**Origin.** Decision `STOCKS-PARAMS-PER-HORIZON-2026-10-05` (ADR `docs/adr/0001-stocks-parameters-per-horizon.md`)
keeps four C4 items as error fixes to land before any tuning. Decision `STOCKS-HORIZON-P0-SCOPE-2026-10-05` split them
into two audit targets. **This plan is P0A**: the data-correctness half.

1. **One shared exclusion list** read by every scan and by the evidence harness (C4 Q6; T1's tuner will read it too).
2. **Confidence evidence on non-overlapping samples**, minimum 20, and **missing confidence = Unvalidated, never PASS**
   on both the options and the stocks path (decision `STOCKS-HORIZON-P0-SCOPE-2026-10-05` item 3).

P0B (bearish block + earnings veto, both paths) is a separate plan and target. Nothing here touches direction or
earnings.

**Live numbers that change, on purpose.**

- Excluded symbols disappear from scan results and appear in `rejected` with an `Excluded:` reason (A2).
- Every cached and freshly computed confidence changes: the replay counts each setup once instead of once per bar
  while its forward window is open, so `sample_size` falls (Phase C measured a median of about 39 non-overlapping
  samples on Swing and 22–25 on Position, `score_calibration.md`) and the hit rate moves. More symbols fall below `min_samples: 20` (A4). `BARS_BASIS_VERSION` moves `b2 → b3` so no
  overlapping-era value is served again.
- A card whose confidence is `None` (fewer than 20 decisive non-overlapping samples) is capped at CAUTION on both
  paths and reads **Unvalidated** (A5, A6). Before, `None` meant "gate not applied" and the card could PASS. The
  Phase C evidence (`score_calibration.md`) measured 450–532 of 535 symbols still at ≥ 20 non-overlapping samples, so
  most symbols keep a measured confidence.

## Global constraints

- **Runtime.** Backend Python **3.11** (Windows `.\.venv\Scripts\python.exe -m pytest`). Frontend
  `cd frontend && npm run typecheck && npm run test`.
- **TDD.** Write the failing test first, run it, see it fail for the predicted reason, then write the code.
- **No threshold or parameter value changes.** `min_samples` stays 20; `confidence_gate` thresholds stay 50 / 35.
- **Numeric golden pins.** A4 and A5 change confidence values and statuses on purpose. A pin that moves must be one
  that depends on overlapping-replay sample counts or on `None` reading PASS; the implementer lists every moved pin
  in the ticket report with the reason. Any other moved pin is a defect: stop and report it.
- **No `persist()` / storage shape change.** No database migration.
- **Commit trailer:** `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Ticket graph

```
A1 (exclusion file + loader) ── A2 (scans read it) ── A3 (evidence harness reads it)
A4 (confidence de-overlap + b3) ── A5 (None = Unvalidated cap, backend) ── A6 (Unvalidated label, frontend)
```

Sequential build in the order A1, A2, A3, A4, A5, A6. A2 and A5 both edit `routers/stock_scan.py` (different
functions); serial order avoids conflicts.

---

## A1 — The exclusion list file and its loader

**Mechanism today.** There is no exclusion list. The SP500 universe is `backend/app/data/sp500.csv`, which
`sp500_scheduler` rewrites from yfinance, so a hand edit there does not survive; NDX100 and DOW30 are hardcoded in
`app/data/universe_presets.py`. The Phase C evidence excluded AVB, CTVA and FI by passing an explicit `--symbols` list.

**Semantics.**

- New file `backend/config/universe_exclusions.yaml`:

  ```yaml
  # One shared list of symbols that scans, the evidence harness and tuning skip.
  # scope: scan     -> skipped by every scan (options, stocks, pre-breakout, fib), the evidence harness and tuning
  # scope: evidence -> skipped by the evidence harness and tuning only; still scanned live
  # Edit by hand; read fresh on every scan (no restart needed). Decision STOCKS-PARAMS-PER-HORIZON-2026-10-05.
  version: 1
  symbols:
    CTVA: {scope: scan, reason: "2026-10-01 corporate action not adjusted by any provider (77.67 -> 12.57)", added: 2026-10-05}
    ...
  ```

- Initial contents (evidence: `docs/superpowers/measurements/2026-10-05-phase-c-evidence/bar_basis.md`, the 29
  symbols `stale_reasons` flags, plus each symbol's last stored bar in `ohlcv_daily`, read 2026-10-05; data end
  2026-10-02):

  | Scope | Symbols | Reason text |
  |---|---|---|
  | `scan` | CTVA | 2026-10-01 corporate action not adjusted by any provider (77.67 -> 12.57) |
  | `scan` | AVB | price feed ended 2026-08-17; 2.793 split not adjusted |
  | `scan` | PXD, SWN, MRO, CTLT, PTVE, JNPR, HES, WBA, K, HOLX, CTRA, EA, EQR | price feed ended `<last stored date>` (no bars in the 30+ days before 2026-10-02); likely delisted |
  | `scan` | ANSS, SGEN | acquired (ANSS by SNPS 2025-07, SGEN by PFE 2023-12); stored bars after that date are not this company (mixed basis) |
  | `evidence` | BIIB, CNC, DOC, DXCM, EPAM, FI, FMC, LCID, MRNA, NWL, PDD, SIRI | bar-basis check flags a close-to-close jump > 40% or mixed basis (`bar_basis.md`); excluded from evidence, still scanned |

  Each of the 13 "feed ended" rows carries its own last stored date in the reason (PXD 2024-05-03, SWN 2024-10-01,
  MRO 2024-11-22, CTLT 2024-12-18, PTVE 2025-04-01, JNPR 2025-07-02, HES 2025-07-18, WBA 2025-08-28, K 2025-12-11,
  HOLX 2026-04-07, CTRA 2026-05-06, EA 2026-08-10, EQR 2026-08-21). 29 symbols in total.

- New module `backend/app/data/universe_exclusions.py`:
  - `class ExclusionListError(ValueError)`.
  - `load_exclusions() -> dict[str, Exclusion]` where `Exclusion` is a frozen dataclass `(symbol, scope, reason)`.
    Reads the file **on every call** (no cache: it is a few hundred bytes, and a cache would need config-health
    registration and a restart to pick up an edit). Symbols are upper-cased.
  - Validation, all raising `ExclusionListError` naming the file and the offending key: file missing or unparsable;
    `version` not 1; `symbols` not a mapping; a scope other than `scan` / `evidence`; an empty or non-string reason.
  - `filter_symbols(symbols: list[str], *, purpose: Literal["scan", "evidence"]) -> tuple[list[str], list[Exclusion]]`.
    For `purpose="scan"` it removes `scope: scan` entries; for `purpose="evidence"` it removes both scopes. Matching is
    case-insensitive; the kept list keeps input order and input spelling; the excluded list is in input order, one
    entry per excluded input symbol (duplicates in the input collapse to the first).
- Not wired anywhere yet (A2, A3).

**Test first.** `backend/tests/test_universe_exclusions.py`:

1. The shipped file loads; it has exactly the 29 symbols above with the scopes above (pin the two sets).
2. `filter_symbols(["aapl", "CTVA", "BIIB"], purpose="scan")` keeps `["aapl", "BIIB"]` and excludes CTVA with its reason;
   `purpose="evidence"` keeps `["aapl"]`.
3. Each validation failure raises `ExclusionListError` (write bad files under `tmp_path`; the loader takes an optional
   `path` argument defaulting to the shipped file).

**Commit:** `feat(universe): shared exclusion list file and loader (STOCKS-HORIZON-P0A)`

---

## A2 — Every scan skips `scope: scan` symbols and says so

**Mechanism today.** Four scan entry points build their symbol list:

- options: `routers/scan.py` (`expand_universe(req.universe)` near line 1651);
- stocks: `routers/stock_scan.py` `/stock-scan` (`req.symbols` or `expand_universe(req.universe)` near line 1549);
- pre-breakout: `/scan/prebreakout` (near line 1911);
- fib pullback: `/scan/fib-pullback` (near line 1784).

Typed symbols (`req.symbols`, `body.symbols`, or a non-preset string inside `universe`) pass straight through.

**Semantics.**

- Each of the four calls `filter_symbols(..., purpose="scan")` on its **final** symbol list (after preset expansion
  and after typed symbols are merged), so a typed excluded symbol is skipped too (decision
  `STOCKS-HORIZON-P0-SCOPE-2026-10-05` item 4).
- `ExclusionListError` → the scan fails with HTTP 500 and the error text as `detail`, logged once, before any
  per-symbol work. A broken list must not silently scan everything.
- **Options and stocks scans:** each excluded symbol becomes a `rejected` entry
  `{"symbol": X, "reason": "Excluded (data): <reason>"}` (options: `RejectedCandidate(symbol=X, reason=...)`), and is
  counted in `scanned`. Funnel buckets:
  - options `OptionsPipeline`: the reason is counted in `failed_data` (extend that bucket's predicate to match the
    `Excluded (data):` prefix);
  - stocks `classify_stock_rejection`: returns `failed_history` for that prefix. Add the literal to
    `tests/test_stock_scan_funnel.py`'s `_REAL_STOCK_REASONS` so `test_every_stock_reason_producer_is_classified`
    stays green.

  The `scanned == sum of buckets` invariants therefore still hold. Locate the options funnel's `failed_data`
  predicate (`routers/scan.py`, the `_buckets` used near line 2084) and its test file before editing.
- **Pre-breakout and fib scans** return a bare `list[dict]` of setups and have no rejected list. They skip excluded
  symbols and log one INFO line listing them. Surfacing them in that UI is out of scope (Pre-Breakout is redesigned in
  STOCKS-HORIZON-T4); state this in the ticket report.
- The scheduled stock/options scans (`scan_scheduler.py`) call the same functions, so they inherit the filter. No
  change to ingestion, EDGAR prefetch, strategy watches, chart, analysis or portfolio: those are not scans, and
  ingestion must keep fetching bars so an excluded symbol can be re-checked.

**Test first.** Extend the existing scan endpoint tests (find the files that patch
`app.data.universe_presets.expand_universe`):

1. Stock scan over `["AAPL", "CTVA"]` (typed): CTVA never reaches per-symbol work (patch the per-symbol function and
   assert it is not called with CTVA), appears in `rejected` with `Excluded (data):`, and `pipeline.failed_history`
   counts it; the sum invariant holds.
2. Same for the options scan with `failed_data`.
3. Pre-breakout and fib: CTVA is not processed.
4. A malformed list (monkeypatch the loader to raise `ExclusionListError`) makes each scan return 500 before any
   per-symbol call.

**Commit:** `feat(scan): skip excluded symbols in every scan and report them (STOCKS-HORIZON-P0A)`

---

## A3 — The evidence harness skips both scopes and prints what it skipped

**Mechanism today.** `scripts/evidence/*.py` read `args.symbols or await stored_symbols()` (every symbol in
`ohlcv_daily`). `report_header` (`scripts/evidence/_bars.py`) prints the symbol list.

**Semantics.**

- One helper in `_bars.py`, `evidence_symbols(requested: list[str] | None) -> tuple[list[str], list[Exclusion]]`: the
  requested list or every stored symbol, filtered with `purpose="evidence"`. All four scripts
  (`bar_basis_check.py`, `score_calibration.py`, `gate_persistence.py`, `strategy_matrix.py`) use it **except
  `bar_basis_check.py`**, which must keep checking every symbol (it is the tool that finds bad symbols).
- A flag `--include-excluded` on the common parser bypasses the filter (for re-checking an excluded symbol).
- `report_header` gains a line `- Excluded (universe_exclusions.yaml): N — SYM (scope), ...` (or `none`), so every
  report states what it left out.
- SELECT-only and read-only as today.

**Test first.** In the existing evidence test module (find it under `backend/tests/` or `scripts/evidence/`): the
helper with a stub stored-symbol list drops both scopes; `--include-excluded` keeps them; the header line renders;
`bar_basis_check` is not filtered.

**Commit:** `feat(evidence): skip the shared exclusion list and print it in the header (STOCKS-HORIZON-P0A)`

---

## A4 — The confidence replay counts each setup once

**Mechanism today.** `compute_confidence` (`app/scoring/signal_confidence.py`) scores every bar from `warmup` to
`len(bars) - n_days`; each PASS bar is a fire with its own forward window `bars[i+1 : i+1+n_days]`. A setup that stays
PASS for eight bars counts eight times with overlapping windows, inflating `sample_size` and making the hit rate a
correlated average. The evidence script already measures the non-overlapping count
(`scripts/evidence/score_calibration.py::distinct`, "a flat fire still occupies its window").

**Semantics.**

- Greedy non-overlap, identical to `distinct(passes, n_days)`: after a fire at bar `i` (any outcome, flat included),
  the next bar that may fire is `i + n_days`. Bars before that are **not scored** (this also makes the replay faster).
- `min_samples` (20, from `confidence_backtest.<horizon>`) and `aggregate` are unchanged; `sample_size` stays "decisive
  fires" (wins + losses).
- `confidence_cache.BARS_BASIS_VERSION` → `"b3"`, with the comment's history line extended ("b3 for
  STOCKS-HORIZON-P0A A4: the confidence replay counts non-overlapping fires"). This also re-keys
  `stock_scan._backtest_key`, which only costs one recompute.

**Test first.** `backend/tests/test_signal_confidence_overlap.py`:

1. A synthetic bar series where `score_stock` is patched to return PASS on bars 70–77 and 100: with `n_days = 10` the
   replay evaluates fires at 70 and 100 only (assert the bars `evaluate_fire` sees, by patching it).
2. A flat fire at 70 still blocks 71–79.
3. Parity with the harness: for one fixture symbol's bars, `compute_confidence(...).sample_size` equals the
   `non_overlapping` count `score_calibration.confidence_counts` reports for the same bars, horizon and direction
   (import the script module the way its existing tests do).
4. `cache_key(...)` ends in `|b3`.

**Commit:** `fix(confidence): count non-overlapping setups only; basis b3 (STOCKS-HORIZON-P0A)`

---

## A5 — Missing confidence caps at CAUTION ("Unvalidated") on both paths

**Mechanism today.** `signal_confidence.status_cap(None, gate)` returns `"PASS"`, so `score_stock` (the options path
and every caller that passes `confidence_gate`) never demotes a card with no confidence. The stocks routes in
`routers/stock_scan.py` (the `/stock-scan` per-symbol function near line 1350 and `_analyze_core` near line 890) apply
their own thresholds only when `conf_val is not None`.

**Semantics.**

- `status_cap(None, gate)` returns `"CAUTION"` **whether or not the gate is enabled**: the decision is "never PASS".
  The gate's `enabled` flag and thresholds still govern measured confidence only. (Options sends thresholds 0/0 when
  the user turns the gate off; that no longer lets an unvalidated card PASS. State this in the Settings help text only
  if a ticket already touches it; otherwise log it.)
- `interpret(None, ...)` text: `"Unvalidated — fewer than {min_samples} non-overlapping past setups on {symbol}
  ({sample_size} found). Capped at CAUTION until there is enough history."` `interpret` gains a keyword
  `min_samples: int = 20`; callers pass the horizon's configured value where they have it.
- `/stock-scan` per-symbol function: when `conf_val is None`, a PASS card becomes CAUTION (never lowers a REJECT),
  the symbol is **not** dropped. `_analyze_core`: same cap, plus
  `gate_flags.append({"gate": "confidence", "status": "CAUTION", "detail": "Unvalidated: <n> non-overlapping samples
  (< <min>)"})`.
- `confidenceText` on both result types carries the new interpretation. The options path already gets it from the
  `confidence` rule's `interpretation`. The two stocks sites today set `conf_txt = ... if conf_val is not None else
  None`; they must call `interpret` for `None` too.
- The stocks "After scan" auto-fire arms on PASS only (Phase C S-T2), so an Unvalidated stock card can no longer
  auto-fire. Options auto-trade is unaffected by card status (known; P0B adds its own refusals).

**Test first.**

1. `status_cap(None, {"enabled": True, ...}) == "CAUTION"` and the same with `enabled: False`.
2. `score_stock(..., confidence=None, confidence_gate=gate)` on a fixture that otherwise PASSes returns CAUTION with a
   `confidence` cap entry.
3. `/stock-scan` with `compute_confidence` patched to return `ConfidenceResult(None, 0.6, 12, 3)` on a PASS fixture:
   the candidate is CAUTION, still present, `confidenceText` starts with `Unvalidated`.
4. `_analyze_core` (via `/analyze-stock`) shows the CAUTION flag.

**Commit:** `fix(confidence): missing confidence is Unvalidated and caps at CAUTION (STOCKS-HORIZON-P0A)`

---

## A6 — The badge says "Unvalidated"

**Mechanism today.** `frontend/components/atoms/ConfidenceBadge/index.tsx` shows `—` and the tooltip "No backtest data
available for this pattern." for a null confidence. `frontend/lib/confidenceText.ts` maps null to tier `unknown`.

**Semantics.** For a null/undefined confidence the badge label is `Unvalidated` (tone `caution`), tooltip: "Fewer than
20 non-overlapping past setups. Not enough history to validate this pattern, so it cannot reach PASS." Tier name
stays `unknown`; only its tone (`dim` → `caution`) and text change. No other component changes.

**Test first.** Extend the ConfidenceBadge test (or add `__tests__` beside it): null → text `Unvalidated`, tone
caution, tooltip text; 62 → `62%` unchanged.

**Commit:** `feat(ui): ConfidenceBadge shows Unvalidated for missing confidence (STOCKS-HORIZON-P0A)`

---

## Verification (coordinator, after A6)

- Backend full suite on Python 3.11; frontend typecheck + Jest.
- On Kenneth's machine, read-only: a Swing Bullish SP500 stock scan and options scan show CTVA/AVB under rejected
  with `Excluded (data):`, and Unvalidated candidates at CAUTION. Re-run `score_calibration.py` on 20 symbols and
  confirm its header lists the exclusions.

## Out of scope (logged, not built)

- Surfacing excluded symbols in the Pre-Breakout/fib UI (T4).
- Automating exclusion maintenance (e.g. auto-adding a symbol whose feed stops). The list is hand-edited.
- Settings help text for "gate off still caps Unvalidated" unless a ticket already edits it.
