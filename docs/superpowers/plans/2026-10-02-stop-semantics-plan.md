# STOP-SEMANTICS — build plan (v2)

Decision: `STOP-SEMANTICS-2026-10-02` (PROJECT_STATE.json). Task: `task_backlog` STOP-SEMANTICS.
Two behaviour changes, one branch, one plan:

- **(a)** A SHORT stock position's percent stop fires when the price RISES X% above entry.
- **(b)** A premium stop whose threshold is below $0.01 is REFUSED when saved.

Part (c) of the decision (COMPOSITE-WATCH-KEYERROR) is closed, so no code.

**v2 changes (plan round 1: 3 blocking / 8 should-fix / 4 nits).** Sub-cent is now defined as exactly the
engines' comparison, with no epsilon (R1-1/2). F2 is computed through the predicate (R1-3). The backend
gets the `> 0` quote guard (R1-4). The short flag is passed at every site (R1-5). The short reason is
price-only (R1-6). The label site with no position is covered (R1-7). "Never fires" copy is gated for
shorts (R1-8). The ledger deviation is stated (R1-9). F3 is re-described and warns (R1-10). Real test
files (R1-11). Nits R1-12..15 are folded in.

---

## 0. Ground truth (read on main fa354b5; re-verified by plan round 1)

### The percent stop is one mechanism for options and stocks

`PREMIUM_STOP` fires on `price <= entry * (1 - pct)` in BOTH engines:

- frontend `lib/alertEngine.ts` `scanPortfolio` PREMIUM_STOP block (L275-311). The guard is
  `p.entryPrice > 0 && p.currentPrice > 0`. There is no `isStock` / `isBearish` term.
- backend `services/alert_generator.py` PREMIUM_STOP block (L306-357). The guard is
  `opt_price is not None and pos.entry_price > 0`. **No `> 0` on the quote.** `data/market.py:866` can
  produce `mid = round(last, 2) = 0.0` for a sub-half-cent last, and that 0 fires a long position's stop
  (`0 <= threshold`). For a `|STOCK` contract, `opt_price` is the stock quote.

A **Bearish `|STOCK` position is a short**: every stock send path maps `Bearish → SELL` to open
(`StockPositionCard:611`, `StockSendDialog:178`, `step-7-position-card:156`). A Bearish OPTION is a long
put, whose premium falls on a loss like a call's. **So (a) applies to `|STOCK` + Bearish only.**

`pnlPct` is **not** direction-aware. `routers/portfolio.py:131-133` computes `(current - entry)/entry*100`,
and `pnlDollar` follows the same rule. `portfolioStore.ts:102` passes it through, and `EditDrawer.tsx:459`
uses the same formula. A short that rose 12% reads +12%. That is a separate defect, logged as a follow-up
(§7) and not fixed here.

Preview and label sites that state the threshold or the alert type:
- `EditDrawer.tsx` `alertFiresAgainst('PREMIUM_STOP')` → `premiumStopFiringPrice(entry, pct)`.
- `EditDrawer.tsx` premium-stop field label (stocks: `Stock stop — fires X below entry`, P2-13).
- `EditDrawer.tsx:1111` `globalNeverFires`, `:1112` `subCent`, and their caution copy (`:1367-1377`).
- `settings/page.tsx:103-123` stored-≥100% note and the "entry below $X puts the stop below a cent / fires
  only on a sub-penny quote" hint.
- `alerts/page.tsx` `alertTypeLabel` — called by `AlertRow` (has the toast and the looked-up position) AND
  by the Alert-types toggle list (`:470`, type + global only, no position). `ToastItem.direction` and
  `contract` are optional (`types/domain.ts:1064-1065`), so older persisted toasts lack them.
- `services/notifications/alert_notifier.py:165` `'PREMIUM_STOP': 'Premium stop hit'` (Gmail/Telegram).
- Reasons: backend `Premium stop — SYM stock|option at $P`; frontend `Premium stop — SYM down N%`.

### Where a per-position premium stop is SAVED (scope of (b))

