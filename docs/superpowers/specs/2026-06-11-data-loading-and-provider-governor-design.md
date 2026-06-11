# Data-Loading Redesign & Provider Governor — Design Spec

- **Date:** 2026-06-11
- **Status:** Approved design, pending implementation plan
- **Owner:** Kenneth
- **Topic:** Rate-limit-safe, multi-provider data sourcing + overnight ingestion + Alpaca integration (data & execution)

---

## 1. Context & Problem

Bamendjou sources market data from Tradier, Tiingo, yfinance, and IBKR. The current design fetches most data **on the scan hot path**, per-symbol, with no shared rate-limit enforcement and no 429 handling. Consequences observed:

- A full **stock scan** touches ~503 unique symbols against **Tiingo's free ~50-symbols/hour** cap → instant breach → every symbol returns "no market data."
- A full **options scan** issues ~1,500–2,000 Tradier calls against a 120/min ceiling → 12–16 min floor and throttling.
- Every fetcher swallows errors (`except: return []`), so a 429 throttle is invisible and the system keeps hammering → escalates to IP/session blocks (observed on IBKR and Tiingo).
- The data-source availability panel is **unreliable**: Tradier-live shows green by merely checking that the token string is non-empty — it never calls Tradier (a revoked token still shows green).

**Tiers (confirmed):** free Tiingo / Tradier / Alpaca / yfinance; **paid IBKR**. Usage assumption: **daily stock + options scans**.

---

## 2. Goals / Non-Goals

### Goals
1. **Respect every provider's tier limit — non-negotiable, structurally enforced.**
2. **No data-quality degradation** vs. today (identical indicator/backtest/score inputs).
3. Never rely on a single provider — automatic fallback when one is unavailable.
4. Move bulk data loading **off the scan hot path** into a paced ingestion job (overnight, manual, or OS-triggered) so scans fetch only the missing delta.
5. Reliable green/red availability detection.
6. Per-scan provenance logging: which provider served what, and which were down.
7. Add Alpaca as the primary daily-bar source (data) and as a Position-Card execution venue (paper now, live prepared-but-locked).

### Non-Goals
- Replacing Tradier for option chains (no free alternative; IBKR is the fallback).
- Unlocking any live trading account (IBKR live and Alpaca live remain locked).
- Fixing the latent adjusted-bars-vs-raw-live-price mismatch beyond storing raw for future use.
- Intraday/streaming redesign (charts unchanged except routed through the Governor).

---

## 3. Provider Tier Reference (bucket sizing)

| Provider | Tier | Bucket | Binding constraint |
|---|---|---|---|
| Alpaca | Free | 200 req/min | IEX feed (fine for daily bars) |
| Tradier | Free | 120 req/min market data | per-symbol option chains |
| Tiingo | Free | ~50 **unique symbols**/hr | the unique-symbol counter |
| yfinance | None | self-throttle ~2/s, Sem(2) | undocumented IP-block risk |
| IBKR | Paid | ~40 req/s (localhost) | session pacing |

---

## 4. Confirmed Design Decisions

1. **Triggers:** in-process scheduler (primary on the future 24/7 Mini PC) **+** manual "Ingest now" button **+** OS task (Windows Task Scheduler), all calling the same idempotent job, **plus** startup catch-up that auto-runs if the DB is behind the last close.
2. **Failover:** Alpaca **batch** primary → **per-symbol gap-fill** on the fallback chain. Partial-result gap-fill runs **immediately within the same ingestion run** (trivial volume).
3. **Price basis:** **store all three bases** (raw, split-adjusted, fully-adjusted). Scanner uses **fully-adjusted** by default = identical to today's Tiingo `adjClose` → no degradation. Raw retained for true price levels later.
4. **Alpaca execution:** **Position Card only** (stock orders), paper now; live prepared but locked.

---

## 5. Architecture

### 5.1 Provider Governor (foundational)

Every outbound provider call — ingestion **and** scan path — passes through one shared module (`app/data/governor.py`). Interface: `await governor.call(provider, key, coro)`. Four mechanisms:

