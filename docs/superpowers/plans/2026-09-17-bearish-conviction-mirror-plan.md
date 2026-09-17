# Bearish conviction mirror — `auto_trader._apply_vol_sizing`

> **One line of arithmetic, one layer, backend only.** `services/auto_trader.py`,
> `data/option_symbol.py`, and their tests. No frontend change, no new endpoint,
> no scan-path change, no scoring-config change.
>
> **Gate-level and live on `main`.** It sizes live broker orders. Introduced at
> `2e027c76` (2026-06-23) and untouched since; `2c478d88` replaced the multiplier
> on the line *below* it and left the mirror as context, so the sizing
> unification neither caused nor closed it.

**Goal, in one sentence:** the auto-trader sizes a bearish option trade by how
strongly the regime supports *that* trade, instead of by how strongly it opposes
it.

---

## 1. The defect, executed rather than argued

`auto_trader.py:176`:

```python
directional_conv = conviction if strategy.action == "BUY" else (100 - conviction)
```

Two independent faults sit in that line. **The second one is the live one**, and
the stop-and-tell recorded in `PROJECT_STATE.json` `pending_kenneth[0]` describes
only the first — this plan corrects that record (§10).

### 1.1 Fault A — `100 - conviction` is not the mirror of a signed scale

`conviction_pct` is **signed, −100..+100**:

| | where | what |
|---|---|---|
| producer | `regime_omm.py:131-133` | `conviction(signal, direction)` returns `signal if direction == "Bullish" else -signal` |
| scale | `regime_omm.py:207` | `conv_pct = int(round(conviction(sig, direction) * 100))` over `signal = P(Bull) − P(Bear)` |
| corroboration | `regime_omm.py:136-141` | `conviction_label` treats −15..+15 as Neutral and formats `{:+d}%` |
| cache | `regime_monitor.py:184` | `compute_omm(closes, direction="Bullish")`, documented at `:26` as the **"bullish frame"** |

The mirror of a signed conviction is `-conviction`. `100 - conviction` is the
mirror of an *unsigned* 0..100 scale that does not exist anywhere in this
codebase.

### 1.2 Fault B — the branch that runs is the unmirrored one

`action` is **always `"BUY"`** on every trade this app arms:

- `frontend/components/organisms/AutoTradeArm/index.tsx:207` hardcodes
  `action: 'BUY'`, commented *"long single-leg option (call or put) is always
  buy-to-open"*.
- It is the **only** production caller of `/auto-trade/arm`
  (`grep -rn armAutoTrade frontend/ --include=*.tsx --include=*.ts`, tests aside).
- `routers/auto_trade.py:83` is the **only** non-test `ArmedStrategy(...)`
  construction (`grep -rn "ArmedStrategy(" backend/app/`).

So the `100 - conviction` arm is **unreachable from the production path**, and
every bearish trade — a long **put** — takes the `BUY` arm and is sized by
**unmirrored bullish** conviction.

### 1.3 What that costs, measured

Executed against the real `conviction_mult` on the **shipped** block
(`scoring_rules.yaml:463-471`, `enabled: true, min_mult: 0.3,
full_conviction_pct: 40`), armed quantity 10, for a **long put**:

| bullish conviction | regime, for a put | mult today | qty today | correct mult | correct qty |
|---|---|---|---|---|---|
| −80 | strong downtrend — **best case** | 0.300 | **3** | 1.000 | **10** |
| −60 | strong downtrend | 0.300 | **3** | 1.000 | **10** |
| −40 | downtrend, at full conviction | 0.300 | **3** | 1.000 | **10** |
| −20 | mild downtrend | 0.300 | **3** | 0.650 | **6** |
| 0 | neutral | 0.300 | 3 | 0.300 | 3 |
| +20 | mild uptrend | 0.650 | **6** | 0.300 | **3** |
| +40 | uptrend | 1.000 | **10** | 0.300 | **3** |
| +80 | strong uptrend — **worst case** | 1.000 | **10** | 0.300 | **3** |

**It is exactly inverted, not merely mis-scaled.** The two ends are each other's
answers: a put gets the **floor** in the regime that most supports it and **full
size** in the regime that most opposes it. Only dead-neutral conviction 0 is
right, and only because 0 is its own negation.

