# Stocks horizon HISTORY: safe daily backfill and retention

> D1 plan draft. Independent plan round 1 has not run. No application code is built.
> Target STOCKS-HORIZON-HISTORY; roadmap D1 #112, D2 #113, mini PC D3 #114.

## Goal and boundaries

Keep about 17 years of daily bars for today's S&P 500 union NDX100 constituents
(the existing nightly universe may also retain DOW30). Today-only constituents
retain the survivorship limitation. D1 designs/audits this change; D2 builds and
checks it with synthetic bars, mocked providers, and isolated databases. All live
stored-bar backfill, migration on the operational database, provider smoke tests,
and the full-span evidence/exclusion decisions belong to #114 on the mini PC.

This is the authorized split from T1-CAP-SPLIT-H0B-2026-10-09. T1's three capped
plan rounds are preserved. HISTORY has its own plan/code stages, each capped at
three independent rounds. It carries T1 round 3 finding 1; it does not reopen T1.
The repo's numeric/persistence audit gate overrides coordinator examples from
other applications. Merge needs the user's go; D3 remains blocked until D2 merges.

## Current mechanism (verified against main aaa7102c)

- ingestion_job fetches six years by default, stores the Alpaca batch, falls back
  only for symbols with no Alpaca bars, and separately prunes the entire table.
- historical_store.get_bars is latest-date/settle aware, but does not fill a missing
  historical prefix when the latest row is current.
- Stored prices/factors come from a fetch-date basis. _read_bars multiplies prices
  by adj_factor; yfinance stores already adjusted prices with factor 1.
- refresh_adjustments accepts a nonempty Alpaca suffix as a full refresh, leaving
  pre-Alpaca rows untouched. stale_reasons flags any multiple-source series.
- Production OHLCV schema is created by Alembic, not app.database.create_all.
- history_retention_years controls audit/trade history, not daily OHLCV; keep it
  unchanged. SchedulingConfig currently exposes only timezone.

## Design

### R1: one OHLCV retention setting, no destructive short request

Use scheduling.history_years, integer 1..20, default 17. A shared loader validates
it and uses 17 for absent/invalid persisted values. Extend GET/PUT /settings/scheduling
with history_years; an omitted field in legacy timezone-only PUT preserves the
existing setting. Preserve unrelated settings keys. No frontend work is needed.

IngestRequest.years permits 1..20, defaults to the configured retention, and the
effective ingestion/prune horizon is max(requested years, configured history_years).
The response and job state expose the effective value. Nightly ingestion uses the
same setting. _prune_old_rows also enforces this lower bound, including direct
shorter callers. Dates remain the existing approximate years * 365 convention.
No silent write to the operator's real settings.yaml in tests.

### R2: persisted floor and verified seam, transactionally with bars

Add OhlcvHistoryStateModel on OhlcvBase with a single row per symbol:
- floor_requested_start, floor_date, floor_provider, floor_checked_at;
- seam_date (first Alpaca date), old_source, seam_signature.
All optional; existing history has no inferred trust. Register the model through
its existing ohlcv_daily module and add an Alembic migration at the current head.
No history_floor.json: the database row makes proof/floor changes atomic with bars
and avoids a sidecar file racing a committed dataset. Update the presence probe
accordingly. Do not apply the migration on a live database from this host.

The seam_signature hashes canonical values of the last older row and first current
row: date, raw close, adj_factor, source, fetched_at (UTC-normalized). Build it from
persisted values after upsert, so numeric rounding/SQLite-naive timestamps match
subsequent reads. It is a verification token, not proof of a generic source mix.

### R3: stage a coherent symbol update before writing

Continue Alpaca batch fetching, but stage its bars; do not commit a current suffix
before validating/rebuilding an existing older prefix. Process one symbol at a
time. Share a per-symbol asynchronous lock between ingestion, adjustment refresh,
and get_bars writes to prevent competing writes changing the staged basis.