1. **Token-bucket rate limiter**, one bucket per provider, sized per the table in §3.
2. **Persisted budget ledger** for Tiingo's unique-symbol/hour cap: counts distinct symbols this hour; when exhausted, the call is **refused and rerouted** to the next provider or deferred — a scan can never re-trigger the breach.
3. **429 / `Retry-After` exponential backoff** — on throttle, the provider bucket pauses and retries with growing delay instead of returning `[]`.
4. **Circuit breaker** per provider — N consecutive failures opens the circuit for a cooldown; calls short-circuit to fallback and the UI shows "degraded."

Provider adapters become thin functions behind the Governor. No module calls a provider directly.

### 5.2 Provider routing & fallback chains

Chains declared as config data (easy reorder/add). Hybrid failover: batch primary, then per-symbol gap-fill.

| Data type | Chain (primary → fallbacks) | Mode |
|---|---|---|
| Daily bars (bulk) | **Alpaca batch** → Tiingo → yfinance | Batch + per-symbol gap-fill |
| Daily bars (gap fill) | Tiingo → yfinance | Per-symbol |
| Live price / quote | **Tradier batch** → Alpaca snapshot → yfinance | Batch |
| Option chains | **Tradier** → IBKR `secdef` | Per-symbol, survivors only |
| Option expirations | **Tradier** (cached nightly) | Per-symbol, cached |
| IV rank / percentile | **IBKR** → Black-Scholes → yfinance | Per-symbol, in ingestion |
| Earnings / dividend calendar | **Tradier batched** → yfinance | Batched nightly |
| Market cap | **Alpaca/Tradier fundamentals** → yfinance | Nightly, cached weekly |
| Intraday chart bars | Tradier (≤15m) + IBKR (1h+) → yfinance | Triggered, on chart open |

Notable improvements vs. today: daily bars gain a real 3-deep chain; option chains gain IBKR as a true fallback (removes Tradier single-point-of-failure); yfinance demoted to last-resort everywhere, always Governor-throttled and semaphore-bounded.

### 5.3 Ingestion job & triggers

All four triggers (scheduler / manual / OS / startup-catch-up) invoke the same idempotent job (upserts). Nightly steps, all Governor-paced:

1. Daily bars for the full universe — Alpaca batch, 3 passes (raw / split / fully-adjusted) ≈ 15 calls → upsert.
2. Per-symbol gap-fill for symbols Alpaca missed (Tiingo → yfinance).
3. Option expirations per symbol → cache (removes one of the two scan-time chain calls).
4. Earnings/dividend calendar — Tradier batched.
5. IV rank/percentile — IBKR, paced.
6. Market cap — fundamentals, cached weekly.
7. Pre-compute signal confidence from fresh bars.

Cold-start first run (6y × ingestion universe × 3 bases) is one-time, paced, finishes in minutes on Alpaca's 200/min.

### 5.3.1 Ingestion universe & retention

**Universe is fully dynamic — never a hardcoded count.** The scanner expands whatever the user selects via `expand_universe()` (presets `SP500`/`NDX100`/`DOW30`, individual tickers, or a custom mix). The current `sp500.csv` holds **~640 symbols**.

**Ingestion universe (the nightly pre-fill set)** is a configurable list, defaulting to the **union** of the presets the user scans: `SP500 ∪ NDX100 ∪ DOW30` ≈ **~680 unique symbols** (NDX100 contributes a few non-S&P names such as ASML/PDD/JD). The union guarantees a morning scan of any of those universes finds zero gaps. The config lives alongside the other scan settings; adding a new universe to scan means adding it to the ingestion union.

**Retention: keep ~6 years.** Backtesting needs 5 years of *signal* history, but indicators evaluated at the first backtest bar need lookback *before* it (a 200-day MA needs ~200 prior bars). So ingestion fetches and retains **6 years** (5y backtest window + ~1y warm-up buffer) — correcting today's exactly-5×365-day fetch, which leaves the earliest backtest bars without warm-up. A single nightly prune step (`DELETE FROM ohlcv_daily WHERE date < today − 6y`) bounds the table.

**Storage footprint (daily granularity, one row per symbol/day, raw + factors — bases derived on read, not stored as separate rows):**

| | Rows | Size (incl. index) |
|---|---|---|
| 6y backfill, ~680 symbols | ~1.03M | **~155–190 MB** |
| Daily growth | ~680 rows/day | **~20 MB/year** |

Negligible on the Mini PC; the 6-year prune keeps it bounded indefinitely. Retention is a hygiene/correctness measure (warm-up buffer), not a space constraint.