For completeness, the unreachable `SELL` arm is wrong too, in the direction the
original stop-and-tell described — `conviction 0 → 100 - 0 = 100 → mult 1.000`
where the correct answer is 0.300. Fixing only Fault A would leave Fault B
running; fixing only Fault B would leave a wrong formula one `curl` away.

---

## 2. Why the mirror cannot key off `action` at all

For a single-leg option, direction is **not** carried by BUY/SELL. It is carried
by BUY/SELL **and** the option right together:

| action | right | position | direction |
|---|---|---|---|
| BUY | C | long call | **bullish** |
| BUY | P | long put | **bearish** |
| SELL | C | short call | **bearish** |
| SELL | P | short put | **bullish** |

So `bullish = (action == "BUY") == (right == "C")` — equivalently, bearish iff
exactly one of *short* and *put* holds. Keying off `action` alone cannot express
this, which is the root cause of both faults rather than a second bug.

The existing test at `test_auto_trader.py:513` demonstrates the confusion it
causes: it arms a **put** with `action="SELL"` and calls that the bearish case.
By the table above, selling a put is **bullish**. See §7.

---

## 3. Where the right comes from

`ArmRequest` (`routers/auto_trade.py:16-`) carries **no** direction or right
field, and `option_symbol` is an unvalidated `str`. The right is already present
in the symbol, in both formats the wire can carry:

| format | example | sent by |
|---|---|---|
| pipe | `AAPL|185|2025-05-16|C` | the frontend — `AutoTradeArm` posts `contractId` |
| OCC | `AAPL260620C00185000` | accepted by the same field; used in tests |

`data/option_symbol.py` already parses **both**, and both regexes capture the
`[CP]` group (`_OCC_RE`, `_PIPE_RE`). A `right_of(option_symbol) -> str` helper
belongs in that module beside `is_occ` / `pipe_to_occ`, not in `auto_trader.py`.

### 3.1 Rejected alternative — thread an explicit direction through `ArmRequest`

Rejected, and the reason is in that schema's own comments (`:51-58`): it inherits
pydantic's default `extra='ignore'`, so a field the frontend fails to send, or
sends camelCased, arrives as **`None` silently** and the endpoint returns 200. A
new optional direction field is therefore a silent-wrong-direction trap on the
exact path this plan exists to make correct. The right is already in the symbol
and cannot disagree with the contract being traded. Recorded here rather than
omitted, because it is the obvious first instinct.

---

## 4. When the right cannot be determined — fail closed as a DATA fault

`option_symbol` is an unvalidated `str`, so `right_of` must have a defined answer
for `"GARBAGE"`. The posture is already settled and this plan follows it rather
than inventing one: §9.1, fail closed — *a datum this path cannot honour stops
the trade*, because the alternative (size at full) is the loudest possible
failure producing the largest possible position.

**It raises `ValueError`, not `SizingConfigError`,** and that distinction is
load-bearing. `conviction_sizing.py:326-330` already makes it explicitly: a bad
*datum* "must not be reported, alerted or recorded as a broken config file." A
malformed option symbol is a datum. `ValueError` lands in `fire()`'s narrow
handler at `:369-391`, which records a history entry with status
**`sizing_data_blocked`** and re-raises — the path the merged guard built for
exactly this, so this fix composes with it instead of adding a mechanism.

### 4.1 One honest consequence, and it is a behaviour change

Today a malformed `option_symbol` arms fine, passes sizing (which never reads
it), and fails later inside `execute_option_order`, recording status
**`order_failed`**. After this change it fails **earlier**, at sizing, recording
**`sizing_data_blocked`**. Same outcome for the trader — nothing is sent, the
auto-trader is disarmed — but a different history status and a different log
line. Stated here so no round has to discover it.

### 4.2 A known mis-wording this makes reachable one new way — NOT fixed here

`fire()`'s inner handler at `:395-397` renders a non-`SizingConfigError` as *"the
regime conviction is not a usable number"*, which is wrong for a malformed
symbol. This plan therefore makes the handlers render **`str(exc)`** for the data
case instead of that hardcoded clause — a message change inside the same handler
this fix already raises through, not a new mechanism.

