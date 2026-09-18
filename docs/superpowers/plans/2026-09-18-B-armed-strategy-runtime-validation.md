# Piece B — validating `ArmedStrategy.direction` at runtime

**Date:** 2026-09-18
**Status:** OPEN QUESTION — not planned, not audited, not implemented.
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
`else` branch. 26 test sites construct `ArmedStrategy` directly (test_auto_trader.py 20,
test_phase_g_arm_pick.py 3, test_premium_stop_per_position.py 3), as would any future non-HTTP
producer.

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