| # | Path | Writes | Entry at save |
|---|---|---|---|
| S1 | `PATCH /api/portfolio/{rec_id}` `premiumStopPct` (`routers/portfolio.py` `update_position`) | fraction | `position.entry_price` (not PATCHable) |
| S2 | `POST /api/portfolio` → `position_writer.create_position`, ratio = `premiumStopDollar / persisted entry` (L507-538). **Also the auto-trade booking**: AutoTradeArm sends both `premium_stop_pct` and `premiumStopDollar` (`AutoTradeArm:366,396`), and `auto_trade_booking.py:199,205` forwards both, so the dollar branch wins | fraction | the persisted entry (may be the live quote / fill) |
| S3 | same, a client `premiumStopPct` with no dollar, or the fallback when the dollar is unusable (L538) | fraction | same |
| F1 | Portfolio `EditDrawer` premium-stop `commit` (frontend refusal before S1) | fraction | yes |
| F2 | TradeCard dollar field, bounded by `premiumStopDollarBounds(mid)` | dollar → S2 | the mid only |
| F3 | AutoTradeArm, `premiumStopAtOrAbovePremium` sibling (`:238,554`, a **warning**, not a disable, because the fill can differ) | dollar + fraction → S2 | the entry-premium estimate |
| G | Settings global `premiumStopPct` (`routers/risk_settings.py`, `ge=0.10 le=0.99`) | fraction | **none** |

The create path already handles a stop it cannot store. A ratio `>= 1` → WARNING log, fall back to
`body.premiumStopPct` (usually None → inherit the global). The client detects
`premiumStopDollar != null && response.premiumStopPct == null` (`portfolioStore.ts:519-521`, `:1068-1074`)
and queues the Portfolio banner (`portfolio/page.tsx:211-217`, `premiumStopDropQueue`). (b) at S2/S3 reuses
that signal.

---

## 1. Definitions (one rule, both languages)

```
isShortStock(contract, dir)        = contract ends with '|STOCK' and dir == 'Bearish'
threshold(entry, pct, short)       = short ? entry * (1 + pct) : entry * (1 - pct)
fires(price, threshold, short)     = price > 0 and (short ? price >= threshold : price <= threshold)
isSubCent(entry, pct, short)       = not short and entry > 0 and not (0.01 <= entry * (1 - pct))
```