### 5.4 Data model — multi-basis `ohlcv_daily`

```
ohlcv_daily(symbol, date,
            open, high, low, close, volume,   -- RAW (actual traded)
            adj_factor,                        -- cumulative split+div → fully-adjusted
            split_factor,                      -- cumulative split-only
            div_cash,                          -- audit / recompute
            fetched_at, source)                -- provenance: provider that wrote the row
```

- Scanner default reads **fully-adjusted** (raw × adj_factor) = identical to today → **§2 Goal 2 guaranteed**.
- Raw retained for true entry/stop price levels later.
- `source` column feeds per-scan provenance logging and data lineage audit.
- Tiingo returns raw + adjusted + divCash + splitFactor in one response; Alpaca's 3-pass yields the same → all columns populate naturally on either path.
- Migration adds columns; existing rows backfilled on next ingestion. `adj_factor` re-bases on new dividends, identical to current behavior.

### 5.5 Reliable availability detection

Replace env-var checks with **real authenticated probes**, 4-state, cached 30–60 s, routed through the Governor:

| State | Dot | Meaning | Determination |
|---|---|---|---|
| `connected` | 🟢 | Credentialed + real call succeeded | live probe 200 |
| `degraded` | 🟡 | Reachable but throttled / circuit-open | Governor reports recent 429s / open breaker |
| `down` | 🔴 | Configured but probe failed | network error / 4xx/5xx |
| `unconfigured` | ⚪ | No key set | credential missing |

Cheapest authenticated probe per provider:
- Alpaca → `GET /v2/account` (or `/v2/clock`)
- Tradier → `GET /v1/markets/clock` (real call, replaces fake env-var check)
- Tiingo → `GET /api/test`
- IBKR → `GET /iserver/auth/status`
- yfinance → one lightweight ticker fetch

The Governor feeds the dot, so the panel reflects **live operational health during scans**, not just a startup ping. `detail` tooltip carries the actionable reason (e.g. "401 — token not approved", "rate-limited, retry in 12s", "circuit open").

### 5.6 Settings — broker/credential slots

Add two Alpaca slots mirroring the existing four:

```
alpaca_live    { key_id, secret_key, base_url=https://api.alpaca.markets }
alpaca_paper   { key_id, secret_key, base_url=https://paper-api.alpaca.markets }
```

- Two fields (key + secret); `secret_key` added to `_SENSITIVE_KEYS` masking.
- Ingestion reads whichever Alpaca slot is configured (prefer `alpaca_live` if both; paper keys carry identical data entitlements).
- Both slots appear in Settings → Brokers and in the availability panel, matching the Tradier/IBKR pattern.

### 5.7 Per-scan provenance logging

End-of-scan structured summary in backend logs **and** the existing SCAN LOG UI panel:

```
SCAN a1b2c3 data-provenance:
  daily_bars   : DB-hit 501/503 | gap-filled 2 via Tiingo | Alpaca SKIPPED (circuit-open)
  live_price   : Tradier 503/503
  option_chains: Tradier 98/100 | 2 failed (no chain)
  iv_rank      : cache 100/100 (IBKR, ingested 21:04)
  earnings     : cache 503/503 (Tradier, ingested 21:05)
  providers_down: Alpaca (since 20:58 — 429 backoff)
```

- Per-symbol DEBUG line: provider that served each symbol (from `source` column).
- Per-scan INFO summary: hit-rate per data type + provider + explicit `providers_down` list.
- UI SCAN LOG panel shows a compact version (counts + down providers).

### 5.8 Alpaca execution venue (Position Card only)

Mirrors the existing IBKR/Tradier execution pattern exactly:

| Layer | Change |
|---|---|
| Adapter | New `AlpacaPaperAdapter.place_order()` → `POST {paper-api}/v2/orders`; returns standard `OrderResult` (`order_id`, `status`, `broker="alpaca_paper"`) |
| Router | Register `alpaca_paper`; add `alpaca_live` to `_LIVE_BROKERS` (prepared-but-locked, like `ibkr_live`) |
| Build | `build_router_from_credentials()` builds `alpaca_paper` from the `alpaca_paper` credential slot (same key+secret as data) |
| Status endpoint | Add `alpaca_paper: {configured}` and `alpaca_live: {configured: False, enabled: False, note: "Locked — not yet activated"}` |
| Frontend | Position Card gains an "Alpaca Paper" execution button (stock orders), disabled until configured |

