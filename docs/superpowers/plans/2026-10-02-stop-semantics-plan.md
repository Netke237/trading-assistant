# STOP-SEMANTICS — build plan (v4)

Decision: `STOP-SEMANTICS-2026-10-02` (PROJECT_STATE.json). Task: `task_backlog` STOP-SEMANTICS.
Two behaviour changes, one branch, one plan:

- **(a)** A SHORT stock position's percent stop fires when the price RISES X% above entry.
- **(b)** A premium stop whose threshold is below $0.01 is REFUSED when saved.

Part (c) of the decision (COMPOSITE-WATCH-KEYERROR) is closed, so no code.

**v4 changes (plan round 3: 2 blocking / 7 should-fix / 9 nits; Kenneth: write v4 and build from it).**
The deploy-time reset is gone. Both blockers were bugs in its mechanics (a marker the next dedup save erased;
a store version bump that re-enabled STRUCTURAL_STOP_BREACHED and a flag that never persisted). v4 removes
the need for a reset: a short-stock PREMIUM_STOP fire uses its OWN dedup key in both stores (`…:short`),
so no state written under the old fall-side rule can silence, throttle or mis-date it (§2.4, R3-B1/B2/S1,
N4). With the side fixed per key, the in-place refresh change is dropped too (N5). The backend derives the
side from the DB row (R3-S2). PATCH refusal segments are joined with ` | ` and mapped per segment (R3-S3/S4,
N2). The label fallback is "unstamped row → legacy label" (R3-S5). The rejection mapper and the drop-note
text move into `lib/` so they can be unit-tested (R3-S6). The drop reason gains `unknown`, and a
fraction-only drop is `below_one_cent` (R3-S7). Nits N1, N3, N6–N9 are folded in. §9 records where each went.

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
  by the Alert-types toggle list (`:470`, type + global only, no position).
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
  step-7 `addSaveNote(droppedStopNote(r))` (`step-7-trade-card/page.tsx:1166, :1214`). Its two
  callers in `lib/stockDirectSend.ts` (:162, :201) pass no callback, and no stock path sets a premium stop,
  so they are a no-op here and stay unchanged (N7).
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
pinned sweep. It is out of this task's scope unless Kenneth chooses it (Q4). **Kenneth chose the
recommendation (no tolerance).**

