# Piece B — validating `ArmedStrategy.direction` at runtime

**Date:** 2026-09-18
**Status:** §5 LOCKED 2026-09-23 by Kenneth ("i agree with your proposal": freeze, not the `__setattr__` fallback; Q2 stays queued after this as one-round hardening). Implemented 2026-09-23 (a7381f2d); adversarial round 1 CLEAN 2026-09-23 (zero gate-level findings). Not merged.
**§1–§3 line numbers are from 2026-09-18 and stale.** §5 cites `origin/main` at `e5e669f5`.
**Split from:** `2026-09-18-auto-trader-direction-sizing-plan.md` (Piece A) after its round 3
fired audit_rule's hard cap. This half produced a MAJOR in two consecutive rounds; Piece A's
engineering half was converged. Splitting is audit_rule's own remedy for that shape.

---

## 1. The hole this exists to close

`ArmedStrategy` is a plain `@dataclass` (`auto_trader.py:24-25`), so a `Literal["Bullish",
"Bearish"]` annotation on it is **not enforced at runtime**. Only `ArmRequest` (pydantic)
validates. So after Piece A lands:

```python
directional_conv = conviction if strategy.direction == "Bullish" else -conviction
```

**fails OPEN to bearish.** `"bullish"`, `"Bulish"`, `""` and `None` all silently take the
`else` branch. **23** test sites construct `ArmedStrategy` directly — `test_auto_trader.py` 20,
`test_phase_g_arm_pick.py` 1, `test_premium_stop_per_position.py` 2 — as would any future
non-HTTP producer, plus one production site (`routers/auto_trade.py:83`) for 24 repo-wide.

> **THE COUNT IS 23, NOT 26, AND THE DIFFERENCE IS THE WHOLE REASON THIS LINE CARRIES A
> NUMBER.** A bare `grep -c "ArmedStrategy("` returns 26 across those three files, but three
> of those hits are DOCSTRING PROSE, not code: `test_phase_g_arm_pick.py:11` and `:127`, and
> `test_premium_stop_per_position.py:368` each mention `ArmedStrategy(**req.model_dump())`
> inside a comment. Counted by walking the AST for `ast.Call` nodes rather than by grepping
> text: 20 / 1 / 2 in tests, plus `routers/auto_trade.py:83` in production (that file greps
> as 2, one of which is also a comment). The sizing piece's own round 1 was faulted for the
> 26 figure and corrected it; this document was ported carrying the uncorrected number.
> Re-measured 2026-09-19 before editing.

This matters because Piece A's own argument for making `direction` **required with no default**
is that a `"Bullish"` default would reintroduce silent mis-direction. A silent default pointed
the *other* way makes that argument cover only the HTTP door.

## 2. Why the obvious fix was rejected by round 3

Round 2 prescribed a bare `raise ValueError(...)` before the expression. Round 3 found two
MAJORs against it, both verified against the real code:

### 2.1 It lands in the wrong refusal bucket and can mask a real one

`fire()` catches `except (SizingConfigError, ValueError)`. So the new raise:

- records history status **`"sizing_data_blocked"`**,
- logs **"the regime conviction is not a usable number"** — which is **false**; the conviction
  is fine, the *direction* is malformed,
- pages Gmail/Telegram under a **shared `rec_id`** that can **suppress a genuine config
  refusal** for the same id.

And Piece A §2.1 asserts *"no new refusal/alert path is added"* while prescribing one. The plan
denied a behaviour it specified. Two existing tests stay green while the alert names the wrong
subsystem.

### 2.2 It is positioned where it cannot fire in the dangerous states

The guard sits **after both full-size early returns**. So a malformed direction is refused only
when regime sizing is **enabled** AND the conviction cache is **warm** — i.e. never in the two
states where the auto-trader ships a **full-size** order. The guard is absent exactly where the
blast radius is largest.

## 3. The question to answer

Three coupled decisions, none of which Piece A can settle without touching `fire()`'s refusal
taxonomy — which has its own tests and its own documented posture:

1. **Which exception type.** A new dedicated type avoids the `ValueError` collision and the
   false log line, but adds a member to the refusal taxonomy.
2. **Where it sits.** Before both early returns, so it fires in the full-size states — which
   means validating direction on a path that today does no validation at all.
3. **Which alert bucket, and which `rec_id`.** Must not be able to suppress a genuine
   `sizing_data_blocked` page for the same id.

## 4. Scope boundary

This piece owns the runtime guard **only**. The `Literal` annotations on `ArmRequest` and
`ArmedStrategy`, and the sizing expression itself, are Piece A's and are converged. Piece A can
ship without this guard; it would then be correct through the HTTP door (pydantic validates)
and silently bearish-on-malformed for direct constructors. **That residual risk is the reason
this piece exists and is the thing to weigh when sequencing it against Piece A.**

---

