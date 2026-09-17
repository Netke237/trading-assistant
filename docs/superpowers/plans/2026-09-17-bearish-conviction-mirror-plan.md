# Bearish conviction mirror — `auto_trader._apply_vol_sizing`

> **One line of arithmetic, one layer, backend only.** `services/auto_trader.py`,
> `data/option_symbol.py`, and their tests. No frontend change, no new endpoint,
> no scan-path change, no scoring-config change.
>
> **Gate-level and live on `main`.** It sizes live broker orders.
>
> **Revision 1** — adversarial round 1 returned 2 gate-level, 8 major, 7 minor
> and 2 nit findings. §4 and §5.1 are redesigned (round 1 proved the planned
> parser would refuse two live S&P names), §10's central claim is withdrawn as
> overreach, §5.3 is deleted as below-gate widening, and the provenance in this
> header was wrong. §13 tallies the round.

**Goal, in one sentence:** the auto-trader sizes a bearish option trade by how
strongly the regime supports *that* trade, instead of by how strongly it opposes
it.

**Provenance, corrected.** The line was written by **`23674da4`** (2026-09-05),
whose parent has no sizing logic at all (`git show 23674da4~1:…/auto_trader.py |
grep conviction` → empty). Round 1 caught that `pending_kenneth[0]`'s
`2e027c76` (2026-06-23) is **not an ancestor of this history** — verified,
`git merge-base --is-ancestor 2e027c76 HEAD` fails; it carries an identical line
on an abandoned lineage. No argument in this plan rests on the defect's age.
`2c478d88` *is* an ancestor and did replace the multiplier on the line below.

---

## 1. The defect, executed rather than argued

`auto_trader.py:176`:

```python
directional_conv = conviction if strategy.action == "BUY" else (100 - conviction)
```

Two independent faults sit in that line. **The second one is the live one.**

### 1.1 Fault A — `100 - conviction` is not the mirror of a signed scale

`conviction_pct` is **signed, −100..+100**:

| | where | what |
|---|---|---|
| producer | `regime_omm.py:131-133` | `conviction(signal, direction)` returns `signal if direction == "Bullish" else -signal` |
| scale | `regime_omm.py:208` | `conv_pct = int(round(conviction(sig, direction) * 100))` over `signal = P(Bull) − P(Bear)` |
| corroboration | `regime_omm.py:136-141` | `conviction_label` treats −15..+15 as Neutral and formats `{:+d}%` |
| cache | `regime_monitor.py:184` | `compute_omm(closes, direction="Bullish")`, documented at `:26` as the **"bullish frame"** |

The mirror of a signed conviction is `-conviction`. `100 - conviction` is the
mirror of an *unsigned* 0..100 scale that exists nowhere in this codebase.

### 1.2 Fault B — the branch that runs is the unmirrored one

`action` is **always `"BUY"`** on every trade this app arms:

- `frontend/components/organisms/AutoTradeArm/index.tsx:207` hardcodes
  `action: 'BUY'`, commented *"long single-leg option (call or put) is always
  buy-to-open"*. It is the **only** production caller of `/auto-trade/arm`.
- `routers/auto_trade.py:83` is the **only** non-test `ArmedStrategy(...)`
  construction. No scheduler or service arms; `scan.py` reaches the auto-trader
  only through `maybe_fire_on_scan`.
- Independently corroborated in backend code: `data/tastytrade_paper.py:35-39`
  already records *"nothing in this codebase's frontend ever sends an options
  order with action=SELL."*

So the `100 - conviction` arm is **unreachable from the production path**, and
every bearish trade — a long **put** — takes the `BUY` arm and is sized by
**unmirrored bullish** conviction. `ArmRequest:20` does accept `SELL` from the
wire, so Fault A is one `curl` away from live.

### 1.3 What that costs, measured

Executed against the real `conviction_mult` on the **shipped** block
(`scoring_rules.yaml:463-471`, `min_mult: 0.3, full_conviction_pct: 40`), armed
quantity 10, for a **long put**:

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