**Sub-cent is the engines' own comparison, with no epsilon (R1-1).** A long stop is sub-cent exactly when the
lowest live quote, $0.01, does not satisfy `0.01 <= threshold`. Both engines (after §2.1's `> 0` backend
guard) treat a 0 quote as no quote, so a sub-cent stop fires never. The predicate cannot disagree with the
engine because it IS the engine's test at price $0.01, written identically in TS and Python. `entry *
(1 - pct)` is one IEEE multiply in both languages, so they agree bit-for-bit. A shared fixture pins that
anyway (§4).

**The float-noise family (R1-2), decided here and put to Kenneth as Q4.** A dollar stop of exactly
`entry − $0.01` derives `ratio = d/e`, and `e*(1-ratio)` lands a few ulps below 0.01 for 2,878 of 4,999 mids
from $0.02 to $50.00 (e.g. $0.02 on $0.03). **Those stops already never fire today**: the engines compare
`0.01 <= 0.009999999999999998`, which is false. v2 classifies them as sub-cent, because that is what they
are under the engines as they stand. The editors therefore never offer them (F2 below), and the server
drops them (S2). The alternative is a tolerance in both engines' comparisons, so that an intended $0.01
threshold fires. That would change the boundary of every premium stop and of `premiumStopFiringPrice`'s
pinned sweep. It is out of this task's scope unless Kenneth chooses it (Q4).

New twin helpers, beside the existing ones:
- TS `lib/premiumStop.ts`: `isShortStockPosition(contract, direction)`,
  `percentStopThresholdPrice(entry, pct, shortStock)` (delegates to `premiumStopThresholdPrice` for the long
  side), `percentStopFiringPrice(entry, pct, shortStock)` (long: the existing `premiumStopFiringPrice`; short:
  the SMALLEST 2dp price `>=` threshold: `cents = round(t*100); if (cents/100 < t) cents += 1`), and
  `premiumStopIsSubCent(entry, pct, shortStock)` (the predicate above, literally).
- Python `services/premium_stop.py`: `is_short_stock_position`, `percent_stop_threshold_price`,
  `premium_stop_is_sub_cent` with the same signatures. **The short flag is a required positional
  argument in both** (no default), so no call site can apply the long rule to a short (R1-5).

The existing `premiumStopFiringPrice <= 0` test (the drawer's `subCent`) is NOT the same predicate at the
float edge. It is replaced by `premiumStopIsSubCent` everywhere.

---

## 2. (a) Direction-aware percent stop for a short stock

### 2.1 Engines

- `alertEngine.ts` PREMIUM_STOP: `shortStock = isStock && isBearish`;
  `threshold = percentStopThresholdPrice(entry, pct, shortStock)`;
  `hit = entry > 0 && currentPrice > 0 && (shortStock ? currentPrice >= threshold : currentPrice <= threshold)`.
  `referenceValue: pythonRound4(threshold)`. Reason: a short reads `Stock stop — SYM at $P` (price-only,
  because `pnlPct` is not direction-aware, §0). Long stock and options keep `Premium stop — SYM down N%`.
- `alert_generator.py` PREMIUM_STOP: the same threshold and side, via `percent_stop_threshold_price`.
  **Add `opt_price > 0`** to the guard (R1-4). This brings parity with the frontend `currentPrice > 0` and
  makes "a sub-cent stop can never fire" true in both engines. Behaviour change: a long position whose quote
  rounds to $0.00 no longer fires PREMIUM_STOP. The frontend already behaves this way. `reference_value`
  and `thresholdPct` in the event log use the direction-aware threshold. Reason text unchanged (price-only).
- `_sustained` / `_muted` unchanged.

### 2.2 Labels, previews, "never fires" copy

- `EditDrawer` field label: long stock `Stock stop — fires X below entry`, short stock
  `Stock stop — fires X above entry`, options unchanged. Delete the Q-P2-1 comment.
- `alertFiresAgainst('PREMIUM_STOP')`: `stock $` + `percentStopFiringPrice(entry, pct, shortStock)`.
- `globalNeverFires` (`EditDrawer.tsx:1111`): `&& !shortStock`. A short at ≥100% fires at ≥2× entry (R1-8).
- `settings/page.tsx:103-123`: the "Stored 100% can never fire" note and the sub-cent hint say "for long
  positions and options". The "fires only on a sub-penny quote" clause becomes "can never fire", which is
  now true in both engines (§2.1).
- `alerts/page.tsx` `alertTypeLabel(type, pct, side?)`. `side` is `'short-stock' | 'long-stock' | 'option'`.
  It gives `Stock stop (+X%)`, `Stock stop (–X%)` and `Premium stop (–X%)` respectively. `AlertRow`
  derives `side` from the toast's `contract`/`direction`, falling back to the looked-up `position` when the
  toast lacks them, and to `option` wording if neither is known. The toggle list (`:470`) passes no side and
  reads `Premium / stock stop (±X%)` (R1-7).
- `alert_notifier.py:165`: the PREMIUM_STOP label becomes stock- and side-aware, using the alert's
  `contract`/`direction`, with the same three wordings (R1-13).

### 2.3 Not changed by (a)
- `STOP_REACHED` / `STRUCTURAL_STOP_BREACHED` / `TP_HIT` are already direction-aware.
- The stored fraction keeps its meaning (distance from entry). There is no migration.
- Option positions of either direction are unchanged, apart from the backend `> 0` guard.
- The 10–99% editor band and the backend `lt=1` stay as they are for shorts too (Q5).

### 2.4 Existing short positions (merge record)
Open short stock positions with a percent stop change behaviour at deploy: they now fire on a RISE. A
wrong-side PREMIUM_STOP that fired recently may still sit in the persisted dedup (`alert_dedup.json`) or as
an unacknowledged toast (R1-15). The merge record says so.

---

## 3. (b) Refuse a sub-cent premium stop at save

### 3.1 Backend (the authority)

- **S1 PATCH** `update_position`: when `"premiumStopPct" in updates`, the value is not None, and
  `premium_stop_is_sub_cent(position.entry_price, value, is_short_stock_position(position.contract,
  position.direction))`, do not write `premium_stop_pct`. Apply every other field, commit, and raise **422**
  at the end: the **late-raise** pattern `qty` uses. The drawer debounces several edits into one PATCH, and an
  early raise would drop a valid stop sent alongside. The detail is a **string**:
  `premium_stop_below_one_cent: at entry $E a X% stop fires below $0.01, so it can never fire.` When qty also
  failed, both reasons are joined with `; ` into one string, which is what `patchPosition`'s `errorDetail`
  renders (R1-14). An explicit null (clear → inherit) is never refused.
  - On a 422 the store toasts and calls `syncFromBackend(true)` (`portfolioStore.ts:668-687`), so the
    optimistic percent reverts while the co-sent stop, which was saved, survives.
- **S2/S3 create** `position_writer.create_position`, after the ratio branch: if `resolved_premium_stop_pct`
  is not None and `premium_stop_is_sub_cent(entry_price, it, is_short_stock_position(body.contract,
  body.direction))`, WARN-log (naming entry, pct and contract) and set it to None (inherit the global).
  **Never refuse the create**: on the broker and auto-trade paths the order may already be at the broker, so
  this mirrors the ratio ≥ 1 branch. The check runs on the final value, so a sub-cent client fraction
  arriving as the fallback (S3) is caught too.
- No DB constraint. Entry is a sibling column, and rows created before this rule must still load and be
  editable.

### 3.2 Frontend

- **F1 drawer `commit`**: after the band check, if `premiumStopIsSubCent(position.entryPrice, next,
  shortStock)`, `revert('At this entry a X% stop fires below $0.01 and could never fire — kept the previous
  value.')`. This is the same revert-with-reason pattern as the band.
- **Drawer caution `subCent`**, now `premiumStopIsSubCent(entry, resolved, shortStock)`, is shown for
  (i) an INHERITED global that is sub-cent at this entry: "At this entry the global stop fires below $0.01
  and can never fire — pin a lower percent." and (ii) a STORED own value from before this rule: "Stored
  before sub-cent stops were refused; it can never fire — set a lower percent." It is never shown for shorts.
- **F2 `premiumStopDollarBounds(mid)`** (R1-3): `max` = the largest whole-cent `d` with
  `min_cents <= d <= floor(cents*0.99)` such that `!premiumStopIsSubCent(mid, d/mid, false)`. Step down from
  `floor(cents*0.99)` in integer cents; at most a few steps, bounded by `min`. When no such `d` exists, the
  field is read-only, as at a $0.01 mid today (P2-24). The TradeCard prices options only, so the short flag
  is false. Example: a $0.03 mid today offers max $0.02, which is sub-cent; v2 offers $0.01.
  - The FILL can still differ from the mid. S2 is the backstop, and the banner names the reason (below).
- **F3 AutoTradeArm**: add `premiumStopSubCent = premiumStopIsSubCent(entryPremium, dollar / entryPremium,
  false)` for `0 < dollar < entryPremium`, shown as a **warning** beside `premiumStopAtOrAbovePremium`, in the
  same way and for the same reason: the fill can differ, and the booking (S2) is the authority (R1-10).
  This is a warning, not a disable. That is a deviation from "refuse at save" for this one path → Q3.
- **Drop banner reason (R1-12)**: `PremiumStopDropNotice` gains `reason: 'total_loss' | 'below_one_cent'`. It is
  computed client-side from the requested dollar or fraction and the server's `entryPrice` in the same
  response (`premiumStopPctFromDollars` undefined → total loss; otherwise below one cent). The banner reads
  "… could not be applied: at the saved premium it is a total loss | fires below $0.01 — this position
  inherits the global stop." For the fraction-only create (S3), detection widens to
  `(premiumStopDollar != null || premiumStopPct != null) && response.premiumStopPct == null`. The notice
  carries the dollar when known, else `entry × pct`.
- **G Settings global**: NOT refused (Q1).

---

## 4. Tests (test-first; each named test must fail on main)

Shared fixture: `frontend/lib/__tests__/fixtures/premium_stop_subcent.json`, generated by
`gen_premium_stop_subcent.py` beside it (the `python_round4.json` pattern). It holds entries $0.01–$2.00 by
cent × pct 10%–99% by 0.25%, plus the full `d = e − $0.01` family for $0.02–$50.00, each with Python's
`premium_stop_is_sub_cent`. CI's checkout is the whole repo (`ci.yml` checks out at the root), so the backend
test reads it by repo-relative path.

Frontend (Jest):
- `lib/__tests__/alertEngine.test.ts`: short stock fires at `>= entry*(1+pct)` and not on a fall; long stock
  unchanged; Bearish option still fires on a fall; boundary equality on both sides; short reason is
  price-only; `referenceValue` is the direction-aware threshold.
- `lib/__tests__/premiumStop.test.ts`: `premiumStopIsSubCent` equals the fixture on every row (fails on main:
  the helper is absent); a short is never sub-cent, including entry $0.05 at 90%; `percentStopFiringPrice`
  short sweep (smallest 2dp `>=` t, and `x - 0.01 < t`); bounds: for every mid $0.02–$50, `max` is not
  sub-cent (fails on main at $0.03 and 2,877 other mids) and `max >= min` or the read-only signal.
- `app/(frame)/portfolio/__tests__/p2EditDrawer.test.tsx`: short label "above entry"; short preview; sub-cent
  commit reverts with the reason and no `onChange`; inherited sub-cent warning (i); stored pre-rule warning
  (ii); `globalNeverFires` hidden for a short; a 422 on `premiumStopPct` alongside `stop` keeps the stop and
  reverts the percent (store + sync mocked).
- `app/(frame)/alerts/__tests__/page.test.tsx`: `Stock stop (+X%)` short, `(–X%)` long stock, `Premium stop`
  option; toast without direction falls back to the position; toggle list neutral label.
- `lib/__tests__/p2PortfolioStore.test.ts`: fraction-only create with `premiumStopPct == null` in the response
  queues a notice; reason `below_one_cent` vs `total_loss`.
- AutoTradeArm test (beside its existing ones): sub-cent warning shown; Arm still enabled.

Backend (pytest):
- `tests/test_alerts.py` (already has Bearish `|STOCK` fixtures at :191, :350-400): short fires on a rise and
  not on a fall; `reference_value` direction-aware; Bearish option unchanged; `opt_price == 0.0` does not fire
  (fails on main).
- `tests/test_premium_stop_per_position.py`: helpers + the shared fixture.
- `tests/test_portfolio_update.py`: sub-cent → 422 string detail `premium_stop_below_one_cent…`,
  `premium_stop_pct` unchanged, a `stop` in the same PATCH saved; null clear allowed; qty + premium failures
  produce one `; `-joined detail; a short at a sub-penny entry is NOT refused.
- `tests/test_position_writer.py`: sub-cent from dollar (incl. $0.02 on $0.03) → None + WARNING, 201; sub-cent
  fraction fallback → None; valid unchanged; short sub-penny entry kept.
- `tests/test_alert_notifier.py`: side-aware PREMIUM_STOP label.

Mutations to run and record: swap `>=`/`<=` on the short branch; drop the `isStock` term (options must break);
drop the late raise (the stop-alongside test must break); drop the backend `> 0` guard; give the short flag a
default (typecheck / pytest signature test must break).

---

## 5. Files

Backend: `app/services/premium_stop.py`, `app/services/alert_generator.py`, `app/routers/portfolio.py`,
`app/services/position_writer.py`, `app/services/notifications/alert_notifier.py`, plus tests.
Frontend: `lib/premiumStop.ts`, `lib/alertEngine.ts`, `lib/portfolioStore.ts`, `app/(frame)/portfolio/EditDrawer.tsx`,
`app/(frame)/portfolio/page.tsx` (banner reason), `app/(frame)/alerts/page.tsx`, `app/(frame)/settings/page.tsx`,
`components/organisms/AutoTradeArm/index.tsx`, plus tests and the fixture + generator. TradeCard consumes
`premiumStopDollarBounds` unchanged.
Ledger: phase `STOP-SEMANTICS` with a verify probe on `premium_stop_is_sub_cent` and `isShortStockPosition`.
Close the two open questions and the round_13 sub-cent item on merge.

## 6. Questions for Kenneth (recommendation first)

- **Q1 — the Settings global (G).** The ledger summary I wrote on 2026-10-02 lists "Settings" among the places
  that refuse (R1-9). The global has no entry, so "sub-cent" is undefined for it. Recommend: leave the global
  unrefused; refuse per-position saves; warn on positions that inherit a sub-cent global. Alternative: refuse a
  global that is sub-cent at any OPEN long position's entry (it depends on what is open that day, so
  surprising). On approval, the ledger summary is corrected.
- **Q2 — create after a fill (S2/S3).** Recommend: drop to the global with the banner, never refuse the row.
- **Q3 — AutoTradeArm (F3).** Recommend: warn, not disable, matching its total-loss sibling, because the fill
  decides and S2 enforces.
- **Q4 — the float-noise family.** Recommend: treat `e − 1¢` stops whose computed threshold is a few ulps under
  $0.01 as sub-cent (what the engines do today). Alternative: a tolerance in both engines so they fire at
  $0.01. That is a wider change to every stop's boundary.
- **Q5 — the band for shorts.** Recommend: keep 10–99% for shorts (a 99% short stop fires at 1.99× entry).
  Raising the cap for shorts is possible later.

## 7. Logged, not fixed here
- `pnlPct` / `pnlDollar` / equity-snapshot `open_pnl` are not direction-aware for short stocks
  (`routers/portfolio.py:131-133`, `portfolio/page.tsx:384`, `EditDrawer.tsx:459`). Goes to `open_questions`
  on merge.
