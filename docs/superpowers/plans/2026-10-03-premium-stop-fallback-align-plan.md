# PREMIUM-STOP-FALLBACK-ALIGN — plan

Decision: `PREMIUM-STOP-FALLBACK-USER-FRACTION-2026-10-03` (Kenneth, option C + page).
Gate (audit_rule): a wrong number in front of a user or on a broker order, or corrupted persisted data.

## 0. The behaviour today

`position_writer.create_position` derives `premium_stop_pct = premiumStopDollar / entry_price`
against the PERSISTED entry (possibly a live re-anchor). When that ratio is not in (0, 1), or
the result is sub-cent at the persisted entry, it falls back to `body.premiumStopPct` (itself
dropped to None if sub-cent). So:

- **Armed auto-trade path** (`auto_trade_booking._build_body`) sends `premiumStopPct =
  s.premium_stop_pct`, the dollar's ratio at ARM time → falls back to the user's own fraction.
  Nothing pages; only a log line.
- **Card paths** (Step 7 `buildPaperPosition` / `positionFromOrder`, via `toBackendBody`) send
  the dollar but `premiumStopPct` is unset on a fresh card position → the fallback is None →
  the position inherits the GLOBAL. The client sees a null `premiumStopPct` in the 201 and shows
  "could not be applied … inherits the global stop" (`premiumStopDropOf` / `premiumStopDropText`).

Reachable through an ordinary fill: $4.50 typed on a $5.20 mid (86.5%), filled at $4.20.

## 1. Frontend — card paths post the user's fraction (one layer, ~60 lines)

1. `step-7-trade-card/page.tsx`: add ONE closure beside `premiumStopDollarFor`:
   `premiumStopPctFor(card, entry) = premiumStopPctFromDollars(premiumStopDollarFor(card), entry) ?? null`
   where `entry` is the SAME `mid` each path stores as `entryPrice` (the divisor the arm path
   already uses, `AutoTradeArm` line ~400). Null when the dollar is untouched (→ inherit global,
   unchanged) or is itself ≥ the mid (unchanged: nothing usable to send).
   - `buildPaperPosition`: set `premiumStopPct: premiumStopPctFor(card, mid)`.
   - `positionFromOrder` is module-level: compute the fraction inside it from its own
     `premiumStopDollar` argument and its own `mid` (no new parameter needed), so the fraction
     and `entryPrice` cannot use different denominators.
   `toBackendBody` already posts `premiumStopPct` when in (0, 1); the writer still prefers the
   dollar when usable, so the ordinary case is unchanged.