**It is exactly inverted, not merely mis-scaled** — and not only on the shipped
config: `mult_today(c) ≡ mult_correct(−c)` holds identically at *any* config, by
construction. A put gets the **floor** in the regime that most supports it and
**full size** in the regime that most opposes it. Only conviction 0 is right,
because 0 is its own negation.

**Whose regime.** `regime_monitor.py:185-187` fetches **SPX** and nothing else.
The number that sizes a long put on any symbol is the *market's* regime, not
that symbol's. Load-bearing for §11, where Kenneth is asked to approve a size-up
"in the regime that supports it."

---

## 2. Why the mirror cannot key off `action` at all

For a single-leg option, direction is carried by BUY/SELL **and** the option
right together:

| action | right | position | direction |
|---|---|---|---|
| BUY | C | long call | **bullish** |
| BUY | P | long put | **bearish** |
| SELL | C | short call | **bearish** |
| SELL | P | short put | **bullish** |

So `bullish = (action == "BUY") == (right == "C")`. Keying off `action` alone
cannot express this, which is the root cause of both faults rather than a second
bug.

**The precondition that makes this table exhaustive, and it must be cited rather
than assumed:** `auto_trader.py:289` hardcodes `effect="OPEN"`, commented
*"Auto-trade is structurally entry-only — arm()/fire() have no existing-position
lookup anywhere … Hardcoded rather than added to ArmRequest/ArmedStrategy so
there's no way to call this endpoint with the wrong effect."* The distinction is
real at the adapter — `data/tradier_paper.py:22-28` maps `("SELL","OPEN") →
sell_to_open` and `("SELL","CLOSE") → sell_to_close`. Two of the four rows above
**invert** for a closing trade, and sizing a *closing* trade by regime conviction
is meaningless in any case. §12 fences this: adding an `effect` field to
`ArmRequest` or `ArmedStrategy` must revisit this line.

The existing test at `test_auto_trader.py:513` shows the confusion the
`action`-only reading causes: it arms a **put** with `action="SELL"` and calls
that the bearish case. By the table, selling a put is **bullish**. See §7.

---

## 3. Where the right comes from

`ArmRequest` (`routers/auto_trade.py:16-`) carries no direction or right field,
and `option_symbol` is an unvalidated `str`. The right is already in the symbol,
in both formats the wire carries:

| format | example | sent by |
|---|---|---|
| pipe | `AAPL\|185\|2025-05-16\|C` | the frontend — `AutoTradeArm:185,206` posts `card.contract` |
| OCC | `AAPL260620C00185000` | accepted by the same field; used in tests |

### 3.1 The actual invariant that makes this sound

Round 1 correctly demolished the draft's claim that the right "cannot disagree
with the contract being traded." It can, twice over:

- `data/ibkr_paper.py:116-118` — when `conid` is present the contract is
  identified by `conidex` and `option_symbol` is **never read**. Nothing
  reconciles the two.
- `routers/scan.py:1007` builds the id as
  `f"{symbol}|{int(strike)}|{contract.get('expiry','TBD')}|{'C' if direction=='Bullish' else 'P'}"`
  — the right is a **copy of the scan direction**, never read off the selected
  contract's own `right`, and `int(strike)` truncates 187.5 → 187, so the id is
  not a faithful description of the contract.

**That second point is the real justification, and it is stronger than the one it
replaces:** the right in the symbol *is* the scan's own `direction`,
round-tripped. `right_of` therefore recovers the direction the scan intended,
which is exactly the quantity the mirror needs. It does not depend on the id
faithfully describing strike or expiry — and it must not (see §4).

### 3.2 Rejected alternative — thread an explicit direction through `ArmRequest`

Round 1 was right that the draft rejected this against a straw man (it argued an
*Optional* field's silent `None`, when `quantity: int = Field(..., ge=1)` at
`auto_trade.py:21` shows a **required** field 422s loudly). The honest reasons:

1. `option_symbol` already exists on the wire and already carries the answer;
   a direction field needs a frontend change, a schema change and a migration
   story for nothing this plan gains.
