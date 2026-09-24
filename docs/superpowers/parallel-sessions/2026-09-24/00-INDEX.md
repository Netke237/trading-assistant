# Open topics and parallel-session plan (2026-09-24)

Written against `origin/main` at `22c49425` (A4b merge). The sources are `PROJECT_STATE.json` (`open_questions`, `pending_kenneth`, `phases`, `already_shipped`) and the 2026-09-24 handoff.
The indices `oq N` point into `open_questions` **at 22c49425**. That list takes new entries, so search for the quoted phrase rather than trusting the index.

> The "groups B–E of the earlier 22-item list" from the handoff are **not recorded anywhere in the repo**. That list lived in a chat. The inventory below is rebuilt from the state file. If an item from that list is missing here, paste the list and it gets mapped in.

---

## 1. Every open topic

### Ready to launch (with a decision from Kenneth first, where marked)

| Lane | Topic | Source | Kind | Kenneth decision needed? |
|---|---|---|---|---|
| **P1** | **A5**: the Analysis page ignores every Step-3 override, the regime gate included. Also: /analysis has no `direction_conviction` gate flag, and it fetches 80 days of 15-min bars where the scans fetch 55 | oq 80, oq 76(a), oq 110 | wrong verdict on screen | **Yes**: is Analysis a *mirror of the scan* or a *defaults view*? |
| **P2** | The user-built intraday alert models still read the forming bar: composite watches `HMM_intraday`, chart composite alerts, `/api/regime/intraday-series`, `require_choppy_regime`, `alert_evaluator.build_regime_snapshot` | oq 108 | alerts fire on a bar that isn't finished | **Yes**: do it at all, and for which models? |
| **P3** | Auto-trade gates and records. **A6**: should the daily-loss gate use the full premium or the declared stop? **A7a**: should the `not_submitted` row carry `regime_gate`? **A7b**: the same broken config gives 500 on scan but 400 on fire. **A7c**: formally close "refuse `min_mult` > 1". Plus: `_apply_vol_sizing` has no catch-all; `cap_blocked`/`daily_loss_blocked` rows have no `error`; check oq 4 is superseded by O4 booking | oq 55, 78, 25, 26, 2, 5, 4 | money (A6), audit trail | **Yes**: A6, A7a, A7b, A7c |
| **P4** | **A8**: the older trade-card questions. The Step-7 context rail shows the *auto-picked* contract after a Step-6 pick (gate-level, needs no decision). The card says "Time stop 18d" but the alert fires at 3 DTE. The stale mid headline. Basket notices vanish. Current price = 0. Global premium stop selectable at 100%. The editors' 10–99% band isn't enforced server-side. Max fill / time stop have no consumer | oq 64, 59, 60, 61, 56, 57, 62, 58 | wrong numbers on the card | **Yes**, per item (64 needs none) |
| **P5** | The bearish `pullback_ema` backtest crashes on a negative target price (WMT, CPRT, TSCO, SRE, LYB). The hypothesis is split-unadjusted history, which would also inflate **bullish** targets silently. Also: the direction banner blames market structure when the gate barely acted | oq 77 | possibly wrong data under every backtest | No (investigate first; a data fix may need one) |
| **P6** | **Screener pinning pass**: the screener layout/tooltip piece has run 7 rounds with none clean, past the cap. The answer on record is a *build* task (tests that pin the behaviour), not an 8th round | `already_shipped` "Screener layout + the tooltip…", active_phase_note | test coverage | No |
| **P7** | Backend hygiene, file-disjoint. `alert_dedup.json` is written without temp+rename, and `forget_alerts` swallows save failures. `PositionCreate.qty` has no `ge=1`, so it can persist qty 0 or negative. The `config_loader` YAML hardening: dotted-key path forgery, anchor holder, self-referential anchor, two untested guards | oq 3, 12, 69, 34–37, pending_kenneth[11] | corrupt persisted data (69, 3) | Light: pending_kenneth[11] asks whether to spend a round on config_loader. The recommendation is yes, the dotted-key one-liner |

### Must run AFTER other lanes (they share hot files)

