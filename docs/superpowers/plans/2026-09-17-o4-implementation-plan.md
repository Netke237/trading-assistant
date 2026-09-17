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
| `ArmedStrategy(**req.model_dump())` carries fields by name | spec §4.1: `auto_trade.py:81` | **`:83`** — `:81` is `async def arm(...)` | **holds, anchor WRONG** |
| `from_orm_model` + `adjustedQty` are the router's half | plan step 1: `:538-539` | `from_orm_model` at **`:537`**, `adjustedQty` `:538-539`, `return resp` `:540`, `if body.tradeCardSnapshot:` `:529` | **holds, boundary off by one** |
| `fireAutoTrade` return type widens | spec §7.1: `api.ts:634` | **`:640`** — `:634` is inside `armAutoTrade`'s doc comment | **holds, anchor WRONG** |

**Round 1 found the last three rows, and they were not in the original table.** That is the finding
that matters most about this table: the twelve rows it *did* cover all verified correctly, and the
drift was entirely in rows it had not thought to check — including `auto_trade.py:83`, which carries
§4.1's whole "no new mapping code" argument, and every frontend anchor in §7, because the original
pass stopped at the language boundary. The frontend anchors are now checked:
`AutoTradeArm/index.tsx:169`, `:196`, `:203-241`, `:207`, `:224`, `:185`, `:206`, `:186-187` all
verify; only `api.ts:634` was wrong.

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
  `log_approval` — guard at `:529`, call at `:533`, `except` through `:535` — and the response,
  `PortfolioPositionSchema.from_orm_model` at **`:537`** with the `adjustedQty` branch at `:538-539`
  and `return resp` at `:540`. In a step whose entire gate is "verbatim, do not tidy in passing", the
  seam is cited to the line; round 1 caught the original off by one at exactly that boundary.
- **`create_position` commits.** Give it a docstring saying so: it calls `db.commit()` (`:505`),
  `db.rollback()` (`:514`) and `db.refresh()` (`:527`), so its caller must own the transaction or
  expect it to end. Spec §5.3 explains why this matters on the scan path.
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
  existing `ArmedStrategy(**req.model_dump())` at **`auto_trade.py:83`** (not `:81` — that is
  `async def arm`).
- **`targets` is `field(default_factory=list)` on the dataclass**, not `= []`. `ArmedStrategy` is a
  `@dataclass`; a bare mutable default raises `ValueError` at import. The house form is at `:66`.
- `portfolio_value` already travels; make sure step 4 actually passes it through (spec §4.4).
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
- **`fire()`'s signature change has callers beyond these two.** Round 1 enumerated them so this is no
  longer a warning to act on later: `routers/auto_trade.py:105`, `auto_trader.py:348`, and roughly
  sixteen direct `svc.fire()` calls across `tests/test_auto_trader.py`,
  `tests/test_premium_stop_per_position.py:359` and `tests/test_phase_g_arm_pick.py:252`. Most ignore
  the return value; a handful assert `result.order_id` and must become `fired.result.order_id`.
- `create_position` gains `stop_required` (spec §6.2) — that lands here, with the writer-side abort,
  not at the door only.
- `book_fired_order` calls `log_approval` itself (spec §5.1), checks `result.status` for a stated
  rejection (§3.2), checks the `option_symbol` shape unconditionally (§6.3.1), passes
  `portfolio_value` through (§4.4), and raises the §6.5 alert on every refusal.
- Replace the tripwire `test_phase_g_arm_pick.py:304` here. Spec tests 1–8, 11, and 14–16, 18–22 land
  here.

### Step 5 — the scan path (spec §5.3 caller 2)

- `maybe_fire_on_scan` returns `Optional[FiredOrder]`; its `except Exception` and `logger.error` stay
  exactly as they are (§9.4).
- At `scan.py:1762-1766`, take the `to_thread` return value and, **guarded `if fired is not None`**,
  `await book_fired_order(fired, db)` **on the event loop** — `db` is already in scope (`:1759`). A
  booking failure logs, raises the §6.5 alert, and does not fail the scan. Spec test 9.
- **The guard is not defensive styling — it is what threads past an existing test double.**
  `tests/test_scan_session.py:293-296` swaps the whole `auto_trader` singleton for a `SimpleNamespace`
  and drives `run_scan` with a `_FakeDb` (`:285-287`) exposing **only `execute`** — no `commit`,
  `rollback`, `add` or `refresh`. It passes today only because the substitute returns `None`
  implicitly. Round 1.
- Do not reuse ORM objects loaded at `:1759` after the booking — `create_position` commits, which
  expires them (spec §5.3).
- **Ships with step 4, not after it** (spec §11.5): between the two steps "Fire now" books and a
  scan-triggered fire of the same arm does not.

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
5. **§6.5's alert channel is the one place this build grows O4 rather than correcting it** (round 1).
   It buys the guarantee that a fired-but-unbooked order reaches a human on both paths; it costs a
   dependency on `alert_service.broadcast` the original spec did not have. Spec §10.4 is Kenneth's
   call on whether to keep it.
6. **The scan trigger can place a real second order into a contract already held**, which O4 then
   refuses to book (round 1; spec §10.3). O4 makes this loud but does not fix it — the fix is a
   pre-trade check, which is outside "a record of a trade that already happened".

---

## 4. Bookkeeping this build must not forget

`PROJECT_STATE.json` has no `already_shipped` entry for O4 (`active_phase_note` says so). The
audit-bookkeeping probe scopes its round counting to `active_phase`'s target, so **create the entry
when the first code lands in step 1**, or the branch's rounds are reported as unphased work.

---

## 5. The gate — round 1 is done, and it was not clean

The spec's closing line asked for one adversarial round before any of it. **Round 1 ran on
2026-09-17**, against both documents and the real tree, by a reviewer with no part in writing either.

**10 gate-level, 13 below-gate.** Both documents were revised; the spec's §12 records the round and
what changed. Three findings changed the design rather than the prose — §6.2 was enforced at the door
instead of at the write, §4.1's `trade_card_snapshot` was guaranteed to be discarded, and every
refusal reported into a channel with no reader.

**Round 1 also found two wrong anchors in §1 of this plan**, both in rows the table had not thought to
cover, and one of them (`auto_trade.py:81` → `:83`) carries §4.1's central argument. §1 now covers
them, and the frontend anchors it originally skipped.

Per `audit_rule`, **this is not clean and the work is not done.** Round 2 runs against *what changed*
— not the cumulative document, which is the documented way these loops fail to converge (the
`2026-09-16-yaml-config-integrity-plan.md` on `claude/session-retrieval-continuation-vf056m` died
exactly that way, at four rounds). The hard cap is three rounds without a clean gate.

**Two items are Kenneth's before step 1** and are not for a further round to settle: spec §10.3 (should
the fire path refuse to order into a contract already held — round 1 showed the scan trigger can place
a real second order) and §10.4 (§6.5's alert channel is a scope addition, and the part to cut if O4 is
to stay minimal).
