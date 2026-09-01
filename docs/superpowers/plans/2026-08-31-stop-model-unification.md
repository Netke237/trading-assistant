# Stop model unification — per-method stops, per-trade selection, and the gate

**Status: DO NOT BUILD AS ONE PIECE.** Two adversarial rounds: 24 findings (3 CRITICAL), then
**32** findings (4 CRITICAL). Findings went *up*, not down — see §8. Treat this document as a
**coupling inventory and a recommended split**, not a build plan.
**Branch:** `claude/tradecard-setstate-render-wo6eru`

---

## 0. Where this came from

The trade card carries **five** different stop numbers that nothing reconciles, and the one that
reaches a position record is the one nobody looks at:

| Number | CVX example | Who reads it |
|---|---|---|
| Flat −3% (`exit.invalidation`) | $195.80 | **`PortfolioPosition.stop`** → `STOP_REACHED`; the Monte Carlo Invalidation row; **and a hard submit gate** — `checkInvalidation` (`risk.ts:303`) blocks every send regardless of method, surfaced as "Invalidation stop required" (`SendToBrokerDialog:270,299`) |
| Raw structural stop | $185.87 | `STRUCTURAL_STOP_BREACHED`; **`structuralRR`'s R:R denominator** (`TradeCard/index.tsx:790-825`); the gate shipped on this branch |
| Exit-plan final stop (`max(structural, 2×ATR)`) | $185.87 | **A submit-blocking gate** — `risk.ts:359-364` feeds it to `maxLossAtStop` → `max_loss_per_trade_exceeded` → `approved = false`; also `recommendedContractSize` (position sizing, `TradeCard:922`). Round 2 caught this: the first two drafts called it "the Arithmetic card only". |
| Premium stop (`premium × 60%`) | $3.12 | **Not display-only**: the risk denominator in `computeEditedRR` (`TradeCard:83`) and `rrContribution` (`:1744`), and one of `isDirty`'s checks (`:69`). The `PREMIUM_STOP` *alert* meanwhile reads a **global** pct — and there are **three** different globals: `reward_risk.premium_stop_pct`, `auto_trade.premium_stop_pct` (`auto_trader.py:254,352`), and `settingsStore.premiumStopPct`. |
| Strategy signal stop (stocks) | — | `signal.stop_price`, stocks path only |

The Monte Carlo card computes a "62% probability of invalidation" against a level three times tighter
than the one displayed above it, and the gate this branch shipped measures a level that never reaches
a position record.

---

## 1. Decisions (settled with Kenneth)

| # | Decision |
|---|---|
| D1 | Each method **owns** a stop. Arithmetic and Monte Carlo both use structural+ATR; Ladder keeps stock ± %. Duplication is deliberate. |
| D2 | The flat −3% is **not deleted** — reassigned from "position default" to "the Ladder method's stop", where it is already YAML + Step 3 configurable. |
| D3 | Arithmetic and Monte Carlo share **one computed** structural+ATR value. |
| D4 | A stock stop **and** a premium stop exist on every method; per trade Kenneth picks which is *armed*. |
| D5 | Per trade: **method** → **one price row** → **stop basis**. Explicit, not "most recently run". |
| D6 | All three alerts stay. One armed, others advisory; the card must say which. |
| D7 | The gate always measures **structural+ATR** — *see §1.2 Q-A, this is not satisfiable for stocks as stated*. |
| D8 | The gate **warns, never blocks**. |
| D9 | Premium stop per trade is a **percentage**, dollars shown read-only. |
| D10 | Stop orders are **not** built here. **All four** paper adapters (IBKR, Tradier, Alpaca, Tastytrade) are `Literal["MKT","LMT"]`. |
| D11 | Existing open positions untouched. |
| D12 | Scope is stocks **and** options. |

### 1.1 Assumptions (my recommendations — reversible)