| # | Topic | Source | Runs after |
|---|---|---|---|
| S1 | Direction-conviction gate: it can't tell *measured mediocre* from *unmeasured* (a data outage reads as "no conviction"), and the threshold is invisible (no config endpoint or store) | oq 75, 76(b) | P1 and P5 (stock_scan.py, stock_scorer.py) |
| S2 | YAML-CONFIG Document C, rewritten from scratch (validation, staleness, surface). Document B (atomic writes) was partly shipped on 2026-09-17, so re-scope what is left first | phase `YAML-CONFIG-INTEGRITY` | P7 (config_loader.py) |
| S3 | Below-gate debt sweep: stale comments and test gaps logged by every round (oq 0, 1, 11, 13, 50–53, 63, 67, 71, 83–107, 109). Per `audit_rule` these are logged, not fixed in-branch; take them as one deliberate cleanup, or leave them | many | **all lanes merged**: it touches every hot file |
| S4 | `scripts/state.py` / bookkeeping items (oq 8 — check whether it's stale now, 9, 15, 29–33) | many | all lanes merged: it's the tool every lane runs |

### Kenneth only (not a session)

| # | Item |
|---|---|
| K1 | Delete the fully merged remote branches from the GitHub UI (the agent gets a 403). Candidates: `claude/auto-trader-direction-sizing-2026-09-18`, `claude/guard-i-snapshot-decision-m50w6u`, `claude/session-recovery-version-o2vklp`, `claude/session-retrieval-continuation-vf056m`. Keep `archive/vf056m-round3-7753b743` (a deliberate archive). Check each is contained in main first: `git branch -r --merged origin/main`. |
| K2 | Keep collecting the **bearish scans** during US hours before moving the 30/40 direction floors (pending_kenneth[7], [8]; so far one day in one regime). A session can run these, read-only, during market hours. |
| K4 | `SCAN-FAILURE-REASON` (already_shipped, 5 rounds, never clean, past the cap) needs Kenneth's word before any sixth round: close it as-is, or give it a pinning pass like P6. |
| K3 | Measure the Phase A seeded thresholds (`iv_rank_pass_max/caution_max` percentiles, `ivAbsThreshold` 50) (oq 65, 66). This is measurement only. |

### Parked / closed

* **Heston** (oq 39–49, 72–74): Kenneth left it as it is on 2026-09-14. If it's ever picked up, the order is fit before coverage.
* **Phase G merge question** (pending_kenneth[12]): `a7545a24` **is** on main, so this can be closed in the state file.
* `stopPremiumThresholdsStore` has no reader (oq 50): fold it into S3.

---

## 2. Parallel-safety matrix

Each lane owns its files. "Soft" means the same file but a different function, so a textual merge conflict is unlikely and easy to resolve.

| | P1 | P2 | P3 | P4 | P5 | P6 | P7 |
|---|---|---|---|---|---|---|---|
| **P1** A5 | – | ✅ | ⚠️ soft `stock_scan.py` (only if A7b touches :1129) | ⚠️ soft `lib/api.ts` | ⚠️ soft `stock_scan.py` (~:1199 banner) | ✅ | ✅ |
| **P2** alert models | | – | ✅ | ✅ | ⚠️ soft `strategy_engine.py` (`require_choppy_regime` vs bearish target build) | ✅ | ✅ |
| **P3** auto-trade | | | – | ⚠️ soft only if the A6/A7 answers touch `AutoTradeArm` | ✅ | ✅ | ✅ |
| **P4** trade card | | | | – | ✅ | ⚠️ both frontend, different folders | ⚠️ soft backend if item 62 lands in `position_writer`/schemas |
| **P5** backtest | | | | | – | ✅ | ✅ |
| **P6** pinning | | | | | | – | ✅ |

**Every lane edits `docs/superpowers/PROJECT_STATE.json`.** That is the one guaranteed conflict. The protocol below keeps it trivial.

### Recommended waves

* **Wave 1, run together:** P1, P2, P3, P4, plus P6 and P7, which are safe and small.
* **Wave 2:** P5 (or run it in wave 1 and merge it after P1 and P2), then S1 and S2.
* **Last:** S3 and S4.

Merge in the order lanes come back clean, **one at a time**.

---

## 3. Shared protocol for every parallel session (each brief includes it)

1. **Start**: `python3 scripts/state.py` (expect exit 0), then `git fetch origin main` and cut your branch from `origin/main`.
2. **State file**: add **one new entry** to `phases` with your lane's unique id, e.g. `A5-ANALYSIS-OVERRIDES`. Set `active_phase` to it **on your branch**. Don't edit other lanes' entries. Serialise with `indent=2`, `ensure_ascii=False` and a trailing newline.
3. **Loop**: small plan in `docs/superpowers/plans/2026-09-2X-<lane>-plan.md`, then an adversarial round on the plan (skill `K-adversarial-audit-loop`), then build, then an adversarial round on the code. Only gate-level findings are fixed; everything else is logged to `open_questions`. **Hard cap of 3 rounds**, then stop and tell Kenneth.
4. **Merge, only when clean** (Kenneth's standing instruction), one lane at a time:
   * `git fetch origin main && git merge origin/main` into your branch.
   * Resolve `PROJECT_STATE.json` as a **union**: keep every lane's phase entries and `open_questions`. Set `active_phase` to your lane. Prepend your merge record to `main` and `active_phase_note`.
   * Re-run the backend suite (`cd backend && .venv/bin/python -m pytest -q`, ~4.5 min, timeout >300s), the frontend suite (`cd frontend && npx jest && npm run typecheck`) and `python3 scripts/state.py`.
   * `git merge --no-ff` to main and push. If the push is rejected because main moved, repeat the merge step.
5. **Baselines at 22c49425**: backend 2959 passed / 1 skipped; frontend 1811 passed / 136 suites. Report your delta as "+N = exactly my new tests".