**Short thresholds carry float noise too (N6).** `entry * (1 + pct)` can land a few ulps ABOVE the nominal
whole-cent price (entry $100.00 at 10% → 110.00000000000001), so a quote of exactly $110.00 does not fire and
$110.01 does: about 0.7% of grid cases fire 1¢ late. Under the Q4 decision this is the engine's rule and is
not corrected. `percentStopFiringPrice` reports the engine's real firing price ($110.01 here), so the preview
never promises a fire the engine will not deliver. Tests compare against the computed threshold, never the
nominal one, and the shared fixture carries short rows to pin TS/Python threshold parity (§4).

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
  `referenceValue: pythonRound4(threshold)`, `stopSide: premiumStopSide(contract, direction)` (§2.2). Reason: a short reads `Stock stop — SYM at $P` (price-only,
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
- **Side stamped at fire time (R2-7a, N1).** A new optional field `stopSide: 'short-stock' | 'long-stock' |
  'option'` goes on the frontend `AlertReason` (`lib/alertEngine.ts:49-69`) and `ToastItem`
  (`types/domain.ts`), and on the backend `AlertItem` (`schemas/__init__.py`). The frontend `AlertItem` type
  is not touched (nothing feeds backend alert items into toasts). Twin helpers `premiumStopSide(contract,
  direction)` / `premium_stop_side(contract, direction)` derive it from `isShortStockPosition` plus the
  `|STOCK` suffix. Both engines set it on PREMIUM_STOP only, in the same spirit as ALERT-THRESHOLD-STAMP
  (`types/domain.ts:1066-1084`): a row reports the rule it FIRED under, never one re-derived later.
  `addToast`'s in-place refresh is **unchanged** (it copies `kind`/`reason`, as today). The side is part of
  the dedup key (§2.4), so a refresh never crosses sides, and a refreshed row keeps the side it fired with.
  The stale `price`/`referenceValue`/`premiumStopPct` on a refreshed row is pre-existing behaviour for every
  type: those fields stamp the FIRST trigger, like `firedAt` (N5).
- `alerts/page.tsx` `alertTypeLabel(type, pct, side?)` gives `Stock stop (+X%)` for `short-stock`,
  `Stock stop (–X%)` for `long-stock`, and `Premium stop (–X%)` for `option` **and for any unstamped row,
  even one for a short position** (R3-S5). Every pre-deploy row fired under the old fall-side rule, so its
  legacy wording stays true. The label never falls back to the position's current contract or direction.
  The toggle list (`:470`) passes no side and reads `Premium / stock stop (±X%)`.
- Type-name tables (R2-11): `alerts/page.tsx:46` and `EditDrawer.tsx:1693` `ALERT_TYPE_LABELS` name the alert
  TYPE, not a row, and become `Premium / stock stop` (the same neutral wording as the toggle list).
- Notifier (R2-7b): `notify_alert` / `_build_notification` (`alert_notifier.py:172, :224`) gain an optional
  `stop_side` parameter. The PREMIUM_STOP label (`:165`) is chosen from it (`Stock stop hit (short)`,
  `Stock stop hit`, `Premium stop hit`; None → `Premium stop hit`). It also selects the dedup key (§2.4).
  Callers:
  - `portfolio_alert_monitor.py:185` passes `alert.stopSide` (set by `alert_generator` from the DB row).
  - `routers/alerts.py` `post_alert_notify` **derives the side from the DB row** (R3-S2), as it already does
    for symbol, contract and direction (:96-101). It does not trust a client value. `AlertNotifyRequest`
    (`routers/alerts.py:63-75`, not schemas) gains an optional `stopSide`, and `alertStore.notifyBackend`
    plus its `addToast` call (`alertStore.ts:79-111, :256-267`) send it. The server uses it only as a
    version signal: when it is absent and the row is a short stock, the POST came from a tab still running
    the pre-deploy engine (a fall-side fire), so the server passes `stop_side=None` (legacy key and label).
    Otherwise it passes the derived side.
  - `auto_trader.py:1595` has no PREMIUM_STOP and passes nothing.

### 2.3 Not changed by (a)
- `STOP_REACHED` / `STRUCTURAL_STOP_BREACHED` / `TP_HIT` are already direction-aware.
- The stored fraction keeps its meaning (distance from entry). There is no migration.
- Option positions of either direction are unchanged, apart from the backend `> 0` guard.
- The 10–99% editor band and the backend `lt=1` stay as they are for shorts too (Q5).

### 2.4 Existing short positions: a separate dedup key, not a reset (R2-1, R3-B1/B2/S1, N4)
Open short stock positions with a percent stop change behaviour at deploy: they now fire on a RISE. State
written under the old fall-side rule must not silence or mis-date the correct alert:
- frontend `alertStore`: `suppressedAlerts["recId-PREMIUM_STOP"]` (set on acknowledge) silences it
  permanently, `firedAlerts` throttles its notify, and an unacknowledged row would absorb it as an in-place
  refresh.
- backend `alert_notifier._fired` / `_first_seen`, persisted to `alert_dedup.json` until the position
  closes, would send it as a "(reminder)" dated at the wrong-side trigger, or suppress it.

v3 cleared that state with a one-time reset. Round 3 found both halves broken. v4 needs no reset: **a
short-stock PREMIUM_STOP fire is keyed separately in both stores.**
- **Frontend**: one helper `alertKey(t)` in `alertStore.ts` = `makeDedupKey(recId, alertType)` plus
  `':short'` when `t.alertType === 'PREMIUM_STOP' && t.stopSide === 'short-stock'`. Every site that keys by
  `(recId, alertType)` uses it: `collapseToasts` (:55), `addToast`'s suppression check, its firedAlerts
  throttle and its existing-row match (:209-221, which compares `alertKey` instead of the two fields),
  `acknowledgeAlert` (:286) and `deleteAlert` (:296). There is **no version bump and no migration**, so
  `migrateAlerts`' one-time STRUCTURAL_STOP_BREACHED backfill (gated on `_version < ALERT_STORE_VERSION`)
  cannot re-run (R3-B2), and there is no flag to persist. A pre-deploy short row (unstamped, legacy key)
  stays in history under its legacy label. The first rise-side fire is a new row with a new key, so the old
  acknowledgement, throttle and open row cannot touch it. All three scan callers (`portfolio/page.tsx:149`,
  `dashboard/page.tsx:100, :143`) go through `addToast`, so none needs a change (R3-S1).
- **Backend**: `notify_alert`'s key is `f'{rec_id}|{alert_type}'`, plus `':short'` when `alert_type ==
  'PREMIUM_STOP' and stop_side == 'short-stock'`. `forget_alerts` splits on the first `|` and still matches
  the rec_id, so a closed short clears both keys. `_save_dedup`/`_load_dedup` are unchanged. The old
  fall-side key simply ages out with the position. It runs whatever `masterEnabled` says, and it does not
  matter whether the monitor or the browser is first after deploy (N4), because nothing has to run once.
- `alert_generator`'s `_sustained` state is keyed by type per position. Old-rule met (`price <= e(1-p)`) and
  new-rule met (`price >= e(1+p)`) are disjoint, so a pending old-rule timer is popped on the first new-rule
  evaluation and cannot shorten a rise-side sustain. No change.
- Tests pin it: a short with an acknowledged pre-deploy `recId-PREMIUM_STOP` key and an unacknowledged
  legacy row still surfaces a NEW rise-side row and notifies; a long's and an option's keys are unchanged
  (regression guards); the backend sends a short's first rise fire as a non-reminder although
  `_first_seen` holds the legacy key, and `forget_alerts` drops both keys; STRUCTURAL_STOP_BREACHED stays off
  for a persisted config without it after rehydration (`useAlertStore.persist.rehydrate()`, regression guard).

---

## 3. (b) Refuse a sub-cent premium stop at save

### 3.1 Backend (the authority)

- **S1 PATCH** `update_position`: when `"premiumStopPct" in updates`, the value is not None, and
  `premium_stop_is_sub_cent(position.entry_price, value, is_short_stock_position(position.contract,
  position.direction))`, do not write `premium_stop_pct`. Apply every other field, commit, and raise **422**
  at the end: the **late-raise** pattern `qty` uses. The drawer debounces several edits into one PATCH, and an
  early raise would drop a valid stop sent alongside. The detail is a **string** of segments joined by
  **` | `** (R2-6, R3-S3/S4), in this order: `qty_error` first, verbatim (it is space-joined risk codes OR
  free text: `portfolio.py:251, 258, 281-285`), then `premium_stop_below_one_cent`, then
  `qty_saved_as_<N>` when the same PATCH saved a trimmed qty (`adjusted_qty`, which the late 422 would
  otherwise lose, R2-13). `qty_error` and `adjusted_qty` are set on exclusive branches, so at most one of
  the first and third segments appears. With a single segment the detail is exactly today's string, so
  every existing qty-only 422 renders as it does now.
  - Frontend mapping moves from `portfolio/page.tsx:34-52` into a new `lib/portfolioRejection.ts` (R3-S6:
    an App Router page cannot carry extra named exports): `REJECTION_LABELS`, `rejectionMessage(detail)`
    and `isPartialSave(detail)`. `rejectionMessage` splits on ` | `. Each segment is mapped as today (its
    space-split tokens through `REJECTION_LABELS`, the raw segment when none maps), so a free-text qty error
    is shown verbatim beside the premium label instead of being swallowed. A segment matching
    `^qty_saved_as_(\d+)$` (N2: exact prefix, digits only) maps to "Quantity saved as N (reduced to fit
    exposure)." New label: `premium_stop_below_one_cent` = "Premium stop not saved: at this entry it would
    fire below $0.01 and could never fire."
  - `isPartialSave(detail)` is true when every segment is `premium_stop_below_one_cent` or
    `qty_saved_as_<N>`. The page's banner header (`page.tsx:203`) then reads "{symbol}: some changes were not
    saved:" instead of "{symbol} was not saved:", because the co-sent fields WERE saved.
  - An explicit null (clear → inherit) is never refused.
  - On a 422 the store sets `lastSyncError` (the Portfolio banner, not a toast, N3) and calls
    `syncFromBackend(true)` (`portfolioStore.ts:668-687`), so the optimistic percent reverts while the
    co-sent stop, which was saved, survives.
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
- **Drop reason, on every signal (R1-12, R2-4, R3-S7)**: one helper in `lib/premiumStop.ts`,
  `premiumStopDropReason(requestedDollar: number | null, savedEntry: number | null | undefined)`, returns
  `'total_loss' | 'below_one_cent' | 'unknown'`:
  - `requestedDollar == null` (a fraction-only create) → `below_one_cent`. A schema-valid fraction is in
    (0, 1), and the server drops one only when it is sub-cent.
  - `savedEntry` null, undefined or `<= 0` (the response's `entryPrice` is optional,
    `portfolioStore.ts:552, 1343`) → `unknown`.
  - `premiumStopPctFromDollars(requestedDollar, savedEntry)` undefined (ratio ≥ 1) → `total_loss`.
  - otherwise → `below_one_cent`.
  It feeds all three signals:
  - the `onPremiumStopDropped` callback becomes `(requestedDollar: number | null, reason)`;
  - `addPosition`'s return gains `premiumStopDropReason`;
  - `PremiumStopDropNotice` gains `reason`, and `requestedDollar` becomes `number | null`.
  One text helper, `premiumStopDropText(requestedDollar, reason)` in `lib/premiumStop.ts` (R3-S6), is used by
  step-7's `droppedStopNote` closure (`:550`, now a one-line delegate) and by the Portfolio banner. It reads
  "Premium stop [of $X/share] could not be applied: at the filled premium it is a total loss | at the
  filled premium it would fire below $0.01 | (reason unavailable) — this position inherits the global
  stop." The bracket is omitted when the dollar is null. Detection widens to
  `(premiumStopDollar != null || premiumStopPct != null) && response.premiumStopPct == null` (fraction-only
  creates, S3). After the S2 fallback (§3.1) a response can carry the CLIENT fraction instead of null. That
  is not a drop, and detection is unchanged for it. The `stockDirectSend.ts` callers are a no-op (N7, §0).
  The auto-trade booking (`auto_trade_booking.py`) does not run through these signals. Its drop is the S2
  WARN log only, exactly as its total-loss drop is today. Not widened here.
- **G Settings global**: NOT refused (Q1). One line under the Settings "Premium stop loss" field (N9):
  "For short stock positions this is how far the price may RISE above entry."

---

## 4. Tests (test-first; each named test must fail on main)

Shared fixture: `frontend/lib/__tests__/fixtures/premium_stop_subcent.json`, generated by
`gen_premium_stop_subcent.py` beside it (the `python_round4.json` pattern). It holds `[entry_cents, pct_bp,
is_sub_cent]` rows (R2-15): the grid entries $0.01–$2.00 × pct 10%–99% by 25 bp, **kept only where
`|entry*(1-pct) − 0.01| < 0.005`** (the boundary neighbourhood), short rows `[entry_cents, pct_bp, threshold]` over the same grid with the
Python-computed `entry*(1+pct)` as a float, kept where it is within 0.005 of a whole cent (N6), plus the full
`d = e − $0.01` family for
$0.02–$50.00 as `[entry_cents, dollar_cents, is_sub_cent]`. CI's checkout is the whole repo, but pytest runs
from `backend/` (`ci.yml:24-25`), so the backend test resolves it as
`Path(__file__).resolve().parents[2] / 'frontend/lib/__tests__/fixtures/premium_stop_subcent.json'` (R2-12).

Frontend (Jest):
- `lib/__tests__/alertEngine.test.ts`: short stock fires at `>= entry*(1+pct)` (the COMPUTED threshold, N6)
  and not on a fall; boundary equality on both sides; short reason is price-only; `referenceValue` is the
  direction-aware threshold; `stopSide` is stamped per side. Regression guards (pass on main too, N8): long
  stock unchanged; Bearish option still fires on a fall.
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
  option; an UNSTAMPED row for a short position reads the legacy `Premium stop (–X%)` (R3-S5); toggle list
  and type-name tables read the neutral label.
- `lib/__tests__/p2PortfolioStore.test.ts`: fraction-only create with `premiumStopPct == null` in the response
  queues a notice with reason `below_one_cent` and a null dollar; `below_one_cent`, `total_loss` and
  `unknown` (no `entryPrice` in the response) on all three signals; a response carrying the client fraction
  (S2 fallback) is not a drop.
- `lib/__tests__/premiumStop.test.ts` also: `premiumStopDropReason` on all four branches;
  `premiumStopDropText` for each reason, with and without a dollar (R3-S6).
- `app/(frame)/screener/step-7-trade-card/__tests__/edited-fields-sync.test.tsx` (its existing
  `droppedStopNote` render tests at :863, :882): the rendered note names the reason. The existing regexes
  still match, because the new text keeps the "Premium stop of $X/share could not be applied" prefix.
- `lib/__tests__/alertStore.test.ts`: §2.4's short-key tests (acknowledged legacy key + open legacy row → a
  new rise-side row is added and notifies; acknowledging it suppresses only the `:short` key; `collapseToasts`
  keeps one legacy and one short row); a long's and an option's keys unchanged (regression guards);
  STRUCTURAL_STOP_BREACHED stays off after `useAlertStore.persist.rehydrate()` of a v3 blob without it
  (regression guard, R3-B2); `notifyBackend` posts `stopSide`.
- `lib/__tests__/portfolioRejection.test.ts` (new, R3-S6): `rejectionMessage` on
  `"single_trade_exposure_too_high | premium_stop_below_one_cent"` shows both labels; on each free-text
  qty error (`portfolio.py:251, 258, 281-285`) joined with the premium code, the free text is shown verbatim
  AND the premium label (R3-S3); `qty_saved_as_3` maps, `qty_saved_as_x` and `xqty_saved_as_3` do not (N2);
  single-segment details render exactly as before; `isPartialSave` true only for premium / qty-saved
  segments. The Portfolio page has no render test, so `isPartialSave` is the unit under test and the page's
  header line is a one-expression use of it.
- `components/organisms/AutoTradeArm/__tests__/AutoTradeArm.test.tsx`: sub-cent warning shown; Arm still
  enabled.

Backend (pytest):
- `tests/test_alerts.py` (already has Bearish `|STOCK` fixtures at :191, :350-400): short fires on a rise and
  not on a fall; `reference_value` direction-aware; `stopSide` stamped; `opt_price == 0.0` does not fire
  (fails on main). Regression guard: Bearish option unchanged.
- `tests/test_premium_stop_per_position.py`: helpers + the shared fixture.
- `tests/test_portfolio_update.py`: sub-cent → 422 string detail `premium_stop_below_one_cent`,
  `premium_stop_pct` unchanged, a `stop` in the same PATCH saved; null clear allowed; qty + premium failures
  produce `"<qty_error> | premium_stop_below_one_cent"` (one free-text and one code-list qty error);
  trimmed qty + premium → `"premium_stop_below_one_cent | qty_saved_as_<N>"` and the trimmed qty is saved;
  a qty-only failure's detail is byte-identical to main's; a short at a sub-penny entry is NOT refused.
- `tests/test_position_writer.py`: sub-cent from dollar (incl. $0.02 on $0.03) → None + WARNING, 201; sub-cent
  fraction fallback → None; valid unchanged; short sub-penny entry kept.
- `tests/test_alert_notifier.py`: side-aware PREMIUM_STOP label (None → legacy); a `short-stock` fire uses the
  `…|PREMIUM_STOP:short` key, so with a legacy `…|PREMIUM_STOP` entry in `_fired` and `_first_seen` it is
  sent and is NOT a reminder; the key survives `_save_dedup` → `_load_dedup`; `forget_alerts` drops both
  keys; a non-PREMIUM_STOP type ignores `stop_side`.
- `tests/test_alert_notify_guard.py`: the side is derived from the DB
  row; a request without `stopSide` for a short row uses the legacy key and label (stale-tab case); a
  request claiming `stopSide: 'option'` for a short row still gets `short-stock`.
- `tests/test_position_writer.py` also: a sub-cent dollar with a valid client fraction stores the fraction
  (R2-5).

Mutations to run and record: swap `>=`/`<=` on the short branch; drop the `isStock` term (options must break);
drop the late raise (the stop-alongside test must break); drop the backend `> 0` guard; give the short flag a
default (typecheck / pytest signature test must break); drop `':short'` from either store's key (the
legacy-key tests must break); join PATCH segments with a space (the free-text test must break).

---

## 5. Files

Backend: `app/services/premium_stop.py`, `app/services/alert_generator.py`, `app/routers/portfolio.py`,
`app/services/position_writer.py`, `app/services/notifications/alert_notifier.py`,
`app/services/portfolio_alert_monitor.py`, `app/routers/alerts.py` (`AlertNotifyRequest.stopSide`, side
derivation), `app/schemas/__init__.py` (`AlertItem.stopSide`), plus tests. `auto_trader.py` needs no change
(the new parameter is optional).
Frontend: `lib/premiumStop.ts`, `lib/alertEngine.ts`, `lib/portfolioStore.ts`, `app/(frame)/portfolio/EditDrawer.tsx`,
`lib/portfolioRejection.ts` (new), `app/(frame)/portfolio/page.tsx` (banner reason and header, imports the
mapper), `app/(frame)/alerts/page.tsx`, `app/(frame)/settings/page.tsx`, `components/organisms/AutoTradeArm/index.tsx`,
`lib/alertStore.ts` (`alertKey`, `notifyBackend`'s `stopSide`), `types/domain.ts`,
`app/(frame)/screener/step-7-trade-card/page.tsx`, plus tests and the fixture + generator. Not touched:
`dashboard/page.tsx`, `lib/stockDirectSend.ts`. TradeCard consumes
`premiumStopDollarBounds` unchanged.
Ledger: phase `STOP-SEMANTICS` with a verify probe on `premium_stop_is_sub_cent` and `isShortStockPosition`.
Close the two open questions and the round_13 sub-cent item on merge.

## 6. Questions for Kenneth (recommendation first) — ANSWERED 2026-10-02: all five recommendations (26d9fd0)

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

## 9. Plan round 3 findings — APPLIED in v4 (Kenneth: write v4 and build from it)

Where each went: R3-B1, R3-B2, R3-S1, N4, N5 → §2.4 (separate `:short` dedup key; no reset, no store
version bump) and §2.2. R3-S2 → §2.2 notifier callers. R3-S3, R3-S4, N2, N3 → §3.1. R3-S5 → §0 and §2.2.
R3-S6 → §3.1 (`lib/portfolioRejection.ts`), §3.2 (`premiumStopDropText`) and §4. R3-S7 → §3.2. N1 → §2.2.
N6 → §1 and §4. N7 → §0 and §3.2. N8 → §4. N9 → §3.2.

The original findings, as recorded at a0a4169:

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
Kenneth chose (2026-10-02) to write v4 and build from it (the WATCH-RESEND-P1-BUILD-FROM-V4-2026-10-02
precedent). The build is then held to the adversarial CODE audit loop until a round comes back clean.

## 10. Build notes (v4 build, 2026-10-02) — where the code differs from the text above

- **Backend tests** for the helpers, the shared fixture, the engine, the PATCH refusal and the create fallback live
  in one new module, `backend/tests/test_stop_semantics.py`, not spread over `test_alerts.py`,
  `test_premium_stop_per_position.py`, `test_portfolio_update.py` and `test_position_writer.py`. Notifier tests are
  in `test_alert_notifier.py`, notify-route tests in `test_alert_notify_guard.py`, as planned.
- **Notify route, absent `stopSide`**: the server passes `stop_side=None` for EVERY row when the request carries no
  `stopSide` (not only for shorts). For a long or an option, None and the derived side share one dedup key, and the
  only difference is the label ("Premium stop hit" rather than "Stock stop hit"), which is the legacy label a
  pre-deploy tab's fire should carry.
- **Fixture short rows** are kept where the computed threshold is within 1e-6 of a whole cent (the rows where float
  noise decides the firing cent), not within 0.005; entries are stepped to keep the file at ~200 KB.
- **The noisy short example** is $100.00 at 10% → 110.00000000000001 (fires at $110.01). §1's first draft said
  $10.00 at 10%, which is exactly 11.0.
- **Settings hint** is two lines: the long/option limit ("… it can never fire.") and N9's short line.
- **Mutations run** (each broke the named tests, then was reverted): short `>=` → `<=` in `alertEngine.ts` (3 engine
  tests fail); `isShortStockPosition` without the `|STOCK` term (the Bearish-option guard fails); `alertKey` without
  `:short` (3 store tests fail). Backend: see the code-audit record. A DEFAULT on the TS short flag is not caught by
  `tsc` (every caller passes it explicitly); only the backend has a signature test.