For nonempty Alpaca data, choose its earliest settled date as the seam. When there
are existing older rows or a missing prefix beyond a seven-calendar-day tolerance:
1. Query Tiingo then yfinance explicitly, skipping Alpaca. Request the desired old
   start through at least the first five settled Alpaca dates (with one extra end
   day to cover provider inclusivity), then filter to the requested dates.
2. Refetch the entire older retained segment every ingestion, even when no stale
   flag exists. This is necessary because Alpaca supplies no actual action markers.
3. Require at least five shared dates, finite positive closes/factors, no duplicate
   dates, and abs(fallback adjusted close / Alpaca adjusted close - 1) <= 0.005 on
   every overlap date. Compare adjusted prices, never raw closes. Try the next
   fallback provider when an earlier provider is empty, invalid, or inconsistent.
4. Require the candidate to contain every already-stored older date being retained;
   require the current suffix to contain every already-stored current date covered
   by this refresh. A partial provider reply cannot count as a whole refresh.
5. Use fallback rows strictly before the seam and Alpaca rows at/after it. Refuse
   missing/invalid overlap or absent required rows. Commit neither side on failure;
   preserve the previous bars and seam metadata, and report seam_mismatch or failed.
6. In one per-symbol transaction, upsert both segments, record the exact validated
   seam signature/source, and update successful floor observations. After commit,
   invalidate confidence; refresh also calls its existing backtest eviction callback.
   If the DB write fails between segments, roll back the whole symbol.

If no Alpaca bars exist, request the whole window directly from the non-Alpaca
chain and use one provider for the entire symbol. Require coverage of previous
retained dates before replacing them. get_bars is not used as a backfill provider,
so a fresh DB suffix cannot short-circuit the missing prefix. Providers remain
mocked in all development verification.

### R4: provider floors are evidence, not an empty-response guess

A floor means the earliest date available in a successful nonempty provider reply,
not a proved IPO date. Record it only after valid overlap/coverage proves a usable
series. Empty replies, exceptions, missing credentials, and partial refreshes do
not create floors. Store the requested start and provider with the observation.

A current floor suppresses another missing-prefix request only when the request
is within that observed range, the existing earliest date matches the floor, the
observation is at most 30 days old, and no older segment needs its nightly refresh.
A wider request, stale floor, or explicit force_backfill re-probes the prefix.
The manual ingestion endpoint accepts force_backfill (default false). A floor
never suppresses refreshing existing older adjustment factors.

### R5: refresh the old segment and selectively recognize a verified seam

refresh_adjustments must use the same staged coherent-update helper for the
production provider chain and rewrite the entire existing stored span. Tests may
inject a full-window fetch; such a fetch must cover every stored settled date.
Do not report refreshed for an Alpaca-only suffix while older dates remain stale.
No partial commit, deletion, or cache eviction on failure. Successful refresh
updates proof and evicts both existing confidence/backtest cache paths.

stale_reasons(rows, verified_seam=None) remains pure/backward compatible. A seam
is recognized only if the actual adjacent boundary pair matches its recorded date,
sources, factors and timestamps, all older rows have old_source, all newer rows
have source alpaca, and every row has a positive non-NULL factor. Then suppress
mixed_basis from that exact two-source partition and batch_step only at that one
boundary. Keep jump, pre_action_fetch, NULL-factor mixtures, same-source batch
steps, and all unrecorded/changed boundaries active. Rewriting a boundary without
updating its proof invalidates the exemption. Never exempt a source name globally.

find_stale_adjustment reads the metadata row in the same DB session. Extend the
SELECT-only evidence harness with a separate load_history_states loader and an
optional states_by_symbol argument to build_report. Keep load_basis_rows' seven-field
tuples unchanged. The full-span D3 report uses the same selective rule without
filtering out excluded symbols.

### R6: job results and pruning

