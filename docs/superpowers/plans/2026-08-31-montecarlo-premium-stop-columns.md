# Monte Carlo R:R columns — REJECTED, with the proof

**Status: rejected after two adversarial audit rounds. Do not implement.**
Kept as a decision record so the idea is not re-proposed a third time.
**Branch:** `claude/tradecard-setstate-render-wo6eru`

---

## The ask

Add a reward/risk column to the Monte Carlo profit-target rows that carries more information than
the existing **R:R vs. structural stop**, which degenerates into echoing the user's typed profit
target. Motivating complaint: *"I don't want to take trades where the system sees me losing my
entire premium as maximum risk."*

## Two designs proposed, both dead

| Draft | Denominator | Reduces to | Multiplier vs. typed target |
|---|---|---|---|
| 1 | `overlay.premiumStop` = `premium × premiumStopPct` | `pct / premiumStopPct` | **1.667×** |
| 2 | `maxLossAtStop(premium, exitPlan.stop.contractPrice, 1)` | `pct / lossFraction` | **1.068×** |

Draft 2 was written specifically to fix draft 1 and came out **worse** — closer to echoing the typed
target than the design it replaced.

## Why — the general result

The numerator is not free. The backend defines the target option price as
`premium × (1 + pct)` (`first_passage.py:185`), so:

```
reward = premium × pct        — ALWAYS, by construction
```

Therefore, for `R:R = reward / risk` to differ between two contracts at the same typed `pct`, the
**denominator must not be proportional to premium**. Check each candidate:

- `premium × premiumStopPct` — proportional by definition. `R:R = pct / premiumStopPct`.
- `premium − stopContractPrice` — `stopContractPrice` is Black-Scholes-repriced *from* premium
  (`reward_risk.py:96`), so this is `premium × lossFraction`. `R:R = pct / lossFraction`. Verified
  numerically on the CVX contract: 0.2136 / 0.3737 / 0.5339 for 20/35/50% — a flat 1.0678× across
  all three rows.
- `min(stockMove × delta, premium)` — the existing cell. The uncapped branch is genuinely
  independent of premium and **does** discriminate. The capped branch is `premium`, giving
  `R:R = pct`.

So the existing column is the only one of the three that can carry contract-specific signal at all,
and it loses that signal exactly when the cap binds.

## The part that makes this not a bug

When the cap binds — `stockMove × delta ≥ premium` — the risk **is** the whole premium. That is not
an approximation artifact; a long option cannot lose more than it cost. And if risk = premium and
reward = premium × pct, then:

```
R:R = (premium × pct) / premium = pct
```

**For any long option whose stop sits beyond total premium loss, every honest R:R equals the profit
target percentage.** It is arithmetic, not a display defect. There is no denominator that repairs
it, because there is nothing to repair.

The existing cell is already correct. Reading `0.2×` next to a 20% target as a malfunction was the
actual error — the cell was reporting, accurately, that the structural stop on that contract is a
near-total loss of premium.

## What to build instead

The quantity that *does* vary per contract, and that actually answers the motivating complaint, is
not a ratio — it is the **loss fraction**:

```
lossFraction = (premium − stopContractPrice) / premium      // 93.7% on the CVX contract
```

"This stop costs 94% of your premium" is contract-specific, directly actionable, and needs no new
R:R. Paired with a CAUTION/REJECT gate at a threshold, it is the feature originally wanted. Both
audit rounds independently pointed back at this.

**Not specced here** — the premise changed enough that it needs its own plan and its own sign-off.

## Other findings worth keeping

Surfaced by the audits, true independent of this feature, and none of them fixed:

1. **Neither "stop" on the card is enforced.** The position sent to a broker uses
   `card.exit.invalidation` (`step-7-trade-card/page.tsx:99, 622`). `overlay.premiumStop` is
   display-only (the real `PREMIUM_STOP` alert fires off the global `settingsStore.premiumStopPct`,
   `alertEngine.ts:100-101, 225`), and `exitPlan.stop.price` reaches no alert or order path. Any UI
   copy calling either one "your stop" is false.
2. **`stop.contractPrice` reprices at half the time to expiry** (`reward_risk.py:82`,
   `dte_at_target = max(expiry_years × 0.5, 7/365)`), so it answers "the stop is hit *and* half the
   remaining time burned off". This is why a 109-DTE contract shows a ~94% loss at its stop, and it
   flows into `recommendedSize` — i.e. into the Apply button's position sizing.
3. **Three premium baselines coexist:** `overlay.entryLimit` (user-editable, drives the Risk/Reward
   card), `data.contractDetails.mid` (scan-time, drives `recommendedSize`), and
   `firstPassageContext.premium` (fresh, drives the Monte Carlo estimate). They can all differ at
   once, and `risk.ts:241-250` already documents the hazard.
4. **The Monte Carlo probability is an option-value barrier**, not a stock-price one —
   `hit_mask = option_paths >= target_option` (`first_passage.py:226`). The Invalidation row's
   probability, by contrast, *is* a stock barrier (`:241`). The card presents both without
   distinguishing them.
5. **`dte < 1` returns `probability = 0.0` for every target** (`first_passage.py:195-205`) — a
   refusal to simulate, not a real zero. The Intraday horizon hits this routinely.

## Audit trail

| Round | Findings | Outcome |
|---|---|---|
| 1 | 20 (4 CRITICAL, 6 HIGH) | Draft 1 rejected; design rewritten |
| 2 | 16 (2 CRITICAL, 5 HIGH) | Draft 2 rejected; premise found unsound |

Loop stopped per `K-adversarial-audit-loop` — the same class of defect recurred across two
independent designs, which is a signal to escalate rather than iterate.