2. The optimistic local row now carries the client fraction paired with the client `mid` as its
   entry — a consistent pair until the 201 replaces both (`adoptSaved…` already adopts the
   server's pct and entry together). Offline/pending retries re-POST both fields; the writer
   re-derives from the dollar at the then-persisted entry. No persisted-store shape change, no
   version bump (`premiumStopPct` is already a persisted row field).
3. Drop detection (`portfolioStore.premiumStopDropOf`) — the existing "inherits the global" note
   would now go SILENT in exactly the case it exists for (the 201 carries the user's fraction,
   non-null), while the stored stop differs from the dollar the card showed. Extend it:
   - dollar sent AND not applicable at the saved entry (`premiumStopPctFromDollars(dollar,
     savedEntry) === undefined`, or `premiumStopIsSubCent(savedEntry, dollar/savedEntry, false)`)
     AND saved pct non-null → a notice with `keptPct = savedPct` and the existing reason.
   - saved pct null → unchanged (true drop to the global).
   - dollar applicable → null (unchanged).
   `PremiumStopDropNotice` and the `addPosition` result gain an optional `keptPct`;
   `premiumStopDropText(requested, reason, keptPct?)` ends "— this position keeps your
   N% of the premium as its stop instead." when `keptPct` is set, else the existing
   "inherits the global stop" ending. EVERY site that carries a drop passes `keptPct` through
   (plan round 1 finding: an optional field type-checks when one is forgotten):
   - `portfolioStore.addPosition`'s result (`~1095-1101`) → the Step 7 basket note (`page.tsx ~1359`);
   - `applyPersistedPosition`'s `onPremiumStopDropped(requestedDollar, reason, keptPct?)`
     callback signature (`portfolioStore ~533-544`) → `droppedStopNote` at both direct-send
     call sites (`page.tsx ~1177, ~1225`);
   - the pending-row retry in `syncFromBackend` (`portfolioStore ~1339-1354`), which builds the
     `PremiumStopDropNotice` LITERAL field by field and is the ONLY writer of
     `premiumStopDropQueue` / `lastPremiumStopDropped` → `keptPct: drop.keptPct` there;
   - the Portfolio banner (`portfolio/page.tsx ~196-200`) passes `lastPremiumStopDropped.keptPct`. Percent printed with the existing `premiumStopPctLabel`-style
   2dp trim (no rounding to a misleading whole percent).
   Short-stock: card sends are options only; `premiumStopDropOf` passes `shortStock=false`
   as `premiumStopDropReason` already does implicitly.

## 2. Backend — the writer reports it, the booking pages it (~50 lines)

1. `WriteOutcome.premium_stop_unapplied: Optional[str] = None` — set when
   `body.premiumStopDollar is not None` and the FINAL stored `premium_stop_pct` is not the
   dollar's ratio (total loss, non-positive entry, or sub-cent). The string names the dollar,
   the persisted entry, the reason and what was stored (`N% (your arm-time fraction)` or
   "nothing — inherits the global"). Computed with an explicit `dollar_applied` flag set in
   the `0 < ratio < 1` branch and cleared by the sub-cent branch — no float comparison.
   No change to what is stored.
2. `auto_trade_booking`: `_ALERT_TYPE_PREMIUM_STOP_UNAPPLIED =
   "AUTO_TRADE_BOOKED_PREMIUM_STOP_UNAPPLIED"`, rec-id key `auto-trade-premium-stop-unapplied`,
   `_alert_premium_stop_unapplied(fired, rec_id, detail)` through `_page`, fired after the
   wrong-side alert on the committed path. `BookingOutcome.premium_stop_unapplied: bool = False`.
   The post-commit "UNVERIFIED" alert text adds the premium stop to what was not checked.
3. Card path: the router ignores the new `WriteOutcome` field (the client detects it from the
   201 as in §1.3). No API shape change.

## 3. Tests

Backend:
- writer: dollar ≥ persisted entry with a client fraction → stored = client fraction,
  `premium_stop_unapplied` set and names the fraction; with no fraction → None stored, detail
  says inherits the global; sub-cent dollar → detail set; usable dollar → None.
- booking: a fired order whose arm-time dollar is ≥ the live fill pages
  `AUTO_TRADE_BOOKED_PREMIUM_STOP_UNAPPLIED` with the per-symbol rec id, stays booked, row holds
  the arm-time fraction; an ordinary booking does not page it.
Frontend:
- `premiumStopDropOf`: kept-fraction case, true-drop case, applicable case.
- `premiumStopDropText` with and without `keptPct`.
- portfolioStore: a PENDING row carrying a dollar and a fraction, retried by
  `syncFromBackend` against a 201 that stores the client fraction (dollar ≥ saved entry) →
  the queued notice carries `keptPct` and `premiumStopDropText` of it says "keeps your N%";
  `applyPersistedPosition` passes `keptPct` to `onPremiumStopDropped`.
- Step 7: both send paths post `premiumStopPct = dollar / the stored entryPrice` when touched,
  null when untouched (extend the existing round-9 "two send paths agree" test).
Each new assertion is shown to fail with its guarded line broken.

## 4. Out of scope (logged, not built)

- A dollar ≥ the LIVE mid on the card (client sends no fraction → global, existing note fires).
- The `/fire` snapshot and PATCH qty races; weighted-average entry (separate open questions).
