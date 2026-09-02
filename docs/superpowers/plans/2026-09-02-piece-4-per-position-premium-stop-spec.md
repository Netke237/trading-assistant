# Piece 4 — a per-position premium stop

**Date:** 2026-09-02 · **Status:** specification, nothing built.
**Independent of every other piece.** Can be built in parallel with the barrier race.
**Delivers:** the second half of Kenneth's stated condition — *"set my stop loss both based on stock
price and premium price"*. The stock-price side already exists (the structural + ATR final stop).

---

## 1. The problem

There are **three** global premium-stop percentages and **no per-position field at all**:

| Where | Read by |
|---|---|
| `risk_rules.yaml → reward_risk.premium_stop_pct` | `trade_plan.py`, `reward_risk.py`, `alert_generator.py:295` |
| `risk_rules.yaml → auto_trade.premium_stop_pct` | `auto_trader.py:254,352` |
| `settingsStore.premiumStopPct` | `alertEngine.ts` |

So every open position shares one number. Changing it silently re-arms every position at once, and
a conviction trade cannot be given more room than a speculative one.

`PortfolioPositionModel` already carries `stop` and `structural_stop` — a per-position *stock* stop.
The premium side has no equivalent.

---

## 2. Database

```python
# backend/app/models/portfolio.py — PortfolioPositionModel
premium_stop_pct = Column(Float, nullable=True, default=None)
```

**Nullable, defaulting to NULL — not to 0.60.** NULL means *"inherit the global"*, and that is a
different, load-bearing state: a position stamped 0.60 at creation would stop responding when the
global changed, which is precisely the behaviour that exists today and that this piece removes.
Every read site resolves `position.premium_stop_pct ?? global`.

Alembic migration, one column, nullable, no backfill. **Check `alembic heads` before generating** —
this repo has had a multiple-heads incident before (`2026-07-17-alembic-merge-heads-ghost-alert-audit.md`).

## 3. Schemas — `backend/app/schemas/__init__.py`

| Class | Change |
|---|---|
| `PortfolioPosition` (:285) | `premium_stop_pct: Optional[float]` |
| `PortfolioPositionCreate` (:612) | `premium_stop_pct: Optional[float] = None` |
| `PortfolioPositionUpdate` (:656) | `premium_stop_pct: Optional[float] = None` |
| `PortfolioPositionSchema` (:702) | same |

**Watch the create/update asymmetry.** `active_tp_method` / `resolved_tp_price` are on the *update*
schema only and absent from `PortfolioPositionCreate` (handoff #4 §7 fact 4). Do not repeat that:
`premium_stop_pct` must be settable **at creation**, or a trade sent from the card cannot carry the
per-trade stop the user just chose, and would silently fall back to the global on its first alert.

Validation: `0 < pct < 1`. A value of 1.0 is a total loss and makes the stop unreachable-by-definition
rather than a stop; 0 is meaningless. Reject both rather than storing them.

## 4. The three alert paths

All three currently read a global. Each must resolve per-position first.

| Path | Today | Change |
|---|---|---|
| `backend/app/services/alert_generator.py:295,299,305` | `_premium_stop_pct()` — module-level global read | Take the position's value, `?? _premium_stop_pct()`. The emitted `thresholdPct` field must carry the **resolved** value, not the global, or the alert's own payload misreports why it fired |
| `frontend/lib/alertEngine.ts` | `scanPortfolio(positions, { premiumStopPct })` — one number for all | Resolve per position inside the loop; keep the settings value as the fallback argument |
| `EditDrawer`'s `alertFiresAgainst` | global | Same resolution, so the drawer's preview matches what will actually fire |

**These three must agree.** A preview that disagrees with the alert that later fires is worse than
no preview. One shared resolver, used by all three, tested once.

## 5. `auto_trader.py` — decide explicitly, do not leave it ambiguous

`auto_trader.py:254` and `:352` size off `auto_trade.premium_stop_pct`, a **different** global from
the one the alerts use. Two options, and the spec must pick one:

- **(chosen)** Thread the per-position value through, `?? auto_trade.premium_stop_pct`. The
  auto-trader is placing the same trade the card described; sizing it off a different number than the
  one the user set is a silent divergence.
- (rejected) Leave it and write a comment. That is how three globals happened.

## 6. Frontend

The card's existing editable **Premium stop** field (`overlay.premiumStop`, a dollar value) becomes
the source. It is stored as a **percentage**, derived at send time:
`premium_stop_pct = overlay.premiumStop / entryLimit`, clamped to `(0, 1)`.

Why percent and not the dollar amount: the alert compares `opt_price <= entry_price * (1 − pct)`.
Storing dollars would need re-deriving the ratio at every comparison against an `entry_price` that
may itself have been edited, and the two would drift.

`buildPaperPosition` and `positionFromOrder` must **both** carry it. These are the two send paths that
already disagree about stop re-anchoring (handoff #4 §7 fact 3) — do not add a second field on which
they disagree. Grep both; a test asserts they produce the same `premium_stop_pct` for the same input.

The Portfolio `EditDrawer` gets an editable field, so an open position's premium stop can be changed
after entry. Display must distinguish **inherited** from **set**: `"60% (global)"` vs `"45%"`. An
inherited value that looks set is how a user comes to believe they have per-position control they
do not have.

## 7. Interaction with the barrier race

The race's third barrier reads the card's `overlay.premiumStop` (decision Q10), which is the same
field this piece persists. Once both ship, the barrier the race simulated and the barrier the alert
fires on are the same number by construction. **Neither piece blocks the other**, and neither needs
the other's schema.

## 8. Tests

1. Migration applies and rolls back; `alembic heads` yields exactly one head afterwards
2. NULL resolves to the global; a set value wins
3. Changing the global moves NULL positions and leaves set positions alone
4. `pct` of 0, 1.0 and negative are all rejected at the schema
5. `premium_stop_pct` survives a create — not update-only (the `active_tp_method` trap)
6. All three alert paths fire at the same price for the same position — one shared resolver
7. `alert_generator`'s emitted `thresholdPct` is the resolved value, never the global
8. `buildPaperPosition` and `positionFromOrder` produce the same value for the same card state
9. `auto_trader` sizes off the resolved value
10. EditDrawer shows "(global)" for NULL and the bare number when set

## 9. Out of scope

- Arming anything at a broker. D10 stands: this is an in-app alert threshold.
- Existing open positions. D11: they stay NULL and keep inheriting the global. No backfill.
