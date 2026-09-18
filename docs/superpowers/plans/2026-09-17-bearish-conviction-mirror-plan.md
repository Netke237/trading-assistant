# Bearish conviction mirror — `auto_trader._apply_vol_sizing`

> **One line of arithmetic, one layer, backend only.** `services/auto_trader.py`,
> `data/option_symbol.py`, and their tests. No frontend change, no new endpoint,
> no scan-path change, no scoring-config change.
>
> **Gate-level and live on `main`.** It sizes live broker orders.
>
> **Revision 2** — round 2 returned 18 findings (1 gate-level, 7 major, 8 minor,
> 2 nits). The gate-level one is mine and it was in the part revision 1 rewrote:
> §5.1 specified the parser in **prose**, and written to that prose it silently
> returns the **wrong right** on four input classes. §5.1 now ships the actual
> regexes. §4.1's "four other consumers" was invented (there is one), §10's
> replacement claim over-corrected in turn, §11 still hid that both downstream
> gates can be inert, and §4.3's "created by this diff" was wrong. §13 tallies
> both rounds with honest dispositions.

**Goal, in one sentence:** the auto-trader sizes a bearish option trade by how
strongly the regime supports *that* trade, instead of by how strongly it opposes
it.

**Provenance.** The line was written by **`23674da4`** (2026-09-05), whose parent
has no sizing logic at all. `pending_kenneth[0]`'s `2e027c76` is **not an
ancestor of this history** (`git merge-base --is-ancestor 2e027c76 HEAD` fails);
it carries an identical line on an abandoned lineage. No argument here rests on
the defect's age. `2c478d88` *is* an ancestor and did replace the multiplier on
the line below.

---

## 1. The defect, executed rather than argued

`auto_trader.py:176`:

```python
directional_conv = conviction if strategy.action == "BUY" else (100 - conviction)
```

Two independent faults. **The second is the live one.**

### 1.1 Fault A — `100 - conviction` is not the mirror of a signed scale

| | where | what |
|---|---|---|
| producer | `regime_omm.py:131-133` | `conviction(signal, direction)` → `signal if direction == "Bullish" else -signal` |
| scale | `regime_omm.py:208` | `conv_pct = int(round(conviction(sig, direction) * 100))` over `signal = P(Bull) − P(Bear)` |
| corroboration | `regime_omm.py:136-142` | `conviction_label`'s bands are symmetric about 0 — `> -15` is Neutral and `>= 15` is Moderate, so **Neutral is −14..+14** (`:137`'s own comment: *"strict > so -15 and -40 map to the worse band"*) |
| corroboration | `regime_omm.py:148` | `conviction_interpretation` formats it `{:+d}%` — a **different function** from `conviction_label` |
| cache | `regime_monitor.py:184` | `compute_omm(closes, direction="Bullish")`, documented at `:26` as the **"bullish frame"** |

The mirror of a signed conviction is `-conviction`. `100 - conviction` is the
mirror of an *unsigned* 0..100 scale that exists nowhere in this codebase.

### 1.2 Fault B — the branch that runs is the unmirrored one

`action` is **always `"BUY"`** on every trade this app arms:

- `frontend/components/organisms/AutoTradeArm/index.tsx:207` hardcodes
  `action: 'BUY'`, commented *"long single-leg option (call or put) is always
  buy-to-open"*. It is the **only** production caller of `/auto-trade/arm`.
- `routers/auto_trade.py:83` is the **only** non-test `ArmedStrategy(...)`
  construction and the only `.arm()` caller. No scheduler or service arms.
- Corroborated in backend code: `data/tastytrade_paper.py:35-39` already records
  *"nothing in this codebase's frontend ever sends an options order with
  action=SELL."*

So the `100 - conviction` arm is **unreachable from the production UI**, and
every bearish trade — a long **put** — takes the `BUY` arm and is sized by
**unmirrored bullish** conviction.