Add backfilled, seam_mismatch and floor_reached counts plus symbol lists and ratio
information to IngestionResult and get_ingestion_state. A backfilled symbol really
added older dates, not just refreshed them. A mismatch is not a successful refresh.
Clear per-run counts/lists each run; done/failed are per requested unique symbol.
An empty universe must not trigger destructive pruning. Serialize ingestion starts
with the existing task/running guard strengthened so two immediate requests cannot
both launch. Prune only after symbol updates, using the configured retention floor.
Pruning may remove old rows but does not create a seam exemption for unrelated data.

## Coordinator work packages and dependencies

| Local ticket | Parent | Blocked by | Independently verifiable outcome |
|---|---|---|---|
| 01 Retention contract | D2 #113 | D1 #112 clean | Nightly/manual requests preserve the configured horizon and expose it |
| 02 Coherent prefix backfill | D2 #113 | 01 | Mock-provider backfill adds older bars atomically; mismatches preserve prior data; floors persist |
| 03 Adjustment refresh and evidence | D2 #113 | 02 | Later split/dividend refreshes the older span; only verified seams avoid false flags |
| 04 Regression and mini PC runbook | D2 #113 | 03 | Synthetic acceptance suite, isolated migration check, exact D3 handoff commands |
| 05 Independent code audit and PR | D2 #113 | 04 | Fresh audit clean, state/tickets reconciled, PR reviewable; merge awaits user |
| 06 Mini PC execution | D3 #114 | 05 + D2 merged | Live counts and full-span bar-basis report; user decides exclusions |

Persist map.md, spec.md and one issue file per ticket in .scratch/stocks-horizon-history.
Publish build tickets under a dedicated HISTORY tracking issue after the plan is
clean; do not start a blocked frontier. Keep checkpoint/state/audit records current.

## Tests and verification

- Isolated SQLite integration: retained row at 16.9 years survives, 17.1 years is
  pruned; explicit six/one-year request cannot prune seventeen-year data.
- Settings GET/PUT/default/bounds and old timezone-only save preserve configured
  retention and unrelated keys. Scheduler passes configured horizon. API accepts
  17/20, rejects >20, exposes effective years and force_backfill.
- Synthetic partial-Alpaca history obtains a pre-2016 prefix from Tiingo then
  yfinance; a fresh DB suffix does not prevent backfill; overlap compares adjusted
  values. Equal raw closes with unequal factors fail; 0.5% threshold is inclusive.
- A post-backfill split and a dividend update both segments on the new basis;
  adjusted seam remains continuous. Old-provider failure/missing dates/insufficient
  overlap preserves old and current rows and previous proof. Injected failure after
  the first upsert rolls back bars and metadata together.
- Successful observed floor avoids a second unnecessary missing-prefix request;
  empty/error replies do not suppress retries; wider/forced/expired requests re-probe.
  Existing old segments are refreshed even with a floor present.
- A verified two-provider seam is clean; invalid proof, an additional provider,
  NULL factors, a real adjusted jump and same-source stale steps still flag.
- Production refresh actually rewrites old dates when Alpaca only supplies the
  recent suffix; incomplete injected fetch is failed, and failed refreshes do not
  evict caches. Existing refresh/settle/evidence/cache tests remain green.
- Status counters reset correctly; empty input and concurrent starts do not prune
  or launch duplicate runs. Migration upgrade/downgrade is checked only on a temp
  database. Full backend regression uses Python 3.11 with no network; frontend
  typecheck is clean before every checkpoint/commit.

## D3 handoff (only after D2 merge)

On the mini PC, confirm the deployed commit, Python 3.11 and operational DB target
without printing credentials; back up operational history before migration; migrate
using the project's Alembic configuration; run POST /api/data/ingest with SP500 and
NDX100, years=17, force_backfill=true. Record final counts/names, failures and seam
ratios from /api/data/ingest/status. Run scripts/evidence/bar_basis_check.py over the
whole stored span, preserving all symbols in that read-only report. Present flagged
and seam-mismatch symbols for user exclusion decisions; update exclusions only from
those decisions. Any live Alpaca/Tiingo smoke test belongs here. D1/D2 never claim
that this operational work ran, nor tune on these bars from the development host.