| # | Assumption |
|---|---|
| A1 | Gate loss = delta-linear by default; the exit plan's repriced `stop.contractPrice` when a plan exists. **Must change the verdict, not just the displayed number** — see Phase 2.3. |
| A2 | A stock's default stop stays the strategy signal's `stop_price`; Arithmetic-on-a-stock owns structural+ATR per D1. |
| A4 | Stock Monte Carlo targets are the Arithmetic R-multiples. |
| A5 | The armed stop is written to `PortfolioPosition.stop` — **conditional on Phase 6.2's re-anchor exemption**. |

### 1.2 Blocking question — D7 cannot hold for stocks

`compute_final_stop` (`exit_plan.py:45-64`) returns `max(structural_distance, atr_multiplier × ATR)`
with `atr_multiplier: 2.0` (`risk_rules.yaml:36`). So a structural+ATR stop is **≥ 2.0 ATR away by
construction, always**. The stocks gate I proposed (REJECT < 1.0 ATR, CAUTION < 1.5) can therefore
**never fire** — the exact failure mode it was invented to avoid.

**Q-A — needs Kenneth's decision before Phase 7:** either
(a) the stocks gate measures the **strategy signal's stop** (A2's default), which *can* sit inside
1 ATR and so can actually fire — this narrows D7 to options only; or
(b) thresholds are expressed **relative to `atr_multiplier`** and read from the same YAML that sets
it (REJECT < 1.0×multiplier, CAUTION < 1.5×multiplier), keeping D7 intact but making the gate a
check on whether the floor bound rather than on noise survival.

Recommend **(a)**. Do not implement Phase 7.3 until this is answered — it changes what the feature
means, and D7 is Kenneth's decision to narrow, not mine.

---

## 2. What already exists (do not rebuild)

- **`compute_final_stop`** (`exit_plan.py:33`) — pure stock-price math, **no contract input**, so it
  already serves stocks.
- **Stock Monte Carlo** — `estimate_stock_first_passage` (`first_passage.py:275`) via
  **`POST /stocks/first-passage`** (`stock_scan.py:1416`). Drops IV back-out, bisection and the BS
  loop. **Already wired in the UI**: `StockPositionCard` has a live "Estimate" button sending
  `overlay.stop` + `[t1,t2,t3]` (`:372-390`) and its own "Check structure" (`:415-430`). Phase 7.2 is
  therefore a **change to a shipped feature**, not new work.
- **A post-trade selection model** — `TpMethod = 'ladder' | 'monte_carlo' | 'exit_plan_2r' |
  'exit_plan_3r'` (`domain.ts:658`), `activeTpMethod` / `resolvedTpPrice` / `resolvedTpUpdatedAt`
  (`:302-311`), persisted as the `active_tp_method` column (`models/portfolio.py:32`), read by
  `alertEngine.ts:152-166`, edited in `portfolio/EditDrawer.tsx:828-843`. See §3.
- **Ladder stop %** — `bullish_invalidation_pct` / `bearish_invalidation_pct` under `reward_risk:`
  in `risk_rules.yaml:24-25`; exposed per-run in Step 3 as "Bullish/Bearish stop %" via the
  `rr_`-prefixed **override** keys (`config_loader.py:56-57`, `step-3-direction/page.tsx:304,306`).
- **Gate thresholds** — per-horizon `scoring_rules.yaml → horizons.<key>.stop_premium`, served by
  `/api/config/stop-premium-thresholds`, consumed via `stopPremiumThresholdsStore`. Shipped.

---

## 3. Reconciling with the shipped `activeTpMethod`

`activeTpMethod` is a **post-trade, persisted, captured-price** selection of a take-profit method on
an open position. The new selection is a **pre-trade, per-candidate** choice of method + price row +
stop basis. They are different objects, but they must not contradict each other.

**Decision:** the pre-trade selection is new state; at send time it **populates** the existing
fields rather than sitting beside them:

| Pre-trade selection | Written to |
|---|---|
| `method: 'arithmetic'` + `{kind:'rr', rrRatio: 2}` | `activeTpMethod = 'exit_plan_2r'` |
| `method: 'arithmetic'` + `{kind:'rr', rrRatio: 3}` | `activeTpMethod = 'exit_plan_3r'` |
| `method: 'monte_carlo'` | `activeTpMethod = 'monte_carlo'` |
| `method: 'ladder'` | `activeTpMethod = 'ladder'` |

`resolvedTpPrice` receives the chosen row's price at send time — **except for `ladder`**, which
deliberately stamps `null` so the ladder keeps tracking its target live (`EditDrawer.tsx:827-844`,
`domain.ts:303-308`; `alertEngine.ts:158-160` resolves `snapshotPrice ?? ladderPrice`, so a stamped
ladder price would silently convert TP_HIT from live-tracking to a frozen snapshot). Round 2 caught
the first draft contradicting this shipped rule.

**This mapping is not currently implementable, and that is the largest single blocker in this
document.** `PortfolioPositionCreate` (`schemas/__init__.py:622-628`) carries `stop`,
`structuralStop`, `exitPlan`, `maxLossOverride`, `scanStockPrice`, `tradeCardSnapshot` — and **no**
`activeTpMethod` / `resolvedTpPrice` / `resolvedTpUpdatedAt`. Those exist only on the PATCH-side
`PortfolioPositionUpdate`. `toBackendPayload` omits them too, and there is a comment in that file
documenting this precise failure mode for `maxLossOverride`: the optimistic local value looks right,
the backend stores the default, the next sync silently overwrites it. Writing the mapping above
without schema work produces `active_tp_method='ladder'`, `resolved_tp_price=NULL` on every send.

The full thread for **any** new field on the create path — this one, Phase 4's `premium_stop_pct`,
Phase 6.2's `stopBasisKind` — is: `PortfolioPositionCreate` + its alias dict → the router's
`PortfolioPositionModel(...)` construction → `portfolioStore.toBackendPayload` → (for display)
`PortfolioPositionSchema` / `from_orm_model`. Four touchpoints each, none of which the earlier drafts
listed.

---

## 4. Phases

Reordered from the first draft: **every consumer of the stop moves in one phase**, because moving
them piecemeal leaves three different stop levels on one card — worse than the two we started with.

### Phase 1 — one shared structural+ATR stop, available before any click

1. **Backend, at scan time.** Call `compute_final_stop` per **symbol** (the level is symbol-scoped,
   not contract-scoped — candles + direction + entry + ATR) and attach `exit.finalStop`:
   `{ price, source, structuralPrice, structuralSource, atrFloorPrice, distanceDollar, atr, computedAt }`.
   - `structuralSource` and `distanceDollar` are **required**, not optional: the "Bottom (final stop)"
     row renders `structuralStopSourceLabel(...)` and `stopJustification(...)`, which read both
     (`TradeCard/index.tsx:167-176, 1298-1345`).
   - `stop.contractPrice` legitimately **cannot** exist at scan time (it needs a contract). The
     row's contract-priced sub-cells and `recommendedSize` degrade to `—` until a plan is computed;
     specify that rendering explicitly.
   - **Wrap in `asyncio.to_thread`.** `find_structural_stop` → `detect_bos_choch` /
     `detect_order_blocks` / `find_swings` is synchronous CPU work, and `scan.py` already offloads
     every comparable computation (`:541`, `:621-624`). Inline, it stalls the whole concurrent fan-out.
   - **The cost worry from the first draft was wrong** and the "top-N candidates" fallback is
     dropped: the scan already runs a vectorised backtest and an HMM fit per surviving candidate;
     three linear passes over the same candles is noise beside that, and ranking happens *after*
     scoring so a top-N gate doesn't map onto the pipeline anyway.