Scope: **Position Card (stock) only** — the user's Alpaca account is stock-only, which also avoids Alpaca's options-enablement requirement. Options Trade Card keeps IBKR Paper / Tradier Paper. Alpaca live is wired end-to-end but blocked at the router, ready to unlock with a one-line change.

---

## 6. Workflow: New Daily Cycle

```
NIGHT (21:00 ET — scheduler / manual / OS)
  └─ Ingestion job → Governor-paced → fills ohlcv_daily (3 bases) +
     expirations + earnings + IV + market cap → pre-computes confidence
        (~30 governed calls, minutes)

MORNING (Scan)
  ├─ STOCK scan : 1 Tradier batch quote + read bars from DB → score → backtest
  │              (~1 network call; was up to 503 Tiingo)
  └─ OPTIONS scan: 1 batch quote → pre-screen from DB → chains for ~100 survivors
                  (~100–250 calls; was ~1,500–2,000)
```

### Advantages vs. today

| | Today | New |
|---|---|---|
| Stock-scan provider calls | up to 503 (Tiingo) | ~1 |
| Options-scan calls | ~1,500–2,000 | ~100–250 |
| Tiingo limit breach | guaranteed | impossible by budget design |
| Throttle behavior | silent "no data" | backoff + fallback, never blocks |
| Single-provider outage | scan dies | degrades, other provider covers |
| Data quality | Tiingo adjusted | identical (fully-adjusted) + raw available |
| Availability light | unreliable (env check) | real authenticated probe + live health |

---

## 7. Performance Bottlenecks (foreseen) & Mitigations

1. **Option chains — hard floor.** No Tradier batch endpoint; ~100 survivors × ≤2 calls @ 120/min ≈ **~100 s minimum** for options scans. Mitigations: nightly-cached expirations (removes 1 of 2 calls), aggressive DB-based survivor pre-screen, adaptive throttle from Tradier headers, IBKR `secdef` overflow/fallback. Remains the dominant cost (expectation set honestly).
2. **Backtest CPU** (not network) becomes the main stock-scan latency once bars are DB-served. Keep 24h backtest cache + ProcessPool.
3. **Cold-start first ingestion** — one-time heavier pull; paced; minutes on Alpaca.
4. **yfinance anywhere** — Sem(2) + Governor, last-resort only, never in a 503 loop.

---

## 8. Guardrails — how limits and performance are both protected

- **Over-limit is structurally impossible:** nothing reaches a provider except through its token bucket + budget ledger; exhausted budget reroutes, not blind-queues.
- **Throttle never escalates to a block:** 429 → exponential backoff → circuit breaker → fallback chain.
- **Performance protected because** slow limiters live in the overnight job (wall-clock irrelevant) while the scan path reads local DB; the only scan-time limiter that bites is survivor chains, where throttling would otherwise make scans *slower* — guardrail and speed align.
- **Continuous-scan floor:** scheduler refuses a cadence any provider's remaining budget can't sustain.

---

## 9. Suggested Implementation Staging

1. **Stage 1 — Provider Governor + 429 backoff + circuit breaker + reliable availability probes.** Immediate protection; no behavior change to data content.
2. **Stage 2 — Alpaca data adapter + multi-basis `ohlcv_daily` migration + fallback router** (Alpaca primary, Tiingo/yfinance fallback) for daily bars.
3. **Stage 3 — Ingestion job + triggers (scheduler / manual / OS / startup catch-up) + configurable union ingestion universe + 6-year retention/prune + scan-path switch to DB-first reads + provenance logging.**
4. **Stage 4 — Settings Alpaca slots + Alpaca Paper Position-Card execution venue.**

Each stage is independently shippable and leaves the system working.

---

## 10. Open Items / Risks

- Confirm exact Tiingo free-tier numbers against the user's account (unique-symbol/hour vs requests/day) when sizing the budget ledger.
- Alpaca IEX feed volume on illiquid names is thinner than SIP — immaterial for S&P 500 daily bars; note for any future small-cap universe.
- Windows Task Scheduler setup is outside the app; provide a documented `.bat`/command and an ingestion endpoint it calls.
- `adj_factor` recomputation strategy on new dividends: recompute affected symbol's series during the nightly job (not on read) to keep scan reads cheap.