It does **not** touch the separate, larger defect logged on 2026-09-17 and
reproduced against `897bfe69`: `maybe_fire_on_scan`'s outer
`except (SizingConfigError, ValueError)` at `:519-527` wraps **all** of `fire()`,
so a non-sizing `ValueError` (e.g. `_check_daily_loss`'s
`float(max_daily_loss_pct)` at `:559`) alerts with sizing wording, records **zero**
history entries and burns the shared dedup `rec_id`. That is its own piece with
its own round (`open_questions[5]` item 1, whose *proposed remedy is also wrong* —
narrowing the outer try walks the genuine sizing refusal back out of the alert
path, the regression round 2 already fixed once). **`audit_rule` forbids widening
this diff to reach it.**

---

## 5. The change, file by file

### 5.1 `backend/app/data/option_symbol.py` — new `right_of`

```python
def right_of(option_symbol: str) -> str:
    """Return 'C' or 'P' for *option_symbol*, in either supported format.

    Raises ValueError if the right cannot be determined. Callers that size a
    position on the answer must not be handed a guess.
    """
```

Implemented off the two existing regexes (adding a capture group to `_OCC_RE`,
which currently has none) so there is **one** definition of each format in the
module. No behaviour change to `is_occ`, `pipe_to_occ` or `to_occ`.

### 5.2 `backend/app/services/auto_trader.py` — the mirror

Replace `:176` with a direction derived from both inputs:

```python
# Direction is carried by action AND the option right, not by BUY/SELL:
# long call and short put are bullish; long put and short call are bearish.
# conviction_pct is the SIGNED bullish frame (regime_monitor.py:26), so the
# mirror of a bearish trade is -conviction, never 100 - conviction.
right = right_of(strategy.option_symbol)          # ValueError => fail closed (§4)
is_bullish = (strategy.action == "BUY") == (right == "C")
directional_conv = conviction if is_bullish else -conviction
```

The `ValueError` propagates to the handler at `:369`; no new try/except.

### 5.3 The two handler messages (§4.2)

`:395-397` and `_alert_sizing_config_refusal`'s equivalent clause render
`str(exc)` for the non-`SizingConfigError` case rather than asserting the
conviction was unusable. Scoped to the wording of the data case only.

**Not changed:** `conviction_mult`, `resolve_sizing`, the clamp, `min_mult`,
`full_conviction_pct`, the ramp, `stock_scan.py`, any config file, any frontend
file, any endpoint contract.

---

## 6. Why the clamp does not already handle this

`conviction_mult` clamps `conv` into `[0, full]` *after* the mirror
(`conviction_sizing.py:337`), so a headwind floors at `min_mult` rather than
going below it. That is correct and stays. It is also precisely why the bug is
invisible in aggregate: every wrong bearish input still yields a multiplier
inside `[0.3, 1.0]`, so nothing ever looks malformed — the number is simply the
wrong one. No test, log line or alert fires today.

---

## 7. The test that pins the wrong behaviour — corrected, not deleted

`backend/tests/test_auto_trader.py:513`
`test_vol_sizing_sell_reduced_in_strongly_bullish_market` asserts *"SELL at
conviction=80 → bearish_conv=20, full=40 → ramp mult=0.65 → 4 rounds to 3"*, with
a docstring explaining that arithmetic as intended.

It is wrong in **both** halves, and both are corrected in place with the reason
written down (the handling Q1 established — an assertion that holds a bug in
place is corrected, never deleted):

1. It asserts `100 - conviction`.
2. Its premise is confused: it arms a **put** with `action="SELL"`, i.e. a
   **short put**, which is **bullish** (§2). At conviction +80 a short put is a
   strongly-supported trade and correctly sizes at **full**, so the corrected
   test asserts `4 → 4` and is renamed to say so.

The bearish case it *meant* to cover becomes a new test on a **long put**.

---

## 8. Tests to add

All in `backend/tests/test_auto_trader.py` unless noted. Each asserts a
**quantity**, executed through `fire()`, not a multiplier in isolation.