2. **Survive a Step 6 contract override.** `mergePlan` (`tradeCardOverride.ts:60`) does
   `exit: plan.exit` — a wholesale replacement — and `/contracts/recompute-plan`'s `TradeExit`
   (`schemas/__init__.py:420-426`) has no `finalStop`, so it would be **wiped for exactly the cards
   the user hand-picked a contract for**. Add `finalStop` to `TradeExit` and echo it back (it is
   contract-independent), **and** splice it in `withCachedEstimate` alongside the other three
   restores as defence in depth.
3. **Persisted-store migration.** `scanStore` persists `scanResult` at `version: 12`
   (`scanStore.ts:311-322, 362-363`). Adding `exit.finalStop` changes the persisted shape → bump to
   **13** with an explicit migration branch, per CLAUDE.md. Restored pre-13 sessions have no
   `finalStop`: render "not computed — re-run the scan", never a blank or a silent PASS.
4. **One memo, both cards.** `sharedFinalStop` = the exit plan's stop when one exists for this
   contract, else `data.exit.finalStop`. Labelled *"Structural + ATR stop — the same level both
   methods use."*

### Phase 2 — move every stop consumer together

All four in one change, so the card is never showing three levels at once.

1. **Monte Carlo `invalidation_price`** ← `sharedFinalStop.price` instead of `exit.invalidation`.
   The Invalidation probability will **drop**, often a lot. That is the correction.
2. **The gate** ← `sharedFinalStop` instead of the raw structural stop.
3. **`structuralRR`** ← `sharedFinalStop` (`TradeCard/index.tsx:790-825`). Round 1 caught this as a
   *fifth* stop the first draft left behind: it computes its R:R denominator off the **raw**
   structural level. It asks the same "what does the stop cost" question as the gate and must use
   the same level.