## 5. Resolution — proposed 2026-09-23, LOCKED 2026-09-23 by Kenneth

Checked against `origin/main` at `e5e669f5` before proposing anything.

### 5.1 What the code says today

- **One production producer.** `routers/auto_trade.py:149` builds `ArmedStrategy(**req.model_dump())`.
  Pydantic has already validated `ArmRequest.direction: Direction` by then, so a bad value is a
  422 before anything is built.
- **One way in.** `AutoTradeService.arm()` (`auto_trader.py:1998`) is the only writer of the
  armed slot, and the slot is in-memory.
- **Production never mutates one; tests do, in three places.** In `app/`, every change goes
  through `dataclasses.replace`: `_dc_replace` at `:1304` and `:1407`, **both inside `fire()`'s
  sizing `try`**. `tests/test_auto_trader.py` assigns fields in three places:
  - `:2661` sets `svc._state.strategy.broker = "ibkr_live"`.
  - `:2757` sets `armed.armed_at`, inside the expired-arm helper.
  - `:2883` sets `twin.armed_at`.

  A first grep missed all three. Setting `frozen=True` and running the auto-trader tests found
  them: **12 failed / 381 passed**, and every failure was `FrozenInstanceError` from one of
  those three sites.
- **The trap is unchanged.** fire()'s inner handler (`:2183`) still catches
  `(SizingConfigError, ValueError)`, so §2.1 still holds for anything raised inside it.

### 5.2 The three decisions

**Placement: at construction, not in `fire()`.** `ArmedStrategy.__post_init__` refuses any
`direction` not in `typing.get_args(Direction)`, and the dataclass becomes `frozen=True`.

- A malformed strategy then never exists, so it is never armed and never fired. §2.2's
  objection (a guard placed after the full-size early returns) has nothing to apply to. The
  refusal comes before both of those returns, and before `arm()`.
- **`frozen=True` is part of the fix.** Without it, `s.direction = "x"` after construction
  skips the check. The next `_dc_replace` inside the sizing `try` would then re-run
  `__post_init__` and raise inside fire()'s refusal taxonomy, which is exactly §2.1's trap.
  Freezing removes that path.
- **Cost of freezing:** rewrite those three test sites to use `dataclasses.replace`, or to pass
  the value to the constructor. Those sites feed 12 tests. No production change is needed.
- **Fallback if Kenneth prefers no test churn:** guard only `direction`, with a `__setattr__`
  that re-runs the same check. That closes the same path without freezing the other fields. It
  is less conventional and does not change the rest of this proposal.

**Exception type: `MalformedDirectionError(TypeError)`.**

- **Not a `ValueError`,** because that is the class `:2183` files as `sizing_data_blocked`.
- `TypeError` fits because the value violates the `Literal` type the field declares.
- It keeps the name the phase's `verify` probe pins. Flip that probe from `absent` to `present`
  in the same commit.
- A test pins `not issubclass(MalformedDirectionError, ValueError)`, so the round-3 lesson
  cannot be undone quietly.

**Alert bucket and `rec_id`: none.**

- The refusal is a synchronous exception to whoever is constructing the strategy, before
  anything is armed. The scan trigger has no fire-time refusal to page about.
- It adds no history status and no `rec_id`, so it can neither share a `rec_id` nor suppress a
  genuine `sizing_data_blocked` page. fire()'s taxonomy and `maybe_fire_on_scan`'s handlers are
  **not touched**.

### 5.3 Folded in, not duplicated

- `_measure_trade_regime`'s abstain on a `compute_omm` ValueError (`:937-949`, from 072d74ff)
  becomes unreachable *for direction*. **Keep it:** it also covers any other `compute_omm`
  failure. Re-word its comment so it stops claiming piece B is open.
- Re-word the carrier comment on `ArmedStrategy.direction` (`:160-171`). It says a direct
  constructor "still lands on the bearish branch", which stops being true.

### 5.4 Tests

- Each of `"bullish"`, `"Bulish"`, `"BULLISH"`, `""` and `None` raises
  `MalformedDirectionError`.
- `"Bullish"` and `"Bearish"` both construct.
- `dataclasses.replace(s, quantity=…)` still works on a valid strategy.
- Assigning a field raises `FrozenInstanceError`.
- `MalformedDirectionError` is not a `ValueError` subclass.

### 5.5 Residual, stated rather than hidden

- `object.__setattr__` on a frozen instance, or writing `svc._state` directly with a hand-built
  object, bypasses the guard. Both are private-surface abuse and are not guarded.
- `horizon` has the same unenforced `Literal`. It is **out of scope**: a missing or unknown
  horizon makes the gate abstain loudly (`:878-893`), and it never picks a sizing branch.

### 5.6 Size

About 30 lines of production code, plus about 60 lines of new tests and the three rewritten
test sites. Two files. One round.
