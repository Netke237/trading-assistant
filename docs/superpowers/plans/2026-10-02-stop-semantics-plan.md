# STOP-SEMANTICS — build plan (v3)

Decision: `STOP-SEMANTICS-2026-10-02` (PROJECT_STATE.json). Task: `task_backlog` STOP-SEMANTICS.
Two behaviour changes, one branch, one plan:

- **(a)** A SHORT stock position's percent stop fires when the price RISES X% above entry.
- **(b)** A premium stop whose threshold is below $0.01 is REFUSED when saved.

Part (c) of the decision (COMPOSITE-WATCH-KEYERROR) is closed, so no code.

**v3 changes (plan round 2: 0 blocking / 7 should-fix / 9 nits).** Deploy-time reset of short
PREMIUM_STOP dedup/suppression in both stores (R2-1). The Settings hint limit goes through the predicate
(R2-2). The F2 fails-on-main count is corrected to 43 (R2-3). The drop reason is threaded through every
consumer, step-7 included (R2-4). S2 falls back to a valid client fraction (R2-5). The 422 join order,
label and partial-save header are specified (R2-6). The side is stamped at fire time, and the notifier
signature and callers are listed (R2-7). Nits R2-8..16 are folded in (§9 lists them).

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
  `opt_price is not None and pos.entry_price > 0`. **No `> 0` on the quote.** The alert path's quote comes from
  `fetch_contract_quote_async` (`data/market.py:1668`). For an option it goes through `fetch_option_chain_async`,
  where `mid = round(last, 2)` (~:1547) can be `0.0` for a sub-half-cent last. For a stock it goes through
  `fetch_price_async` (:1438-1440), which can return `round(last, 2) = 0.0` too. That 0 fires a long position's
  stop (`0 <= threshold`). For a `|STOCK` contract, `opt_price` is the stock quote.

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
`premiumStopDollar != null && response.premiumStopPct == null` through **three** signals:
- `applyPersistedPosition`'s `onPremiumStopDropped(requestedDollar)` callback (`portfolioStore.ts:519-521`) →
  step-7 `addSaveNote(droppedStopNote(r))` (`step-7-trade-card/page.tsx:1166, :1214`). It also has two
  callers in `lib/stockDirectSend.ts` (:162, :201).
- `addPosition`'s return `premiumStopDropped` (`portfolioStore.ts:1068-1074`) → step-7 `:1340-1341`
  `droppedStopNote`.
- The offline retry (`portfolioStore.ts:1310-1327`) → `premiumStopDropQueue` → the Portfolio banner
  (`portfolio/page.tsx:211-217`).