| # | case | armed | conviction | expect |
|---|---|---|---|---|
| 1 | long put, strong downtrend — **the regression** | BUY P, qty 10 | −80 | 10 (not 3) |
| 2 | long put, strong uptrend | BUY P, qty 10 | +80 | 3 (not 10) |
| 3 | long put, mild downtrend — pins the ramp, not just the ends | BUY P, qty 10 | −20 | 6 |
| 4 | long call, strong uptrend — the bullish side is unchanged | BUY C, qty 10 | +80 | 10 |
| 5 | long call, strong downtrend | BUY C, qty 10 | −80 | 3 |
| 6 | short call is bearish | SELL C, qty 10 | −80 | 10 |
| 7 | short put is bullish (§7's corrected case) | SELL P, qty 4 | +80 | 4 |
| 8 | neutral conviction is its own mirror | BUY P, qty 10 | 0 | 3 |
| 9 | pipe-format symbol sizes identically to OCC | BUY `AAPL|185|…|P` | −80 | 10 |
| 10 | malformed symbol fails closed | BUY `"GARBAGE"` | −80 | no order; history `sizing_data_blocked` |
| 11 | `conviction is None` still returns full size, unchanged | BUY P | None | 10 |
| 12 | `right_of` unit cases (in `test_option_symbol.py`) | — | — | both formats, both rights, and raises |

Cases 4/5 exist to prove the bullish side is **not** silently changed by this
diff — the claim the original stop-and-tell made without evidence.

---

## 9. Verification

1. `cd backend && .venv/bin/python -m pytest -q` — baseline is **2604 passed /
   1 skipped**; expect that plus the new tests, zero failures.
2. `python3 scripts/state.py` — exit 0, no drift.
3. **Reproduce before fixing:** run case 1 against unmodified `main` and record
   that it returns 3. A regression test that was never seen red proves nothing.
4. **Mutation check** on the new line: invert `is_bullish`, and separately
   restore `100 - conviction`; both must kill at least one new test.
5. `cd frontend && npm run typecheck` — expected untouched (no frontend file is
   in this diff), run to prove it.

---

## 10. The record this plan corrects

`PROJECT_STATE.json` `pending_kenneth[0]` says *"The bullish side is correct
throughout"* and *"only the deep-bearish end (−40 and below) happens to come out
right."* Both are **false**, and in the reassuring direction:

- The bullish side is correct — but by accident, not by design: it is correct
  because the unmirrored `BUY` arm happens to be right for long **calls**, and
  the same arm is exactly wrong for long **puts**.
- The deep-bearish end is the **worst** case, not the one that comes out right:
  conviction −80 on a long put sizes at the floor (3 of 10) when it should size
  full.

The state file must be updated with §1.3's measured table as part of this piece.
The original entry stays verbatim beneath the correction, per this file's own
convention.

---

## 11. Kenneth's decision — surfaced, not assumed

**This changes live auto-trade sizing on the bearish side**, exactly as the
ramp-versus-step question did. On the numbers in §1.3, with `min_mult: 0.3` and
an armed quantity of 10:

- A long put in a **downtrend** goes from 3 contracts to **10** — it sizes *up*,
  3.3×, in the regime that supports it.
- A long put in an **uptrend** goes from 10 contracts to **3** — it sizes *down*.

The second half is the conservative direction. **The first half is not**: it is a
real increase in size on live bearish orders, and it is an increase this app has
never placed. The arithmetic is not in question — the only alternative to
sizing up in a supportive regime is keeping a number that is provably inverted —
but the *magnitude* is a knob he owns:

- **As planned:** `min_mult: 0.3` unchanged, bearish trades reach full size at
  conviction −40, matching the bullish side exactly. Symmetric, and symmetry is
  what every other direction-aware piece of this codebase now has after
  `49ffa53`.
- **If he wants the correction without the size-up:** raise `min_mult`, or gate
  bearish sizing at a stiffer `full_conviction_pct`. Both are `scoring_rules.yaml`
  edits and neither needs code — worth saying, because it means shipping the
  correct arithmetic does not commit him to the magnitude.

Also still his, and unchanged by this piece: the bearish floors 30/40 from
`49ffa53` remain **unmeasured** pending the bearish validation scans.

---

## 12. Scope fence

| in | out |
|---|---|
| `services/auto_trader.py:176` and the two message clauses in §5.3 | `maybe_fire_on_scan`'s outer handler (§4.2) — its own piece |
| `data/option_symbol.py` `right_of` | `is_occ` / `pipe_to_occ` / `to_occ` behaviour |
| `tests/test_auto_trader.py`, `tests/test_option_symbol.py` | the scan path (§1, fact 6) — already direction-aware |
| `PROJECT_STATE.json` (§10) | `scoring_rules.yaml` — no config edit is needed or made |
| — | `stock_scan.py:685`'s falsy trap — logged, unreachable once zero is refused |
| — | any frontend file, any endpoint contract, any schema field |