4. **Freshness.** `sharedFinalStop` flips value the moment a plan is computed (the plan refetches
   candles and uses the card's **live** `entry_price`, `contracts.py:502-535`), silently
   invalidating an already-rendered Monte Carlo probability. Stamp the stop each estimate ran
   against into `FirstPassageEstimate`, and relabel the row when it no longer matches — reusing the
   `structuralIsFreshRef` / `firstPassageIsFreshRef` discipline already in the file (`:790-825`).
5. **Ranking-table badge (D8).** Needs data `WatchlistRow` does not carry — it has no `exit`, no
   `contractDetails` (`domain.ts:133-149`). Add `stopCostPct` + `stopCostStatus` to `WatchlistRow`,
   populated in `cardToRow`; add one grid track to `COLUMNS` (`step-4-ranking/page.tsx:38`) and to
   `TableRow`, verified against the 1200px min-width gate. State on the badge that it describes the
   **auto-picked** contract, since a Step 6 override can later change it.

### Phase 3 — per-trade selection

Page-level state, **keyed by contract** for `monte_carlo` and for `stopBasis`, **by symbol** for
`ladder` — matching the existing split (`estimatesByContract` / `exitPlanByContract` are per
contract for exactly this reason; `maxLossOverrideBySymbol` is per symbol because it is a symbol-level
risk decision).

```ts
type PriceRef =
  | { kind: 'rr';           rrRatio: number }   // 2.0 | 3.0
  | { kind: 'target';       pct: number }       // options MC — keyed by pct
  | { kind: 'stock_target'; price: number }     // stock MC — StockFirstPassageTarget has price, NO pct
  | { kind: 'rung';         index: number };

interface TradeSelection { method: 'arithmetic'|'monte_carlo'|'ladder'; priceRef: PriceRef;
                           stopBasis: 'stock'|'premium'; selectedAt: string; }
```

- The `stock_target` variant exists because `StockFirstPassageTarget` (`stockDomain.ts:59-69`) is
  keyed by `price` with **no `pct` field** — the options variant cannot address a stock MC row.
- **Clear-vs-keep, all four paths** (the first draft specified only re-run):
  | Event | Behaviour |
  |---|---|
  | Method re-run, row still present | Keep |
  | Method re-run, row gone | Clear + say so |
  | Re-estimate **fails** (state → `null`, `TradeCard:730-740`) | Keep the selection, mark it stale — a failed fetch must not disarm a decision |
  | Contract switch | Clear the contract-keyed parts; keep a `ladder` selection |
  | Restore from cache | Keep, marked "as of `selectedAt`" |
- `lastRunMethod` stays the read-only Final Recommendation summary, explicitly **not** the selection.

### Phase 4 — per-position premium stop (schema first)

**This must land before Phase 5's UI**, or the percentage is editable and labelled "armed" while
nothing downstream reads it.

There is **no per-position premium stop anywhere** — not on `PortfolioPosition` (`domain.ts:265-345`),
not on the ORM model. `alertEngine.ts:100-101` and `alert_generator.py:26-27,295` both read the
**global** pct. So:

1. `premium_stop_pct` column on the portfolio model + **Alembic migration** (follow
   `bbb04a057515_add_exit_plan_pipeline_columns_to_.py`, which added `active_tp_method`).
2. Thread through `portfolioStore.toBackendPayload`, `alertEngine.scanPortfolio`, and
   `alert_generator._premium_stop_pct` → per-position with the global as fallback.
3. `portfolio/EditDrawer.tsx:896-922`'s `alertFiresAgainst` renders the threshold from the global
   pct — update it, or it displays a false level for any position with an override.
4. **`auto_trader.py:254,352`** sizes risk off the global `premium_stop_pct`. Either thread the
   per-position value through or state in §6 that auto-trade deliberately ignores it.

### Phase 5 — premium stop becomes a percentage (D9)

1. `overlay.premiumStop` (dollars) → `overlay.premiumStopPct`, dollars rendered read-only alongside.
2. **`overlay.premiumStop` is not display-only** — it is the risk denominator in `computeEditedRR`
   (`TradeCard/index.tsx:83`) and in the sell-to-close ladder rows (`:1538` → `:1744`
   `rrContribution(estOptionPrice, entryLimit, premiumStop)`), and one of the seven equality checks
   in `isDirty` (`:69`). **Every one of those must be updated in the same change** or both R:R
   figures silently divide by a fraction instead of a dollar.
3. **Seed from one source, not two.** The first draft said `settingsStore.premiumStopPct` in one
   place and "derive from `exit.premiumStop`" in another; those can disagree (the backend value is
   per-run overridable, the client one is not). Use **`exit.premiumStop ÷ premium`** — it is the
   value the card was actually built with.
4. **Honest scope note:** the backend dollar field is *already* contract-aware — a Step 6 override
   recomputes it (`trade_plan.py:117`, asserted by `tradeCardOverride.test.ts:140-141`). The stale-
   dollar problem this phase fixes applies **only to a user's manual overlay edit**, which is
   narrower than the first draft claimed.

### Phase 6 — alerts follow the armed stop

1. `PortfolioPosition.stop` ← the armed stock stop (A5), at **both** send paths.
2. **The re-anchor exemption (CRITICAL).** `portfolio.py:198-213` does
   `adjusted_stop = round(adjusted_stop + (live_price − scanStockPrice), 2)`, and does the same to
   `adjusted_structural_stop`. Parallel-shifting is defensible for a *percentage-of-scan-price*
   level; it is wrong for a structural/ATR stop, which is an **absolute price on the chart** (an
   order-block or swing low, `structural_stop.py:52-70`). Add a `stopBasisKind` to the create payload
   and skip re-anchoring when it is structural/ATR.
   - The two send paths already disagree: `buildPaperPosition` sets `scanStockPrice: card.price`
     (`step-7-trade-card/page.tsx:637`) so it re-anchors; `positionFromOrder` (`:87-113`) never sets
     it, so the basket path does not. **Same armed stop, two persisted values depending on which
     button was pressed.** Fix both.
3. **The no-selection fallback is the common path, and D2 is only partially delivered.** The basket
   loop (`:733-739`) builds positions for every pinned symbol including ones never opened, and step
   navigation unmounts the page, dropping component-state caches. Those still get
   `exit.invalidation` — the flat 3%. Blocking the send would contradict D8, so instead: the send
   dialog shows **"no stop selected — using the default −3%"** per affected row. §6 records that D2
   is partial.
4. **Retract the now-false on-card copy.** `TradeCard/index.tsx:1596-1599` says the stop "is not
   automatically monitored by alerts unless copied into the position's stop field" — untrue once
   this phase lands.
5. Add the D10 notice: *"Alerts only — no stop order is placed at the broker."*

### Phase 7 — stocks

**Do not start 7.3 until Q-A (§1.2) is answered.**

1. **Arithmetic for stocks needs a backend endpoint.** `compute_final_stop`, `compute_target_row`,
   `find_structural_target` and the candle fetch are all backend, and the only endpoint exposing
   them — `/contracts/exit-plan` — requires `strike > 0`, `dte`, `premium > 0` (`contracts.py:433-440`),
   none of which a stock has. Add **`POST /stocks/exit-plan`** (or an option-less mode). The first
   draft's "no new backend" claim covered only 7.2 and must not be read as covering this.
2. **Stock Monte Carlo is a change, not an addition.** `StockPositionCard` already sends
   `overlay.stop` + `[t1,t2,t3]` to `/stocks/first-passage`. A4 replaces those targets with the
   R-multiples. Account for: the endpoint returns `modelCaveat` and `horizonDays`
   (`stock_scan.py:1393-1414`), and **422s** on any target on the wrong side of `stock_price`
   (`:1428-1440`) — a 1R target that lands wrong-side is a hard error, not a blank row, so validate
   client-side first.
3. **The stocks gate** — blocked on Q-A. Whichever resolution: serve thresholds from a **sibling**
   endpoint, not by extending `/api/config/stop-premium-thresholds` — that returns a flat
   `{reject_fraction, caution_fraction}` per horizon and adding a nested block breaks its type and
   the Step 3 override layer. Also note the **polarity inversion**: `stopPremiumRisk` sanitises with
   `caution_fraction <= rejectAt` (`risk.ts:83-89`) because its metric is lower-is-better; an ATR
   gate is higher-is-better, so routing it through that helper would silently discard the caution
   threshold. It needs its own helper.
4. **Seven creation sites.** `buildPaperStockPosition` is called from `ChartWorkspace:851`,
   `StockPositionCard:329,467`, `StockSendDialog:124,155,175`, `step-7-position-card:136`,
   `step-4-stocks:196`. Any that must carry an armed stop needs the change; `stockPositionLevels`
   (`paperTrade.ts:36-70`) also drops a stop on the wrong side of entry and rounds to cents.
5. Selection for stocks: same shape, `stopBasis` fixed to `'stock'` (no premium). Hide, don't disable.

---

## 5. Tests

Pure helpers carry most of the weight.

- `sharedFinalStop` resolution: plan → plan's stop; no plan → scan's; neither → null; **pre-v13
  restored scan → "not computed"**.
- **Gate basis (A1) drives the verdict, not just the number** — a contract where delta-linear says
  CAUTION and repriced says REJECT must render REJECT, and `formatStopPremiumRisk` must not emit
  `"$X away × Δd = $Y"` when `Y` no longer equals `X × d`. Round 1's finding: a `lossOverride` that
  only touches `loss`/`fraction` leaves `capped` (and so the status) on the delta basis, making the
  "(repriced)" label a lie.
- All four `TradeSelection` transition paths (re-run/keep, re-run/clear, **failure/keep-stale**,
  contract-switch/partial-clear).
- The three stop consumers (MC request, gate, `structuralRR`) all read the **same** value — the
  anti-regression for someone later re-pointing one of them.
- `mergePlan` on a Step 6 override **preserves** `exit.finalStop`.
- Re-anchor exemption: a structural-basis stop survives `live_price ≠ scanStockPrice` unchanged,
  **via both send paths**.
- Per-position `premium_stop_pct` reaches `alertEngine` and `alert_generator`; absent → global.
- Premium %→$ conversion, plus `computeEditedRR` and `rrContribution` unchanged in value after the
  units change.
- Stocks: 422 avoidance on wrong-side targets; the gate fires at all (the Q-A regression).

`npm run typecheck` clean + full Jest suite green before every commit; `pytest` for backend.

---

## 6. Risks and what stays broken

Round 1 judged the first draft's risk list "selectively honest". Full inventory:

- **Q-A unresolved** blocks Phase 7.3 (§1.2).
- **D2 is only partially delivered** — un-selected sends still carry the flat 3% (Phase 6.3).
- **Nothing protective reaches a broker** (D10). After all seven phases you have alerts, not stops.
- **`auto_trader.py` sizes off the global premium pct** and will ignore a per-trade value unless
  Phase 4.4 threads it.
- **The three alerts still fire in any order**; the tightest still trips first (D6).
- **`stop.contractPrice` reprices at half time-to-expiry** (`reward_risk.py:82`) — why a 109-DTE
  contract shows a ~94% loss. Inherited, uncorrected.
- **`structuralStop` is already re-anchored today** (`portfolio.py:213`) — a pre-existing bug this
  plan fixes only incidentally, for new positions.
- **Step 4 and Step 7 badges can disagree** for one symbol after a Step 6 override (Phase 2.5).
- **Existing positions keep the flat 3%** (D11).

## 7. Out of scope

Stop/bracket order support; rewriting existing positions; joint "target before stop" simulation;
correcting `dte_at_target`; consolidating the three alert types.

---

## 8. Why this document says DO NOT BUILD AS ONE PIECE

| Round | Findings | CRITICAL |
|---|---|---|
| 1 | 24 | 3 |
| 2 | **32** | **4** |

Findings went **up** after a full rewrite that fixed every round-1 item. That is not a document
quality problem — it is a signal about scope. Both rounds failed the same way: the plan asserted
things about the codebase that were false, and missed consumers of the values it proposed to move.
Round 2 found consumers round 1 never reached (`checkTradeRisk`'s submit gate, `checkInvalidation`,
the three separate global premium percentages, eight position-creation sites), and there is no
reason to believe a round 3 would not find more.

**Root cause:** the blast radius exceeds what any single review can enumerate. The plan touches the
scan pipeline, two screener modes, five stop levels, three alert paths, two submit-blocking gates,
a DB migration, and eight position-creation call sites. Every value it moves is read by consumers
that are only discoverable by grepping for them one at a time.

**Recommendation: split into independently shippable pieces, and audit each one separately.** In
rough dependency order, smallest first:

1. **Monte Carlo stops simulating the flat −3%** (Phase 2.1 alone). One field on one request. Fixes
   the worst factual wrongness on the card — a probability computed against a stop three times
   tighter than the one displayed. No new state, no schema, no migration.
2. **`structuralRR` and the gate read the same stop as each other** (Phase 2.2 + 2.3). Frontend-only,
   no new consumers.
3. **Scan-time `finalStop`** (Phase 1). Backend + persisted-shape + `mergePlan` survival. Ships the
   ranking-table badge.
4. **Per-position `premium_stop_pct`** (Phase 4). Schema + migration + three alert paths. Independent
   of everything above.
5. **The per-trade selection** (Phase 3 + 5 + 6). The largest piece and the one with the most
   unknowns — it needs the create-schema work in §3, a TradeCard→page channel that does not exist
   today (only `contracts` crosses that boundary), and persistence, because component state dies on
   step navigation and would silently disarm the choice.
6. **Stocks** (Phase 7). Blocked on Q-A regardless.

Pieces 1 and 2 are worth doing now and are small enough to review properly. Piece 5 should not be
attempted until 1–4 have shipped and the coupling around the send path is understood from having
touched it, rather than from greps.