2. It would be a **second** source of truth for the same fact, free to disagree
   with the contract actually being traded.

---

## 4. When the right cannot be determined

### 4.1 Round 1 killed the draft's parser, and this is the redesign

The draft built `right_of` on the module's existing `_OCC_RE` / `_PIPE_RE`. Round
1 proved that refuses **live production symbols**. Executed:

```
AAPL|185|2025-05-16|C        pipe=True   occ=False
BRK.B|185|2027-01-15|P       pipe=False  occ=False   <-- live S&P name
BF.B|70|2027-01-15|C         pipe=False  occ=False   <-- live S&P name
AAPL|185|TBD|C               pipe=False  occ=False   <-- scan.py:1007 default
AAPL260620P00185000          pipe=False  occ=True
GARBAGE                      pipe=False  occ=False
```

`_PIPE_RE`'s `[A-Z]{1,6}` root rejects dotted tickers, and **`BRK.B` and `BF.B`
are both live** in `data/sp500.csv:63,77`. `scan.py:1007`'s `'TBD'` expiry
default is reachable whenever a contract carries no expiry. The draft would have
refused every auto-trade on those — a regression introduced by a bug fix.

**The redesign: reading the right does not require validating the symbol.** The
right is the last pipe-delimited field, or the `[CP]` before OCC's 8-digit
strike. `right_of` gets its own two right-focused patterns — strict about
*shape*, permissive about the ticker root and the expiry text — so all four real
shapes above resolve and `GARBAGE` still raises.

**`_PIPE_RE` and `_OCC_RE` are NOT widened.** They gate `pipe_to_occ` / `to_occ`,
which four other consumers depend on; changing what they accept is out of scope
and would be widening. (That dotted tickers already fail `pipe_to_occ`, so
`BRK.B` options presumably cannot reach the Tradier path today, is a
**pre-existing defect logged against main by this plan, not fixed here.**)

### 4.2 The residual failure, and it is a real behaviour change

For a symbol with no determinable right, the posture is §9.1, fail closed — *a
datum this path cannot honour stops the trade* — because the alternative, sizing
at full, is the loudest failure producing the largest position.

**It raises `ValueError`, not `SizingConfigError`.** `conviction_sizing.py:326-330`
already draws that line: a bad *datum* "must not be reported, alerted or recorded
as a broken config file." `ValueError` lands in `fire()`'s handler
(`try` at `:369`, `except` at `:370-390`), which records history status
**`sizing_data_blocked`** and re-raises — the path the merged guard built, so this
composes with it rather than adding a mechanism.

**What the draft got wrong, per round 1:** it claimed "same outcome for the
trader — nothing is sent." False. `ibkr_paper._build_payload` (`:104-121`) never
reads `option_symbol` at all — with `conid` set it sends `conidex`, otherwise
`{"symbol": order.symbol, "secType": "OPT"}` — so on `ibkr_paper` a malformed
symbol **is submitted today**. After this change it is refused. That is a live
order that stops going out, not a status rename. It is the correct trade-off
(an order whose direction cannot be established must not be sized), but it is a
behaviour change and §8 tests it.

**The refusal is conditional, and the draft stated it unconditionally.**
`right_of` is reached only after two early returns — `:156`
(`resolve_sizing(cfg) is None`, sizing off) and `:171` (`conviction is None`,
monitor has not ticked). With sizing disabled or before the first tick, the same
symbol arms and fires exactly as today. That is defensible — the datum is only
needed when it is read — and it is stated rather than moved, because validating
above the early returns would refuse trades in states where sizing is not
consulted at all.

### 4.3 Two consequences this diff creates and does NOT fix — logged

Round 1 was right that the draft's own message fix was the widening it invoked
`audit_rule` to forbid elsewhere. `audit_rule`: *"only gate-level findings are
fixed in-branch. Nothing else — not 'while I am here', not a one-line nit."* A
misleading log clause puts no wrong number on a broker order. **The draft's §5.3
is deleted.** Logged against main instead:

