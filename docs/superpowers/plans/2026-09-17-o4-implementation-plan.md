# O4 — implementation plan

**Status: PLAN, not built. Written 2026-09-17 on `claude/o4-auto-trade-books-a-position-2026-09-15`.**

This plan implements `docs/superpowers/plans/2026-09-15-o4-auto-trade-books-a-position-spec.md`.
The spec owns the *design* — its §3 decisions, §6 rules and §9 non-goals are settled and this plan
does not reopen any of them. This plan owns the *execution*: what the spec's claims look like against
today's code, the concrete edit list per step, and the gate each step ends on.

---

## 0. Why this plan exists at all

The spec was written **2026-09-15** and `main` has moved **29 commits** since, including a merge
(`fc451c2d`, 2026-09-17) that changed `auto_trader.py` itself. A spec that cites line numbers is a
spec that rots. §1 below is the re-verification; it is the first deliverable, and it is why no code
is written in this document.

---

## 1. The spec re-verified against `a6c1883f` — every structural claim HOLDS, every line number MOVED

Each row was executed against the current tree, not remembered.

| Spec claim | Spec's anchor | Today | Verdict |
|---|---|---|---|
| `fire()` clears `_state.strategy` before executing | `auto_trader.py:198`, `:224-225` | `:196`, `:223` | **holds**, −2 |
| `fire()` returns `OrderResult` alone | `:298` | `:296` (`return result`) | **holds**, −2 |
| `_apply_vol_sizing` returns a NEW strategy via `_dc_replace` | `:228` | defined `:110`, called `:226`, `_dc_replace` at `:138` | **holds** |
| `maybe_fire_on_scan` returns `None` unconditionally | `:325` | `:323` | **holds**, −2 |
| `OrderResult` has no fill price | `ibkr_paper.py:85-89` | `:85-89`, four fields | **holds, exactly** |
| `add_position` is the fat create path | `portfolio.py:145-535` | `:146-541` | **holds**, +6 at the tail |
| exposure gate / `risk.approved` 422 | `:329-343` | `check_position_risk` `:328`, `if not risk.approved` `:337` | **holds** |
| `risk.adjusted_size` shrinks qty | (implied by §5.2) | `:457` — `qty=risk.adjusted_size or body.qty` | **holds** — this is the exact line §5.2 branches |
| `seed_tp_from_pick` runs in the create path | §2.7 | `:441` | **holds** |
| `log_approval` is guarded, never 500s the response | `:522-527` | `:530-535` | **holds**, +8 |
| `PortfolioPositionCreate` requires recId/symbol/contract/direction/entryPrice(gt=0)/entryDate | `schemas/__init__.py:855` | `:884-898`, all six confirmed required | **holds**, +29 |
| `fire_now` holds `db` and queries positions | `auto_trade.py:94`, `:99-101` | `:95`, `:101-103` | **holds**, +1..+2 |
| scan path holds `db` on both sides of `to_thread` | `scan.py:1697`, `:1691-1700` | `:1763`, `:1757-1766`; `db.execute` at `:1759` | **holds**, **+66** |
| the tripwire test exists and asserts `rows == []` | `test_phase_g_arm_pick.py:304` | `:304` | **holds, exactly** |
| `ArmRequest` has no stop/direction/plan | `auto_trade.py:16-78` | `:16-…`, confirmed absent | **holds** |

**Conclusion: the spec is sound and buildable as written.** No decision in §3 is invalidated. The
only remediation needed is line-number refresh, and the scan call site has moved furthest (+66) — do
not navigate that one by the spec's number.

**One thing the merge changed that the spec could not have known.** `_apply_vol_sizing` now calls
`conviction_mult` from `scoring/conviction_sizing.py` (`auto_trader.py:12`, `:128`) — the shared ramp
merged at `fc451c2d`, replacing the local clamp. This *strengthens* §2.1 rather than threatening it:
the quantity that reaches the broker still differs from the armed quantity, still via `_dc_replace`
(`:138`), and now differs **more often**, because the ramp moves on every conviction where the old
clamp was flat across the bottom half of the scale. §2.1's "the strategy handed back must be the
post-sizing one" is therefore a sharper requirement today than when it was written, and test 2 (§8)
matters more.

---

## 2. Build order — six steps, each ending green

The spec's §11 order is correct and is kept. What follows is the concrete edit list per step.

**Every step ends on all four gates:**
`cd backend && pytest -q` · `cd frontend && npm run test` · `npm run typecheck` · `python3 scripts/state.py`

### Step 1 — extract `create_position` (spec §5.1)

- **New** `backend/app/services/position_writer.py` with
  `async def create_position(body, db, *, enforce_pre_trade_gates=True) -> tuple[PortfolioPositionModel, Optional[int]]`.
- Move `portfolio.py:146`'s body — duplicate-contract 409 through `await db.refresh(position)` (`:527`)
  — **verbatim**. Do not tidy it in passing; a behaviour-preserving move is the only thing that makes
  the existing suite a valid proof.