`droppedStopNote` (`step-7:550`) and the banner both use fixed total-loss wording ("could not be applied at
the filled/saved premium"). (b) at S2/S3 reuses all three signals and adds a reason (§3.2).

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

The drawer's existing `premiumStopFiringPrice(...) <= 0` test agrees with `premiumStopIsSubCent` on 5,004,499
swept cases (plan round 2). It is still replaced by the named predicate, so there is one spelling of the rule.

`isShortStockPosition` matches **exactly** what the engines test today: case-sensitive
`contract.endsWith('|STOCK')` / `contract.endswith('|STOCK')` and `direction === 'Bearish'`.
`market.py:1680`'s upper-casing is quote routing, not position classification, and is not copied.

---

## 2. (a) Direction-aware percent stop for a short stock

### 2.1 Engines

- `alertEngine.ts` PREMIUM_STOP: `shortStock = isStock && isBearish`;
  `threshold = percentStopThresholdPrice(entry, pct, shortStock)`;
  `hit = entry > 0 && currentPrice > 0 && (shortStock ? currentPrice >= threshold : currentPrice <= threshold)`.
  `referenceValue: pythonRound4(threshold)`. Reason: a short reads `Stock stop — SYM at $P` (price-only,
  because `pnlPct` is not direction-aware, §0). **Both engines use this exact string for a short** (R2-10),
  so the in-place toast refresh cannot flip between wordings. Long stock and options keep their current
  per-engine reasons (unchanged behaviour, out of scope).
- `alert_generator.py` PREMIUM_STOP: the same threshold and side, via `percent_stop_threshold_price`.
  **Add `opt_price > 0`** to the guard (R1-4). This brings parity with the frontend `currentPrice > 0` and
  makes "a sub-cent stop can never fire" true in both engines. Behaviour change: a long position whose quote
  rounds to $0.00 no longer fires PREMIUM_STOP. The frontend already behaves this way. `reference_value`
  and `thresholdPct` in the event log use the direction-aware threshold. Reason for a short:
  `Stock stop — SYM at $P` (same string as the frontend). Long and option reasons are unchanged.
- `_sustained` / `_muted` unchanged.

### 2.2 Labels, previews, "never fires" copy

- `EditDrawer` field label: long stock `Stock stop — fires X below entry`, short stock
  `Stock stop — fires X above entry`, options unchanged. Delete the Q-P2-1 comment.
- `alertFiresAgainst('PREMIUM_STOP')`: `stock $` + `percentStopFiringPrice(entry, pct, shortStock)`.
- `globalNeverFires` (`EditDrawer.tsx:1111`): `&& !shortStock`. A short at ≥100% fires at ≥2× entry (R1-8).
- `settings/page.tsx:103-123`: the "Stored 100% can never fire" note and the sub-cent hint say "for long
  positions and options". The "fires only on a sub-penny quote" clause becomes "can never fire", which is
  now true in both engines (§2.1). **The hinted limit entry is derived through the predicate** (R2-2):
  the smallest whole-cent entry `e` with `!premiumStopIsSubCent(e, pct, false)`, found by stepping up from
  today's `ceil(...)` estimate. Today's formula names a limit that is itself sub-cent at 80% ($0.05), 90%
  ($0.10) and 98.75% ($0.80). A sweep test over 10.00%–99.00% by 0.01% pins it.
- **Side stamped at fire time (R2-7a).** A new optional field `stopSide: 'short-stock' | 'long-stock' |
  'option'` goes on the frontend `AlertReason`/`ToastItem` (`types/domain.ts`) and the backend `AlertItem`
  (`schemas/__init__.py`). Both engines set it on PREMIUM_STOP, in the same spirit as
  ALERT-THRESHOLD-STAMP (`types/domain.ts:1066-1084`): a row reports the rule it FIRED under, never one
  re-derived later. `addToast`'s in-place refresh copies `stopSide`, `price`, `referenceValue` and
  `premiumStopPct` along with `kind`/`reason` (today only `kind`/`reason`, `alertStore.ts:236-240`), so a
  refreshed row is internally consistent.
- `alerts/page.tsx` `alertTypeLabel(type, pct, side?)` gives `Stock stop (+X%)` for `short-stock`,
  `Stock stop (–X%)` for `long-stock`, and `Premium stop (–X%)` for `option` **and for any row without a
  stamp** (every pre-deploy row, which fired under the old fall-side rule: its legacy wording stays true).
  The toggle list (`:470`) passes no side and reads `Premium / stock stop (±X%)`.
- Type-name tables (R2-11): `alerts/page.tsx:46` and `EditDrawer.tsx:1693` `ALERT_TYPE_LABELS` name the alert
  TYPE, not a row, and become `Premium / stock stop` (the same neutral wording as the toggle list).
- Notifier (R2-7b): `notify_alert` / `_build_notification` (`alert_notifier.py:172, :224`) gain an optional
  `stop_side` parameter. The PREMIUM_STOP label (`:165`) is chosen from it (`Stock stop hit (short)`,
  `Stock stop hit`, `Premium stop hit`; None → `Premium stop hit`). Callers updated: `portfolio_alert_monitor.py:185`
  (passes `alert.stopSide`), `routers/alerts.py:147` (passes the posted toast's `stopSide`) and `auto_trader.py:1595`
  (no PREMIUM_STOP, passes nothing).

### 2.3 Not changed by (a)
- `STOP_REACHED` / `STRUCTURAL_STOP_BREACHED` / `TP_HIT` are already direction-aware.
- The stored fraction keeps its meaning (distance from entry). There is no migration.
- Option positions of either direction are unchanged, apart from the backend `> 0` guard.
- The 10–99% editor band and the backend `lt=1` stay as they are for shorts too (Q5).

### 2.4 Existing short positions: one-time reset at deploy (R2-1)
Open short stock positions with a percent stop change behaviour at deploy: they now fire on a RISE. Old
fall-side state would otherwise silence or mis-date the correct alert:
- frontend `alertStore`: `suppressedAlerts["recId-PREMIUM_STOP"]` (set on acknowledge, `:283-290`, checked
  first in `addToast`, `:212`) silences it permanently. `firedAlerts` holds its notify dedup, and an
  unacknowledged row keeps stale numbers.
- backend `alert_notifier._first_seen` (`:276-282`), persisted to `alert_dedup.json` until the position
  closes, would send the correct fire as a "(reminder)" dated at the wrong-side trigger, or suppress it.

The reset:
- **Backend**: a one-time function `reset_short_stock_premium_stop_dedup(rec_ids)` in `alert_notifier.py`
  drops the `PREMIUM_STOP` keys for the given rec_ids (the `forget_alerts` pattern, `:309`). The first
  `portfolio_alert_monitor` cycle after deploy calls it with its open `|STOCK` + Bearish rec_ids. A marker
  in the dedup file (`"_migrations": ["stop-semantics-short-2026-10"]`) makes it run exactly once.
- **Frontend**: `alertStore` version bump. `migrateAlerts` sets `pendingShortStopReset: true`. A store action
  `resetShortStockPremiumStops(positions)` removes `suppressedAlerts`/`firedAlerts` PREMIUM_STOP keys and
  marks unacknowledged PREMIUM_STOP rows acknowledged for the short-stock recIds among `positions`, then
  clears the flag. `scanPortfolio`'s two callers (`portfolio/page.tsx:143-149`, `dashboard/page.tsx:94-100`)
  call it once before their first scan while the flag is set. Option and long-stock keys are untouched, so
  no acknowledged alert re-fires for them.
- Tests pin both: a short's acknowledged pre-deploy key is cleared and the rise-side alert surfaces; a long's
  and an option's keys survive; the backend marker prevents a second run.

---

## 3. (b) Refuse a sub-cent premium stop at save

### 3.1 Backend (the authority)

- **S1 PATCH** `update_position`: when `"premiumStopPct" in updates`, the value is not None, and
  `premium_stop_is_sub_cent(position.entry_price, value, is_short_stock_position(position.contract,
  position.direction))`, do not write `premium_stop_pct`. Apply every other field, commit, and raise **422**
  at the end: the **late-raise** pattern `qty` uses. The drawer debounces several edits into one PATCH, and an
  early raise would drop a valid stop sent alongside. The detail is a **string**, in this order (R2-6):
  `qty_error` first, unchanged (space-joined risk codes, which `rejectionMessage` maps), then the code
  `premium_stop_below_one_cent`, space-separated. The human text lives in the frontend map: a new
  `REJECTION_LABELS.premium_stop_below_one_cent` = "Premium stop not saved: at this entry it would fire below
  $0.01 and could never fire." With no space-joined free text, `rejectionMessage`'s token split maps every
  code, and neither refusal can hide the other. When the same PATCH trimmed qty (`adjusted_qty`), the late
  422 loses `adjustedQty` (R2-13), so the code `qty_saved_as_<N>` is appended and mapped to "Quantity saved
  as N (reduced to fit exposure)." The Portfolio error banner's header "{symbol} was not saved" becomes
  "{symbol}: some changes were not saved" when the detail contains only `premium_stop_below_one_cent` /
  `qty_saved_as_*` codes, because the co-sent fields WERE saved. An explicit null (clear → inherit) is never refused.
  - On a 422 the store toasts and calls `syncFromBackend(true)` (`portfolioStore.ts:668-687`), so the
    optimistic percent reverts while the co-sent stop, which was saved, survives.
- **S2/S3 create** `position_writer.create_position`, after the ratio branch: if `resolved_premium_stop_pct`
  is not None and `premium_stop_is_sub_cent(entry_price, it, is_short_stock_position(body.contract,
  body.direction))`, WARN-log (naming entry, pct and contract). Then fall back **exactly as the ratio ≥ 1 branch
  does** (R2-5, `position_writer.py:533-538`): to `body.premiumStopPct` when that is itself not sub-cent,
  else None (inherit the global). An unusable dollar is no reason to discard a fraction that is independently
  valid.
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
  `floor(cents*0.99)` in integer cents; at most a few steps, bounded by `min`. For every mid $0.02–$50 the step-down
  needs at most one step and always finds a `d` (plan round 2 sweep). At a $0.01 mid `bounds` keeps returning
  `max = min = 0.01` exactly as today, and TradeCard's existing read-only detection (`:1740-1742`, via a ratio
  ≥ 1) is unchanged, so "TradeCard unchanged" stays true. The TradeCard prices options only, so the short flag
  is false. Example: a $0.03 mid today offers max $0.02, which is sub-cent; v2 offers $0.01.
  - The FILL can still differ from the mid. S2 is the backstop, and the banner names the reason (below).
- **F3 AutoTradeArm**: add `premiumStopSubCent = premiumStopIsSubCent(entryPremium, dollar / entryPremium,
  false)` for `0 < dollar < entryPremium`, shown as a **warning** beside `premiumStopAtOrAbovePremium`, in the
  same way and for the same reason: the fill can differ, and the booking (S2) is the authority (R1-10).
  This is a warning, not a disable. That is a deviation from "refuse at save" for this one path → Q3.
- **Drop reason, on every signal (R1-12, R2-4)**: one helper `premiumStopDropReason(requestedDollar,
  requestedPct, savedEntry, shortStock)` returns `'total_loss' | 'below_one_cent'`
  (`premiumStopPctFromDollars` undefined → total loss; otherwise below one cent). It feeds all three
  signals:
  - the `onPremiumStopDropped` callback becomes `(requestedDollar: number, reason)`;
  - `addPosition`'s return gains `premiumStopDropReason`;
  - `PremiumStopDropNotice` gains `reason`.
  Step-7's `droppedStopNote(requested, reason)` and the Portfolio banner both read "… could not be applied:
  at the filled premium it is a total loss | it would fire below $0.01 — this position inherits the global
  stop." The `stockDirectSend.ts` callers (:162, :201) pass the reason through. Detection widens to
  `(premiumStopDollar != null || premiumStopPct != null) && response.premiumStopPct == null` (fraction-only
  creates, S3), and the notice carries the dollar when known, else `entry × pct`. After the S2 fallback
  (§3.1) a response can carry the CLIENT fraction instead of null. That is not a drop, and detection is
  unchanged for it.
- **G Settings global**: NOT refused (Q1).

---

## 4. Tests (test-first; each named test must fail on main)

Shared fixture: `frontend/lib/__tests__/fixtures/premium_stop_subcent.json`, generated by
`gen_premium_stop_subcent.py` beside it (the `python_round4.json` pattern). It holds `[entry_cents, pct_bp,
is_sub_cent]` rows (R2-15): the grid entries $0.01–$2.00 × pct 10%–99% by 25 bp, **kept only where
`|entry*(1-pct) − 0.01| < 0.005`** (the boundary neighbourhood), plus the full `d = e − $0.01` family for
$0.02–$50.00 as `[entry_cents, dollar_cents, is_sub_cent]`. CI's checkout is the whole repo, but pytest runs
from `backend/` (`ci.yml:24-25`), so the backend test resolves it as
`Path(__file__).resolve().parents[2] / 'frontend/lib/__tests__/fixtures/premium_stop_subcent.json'` (R2-12).

Frontend (Jest):
- `lib/__tests__/alertEngine.test.ts`: short stock fires at `>= entry*(1+pct)` and not on a fall; long stock
  unchanged; Bearish option still fires on a fall; boundary equality on both sides; short reason is
  price-only; `referenceValue` is the direction-aware threshold.
- `lib/__tests__/premiumStop.test.ts`: `premiumStopIsSubCent` equals the fixture on every row (fails on main:
  the helper is absent); a short is never sub-cent, including entry $0.05 at 90%; `percentStopFiringPrice`
  short sweep (smallest 2dp `>=` t, and `x - 0.01 < t`); bounds: for every mid $0.02–$50, `max` is not
  sub-cent and `max >= min` (**fails on main at 43 mids**: $0.03, $0.06, $0.08, $0.09, $0.11, … — R2-3); Settings
  hint limit sweep (fails on main at 80%, 90%, 98.75%).
- `app/(frame)/portfolio/__tests__/p2EditDrawer.test.tsx`: short label "above entry"; short preview; sub-cent
  commit reverts with the reason and no `onChange`; inherited sub-cent warning (i); stored pre-rule warning
  (ii); `globalNeverFires` hidden for a short; a 422 on `premiumStopPct` alongside `stop` keeps the stop and
  reverts the percent (store + sync mocked).
- `app/(frame)/alerts/__tests__/page.test.tsx`: `Stock stop (+X%)` short, `(–X%)` long stock, `Premium stop`
  option; toast without direction falls back to the position; toggle list neutral label.
- `lib/__tests__/p2PortfolioStore.test.ts`: fraction-only create with `premiumStopPct == null` in the response
  queues a notice; reason `below_one_cent` vs `total_loss` on all three signals; a response carrying the
  client fraction (S2 fallback) is not a drop.
- step-7 test (beside its existing `droppedStopNote` tests): the note names the reason.
- `alertStore` test: `resetShortStockPremiumStops` clears only short-stock PREMIUM_STOP keys; in-place refresh
  copies `stopSide`/`price`/`referenceValue`/`premiumStopPct`; migrate sets the flag once.
- `portfolio/page` test: `rejectionMessage` on `"single_trade_exposure_too_high premium_stop_below_one_cent"`
  shows both labels; the partial-save header.
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
- `tests/test_alert_notifier.py`: side-aware PREMIUM_STOP label (None → legacy); the one-time reset drops
  only the given rec_ids' PREMIUM_STOP keys and the marker blocks a second run.
- `tests/test_position_writer.py` also: a sub-cent dollar with a valid client fraction stores the fraction
  (R2-5).

Mutations to run and record: swap `>=`/`<=` on the short branch; drop the `isStock` term (options must break);
drop the late raise (the stop-alongside test must break); drop the backend `> 0` guard; give the short flag a
default (typecheck / pytest signature test must break).

---

## 5. Files

Backend: `app/services/premium_stop.py`, `app/services/alert_generator.py`, `app/routers/portfolio.py`,
`app/services/position_writer.py`, `app/services/notifications/alert_notifier.py`,
`app/services/portfolio_alert_monitor.py`, `app/routers/alerts.py`, `app/schemas/__init__.py` (`AlertItem.stopSide`;
the toast-notify request body), `app/services/auto_trader.py` (call-site signature only, if needed), plus tests.
Frontend: `lib/premiumStop.ts`, `lib/alertEngine.ts`, `lib/portfolioStore.ts`, `app/(frame)/portfolio/EditDrawer.tsx`,
`app/(frame)/portfolio/page.tsx` (banner reason), `app/(frame)/alerts/page.tsx`, `app/(frame)/settings/page.tsx`,
`components/organisms/AutoTradeArm/index.tsx`, `lib/alertStore.ts`, `types/domain.ts`, `app/(frame)/dashboard/page.tsx`,
`app/(frame)/screener/step-7-trade-card/page.tsx`, `lib/stockDirectSend.ts`, plus tests and the fixture + generator. TradeCard consumes
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

## 8. Plan round 2 nits — where each went
R2-8 the quote paths are cited correctly (§0). R2-9 the predicate-equivalence claim is corrected (§1). R2-10 there is
one short reason string (§2.1). R2-11 the type-name tables (§2.2). R2-12 the fixture path (§4). R2-13
`qty_saved_as_<N>` (§3.1). R2-14 F2 at a $0.01 mid (§3.2). R2-15 the fixture is trimmed to the boundary
neighbourhood (§4). R2-16 `|STOCK` matching (§1).

## 9. Plan round 3 findings — OPEN, to apply in v4 (round cap reached; stopped for Kenneth)

Round 3 (fresh reviewer, against v3 at abb0454): NOT clean, 2 blocking / 7 should-fix / 9 nits. Every numeric
claim in v3 reproduced. The defects are in v3's additions.

Blocking:
- **R3-B1.** The backend "run once" marker is erased. `alert_notifier._save_dedup` (:83) writes only
  `{'fired','first_seen'}` and `_load_dedup` (:107-113) reads only those, so the next save drops
  `_migrations` and the reset re-runs on every restart, re-emailing. Fix: a module-level `_migrations`
  set that load reads and save always writes. Check and set it under `_fired_lock`, and mark it done only
  when `_save_dedup()` returns True. Test: reset → notify (save) → reload → the marker is present.
- **R3-B2.** The frontend version bump re-enables STRUCTURAL_STOP_BREACHED. `alertStore.ts:172` backfills it
  whenever `_version < ALERT_STORE_VERSION` (`types/domain.ts:1076-1080` warns about this). Separately,
  `pendingShortStopReset` never survives: `merge` (:338-357) and `partialize` (:332-337) copy only four
  fields. Fix: gate the backfill on `_version < 3`; set the flag only when `_version < 4`; add the flag to
  `partialize` and to `merge` (`ps.pendingShortStopReset ?? false`). Test through
  `useAlertStore.persist.rehydrate()` with a v3 blob that has STRUCTURAL removed.

Should-fix:
- **R3-S1.** A third scan caller: `dashboard/page.tsx:141-144` (mount/deps effect) runs first. Call the reset
  at all three call sites, or inside `scanPortfolio`/`addToast` keyed on the flag.
- **R3-S2.** `stopSide` never reaches `/api/alerts/notify`. `alertStore.ts:79-111` `notifyBackend` and the
  `addToast` call (:256-267) omit it. The request model is `AlertNotifyRequest` in `routers/alerts.py:63-75`,
  not schemas. Better: derive the side server-side from the DB position, as the endpoint already does for
  symbol, contract and direction (:96-101).
- **R3-S3.** `qty_error` can be free text (`portfolio.py:251, 258, 281-285`), so `rejectionMessage`'s token mapping
  hides it. Join segments with `" | "`, map each segment by its tokens, and fall back to the raw segment. Test
  each free-text qty error.
- **R3-S4.** The separator is contradictory (§3.1 says space, §4 says `; `). Use the R3-S3 separator.
- **R3-S5.** The label fallback is contradictory. §4's "toast without direction falls back to the position" is
  pre-v3. Rewrite it as "unstamped row → legacy label even for a short", and drop the §0 sentence about
  optional direction/contract.
- **R3-S6.** The tests can't be written as named. There is no `portfolio/__tests__/page.test.tsx`;
  `rejectionMessage`/`REJECTION_LABELS` are private in an App Router page (a named export breaks
  `next build`); `droppedStopNote` is a closure (step-7 :550). Move them into a `lib/` module, or specify
  render-level tests (`step-7-trade-card/__tests__/edited-fields-sync.test.tsx` pattern).
- **R3-S7.** `premiumStopDropReason` mislabels drops. Fraction-only (`requestedDollar == null`) must be
  `below_one_cent`, because a schema fraction is in (0, 1). An unknown saved entry (optional `entryPrice`,
  `portfolioStore.ts:552, 1343`) gets a third value, `unknown`, with neutral wording.

Nits:
- N1: `AlertReason` lives in `lib/alertEngine.ts:49-69`, and the frontend `AlertItem` needs no `stopSide`.
- N2: `qty_saved_as_<N>` needs a prefix rule.
- N3: a 422 sets the `lastSyncError` banner, not a toast.
- N4: run the backend reset only after the positions query succeeds, and state what happens with
  `masterEnabled` false. A browser notify before the first tick sees stale keys; consider a lazy reset
  inside `notify_alert`, or at lifespan startup.
- N5: state the intent of copying `premiumStopPct` on an in-place refresh, given ALERT-THRESHOLD-STAMP.
- N6: short thresholds carry float noise too (~0.7% fire 1¢ late). Test with the computed threshold, and
  add short rows to the fixture.
- N7: the stockDirectSend callers pass no callback, and no stock path sets a premium stop, so say "no-op".
- N8: mark "long stock unchanged" and "Bearish option unchanged" as regression guards, not fails-on-main.
- N9: a one-line note that the Settings "Premium stop loss" also governs shorts' rise-side stop.

**Status:** three plan rounds used (1: 3B/8S/4N, 2: 0B/7S/9N, 3: 2B/7S/9N), none clean, so this is the cap.
Kenneth decides: write v4 and build from it (the WATCH-RESEND-P1-BUILD-FROM-V4-2026-10-02 precedent), write
v4 and run one more round, or park.