1. **Wording.** `:395-396` renders a non-`SizingConfigError` as *"the regime
   conviction is not a usable number"*, wrong for an unparseable symbol. Both
   handlers already append `str(exc)`, so the operator does see the real reason
   ("Cannot determine option right from 'GARBAGE'"); the clause preceding it is
   merely wrong. Below the gate.
2. **Alert routing, and this one is *created* by this diff.** `:245`
   `alert_type="CONFIG_ERROR"` and `:257` `rec_id="auto-trade-sizing-config"` are
   justified in-code as *"the file is broken, not the symbol"* — a
   symbol-independent key. A malformed option symbol is the **first** case
   reaching that alert which *is* symbol-specific, so one bad symbol now
   suppresses genuine sizing-config alerts for every other symbol inside the
   dedup window, and `:258` `type_enabled=True` bypasses `enabledTypes` on the
   same now-false premise. Below the gate (it suppresses an alert; it does not
   mis-size an order) but **introduced here**, so it is logged as such rather
   than as pre-existing.

Both belong with the separate, larger defect already logged and reproduced
against `897bfe69`: `maybe_fire_on_scan`'s outer
`except (SizingConfigError, ValueError)` at `:519-527` wraps **all** of `fire()`,
so a non-sizing `ValueError` (`_check_daily_loss`'s `float(max_daily_loss_pct)`,
`:559`) alerts with sizing wording, records **zero** history entries and burns
the same `rec_id`. That piece — `open_questions[5]` item 1, whose *own proposed
remedy is wrong* — is where all three should be fixed together. **`audit_rule`
forbids widening this diff to reach it.**

---

## 5. The change, file by file

### 5.1 `backend/app/data/option_symbol.py` — new `right_of`

```python
def right_of(option_symbol: str) -> str:
    """Return 'C' or 'P' for *option_symbol*, in either supported format.

    Deliberately NOT built on _PIPE_RE/_OCC_RE: those validate the WHOLE
    symbol, and their [A-Z]{1,6} root rejects BRK.B and BF.B (both live in
    sp500.csv) while scan.py:1007's 'TBD' expiry default fails the date
    group. Reading the right needs neither the ticker nor the expiry, so it
    matches only the right's own position and is permissive about the rest.

    Raises ValueError if the right cannot be determined. A caller that sizes
    a position on the answer must never be handed a guess.
    """
```

No behaviour change to `is_occ`, `pipe_to_occ` or `to_occ`.

### 5.2 `backend/app/services/auto_trader.py` — the mirror

Replace `:174-176` — **the two comment lines go with it**; they are the
authoritative statement of the defect:

```python
# Direction is carried by action AND the option right, not by BUY/SELL alone:
# long call and short put are bullish, long put and short call are bearish.
# Exhaustive only because :289 hardcodes effect="OPEN" -- a CLOSE would invert
# two of those four rows. conviction_pct is the SIGNED bullish frame
# (regime_monitor.py:26), so the mirror of a bearish trade is -conviction,
# never 100 - conviction.
right = right_of(strategy.option_symbol)      # ValueError => fail closed (§4.2)
if strategy.action not in ("BUY", "SELL"):    # dataclass, so Literal is unenforced
    raise ValueError(f"cannot size an order with action {strategy.action!r}")
is_bullish = (strategy.action == "BUY") == (right == "C")
directional_conv = conviction if is_bullish else -conviction
```

The `action` guard answers round 1's asymmetry finding: `ArmedStrategy` is a
plain dataclass (`:24`), so its `Literal` is unenforced and only `ArmRequest:20`
validates. A direct construction with `"buy"` would otherwise **silently invert**
the direction for a call. Same fail-closed posture as `right`, same handler.

`_apply_vol_sizing`'s docstring (`:143-149`) currently promises only
`SizingConfigError`; it must name `ValueError` too.

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
is simply the wrong one. No test, log line or alert fires today.

---

## 7. The test that pins the wrong behaviour — corrected, not deleted