- `add_position` becomes a wrapper that calls it and then does the two router-only things:
  `log_approval` (`:530-535`) and the `PortfolioPositionSchema.from_orm_model` + `adjustedQty`
  response (`:538-539`).
- **Gate:** the whole existing `POST /api/portfolio` suite passes **unedited** (spec test 10). An
  edit needed here means the extraction was unfaithful — revert and redo, do not amend the test.

### Step 2 — `enforce_pre_trade_gates` (spec §5.2)

- Branch exactly two places: `if not risk.approved` (`:337`) → warn-and-continue; and
  `qty=risk.adjusted_size or body.qty` (`:457`) → `body.qty` when gates are off.
- Wrong-side-stop guard → warn instead of raise when gates are off.
- Must stay ON in both modes: the 409, the live refetch, the re-anchor, the `entryPrice` replacement,
  the premium-stop derivation, `seed_tp_from_pick`.
- No caller passes `False` yet. Unit-test both branches.

### Step 3 — grow the wire (spec §4.1, §4.2, §4.4)

- Eleven Optional snake_case fields on `ArmRequest`, same eleven on `ArmedStrategy`, carried by the
  existing `ArmedStrategy(**req.model_dump())` at `auto_trade.py:81`.
- Bounds per §4.1: `stop` `gt=0`, `scan_stock_price` `gt=0`, `structural_stop` `gt=0`,
  `dte_total` `ge=0`, `premium_stop_dollar` `gt=0`.
- Fields travel and are unread at the end of this step. Say so plainly in the commit message — this
  is the same shape as Phase G build step 5.
- **Do not** add `extra='forbid'`. That is G5-1 and it is sequenced after O4 (spec §9.6).

### Step 4 — `FiredOrder` + `book_fired_order`, wired to `/fire` (spec §5.3, §6)

- `@dataclass FiredOrder{result, strategy}`; `fire()` returns it instead of `OrderResult`
  (`:296`). Every raise path unchanged.
- **New** `backend/app/services/auto_trade_booking.py` —
  `async def book_fired_order(fired, db) -> BookingOutcome(booked, rec_id, error)`, which
  **never raises** (§6.1) and applies the four refusals (§6.2, §6.3).
- `rec_id` generated here, not at arm time (§4.3).
- Call from `fire_now` **after and outside** the existing `try/except` at `auto_trade.py:104-110`;
  response grows `booked` / `rec_id` / `book_error` (`:111`).
- **`fire()`'s signature change has callers beyond these two — find them before editing.** Tests call
  it directly.
- Replace the tripwire `test_phase_g_arm_pick.py:304` here. Spec tests 1–8 and 11 land here.

### Step 5 — the scan path (spec §5.3 caller 2)

- `maybe_fire_on_scan` returns `Optional[FiredOrder]`; its `except Exception` and `logger.error` stay
  exactly as they are (§9.4).
- At `scan.py:1762-1766`, take the `to_thread` return value and `await book_fired_order(fired, db)`
  **on the event loop** — `db` is already in scope (`:1759`). A booking failure logs and does not fail
  the scan. Spec test 9.

### Step 6 — frontend (spec §7)

- `AutoTradeArm` sends the eleven fields; `stop` reads **the same expression** `stopMissing` is
  derived from at `AutoTradeArm/index.tsx:169`. Five new props resolved at the Step-7 call site.
- `handleFireNow` renders a **caution** (not an error) on `booked: false`, naming the missing stop
  alert in plain words.
- `frontend/lib/api.ts` widens `fireAutoTrade`'s return type. Spec tests 12–13.

---

## 3. Risks this plan is carrying, named

1. **The extraction (step 1) is the whole bet.** If `create_position` is not faithful, every later
   step inherits a silent behaviour change on the *card* path — the path that works today. The
   unedited-suite gate is the only thing standing there, so it is not negotiable.
2. **`fire()`'s return type is a breaking change inside the repo.** Step 4 must sweep every caller,
   tests included, in the same commit.
3. **Phantom positions are accepted, not solved** (spec §3.2/§9.2). A resting LMT that never fills
   books a position anyway, exactly as the other eight paths do.
4. **§6.2 refuses to book a stopless position**, which means a fired order can still end with no
   record. That is deliberate, the counter-argument is written into §6.2, and spec §10.2 flags it as
   Kenneth's to reverse — if he does, only §6.2 and test 5 change.

---

## 4. Bookkeeping this build must not forget

`PROJECT_STATE.json` has no `already_shipped` entry for O4 (`active_phase_note` says so). The
audit-bookkeeping probe scopes its round counting to `active_phase`'s target, so **create the entry
when the first code lands in step 1**, or the branch's rounds are reported as unphased work.

---

## 5. The gate before building

The spec's own last line: **"Before any of it: one adversarial round on this spec."**

That has **not** run. This plan does not substitute for it — §1 re-verified the spec's factual
anchors against current code, which is a different question from whether its design is right. Per
`audit_rule`, one adversarial round on the spec (and on this plan) comes before step 1.
