# D3 history recovery — single-provider rebuild on the mini PC (2026-10-15/16)

Issue #114 (D3 recovery checklist) · code: #324 / PR #341 (`HISTORY-SINGLE-PROVIDER-REBUILD`) · plan: `docs/superpowers/plans/2026-10-15-history-single-provider-rebuild-plan.md` §4.
Live backend only (mini PC). Database reads below are plain SELECTs; nothing was deleted, restored or edited by hand.

## Environment

| Item | Value |
|---|---|
| Deployed code | `6d5b6ec2` (main, includes PR #341 at `a999b274`); the checkout later moved to `9abffcb1` / `27fe5182` (UI-only PRs #345/#346) outside this run |
| Python | 3.11.9 (`backend/.venv`) |
| Alembic | `a93b8d24f760` → `35c19d72ef80` (head, mergepoint): adds nullable `ohlcv_history_state.basis_provider` / `basis_rebuilt_at`, plus main's `bpr001`, `b47d68e91a20`, `c29a451f911c` |
| `history_years` | 17 (`/settings/scheduling`, timezone Europe/Berlin) |
| Pre-run backup | `pg_dump -Fc`, 40,216,283 bytes, sha256 `429c346c…f5337f`, listing verified (kept locally on the mini PC, `.scratch/history-d3-recovery/`) |
| Post-run backup | `pg_dump -Fc`, 43,183,775 bytes, sha256 `efeb9259…013013`, listing verified (27 table-data entries; same local folder) |

## Sequence (UTC)

1. 20:25 — pre-run backup. An old-code startup catch-up (started 16:00) was at 205/536 with 32 seam refusals; it was stopped with the backend.
2. 20:26 — `alembic upgrade head`, backend restarted on the new code. **SPY's last bar was 2026-10-14, so no startup catch-up started** (`status: idle`): the startup staleness check no longer triggers a full ingestion once SPY is current (plan acceptance 4; seen again at the 21:27 restart).
3. 20:28 — `POST /api/data/ingest {"symbols": <97>, "rebuild": true}` (`rebuild-list.txt`: the 76 symbols starting 2020-10-12, SPY, gap symbols PSX CSCO CTAS TSCO LNC, today's new seam refusals ABT ABBV ACN CEG, the stale NDX names DDOG FI GFS JD LCID OKTA PDD RIVN TEAM WDAY ZS, and WBD).
4. 21:24 — the backend process stopped (no error in its log; it had been started from an agent shell that ended). Pass 1 had processed 47 symbols alphabetically (through `K`, `LEN` in progress). Each rebuild commits per symbol, so the 38 rebuilds were kept; refusal reasons are preserved in `rebuild-pass1-refusals.log`. The in-memory per-symbol `rows_before` for pass 1 was lost.
5. 21:27 — backend restarted; `POST /api/data/ingest {"symbols": <50 from LEN>, "rebuild": true}`. Completed 22:25: `rebuild-pass2-final-status.json`.
6. 22:28 — full-span SELECT-only bar-basis check (`history-bar-basis-2026-10-15.md`), SELECT-only coverage (`coverage-after-rebuild.txt`), post-run backup.
7. Nightly ingestion was **disabled** on this machine (`enabled: false`); enabled at 02:00 Berlin with Kenneth's approval in chat (first run 2026-10-16 02:00). That run is the "next normal ingestion" check (plan acceptance 2, observed half).

## Results

| | Pass 1 | Pass 2 | Total |
|---|---:|---:|---:|
| Requested | 47 | 50 | 97 |
| Rebuilt | 38 (33 Tiingo, 5 yfinance) | 48 (39 Tiingo, 9 yfinance) | **86** (72 Tiingo, 14 yfinance) |
| Refused (rows left untouched) | 9 | 2 | **11** |
| Pruned rows (older than the 17-year cutoff) | — (run cut off) | 435 | 435 |

Every single-provider symbol has exactly one `source` in `ohlcv_daily` (SELECT check: 0 mixed). Per-symbol first/last dates and row counts: `rebuilt-symbols-table.md`, `single-provider-symbols.txt`.

### Refused (the 11 still starting 2020-10-12)

| Symbol | Reason (both providers) | Last stored bar | Likely cause (not verified here) |
|---|---|---|---|
| ANSS | Tiingo internal gap 2025-07-17 → 2026-02-06; yfinance no bars | 2026-10-08 | acquired by SNPS (2025-07); already excluded (scan) |
| AXL | no settled bars | 2026-02-04 | ticker change/delisting |
| BF.B, BRK.B | no settled bars | current | **dot-class tickers**: providers expect `BF-B`/`BRK-B`; looks like a symbol-mapping gap in the rebuild/fallback fetch (follow-up) |
| EA | reply omits existing stored dates | 2026-08-10 | feed ended; rebuild refuses rather than delete stored rows |
| EQR | Tiingo no bars; yfinance omits existing dates | 2026-08-21 | feed ended |
| FBHS | no settled bars | 2022-12-14 | renamed (FBIN) |
| FI | no settled bars | 2026-10-09 | ticker/listing change suspected; internal gap 2021-10-01 → 2023-06-07 remains |
| K | no settled bars | 2025-12-11 | delisted |
| MMC | no settled bars | 2026-01-13 | ticker change suspected |
| PKI | no settled bars | 2023-05-15 | renamed (RVTY) |

### Coverage before → after (SELECT-only)

| | 2026-10-14 snapshot / pre-run | After rebuild |
|---|---|---|
| Rows / symbols | 1,957,209 / 539 (2009-10-19 → 2026-10-14) | **2,129,876 / 539** (2009-10-20 → 2026-10-15) |
| Symbols starting 2020-10-12 | 76 | **11** (the refused list above) |
| SPY | 2021-07-21 → 2026-10-14 | **2009-10-20 → 2026-10-15** (Tiingo, 4,273 rows) |
| Internal gaps > 7 days | PSX, CSCO, CTAS, TSCO, LNC, FI, CTRA (+ ANSS, SGEN) | **ANSS, FI, SGEN** only |
| Actively traded symbols stuck ≥ 4 trading days | 45 (14 Oct issue) | FI (2026-10-09), WBD (10-07), QRVO (10-05) — both providers end there too |

Single-provider symbols starting later than 2009-10 are provider floors / listing dates (e.g. LIN 2018-10-01, WTW 2016-01-05, NXPI 2010-08-06, CTVA 2019-05-24), not gaps.

### Full-span bar-basis check (SELECT-only, all 539 stored symbols, no exclusions filtered)

| | 2026-10-09 | 2026-10-15 |
|---|---:|---:|
| Bars | 1,913,857 | 2,129,876 |
| OHLC range violations | 4 (all BCB) | 4 (all BCB) |
| Symbols flagged by `stale_reasons` | 50 | **37** (30 jump, 4 mixed_basis, 2 batch_step, 1 both) |
| Close-to-close moves > 40% | 631 (594 BCB) | 628 (594 BCB) |
| Residual-exposed symbols | 482 | 67 |

- **CTVA** is now coherent: Tiingo applies factor 0.150 before the 2026-10-01 corporate action (adjusted 11.65 → 12.57); no jump or stale flag.
- **DOC** is no longer flagged.
- The 34 non-BCB jumps are dated on recognisable market events (2020-03-09 oil crash: APA FANG MRO OVV OXY TRGP; COVID rebounds: AAL CZR NCLH; PCG 2019 bankruptcy; earnings/trial days: AMD NFLX VRTX ZM ENPH FSLR ILMN BLDR SMCI). They appear now because the span is 17 years, not because of the rebuild.
- `mixed_basis`: ANSS, EA, EQR, K, FI (all refused symbols keeping an Alpaca-only series). `batch_step`: MAA, MU.

## Open after this run

- Observe the 2026-10-16 02:00 nightly run: `single_provider_updated > 0`, no seam refusal for rebuilt symbols (plan acceptance 2, live half).
- Exclusion-list decisions (Kenneth): proposal posted on #114.
- Follow-up candidates: dot-class ticker mapping for BF.B / BRK.B; renamed/delisted universe tickers (FBHS→FBIN, PKI→RVTY, AXL, MMC, FI).