**One reachability standard, applied throughout (round 2's finding).** This plan
uses exactly one: *reachable* means reachable from the production UI;
*crafted-request reachable* means reachable only by posting to the API directly
or constructing `ArmedStrategy` in code. `ArmRequest:20` accepts `SELL` and
`:19`'s `option_symbol` is an unvalidated `str`, so **Fault A, a crafted
`option_symbol`, a non-`str` symbol and an out-of-`Literal` `action` are all in
the second class** — and this plan treats that class consistently: it is not
what justifies the fix (Fault B is), but every input in it must fail closed
rather than silently size (§4, §5.2). Where §10 says the SELL arm "never runs"
it means the first standard only.

### 1.3 What that costs, measured

Real `conviction_mult`, shipped block (`scoring_rules.yaml:463-471`,
`min_mult: 0.3, full_conviction_pct: 40`), armed quantity 10, **long put**:

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

**Exactly inverted, not merely mis-scaled** — and not only here:
`mult_today(c) ≡ mult_correct(−c)` holds identically at *any* config, by
construction. A put gets the **floor** in the regime that most supports it and
**full size** in the one that most opposes it. Only conviction 0 is right,
because 0 is its own negation.

**Whose regime.** `regime_monitor.py:180` fetches **SPX** and nothing else. The
number that sizes a long put on any symbol is the *market's* regime, not that
symbol's. Load-bearing for §11.

---

## 2. Why the mirror cannot key off `action` at all

| action | right | position | direction |
|---|---|---|---|
| BUY | C | long call | **bullish** |
| BUY | P | long put | **bearish** |
| SELL | C | short call | **bearish** |
| SELL | P | short put | **bullish** |

So `bullish = (action == "BUY") == (right == "C")`. Keying off `action` alone
cannot express this — the root cause of both faults rather than a second bug.

**The precondition that makes the table exhaustive, cited rather than assumed:**
`auto_trader.py:289` hardcodes `effect="OPEN"`, commented *"Auto-trade is
structurally entry-only … Hardcoded rather than added to
ArmRequest/ArmedStrategy so there's no way to call this endpoint with the wrong
effect."* The distinction is real at the adapter — `data/tradier_paper.py:22-27`
maps `("SELL","OPEN") → sell_to_open` and `("SELL","CLOSE") → sell_to_close`. Two
of the four rows **invert** for a closing trade, and sizing a *closing* trade by
regime conviction is meaningless anyway. §12 fences it: adding an `effect` field
must revisit this line.

`test_auto_trader.py:514` shows the confusion the `action`-only reading causes:
it arms a **put** with `action="SELL"` (`:534-535`) and calls that the bearish
case. Selling a put is **bullish**. See §7.

---

## 3. Where the right comes from

`ArmRequest` (`routers/auto_trade.py:16-`) carries no direction or right field,
and `option_symbol` (`:19`) is an unvalidated `str`. The right is already in the
symbol, in both formats the wire carries:

| format | example | sent by |
|---|---|---|
| pipe | `AAPL\|185\|2025-05-16\|C` | the frontend — `AutoTradeArm:185,206` posts `card.contract` |
| OCC | `AAPL260620C00185000` | accepted by the same field; used in tests |

### 3.1 The invariant that makes this sound

The right **can** disagree with the contract traded, twice over:

- `data/ibkr_paper.py:116-118` — with `conid` set the contract is identified by
  `conidex` and `option_symbol` is **never read**. Nothing reconciles them.
- `routers/scan.py:1007` builds the id as
  `f"{symbol}|{int(strike)}|{contract.get('expiry','TBD')}|{'C' if direction=='Bullish' else 'P'}"`
  — the right is a **copy of the scan direction**, never read off the contract's
  own `right`, and `int(strike)` truncates 187.5 → 187.

**That second point is the justification:** the right in the symbol *is* the
scan's own `direction`, round-tripped. `right_of` recovers the direction the scan
intended — exactly what the mirror needs — and does not depend on the id
faithfully describing strike or expiry (and must not; see §4.1).

### 3.2 Rejected alternative — an explicit direction through `ArmRequest`

Not because an optional field would silently default (a **required** field 422s
loudly — `auto_trade.py:21`'s `quantity: int = Field(..., ge=1)` is the pattern).
The real reasons:

1. `option_symbol` already carries the answer; a direction field needs a
   frontend change, a schema change and a migration story for nothing gained.
2. It would be a **second** source of truth for the same fact, free to disagree
   with the contract traded.

---

## 4. When the right cannot be determined

### 4.1 Two rounds killed two parsers. This is the third, and it is code, not prose

**Round 1** killed building on the module's `_PIPE_RE`/`_OCC_RE`: they validate
the *whole* symbol, and `_PIPE_RE`'s `[A-Z]{1,6}` root rejects live S&P names.
**Round 2** killed the prose replacement — *"the last pipe-delimited field, or
the `[CP]` before OCC's 8-digit strike"* — by writing it three ways and showing
all three **silently return a wrong right**:

```
input                          naive spec   date-anchored
'SNAP00185000'                     P          ValueError   <-- ticker's own P
'P00185000'                        P          ValueError
'XC00000000'                       C          ValueError
'AAPL|185|C00185000'  (3 fields)   C          ValueError   <-- read as a CALL
```

A silent wrong right is **worse than the bug being fixed**: it inverts sizing
with no error, no log and no alert. So the spec is no longer prose. §5.1 ships
the regexes, both anchored `^…$`, the OCC branch anchored on OCC's **6-digit
date** before the right, and the pipe branch on an **exact 4-field** shape.

Executed against that design — all 8 real shapes resolve, all 9 bad inputs raise:

```
resolve: AAPL|185|2025-05-16|C -> C   BRK.B|185|2027-01-15|P -> P
         BF.B|70|2027-01-15|C  -> C   AAPL|185|TBD|C         -> C
         AAPL|187.5|…|P        -> P   AAPL260620P00185000    -> P
         AAPL260620C00185000   -> C   BRK260620P00185000     -> P
raise:   SNAP00185000  P00185000  XC00000000  AAPL|185|C00185000
         GARBAGE  ''  aapl|185|2025-05-16|c  …|X  …|C|extra
```

Why the permissiveness is needed at all — executed against the *existing*
regexes:

```
AAPL|185|2025-05-16|C        pipe=True   occ=False
BRK.B|185|2027-01-15|P       pipe=False  occ=False   <-- live S&P name
BF.B|70|2027-01-15|C         pipe=False  occ=False   <-- live S&P name
AAPL|185|TBD|C               pipe=False  occ=False   <-- scan.py:1007 default
```

`BRK.B` and `BF.B` are both live in `data/sp500.csv:63,77`; `scan.py:1007`'s
`'TBD'` default is reachable whenever a contract carries no expiry. Reading the
right needs neither the ticker nor the expiry, so `right_of` is permissive about
both and strict about the right's own position.

**`_PIPE_RE` and `_OCC_RE` are NOT widened.** Round 2 corrected the draft's
claim that "four other consumers" depend on them — repo-wide there is **one
production consumer**: `data/tradier_paper.py:9` imports `to_occ` and calls it at
`:92` (plus two test modules). The decision stands on `audit_rule`'s
anti-widening rule alone, which is sufficient; the invented number is withdrawn.

**Logged against main, not fixed (and no longer hedged):** a dotted ticker fails
`pipe_to_occ`, so `to_occ` raises `ValueError` at `tradier_paper.py:92`, inside
`_build_params` called at `:99` within the `try:` at `:97`, whose
`except Exception` at `:102` re-raises it as
`RuntimeError("Tradier paper order failed: connection error — …")`. **A `BRK.B`
option order is reported to the operator as a network fault.** Pre-existing.

### 4.2 The residual failure, and it is a real behaviour change

For a symbol with no determinable right the posture is §9.1, fail closed — *a
datum this path cannot honour stops the trade* — because sizing at full is the
loudest failure producing the largest position.

**It raises `ValueError`, not `SizingConfigError`.** `conviction_sizing.py:326-330`
draws that line: a bad *datum* "must not be reported, alerted or recorded as a
broken config file." `ValueError` lands in `fire()`'s handler (`try:` at `:368`,
`except` at `:370-398`), which records history status **`sizing_data_blocked`**
(`:382-384`) and re-raises at `:398` — the path the merged guard built.

**The two operator-facing outcomes differ, and neither was stated before:**

| path | result | alert? | history? |
|---|---|---|---|
| `/auto-trade/fire` (manual) | **400** — `routers/auto_trade.py:109-110` catches `ValueError` | **no** — `_alert_sizing_config_refusal` has exactly one caller, `maybe_fire_on_scan:527` | yes, `sizing_data_blocked` |
| `maybe_fire_on_scan` (scan trigger) | nothing sent | yes, one | yes, `sizing_data_blocked` |

**A live order stops going out.** The draft claimed "same outcome for the trader
— nothing is sent." False: `ibkr_paper._build_payload` (`:104-121`) never reads
`option_symbol` — with `conid` set it sends `conidex`, else
`{"symbol": order.symbol, "secType": "OPT"}` — so on `ibkr_paper` a malformed
symbol **is submitted today** and is refused after this change. Correct
trade-off (an order whose direction cannot be established must not be sized), but
a behaviour change, and **it is direction-agnostic**: it stops malformed-symbol
**calls** too, not just puts. §11 says so.

**The refusal is conditional.** `right_of` is reached only after two early
returns — `:156` (`resolve_sizing(cfg) is None`, sizing off) and `:171`
(`conviction is None`, monitor has not ticked). In those states the same symbol
arms and fires exactly as today. Defensible — the datum is only needed when read
— and stated rather than moved, because validating above the early returns would
refuse trades in states where sizing is never consulted.

### 4.3 Consequences this diff does NOT fix — logged

Round 1 was right that the draft's own message fix was the widening it invoked
`audit_rule` to forbid elsewhere. `audit_rule`: *"only gate-level findings are
fixed in-branch. Nothing else — not 'while I am here', not a one-line nit."* A
misleading log clause puts no wrong number on a broker order. **The draft's §5.3
is deleted.** Logged instead:

1. **Wording.** The clause *"the regime conviction is not a usable number"* is
   wrong for an unparseable symbol, and it appears **twice**: the log line at
   `:395-396` and — the one that reaches Kenneth's phone — the alert body at
   `:250`, inside the `notify_alert(...)` call at `:243-259`. Both already append
   `str(exc)`, so the operator does see the real reason ("Cannot determine option
   right from 'GARBAGE'"); the clause preceding it is merely wrong. Below the
   gate.
2. **Alert routing — pre-existing, and round 2 corrected the draft's claim that
   this diff *creates* it.** `:245` `alert_type="CONFIG_ERROR"` and `:257`
   `rec_id="auto-trade-sizing-config"` are justified in-code as *"the file is
   broken, not the symbol"*. A **symbol-specific** case already reaches that
   alert without this diff: `_check_daily_loss:575` calls
   `resolve_premium_stop_pct(strategy.premium_stop_pct, …)`, whose
   `return float(position_pct)` raises `ValueError` on a non-numeric per-trade
   value — executed, `resolve_premium_stop_pct('sixty percent', 0.60)` →
   `ValueError` — and `open_questions[5]` item 1 names that source itself. This
   diff **adds a second** such case, it does not create the class. Two
   consequences, both below the gate: one bad symbol suppresses genuine
   sizing-config alerts for every other symbol in the dedup window, **and two
   malformed symbols in one window suppress each other**, so the second refused
   trade is silent on the scan path (history and log only). `:258`
   `type_enabled=True` bypasses `enabledTypes` on the same premise.

Both belong with the separate, larger defect already logged and reproduced
against `897bfe69`: `maybe_fire_on_scan`'s outer
`except (SizingConfigError, ValueError)` at `:519-527` wraps **all** of `fire()`,
so a non-sizing `ValueError` (`_check_daily_loss`'s `float(max_daily_loss_pct)`,
`:559`) alerts with sizing wording, records **zero** history entries and burns
the same `rec_id`. That piece — `open_questions[5]` item 1, whose own proposed
remedy is wrong — is where all three should be fixed together. **`audit_rule`
forbids widening this diff to reach it.**

---

## 5. The change, file by file

### 5.1 `backend/app/data/option_symbol.py` — new `right_of`

```python
# Right-focused patterns, deliberately NOT _PIPE_RE/_OCC_RE: those validate the
# WHOLE symbol, and their [A-Z]{1,6} root rejects BRK.B and BF.B (both live in
# sp500.csv) while scan.py:1007's 'TBD' expiry default fails their date group.
# Reading the right needs neither the ticker nor the expiry.
#
# Both are anchored ^...$ and both pin the right's POSITION, which is what stops
# a silent wrong answer: _RIGHT_OCC requires OCC's 6-digit date immediately
# before the right, so 'SNAP00185000' (the ticker's own P) and 'XC00000000' raise
# instead of resolving; _RIGHT_PIPE requires exactly four fields, so a pipe id
# missing its right field ('AAPL|185|C00185000') raises instead of reading C.
_RIGHT_PIPE = re.compile(r'^[^|]+\|[^|]+\|[^|]+\|([CP])$')
_RIGHT_OCC  = re.compile(r'^[^|]{1,6}\d{6}([CP])\d{8}$')


def right_of(option_symbol: str) -> str:
    """Return 'C' or 'P' for *option_symbol*, in either supported format.

    Raises ValueError if the right cannot be determined, INCLUDING for a
    non-str input. A caller that sizes a position on the answer must never be
    handed a guess, and must never be handed a TypeError either -- the sizing
    path catches ValueError, not TypeError (auto_trader.py:370).
    """
    if not isinstance(option_symbol, str):
        raise ValueError(
            f"option symbol must be a str, got {type(option_symbol).__name__}"
        )
    for rx in (_RIGHT_PIPE, _RIGHT_OCC):
        m = rx.match(option_symbol)
        if m:
            return m.group(1)
    raise ValueError(
        f"cannot determine option right from {option_symbol!r}"
    )
```

Both regexes and both anchors are pinned by §8 case 18. No behaviour change to
`is_occ`, `pipe_to_occ` or `to_occ`.

### 5.2 `backend/app/services/auto_trader.py` — the mirror

Add the import (round 2: it is required and sat outside the draft's fence):

```python
from app.data.option_symbol import right_of
```

Replace `:174-176` — **both comment lines go with it**; they are the
authoritative statement of the defect:

```python
# Direction is carried by action AND the option right, not by BUY/SELL alone:
# long call and short put are bullish, long put and short call are bearish.
# Exhaustive only because :289 hardcodes effect="OPEN" -- a CLOSE would invert
# two of those four rows. conviction_pct is the SIGNED bullish frame
# (regime_monitor.py:26), so the mirror of a bearish trade is -conviction,
# never 100 - conviction.
#
# Both inputs fail CLOSED, and for one reason: ArmedStrategy is a plain
# dataclass (:24), so neither its Literal nor its str annotation is enforced --
# only ArmRequest validates, and :19's option_symbol is an unvalidated str even
# there. An unrecognised action would otherwise silently INVERT the direction.
right = right_of(strategy.option_symbol)      # ValueError => fail closed (§4.2)
if strategy.action not in ("BUY", "SELL"):
    raise ValueError(f"cannot size an order with action {strategy.action!r}")
is_bullish = (strategy.action == "BUY") == (right == "C")
directional_conv = conviction if is_bullish else -conviction
```

`right_of` raises `ValueError` rather than `TypeError` for a non-`str` (§5.1)
because `fire()`'s handler at `:370` catches `(SizingConfigError, ValueError)`
only: a `TypeError` would skip the history entry at `:382-391` entirely, return
an unhandled **500** from `/auto-trade/fire` (`routers/auto_trade.py:109` catches
`(ValueError, RuntimeError)`), and fall to `maybe_fire_on_scan`'s bare
`except Exception` at `:528` — log line only, **no alert, no history**. That is
verbatim the failure the comment at `:371-378` calls *"strictly worse than what
it replaced on both halves of §9.1"*.

`_apply_vol_sizing`'s docstring (`:143-150`) promises only `SizingConfigError`;
it must name `ValueError` too.

**Not changed:** `conviction_mult`, `resolve_sizing`, the clamp, `min_mult`,
`full_conviction_pct`, the ramp, any handler message (§4.3), `stock_scan.py`, any
config file, any frontend file, any endpoint contract.

---

## 6. Why the clamp does not already handle this

`conviction_mult` clamps the fraction into `[0, 1]` *after* the mirror
(`conviction_sizing.py:339`, `frac = max(0.0, min(conv / full, 1.0))`), so a
headwind floors at `min_mult` rather than going below it. Correct, and it stays.
It is also why the bug is invisible in aggregate: every wrong bearish input still
yields a multiplier inside `[0.3, 1.0]`, so nothing looks malformed — the number
is simply wrong. No test, log line or alert fires today.

---

## 7. The test that pins the wrong behaviour — corrected, not deleted

`test_auto_trader.py:514`
`test_vol_sizing_sell_reduced_in_strongly_bullish_market` asserts *"SELL at
conviction=80 → bearish_conv=20, full=40 → ramp mult=0.65 → 4 rounds to 3"*, with
a docstring at `:515` explaining that arithmetic as intended. Wrong in **both**
halves, both corrected in place with the reason written down (the handling Q1
established — an assertion holding a bug in place is corrected, never deleted):

1. It asserts `100 - conviction`.
2. Its premise is confused: it arms a **put** with `action="SELL"` (`:534-535`),
   i.e. a **short put**, which is **bullish** (§2). At conviction +80 a short put
   is strongly supported and correctly sizes at **full**, so the corrected test
   asserts `4 → 4` and is renamed to say so.

The bearish case it *meant* to cover becomes §8 case 1.

---

## 8. Tests

`backend/tests/test_auto_trader.py` unless noted. Each quantity case is driven
through `fire()`, not asserted on a multiplier in isolation.

| # | case | armed | conviction | expect |
|---|---|---|---|---|
| 1 | long put, strong downtrend — **the regression** | BUY P, qty 10 | −80 | 10 (not 3) |
| 2 | long put, strong uptrend | BUY P, qty 10 | +80 | 3 (not 10) |
| 3 | long put, mild downtrend — pins the ramp, not just the ends | BUY P, qty 10 | −25 | 7 |
| 4 | long call, strong uptrend — bullish **sizing** unchanged | BUY C, qty 10 | +80 | 10 |
| 5 | long call, strong downtrend — bullish **sizing** unchanged | BUY C, qty 10 | −80 | 3 |
| 6 | short call is bearish | SELL C, qty 10 | −80 | 10 |
| 7 | short put is bullish (§7's corrected case) | SELL P, qty 4 | +80 | 4 |
| 8 | neutral conviction is its own mirror | BUY P, qty 10 | 0 | 3 |
| 9 | pipe-format symbol sizes identically to OCC | BUY `AAPL\|185\|2025-05-16\|P` | −80 | 10 |
| 10 | `BRK.B` dotted root still sizes | BUY `BRK.B\|185\|2027-01-15\|P` | −80 | 10 |
| 11 | `TBD` expiry still sizes (`scan.py:1007`) | BUY `AAPL\|185\|TBD\|P` | −80 | 10 |
| 12 | malformed symbol fails closed | BUY `"GARBAGE"` | −80 | no order; history `sizing_data_blocked` |
| 13 | **malformed symbol on a CALL also fails closed** — the refusal is direction-agnostic | BUY `"GARBAGE"` C-intent | +80 | no order; `sizing_data_blocked` |
| 14 | **non-`str` symbol raises `ValueError`, not `TypeError`** | BUY `None` | −80 | no order; history entry **exists**; 400 not 500 |
| 15 | unrecognised `action` fails closed | `"buy"` + C, qty 10 | +80 | no order; `sizing_data_blocked` — **not qty 3**, which is what dropping the guard yields |
| 16 | malformed symbol through `maybe_fire_on_scan` | BUY `"GARBAGE"` | −80 | no order, history entry exists, **one** alert |
| 17 | **`/auto-trade/fire` returns 400 and sends NO alert** | BUY `"GARBAGE"` | −80 | 400; `notify_alert` not called |
| 18 | `right_of` units, in `tests/test_option_symbol.py` | — | — | the 8 resolve / 9 raise rows of §4.1 **including `SNAP00185000`, `P00185000`, `XC00000000` and the 3-field pipe id** |
| 19 | sizing **disabled** ⇒ malformed symbol still fires (§4.2 conditionality) | BUY `"GARBAGE"` | −80 | order at full size |
| 20 | `conviction is None` ⇒ full size, unchanged | BUY P, qty 10 | None | 10 |
| 21 | mirror is config-independent (§11's knob) | BUY P, qty 10 @ `min_mult 0.5 / full 20` | −80 | 10 |
| 22 | **`entry_premium == 0` ⇒ neither downstream gate runs** (§11) | BUY P, qty 10, premium 0 | −80 | order at 10, no `cap_blocked`, no `daily_loss_blocked` |

Case 18's reject rows are the point: `GARBAGE` and `""` alone raise under *every*
reading of the spec, including the broken one round 2 found, so they cannot
distinguish a correct parser from a dangerous one. The four position-sensitive
inputs can.

Case 15's counterfactual corrected (round 2): dropping the `action` guard gives
`is_bullish = False` → `dir_conv = −80` → `mult 0.300` → **qty 3**, executed. The
draft said 10.

Case 3 sits at −25 rather than −20 (round 1): at dir-conv 20 the product is
`6.499999999999999`, which is **below** 6.5, so it rounds to 6 by ordinary
rounding — the banker's tie rule never engages, and the draft's "float underflow
*and* a tie rule" was a false conjunction (round 2). Either way the expected
value turned on float representation; −25 → `0.7375` → `7.375` → **7** does not.

Cases 4/5 prove the bullish **sizing** is unchanged; case 13 proves the
**refusal** is not bullish-exempt. Case 16 asserts the history entry whose
absence is §4.3's neighbour defect. Case 22 pins §11's inert-gate case.

---

## 9. Verification

1. `cd backend && .venv/bin/python -m pytest -q` — baseline **2604 passed / 1
   skipped** (re-measured twice this session), plus the new tests, zero failures.
2. `python3 scripts/state.py` — exit 0, no drift.
3. **Reproduce before fixing:** run case 1 against unmodified `main` and record
   that it returns 3. A regression test never seen red proves nothing.
4. **Mutation checks** — each must kill ≥1 new test:
   - invert `is_bullish`
   - restore `100 - conviction`
   - drop the `action` guard (killed by case 15)
   - build `right_of` on `_PIPE_RE` (killed by cases 10/11)
   - **drop the OCC `\d{6}` date anchor** (killed by case 18's `SNAP00185000`) —
     the mutation round 2 proved is live
   - **drop the 4-field pipe anchor** (killed by case 18's `AAPL|185|C00185000`)
   - **raise `TypeError` instead of `ValueError` for a non-`str`** (killed by
     case 14)
5. No frontend file is in this diff, so `npm run typecheck` is vacuous; skipped
   deliberately rather than listed as evidence.

---

## 10. The record this plan corrects — two withdrawals, both mine

`pending_kenneth[0]` says *"only the deep-bearish end (−40 and below) happens to
come out right. The bullish side is correct throughout."*

**Withdrawal 1 (round 1).** The draft called both claims **"false."** Overreach:
on the **SELL arm** the entry was describing, conviction −40 does come out right
(`mult(140) == mult(40) == 1.000`, executed).

**Withdrawal 2 (round 2).** Revision 1 replaced that with *"correct about a
branch that never runs"* — which over-corrected in the other direction. The word
**"only"** is wrong. Executed, old SELL arm `mult(100−c)` vs that frame's correct
`mult(−c)`, shipped config, qty 10, over all `c ∈ [−100, 100]`:

```
quantity-level agreement runs: [(-100, -38), (98, 100)]
```

Two errors in the old entry, not none: the boundary is **−38**, not −40, and the
**extreme-bullish end (+98..+100) also agrees** — structurally attainable from a
transition row whose observed mass all went to Bull (`regime_omm.py:207-208`).

**The accurate statement, which is what goes in the state file:** the old entry
is correct *within its own frame* — that `action` partitions bullish trades from
bearish ones — **except at the extreme-bullish end, and its −40 boundary is
really −38**. And that frame is the defect: it does not describe this app,
because `AutoTradeArm` sends `BUY` for calls *and* puts, so the bearish half of
the scale was never on the SELL arm the entry analysed.

The state file must carry §1.3's table, both withdrawals, and the −38/+98
correction. The draft's "both false" also reached `606ba015`'s commit message and
revision 1's "correct about a branch that never runs" reached `12d485b1`'s; both
are corrected in the next commit message rather than silently dropped. The
original entry stays verbatim beneath, per this file's convention.

---

## 11. Kenneth's decision — surfaced, not assumed

Two separable changes. **Only the first is a sizing change, and only the first is
bearish-only.**

### 11.1 The sizing correction — bearish only

`min_mult: 0.3`, armed quantity 10:

- long put in a **downtrend**: 3 contracts → **10**. It sizes *up*, 3.3×.
- long put in an **uptrend**: 10 contracts → **3**. It sizes *down*.

Bullish sizing is untouched (§8 cases 4/5).

**The 3.3× propagates into two downstream gates that refuse rather than trim** —
sizing at `:369`, `_check_exposure` called at `:404`, `_check_daily_loss` at
`:422`:

- `_check_exposure` has **two** raises: `:485` `RuntimeError(f"Exposure cap
  breach: {result.reasons}")`, unconditional and with **no suggested re-arm
  quantity**, and `:491-493` *"Quantity {N} exceeds exposure cap — re-arm with
  {M} contracts"*. Either way it means a **manual re-arm**; the first gives the
  less actionable message.
- `_check_daily_loss` is linear in quantity — `:591`
  `this_risk = entry_premium * quantity * 100 * stop_pct`.

So trades firing today at 3 contracts will, at 10, consume **3.3× the daily-loss
budget** and start coming back `cap_blocked` / `daily_loss_blocked` needing a
manual re-arm.

**But both gates can be completely inert, and round 2 was right that hiding this
was the worst omission in the draft.** `:402` is
`if portfolio_snapshot is not None and strategy.entry_premium > 0:` — the
exposure cap is **skipped entirely** when `entry_premium == 0` — and `:591`'s
`this_risk` is **0 for any quantity** at zero premium, so the daily-loss breaker
cannot fire either. `ArmRequest.entry_premium` defaults to `0.0` and its own
comment at `routers/auto_trade.py:28` says *"exposure check is skipped if 0"*;
the value comes from an all-`??` chain at `AutoTradeArm/index.tsx:159-161`, so if
every term resolves undefined the key is omitted and the default applies.

**Where `entry_premium` is zero, a 3.3× position goes out with no cap check and
no daily-loss check at all.** §8 case 22 pins it.

One more understatement: `this_risk` multiplies by `stop_pct` (0.60) while the
auto-trader **places no protective order** — the in-code note at `:560-574` says
so ("the true exposure is the whole premium either way"). So even when the gate
does run it under-counts true exposure by `1/0.6`.

**And the conviction is SPX's, not the symbol's** (`regime_monitor.py:180`). "The
regime that supports it" means the *market's* regime.

The arithmetic is not in question — the only alternative to sizing up in a
supportive regime is keeping a number that is provably inverted — but the
*magnitude* is a knob he owns:

- **As planned:** `min_mult: 0.3` unchanged, bearish trades reach full size at
  conviction −40, symmetric with the bullish side. Symmetry is what every
  direction-aware piece of this codebase has had since `49ffa53`.
- **Correction without the size-up:** raise `min_mult`, or set a stiffer
  `full_conviction_pct`. Both are `scoring_rules.yaml` edits, neither needs code,
  and §8 case 21 pins that the mirror is config-independent — so shipping the
  correct arithmetic does not commit him to the magnitude.

### 11.2 The fail-closed refusal — direction-agnostic, and it stops orders that fire today

A symbol whose right cannot be determined now refuses the trade. On `ibkr_paper`
that order **is submitted today** (§4.2), and the refusal applies to **calls as
well as puts**. This is the correct posture — an order whose direction cannot be
established must not be sized — but it is a second, separate behaviour change and
it is not bearish-only. §8 cases 12/13/14 cover it; §4.1's parser is what keeps
it from firing on the real shapes (`BRK.B`, `BF.B`, `TBD`).

Also still his and unchanged here: `49ffa53`'s bearish floors (30 Swing /
40 Position) remain **unmeasured** pending the bearish validation scans.

---

## 12. Scope fence

| in | out |
|---|---|
| `services/auto_trader.py:174-176`, its docstring `:143-150`, one added import | every handler message, `:250` and `:395-396` (§4.3) — logged |
| `data/option_symbol.py` — new `right_of` + its two patterns only | `_PIPE_RE` / `_OCC_RE` / `pipe_to_occ` / `to_occ` behaviour (§4.1) |
| `tests/test_auto_trader.py`, `tests/test_option_symbol.py` | `maybe_fire_on_scan`'s outer handler — its own piece (§4.3) |
| `PROJECT_STATE.json` (§10) | the alert `rec_id`/`alert_type` incoherence — logged; the symbol-specific class **already exists** via `premium_stop_pct` (§4.3) |
| — | the scan path: `stock_scan.py:767` calls `compute_omm(direction=req.direction)` and `:970` feeds that straight to `_conviction_mult`, so it is **already in the trade's own frame**. Fence verified complete: repo-wide `conviction_mult` has exactly two consumers (`auto_trader.py:177`, `stock_scan.py:970`) and `get_last_conviction` exactly one (`auto_trader.py:170`) |
| — | `entry_premium == 0` disabling both risk gates (§11.1) — pre-existing, logged, and **it is the biggest thing on this page that is not being fixed** |
| — | `BRK.B`/`BF.B` reported as a Tradier network fault (§4.1) — pre-existing, logged |
| — | adding an `effect` field anywhere: it inverts two rows of §2's table |
| — | `scan.py:1007`'s `int(strike)` truncation and `'TBD'` default — pre-existing, logged |
| — | `scoring_rules.yaml` — no config edit is needed or made |

---

## 13. Round tally

Dispositions are honest: **fixed** = the plan now specifies different behaviour;
**logged** = recorded against main, deliberately not fixed; **withdrawn** = a
claim of mine removed as unsupported.

### Round 1 — 19 findings (2 gate-level, 8 major, 7 minor, 2 nits)

| # | finding | disposition |
|---|---|---|
| G1 | parser built on `_PIPE_RE` would refuse live `BRK.B`/`BF.B`/`TBD`; "nothing is sent" false | **fixed** (superseded by round 2's G1 — the *replacement* was also wrong) |
| G2 | §10's "both are false" is overreach | **withdrawn** |
| M1 | `effect="OPEN"` precondition uncited | **fixed** — §2, §12 |
| M2 | §3.1 rejected a straw man (Optional vs required field) | **fixed** — §3.2 |
| M3 | "right cannot disagree with the contract" false | **withdrawn**, real invariant stated — §3.1 |
| M4 | fail-closed sits after two early returns; stated unconditionally | **fixed** — §4.2; case 19 |
| M5 | `str(exc)` duplicates existing text; alert routing incoherent | **logged**, not fixed — §4.3 |
| M6 | the draft's own message fix was the widening it forbade | **logged** — §5.3 deleted |
| M7 | §11 hid the exposure-cap / daily-loss consequence | **fixed** (incompletely — see round 2 M4) |
| M8 | changed strings had no test coverage | **moot** — no string is changed now |
| m1 | provenance `2e027c76` not an ancestor | **fixed** — header |
| m2 | case 3's `6` sat on a rounding tie | **fixed** — −25 → 7 |
| m3 | comment above `:176` and docstring not in the plan | **fixed** — §5.2 |
| m4 | unrecognised `action` silently picks a direction | **fixed** — §5.2 guard, case 15 |
| m5 | §12's "§1, fact 6" dangling | **fixed** — §12 |
| m6 | conviction is SPX-derived, never said | **fixed** — §1.3, §11 |
| m7 | no test at a second config | **fixed** — case 21 |
| n1 | citation drift | **fixed** (incompletely — see round 2 n1) |
| n2 | missed `tastytrade_paper.py` corroborating Fault B | **fixed** — §1.2 |

### Round 2 — 18 findings (1 gate-level, 7 major, 8 minor, 2 nits)

| # | finding | disposition |
|---|---|---|
| **G1** | **§5.1 specified the parser in prose; written to that prose it silently returns the WRONG right on `SNAP00185000`, `P00185000`, `XC00000000` and a 3-field pipe id** | **fixed** — §5.1 ships anchored regexes; §4.1 carries the executed reject list; case 18 pins the four inputs; §9.4 adds both anchor mutations |
| M1 | `right_of(None)` → `TypeError`, caught nowhere: no history, 500 not 400, no alert | **fixed** — `isinstance` guard raising `ValueError`, §5.1/§5.2; case 14 |
| M2 | "four other consumers depend on `_PIPE_RE`" invented; there is **one** | **withdrawn** — §4.1 names `tradier_paper.py:9`/`:92` |
| M3 | §11's two gates can be **inert** at `entry_premium == 0`; `:485` raise and `stop_pct` under-count omitted | **fixed** — §11.1; case 22; logged in §12 as the biggest unfixed item |
| M4 | §10's replacement claim over-corrected: boundary is −38, and +98..+100 also agrees | **withdrawn** — §10 |
| M5 | "first symbol-specific case" false — `premium_stop_pct` already reaches that alert | **withdrawn** — §4.3 item 2, now "adds a second, does not create the class" |
| M6 | §8 could not detect G1; four uncovered modes (call refusal, non-`str`, fire()'s 400/no-alert, §11's own claim) | **fixed** — cases 13, 14, 17, 22; case 18 rewritten |
| M7 | §13's dispositions overstated ("fixed" for what was logged) | **fixed** — this section, with a disposition legend |
| m1 | `conviction_label` is `:136-142`; `{:+d}%` is `conviction_interpretation:148`; Neutral is −14..+14 | **fixed** — §1.1 |
| m2 | SPX fetch is `:180`, not `:185-187` | **fixed** — §1.3, §11 |
| m3 | the test is at `:514`, not `:513` (inherited from the state file unchecked) | **fixed** — §2, §7 |
| m4 | `fire()`'s `try:` is `:368`, `except` runs `:370-398` | **fixed** — §4.2 |
| m5 | the wording defect's operator-facing instance is the alert at `:250`, uncited | **fixed** — §4.3 item 1 |
| m6 | scope fence cannot compile — no import shown | **fixed** — §5.2, §12 |
| m7 | case 13's "(not 10)" wrong — dropping the guard yields **3** | **fixed** — case 15 |
| m8 | Tradier dotted-ticker outcome hedged as "presumably" | **fixed** — §4.1, it surfaces as a network fault |
| n1 | six citations still drifting | **fixed** — m1–m6 above |
| n2 | case 3's rounding rationale a false conjunction | **fixed** — §8 |

Nothing deferred across either round. Round 3 pending.