`test_auto_trader.py:513`
`test_vol_sizing_sell_reduced_in_strongly_bullish_market` asserts *"SELL at
conviction=80 → bearish_conv=20, full=40 → ramp mult=0.65 → 4 rounds to 3"*, with
a docstring explaining that arithmetic as intended. Wrong in **both** halves,
both corrected in place with the reason written down (the handling Q1
established — an assertion that holds a bug in place is corrected, never
deleted):

1. It asserts `100 - conviction`.
2. Its premise is confused: it arms a **put** with `action="SELL"`, i.e. a
   **short put**, which is **bullish** (§2). At conviction +80 a short put is
   strongly supported and correctly sizes at **full**, so the corrected test
   asserts `4 → 4` and is renamed to say so.

The bearish case it *meant* to cover becomes a new test on a long put (§8 case 1).

---

## 8. Tests

All in `backend/tests/test_auto_trader.py` unless noted. Each asserts a
**quantity** driven through `fire()`, not a multiplier in isolation.

| # | case | armed | conviction | expect |
|---|---|---|---|---|
| 1 | long put, strong downtrend — **the regression** | BUY P, qty 10 | −80 | 10 (not 3) |
| 2 | long put, strong uptrend | BUY P, qty 10 | +80 | 3 (not 10) |
| 3 | long put, mild downtrend — pins the ramp, not just the ends | BUY P, qty 10 | **−25** | **7** |
| 4 | long call, strong uptrend — bullish side unchanged | BUY C, qty 10 | +80 | 10 |
| 5 | long call, strong downtrend — bullish side unchanged | BUY C, qty 10 | −80 | 3 |
| 6 | short call is bearish | SELL C, qty 10 | −80 | 10 |
| 7 | short put is bullish (§7's corrected case) | SELL P, qty 4 | +80 | 4 |
| 8 | neutral conviction is its own mirror | BUY P, qty 10 | 0 | 3 |
| 9 | pipe-format symbol sizes identically to OCC | BUY `AAPL\|185\|2025-05-16\|P` | −80 | 10 |
| 10 | **`BRK.B` dotted root still sizes** (round 1) | BUY `BRK.B\|185\|2027-01-15\|P` | −80 | 10 |
| 11 | **`TBD` expiry still sizes** (`scan.py:1007`) | BUY `AAPL\|185\|TBD\|P` | −80 | 10 |
| 12 | malformed symbol fails closed | BUY `"GARBAGE"` | −80 | no order; history `sizing_data_blocked` |
| 13 | **unrecognised `action` fails closed** | `"buy"` C, qty 10 | +80 | no order; `sizing_data_blocked` (not 10) |
| 14 | **malformed symbol through `maybe_fire_on_scan`** | BUY `"GARBAGE"` | −80 | no order, **a history entry exists**, one alert |
| 15 | sizing **disabled** ⇒ malformed symbol still fires (§4.2 conditionality) | BUY `"GARBAGE"` | −80 | order at full size |
| 16 | `conviction is None` ⇒ full size, unchanged | BUY P, qty 10 | None | 10 |
| 17 | **mirror is config-independent** (§11's knob) | BUY P, qty 10 @ `min_mult 0.5 / full 20` | −80 | 10 |
| 18 | `right_of` units, in `tests/test_option_symbol.py` | — | — | both formats × both rights, dotted root, `TBD` expiry, and raises on `GARBAGE`/`""` |

Case 3's conviction moved from −20 to **−25** on round 1's finding: at dir-conv
20 the product is `6.499999999999999` and `round(6.5) == 6` (banker's), so the
expected `6` depended on a float underflow *and* a tie rule. At −25 → mult
0.7375 → 7.375 → **7**, on neither.

Cases 4/5 prove the bullish side is not silently changed. Case 14 asserts the
history entry whose absence is the §4.3 neighbour's defect. Case 15 pins the
conditionality honestly rather than leaving it undiscovered. Case 17 pins the one
knob §11 hands Kenneth.

---

## 9. Verification

1. `cd backend && .venv/bin/python -m pytest -q` — baseline **2604 passed / 1
   skipped** (re-measured this session), plus the new tests, zero failures.
2. `python3 scripts/state.py` — exit 0, no drift.
3. **Reproduce before fixing:** run case 1 against unmodified `main` and record
   that it returns 3. A regression test never seen red proves nothing.
4. **Mutation check:** invert `is_bullish`; restore `100 - conviction`; drop the
   `action` guard; build `right_of` on `_PIPE_RE`. Each must kill ≥1 new test —
   the last one is what round 1 caught, so case 10/11 must be the killers.
5. No frontend file is in this diff, so `npm run typecheck` is vacuous; skipped
   deliberately rather than listed as evidence.

---

## 10. The record this plan corrects — and the draft's own overreach, withdrawn

**Withdrawn.** The draft said `pending_kenneth[0]`'s *"The bullish side is
correct throughout"* and *"only the deep-bearish end (−40 and below) happens to
come out right"* were **"both false."** Round 1 showed that is overreach, and it
is right: on the **SELL arm** — the branch that entry was describing — conviction
−40 does come out right (`100−(−40) = 140` and `−(−40) = 40` both clamp to
`mult 1.000`, executed and identical), and the BUY arm *is* correct for calls,
which the draft conceded one sentence later while calling it false.

**What is actually true, and it is the more useful statement:** both sentences
hold *within the frame the old entry assumed* — that `action` partitions bullish
trades from bearish ones. **That frame is the defect.** It does not describe this
app, because `AutoTradeArm` sends `BUY` for calls *and* puts, so the bearish half
of the scale was never on the SELL arm the entry analysed. The old entry is
neither false nor merely incomplete: it is correct about a branch that never
runs.

The state file must carry §1.3's measured table, this correction, and the
withdrawal of the draft's "both false" claim — which also reached the plan commit
message at `606ba015` and must be corrected in the next commit's message rather
than silently dropped. The original entry stays verbatim beneath, per this file's
convention.

---

## 11. Kenneth's decision — surfaced, not assumed

**This changes live auto-trade sizing on the bearish side.** On §1.3's numbers,
`min_mult: 0.3`, armed quantity 10:

- A long put in a **downtrend** goes from 3 contracts to **10** — it sizes *up*,
  3.3×, in the regime that supports it.
- A long put in an **uptrend** goes from 10 contracts to **3** — it sizes *down*.

The second half is conservative. **The first half is not**, and round 1 was right
that the draft stopped there and hid what follows from it:

**The 3.3× propagates into both downstream gates, which do not trim.** Sizing
runs first (`:369`), then `_check_exposure` (`:401`), then `_check_daily_loss`
(`:423`):

- `_check_exposure` **refuses** rather than resizing — `:492` raises *"Quantity
  {N} exceeds exposure cap — re-arm with {M} contracts"*, which means a **manual
  re-arm**.
- `_check_daily_loss` is linear in quantity — `:591`
  `this_risk = entry_premium * quantity * 100 * stop_pct`.

So trades that fire today at 3 contracts will, at 10, consume **3.3× the
daily-loss budget** and will start coming back `cap_blocked` /
`daily_loss_blocked` with a manual re-arm required. That is the operational
consequence of this decision, not a footnote.

**And the conviction is SPX's, not the symbol's** (`regime_monitor.py:185-187`).
"The regime that supports it" means the *market's* regime.

The arithmetic is not in question — the only alternative to sizing up in a
supportive regime is keeping a number that is provably inverted — but the
*magnitude* is a knob he owns:

- **As planned:** `min_mult: 0.3` unchanged, bearish trades reach full size at
  conviction −40, symmetric with the bullish side. Symmetry is what every
  direction-aware piece of this codebase has had since `49ffa53`.
- **Correction without the size-up:** raise `min_mult`, or gate bearish sizing at
  a stiffer `full_conviction_pct`. Both are `scoring_rules.yaml` edits, neither
  needs code, and §8 case 17 pins that the mirror is config-independent — so
  shipping the correct arithmetic does not commit him to the magnitude.

Also still his and unchanged here: `49ffa53`'s bearish floors (30 Swing /
40 Position) remain **unmeasured** pending the bearish validation scans.

---

## 12. Scope fence

| in | out |
|---|---|
| `services/auto_trader.py:174-176`, its docstring `:143-149` | every handler message (§4.3) — logged, not fixed |
| `data/option_symbol.py` — new `right_of` only | `_PIPE_RE` / `_OCC_RE` / `pipe_to_occ` / `to_occ` behaviour (§4.1) |
| `tests/test_auto_trader.py`, `tests/test_option_symbol.py` | `maybe_fire_on_scan`'s outer handler — its own piece (§4.3) |
| `PROJECT_STATE.json` (§10) | the alert `rec_id` / `alert_type` incoherence (§4.3) — logged as introduced here |
| — | the scan path: `stock_scan.py:767` calls `compute_omm(direction=req.direction)` and `:970` feeds that straight to `_conviction_mult`, so it is **already in the trade's own frame** and needs no mirror (round 1 verified this independently; the draft's `§12` cited a "fact 6" that did not exist in it) |
| — | `BRK.B`/`BF.B` failing `pipe_to_occ` on the Tradier path — pre-existing, logged (§4.1) |
| — | adding an `effect` field anywhere: that inverts two rows of §2's table |
| — | `scoring_rules.yaml` — no config edit is needed or made |
| — | `scan.py:1007`'s `int(strike)` truncation and `'TBD'` default — pre-existing, logged |

---

## 13. Round tally

**Round 1** (independent subagent, `bmad-review-adversarial-general`, checked
against the real code and executed): **19 findings** — 2 gate-level, 8 major,
7 minor, 2 nits.

| # | finding | disposition |
|---|---|---|
| G1 | §4.1's "nothing is sent" false; IBKR ignores `option_symbol`; parser would refuse live `BRK.B`/`BF.B`/`TBD` | **fixed** — §4.1 redesigned, §4.2 corrected, cases 10/11/12 added |
| G2 | §10's "both are false" is overreach | **fixed** — withdrawn in §10 |
| M1 | `effect="OPEN"` precondition uncited | **fixed** — §2, §12 |
| M2 | §3.1 rejected a straw man (Optional vs required field) | **fixed** — §3.2 rewritten |
| M3 | "right cannot disagree with the contract" false | **fixed** — §3.1 states the real invariant |
| M4 | fail-closed sits after two early returns; stated unconditionally | **fixed** — §4.2 states the conditionality; case 15 |
| M5 | `str(exc)` duplicates existing text; alert routing incoherent | **fixed** — change deleted; routing logged (§4.3) |
| M6 | §4.2's own message fix was the widening it forbade | **fixed** — §5.3 deleted |
| M7 | §11 hid the exposure-cap / daily-loss consequence | **fixed** — §11 |
| M8 | changed strings had no test coverage | **moot** — no string is changed now; case 14 added anyway |
| m1 | provenance `2e027c76` not an ancestor | **fixed** — header, corrected to `23674da4` |
| m2 | case 3's `6` sat on a rounding tie | **fixed** — −25 → 7 |
| m3 | comment above `:176` and docstring not in the plan | **fixed** — §5.2 |
| m4 | asymmetric fail-closed: unrecognised `action` silently picks | **fixed** — §5.2 guard, case 13 |
| m5 | §12's "§1, fact 6" dangling | **fixed** — evidence now in §12 |
| m6 | conviction is SPX-derived, never said | **fixed** — §1.3, §11 |
| m7 | no test at a second config | **fixed** — case 17 |
| n1 | citation drift (`:207`→`:208`, `:337`→`:339`, handler ranges) | **fixed**, and round 1's own drift corrected: the alert is `:245`/`:257`/`:258`, the cap raise `:492`, `this_risk` `:591` |
| n2 | missed `tastytrade_paper.py:36-39` corroborating Fault B | **fixed** — §1.2 |

Nothing deferred. Round 2 pending.
