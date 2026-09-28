# YAML config integrity — an edit either takes effect, or fails loudly

> ## ⛔ STOPPED — `audit_rule`'s HARD CAP has fired. Do not run a fifth round.
>
> Four adversarial rounds; none came back clean at the gate. `audit_rule`:
> *"if a phase reaches THREE rounds without going clean, STOP AUDITING AND TELL
> KENNETH. That is evidence the batch is too big to audit, not that it needs a
> fourth round."* The cap fired after round 3 and round 4 was run anyway; its
> findings are recorded in §11 but **were not fixed**, because fixing them is
> the behaviour the cap exists to stop.
>
> **The non-convergence signature is unambiguous.** Findings per round:
> 24/15 gate → 25/16 → 11 gate+19 nit → 11 gate+8 nit. More telling than the
> counts: **round 4's findings 3, 6, 7 and 8 all sit in round 3's FIX TEXT.**
> `audit_rule` predicts exactly this — *"Re-auditing the cumulative diff every
> round is what turned each round's fixes into the next round's findings."*
>
> **Two process errors made it worse, and they are mine, not the plan's:**
> 1. I briefed every round on the **whole document**. `audit_rule` (2) says the
>    target shrinks: round N>1 reviews only what changed since N-1. Auditing the
>    cumulative document each time is the documented way to never converge.
> 2. I continued past the cap into a fourth round instead of stopping.
>
> **Recommendation — split the document, do not revise it again.** §2
> (`regime_sizing`) is gate-level, self-contained, and fixes a wrong number that
> is live today; it should be lifted into its own one-page plan and audited
> alone, with the round-2-style shrinking target. Everything else — validation,
> staleness, the surface — is a second document. See §12.

**Status:** STOPPED at the hard cap after four rounds. The DIAGNOSIS in §1, §2
and §11 is verified and worth keeping — every factual claim in it has been
executed against the real code, repeatedly, by independent reviewers. The
STAGING (§3-§8) is what failed to converge and should be rewritten from the
split in §12 rather than patched further. §9 holds nine decisions for Kenneth.

**Goal, in one sentence:** when Kenneth maintains a config YAML, the change he
made is the change the app runs — or the app tells him, by name, that it is not.

**Why now.** The direction-conviction gate ran BACKWARDS for three months
(2026-06-18 → 2026-09-16) and nothing on screen or in a log said so. That was a
code bug, not a config bug, but it exposed the same class of hazard: this app
can run on a number nobody intended and give no sign. The next threshold change
Kenneth makes will be to the bearish floors in `scoring_rules.yaml`, by hand,
based on scan evidence. That edit must hold.

**What round 3 changed — read this before §2.**

1. **The two `regime_sizing` formulas disagree on the SHIPPED, VALID config** —
   by up to 1.5× — so there is a wrong number on a broker order **today**, with
   no typo and nothing malformed (§2.2). Round 2 found the divergence and filed
   it as "independent of validation", assigning it to no stage. That was wrong:
   it is the most immediate gate-level item in this document.
2. **Stage 0 was not standalone.** Its acceptance ("rejected at startup") needed
   a startup call site that §4 said Stage 4 owned. The holder and call site move
   into Stage 0 (§2.3, §4.1).
3. **The banner had no poll.** Stage 4 mirrored `EventThresholdsBootstrap`,
   which fetches once on mount with no interval — so "the banner clears on the
   next poll" described a mechanism that did not exist, and restart discipline
   remained the only detection (§4.5).
4. **Mode A1's optimism was too broad**, and **D2's "only writer" was false**
   (§1).

**What round 2 changed — read this before §2.** Round 1 established that this
work *does* touch a broker order, correcting the first draft's claim that it
could not. Round 2 found that correction itself was wrong, in the dangerous
direction:

1. Round 1 reasoned that a broken `regime_sizing` block can only make an order
   **at least as large as intended**, because the multiplier is "bounded above
   by 1.0". **That is false.** The expression is
   `max(min_mult, min(1.0, …))` — the outer `max` takes a
   config-supplied value, so it is bounded above by `min_mult`, not by 1.0. A
   one-character typo scales a live order **up without bound** (§2).
2. The hazard is therefore *not* confined to a malformed file. A **well-formed
   config with a wrong number** — the precise thing this plan is named for —
   is what multiplies the order. Round 1's Stage 0 (re-route the exception
   path) does not touch that case at all, because nothing raises.
3. `regime_sizing` has a **second money-touching consumer on the scan path**,
   using a **different formula** over the same block (§2.2).
4. The cache inventory round 1 introduced as its headline correction was itself
   incomplete: there are **six**, and the missing one is the money-touching one
   (§1 Mode A).

---

## 1. The failure modes — four, and one of them is mis-modelled by `lru_cache`

### Mode A — STALENESS, across six caches

`scoring_rules.yaml` is loaded by six separate `@lru_cache(maxsize=1)` readers,
each with its own path constant, none going through a common loader (verified by
`grep -rn "scoring_rules" backend/app/`, not by recall — round 1 listed five and
missed the sixth):

| Reader | Location | Reads | Catches? |
|---|---|---|---|
| `load_scoring_cfg` | `services/config_loader.py:15` | whole file | no |
| `_load_full_scoring_cfg` | `routers/stock_scan.py:129` | whole file | no |
| `_load_scoring_config` | `services/auto_trader.py:97` | `regime_sizing` | **yes → `{}`** |
| `_load_config` | `scoring/stock_scorer.py:46` | whole file | no |
| `_load_config` | `scoring/entry_quality.py:16` | whole file | no |
| `_cfg` | `scoring/signal_confidence.py:23` | whole file | no |

**No `cache_clear()` for any of them exists anywhere under `backend/app/`**
(verified — the only three in the tree are `risk_settings.py:159-161`, for the
risk config).

**A1 — staleness, and it splits in two. Round 2's version of this was too
optimistic and would have misled whoever implements Stage 2.**

- **A1a — the file does not parse.** `functools.lru_cache` does not cache
  exceptions (verified — a raising cached function re-executes on every call),
  so the five non-catching readers **re-read on every call** and a fix takes
  effect with no restart. `auto_trader._load_scoring_config` is the exception:
  it catches and returns `{}` (`auto_trader.py:103-106`), and **`{}` caches
  permanently**, so auto-trade stays silently unsized for the life of the
  process while every scan recovers.
- **A1b — the file parses to the WRONG value. All six caches are poisoned, and
  only a restart clears them.** Round 2 stated the recovery property as though
  it covered broken files generally. It does not, and the cases it misses are
  the ones this plan exists for:
  - `yaml.safe_load('')` returns `None` (verified). All five non-catching
    readers return that without indexing (`config_loader.py:19`,
    `stock_scan.py:131`, `stock_scorer.py:48-49`, `entry_quality.py:18-19`,
    `signal_confidence.py:25-26`), so **`None` is cached permanently in all
    five**, `{}` in the sixth. All six poisoned, not one.
  - A copy of `scoring_rules.yaml` truncated at a line boundary — exactly what a
    crash mid-`open(path,'w')` produces, i.e. what D2 below can create —
    **parses cleanly**, yielding a dict missing `regime_sizing`, `regime_gate`
    and `fundamentals_gate`. Cached in all six.
  - And §2.1's headline hazard, a well-formed file with a wrong number, is
    cached identically by all six with no restart-free recovery.

  **A1b is the case that matters**, and it is the one where restart discipline
  is the only remedy. Stage 0 requirement #6 and Stage 2's design must be read
  against A1b, not A1a.

**A2 — torn read.** The six caches populate lazily at six different moments, so
an edit landing between two of them leaves two versions live at once: a scan can
score trend from the old `stock_scorer` copy and confidence from the new
`signal_confidence` copy — numbers matching no file that ever existed.
**Round 1 claimed Stage 2 detects this. It does not — see §6, 2.1.**

### Mode B — MISPLACEMENT. The edit is read, but not from where it sits.

`direction_conviction` has a positional validator with three logged holes, plus a
fourth logged in round 1. All re-derived against the running code.

- **B1 — a flat dotted key forges a legal path.** `_walk_direction_conviction_paths`
  joins segments with `"."` (`config_loader.py:124`), so a top-level key spelled
  `"horizons.position":` yields exactly the path `legal_paths` accepts —
  *provided a real `horizons:` mapping is also present*. Validation then passes
  and the operator's value is never read: with `99` in the forged block,
  `load_direction_conviction_min_trend('Bearish','Position')` still returns
  `40.0`. **Live hazard.** (Round 1's printed repro omitted the real `horizons:`
  block and therefore did not reproduce this — corrected in §5.)
- **B2 — a `_defaults: &anchor` holder carrying a block raises `ValueError`**
  naming `horizons._defaults.direction_conviction`, although the round-3
  docstring (`config_loader.py:153-159`) names that holder as the shape the
  positional rewrite unblocked. The existing test
  (`test_config_loader.py:403-407`) parametrises `("_defaults", {"weights":
  {"trend": 0.3}})` — a holder carrying a *non-`direction_conviction`* block, not
  an empty one as round 1 stated. **Not a live hazard**: the shipped
  `scoring_rules.yaml` has no anchors or merge keys at all.
- **B3 — `RecursionError`, not `ValueError`**, escaping both routers as a bare
  500 with no detail. Trigger: a self-referential anchor whose cycle contains
  **no** `direction_conviction` key.
- **B3b — a cycle that *does* contain one** yields a `ValueError` naming a path
  **that does not exist in the file** (e.g. `horizons.loop.swing.direction_conviction`),
  destroying the name-the-key guarantee in a different way.

### Mode C — NO VALIDATION for everything else, failing in THREE ways

Nine top-level families (verified): `stock_score_thresholds`, `confidence_gate`,
`confidence_backtest`, `horizons`, `entry_quality`, `regime`, `regime_gate`,
`regime_sizing`, `fundamentals_gate`. Exactly ONE sub-key of ONE family is
positionally validated.

- **C1 — silently defaults.** A misspelled key falls through to a code-side
  default, forever. The hazard the plan is named for.
- **C2 — bare 500, no detail.** Readers that index bare and raise `KeyError`:
  `routers/config.py:31,60,84`, `routers/scan.py:593,682`,
  `scoring/stock_scorer.py:58`, `scoring/entry_quality.py:23`,
  `scoring/signal_confidence.py:34`. They fail loudly but uselessly: they need a
  *message*, not a *check*.
- **C3 — swallowed into a per-symbol rejection, which empties the scan
  silently (new in this revision).** `stock_scan.py:141-142` bare-indexes
  `sizing["full_conviction_pct"]` and `sizing["min_mult"]` inside
  `_conviction_mult`, which is called at `:968` — **inside `_process_stock`'s
  try** (`:706`), whose handler at `:1030-1032` is
  `except Exception as exc: return {"symbol": symbol, "reason": str(exc)}`.
  So a `regime_sizing` block missing `min_mult` makes **every symbol in the
  universe return `reason: "'min_mult'"`** — an empty scan, no 500, and
  nothing naming the file. (There *is* a per-symbol traceback:
  `stock_scan.py:1031` is `logger.exception("Error processing %s", symbol)`.
  What is missing is any signal that the CONFIG is the cause.) This is the plan's own thesis failure, on a path
  round 1 listed as deliberately left running.

**C2's consequence outside the scan.** Because `routers/config.py` indexes bare,
a malformed file 500s `/api/config/iv-thresholds`, `/stop-premium-thresholds`
and `/event-thresholds`. Those feed `ivThresholdsStore`,
`stopPremiumThresholdsStore` and `eventThresholdsStore`, all
**fetch-with-hardcoded-fallback** (`eventThresholdsStore.ts:25-40` holds
`FALLBACK` and `catch { set({loaded:true}) }`). So a bad config already makes the
Step-5 UI display thresholds that are not in the file, silently.

### Mode D — MACHINE OVERWRITE, and a non-atomic write

`routers/risk_settings.py:157` calls `_save_risk(cfg)`, which at `:40-43` does a
plain truncating `open(path,'w')` + `yaml.dump` over the whole file.

- **D1 — formatting loss.** `risk_rules.yaml`'s **28 comment lines** are erased
  on the first Settings→Risk save, along with blank lines and quoting style.
  **Correction to round 1, which overstated this:** hand-added *keys* survive.
  The handler (`:134-157`) does `cfg = _load_risk()`, patches individual keys,
  then dumps `cfg`, so unknown keys round-trip intact and `sort_keys=False`
  preserves order. Comments and formatting only.
- **D2 — NON-ATOMIC WRITE, and this is gate-level. There are THREE of them,
  not one** (round 2 said "the only YAML writer in the repo that does this";
  `grep -rn "yaml.dump\|yaml.safe_dump" backend/app/` says otherwise):
  - `routers/risk_settings.py:40-43` — `_save_risk` → `risk_rules.yaml`.
  - `routers/risk_settings.py:24-29` — `_save_settings` → `settings.yaml`.
  - `routers/notification_settings.py:25-28` — `_save_yaml` → `settings.yaml`,
    the identical `open(path,'w')` + `yaml.dump(data, f)` pattern.

  A crash or full disk mid-write leaves the file truncated — position sizing and
  max-loss config, or broker and scheduler configuration, gone. Under
  `audit_rule`'s "**CORRUPT PERSISTED DATA**" clause all three block.
  `settings.yaml` being out of scope for *validation* (§3) does not exempt it
  from this: the exclusion criterion is about which hazard applies, and D2 is
  the Mode D hazard the criterion names. Two modules also independently
  read-modify-write `settings.yaml`, so they can lose each other's updates.

  Every other writer is atomic — all six schedule stores, `strategy_param_store`,
  `credential_store.py:111` and `settings_migrations.py:48` use
  tmp + `os.replace` (`scan_schedule_store.py:71-72`,
  `ingestion_schedule_store.py:56-57`, `edgar_schedule_store.py:51-52`,
  `tuning_schedule_store.py:54-55`, `sp500_schedule_store.py:51-52`,
  `strategy_watch_store.py:86-87`, `strategy_param_store.py:157-158`).

---

## 2. THE GATE-LEVEL HAZARDS — `regime_sizing` multiplies live orders

Under `PROJECT_STATE.json`'s `audit_rule` — "a finding blocks only if it can put
a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED
DATA" — this section and D2 are the only gate-level items in this document.

### 2.1 — The multiplier is NOT bounded above by 1.0

`auto_trader.py`, stitched from `:124`, `:130` and `:131`:

```python
min_mult        = float(cfg.get("min_mult", 0.5))
mult = max(min_mult, min(1.0, directional_conv / full_conviction))
adjusted_qty = max(1, round(strategy.quantity * mult))
```

The inner `min(1.0, …)` is bounded. The outer `max` is not: `min_mult` comes
from the same YAML block. Executed against the real function —
`min_mult: 5` (the obvious decimal typo for the shipped `0.5`),
conviction 10, full 40 → `mult = 5` → **quantity 10 becomes 50**.

The shipped config has `regime_sizing.enabled: true`
(`scoring_rules.yaml:463-466`), so this is live, not latent.

**This reframes the whole stage.** The hazard is not "a malformed file disables
sizing"; it is **a well-formed file with a wrong number multiplying an order**.
Nothing raises, so exception handling is irrelevant to it.

### 2.2 — A second consumer, on the scan path, with a DIFFERENT formula

`grep -rn regime_sizing backend/app/` returns exactly two consumers. Round 1
declared the second surface "auto-trade fire path, NOT a scan". Wrong.
`stock_scan.py:967-969`, inside `_process_stock` on `POST /stock-scan`:

```python
sizing_cfg = full_cfg.get("regime_sizing", {"enabled": False})
mult = _conviction_mult(regime_signal["conviction_pct"], sizing_cfg) if regime_signal else 1.0
sized_risk_pct = (req.risk_pct * mult) if req.risk_pct is not None else None
```

That flows into `_position_size(...)` (`:971`, which also takes the
similarly-multiplied `sized_risk_fixed` from `:970`) → the share count on
`StockPositionCard` → `StockSendDialog` → broker.

And it is a **different formula over the same block** (`stock_scan.py:138-144`):
`lo + (1.0 - lo) * frac`, versus auto_trader's `max(lo, min(1.0, frac))`.

**These disagree on the SHIPPED, VALID config — today, with no typo and nothing
malformed.** Executed against both real functions with the shipped
`min_mult: 0.5, full_conviction_pct: 40, enabled: true`:

| conviction | `auto_trader` | `stock_scan` | ratio |
|---|---|---|---|
| 0 | 0.500 | 0.500 | 1.00× |
| 10 | 0.500 | 0.625 | **1.25×** |
| 20 | 0.500 | 0.750 | **1.50×** |
| 30 | 0.750 | 0.875 | 1.17× |
| 40 | 1.000 | 1.000 | 1.00× |

The scan card's share count and the auto-trade fire path size the same setup up
to **50% apart**. That is a wrong number on a broker order under
`audit_rule`'s gate, requiring no config edit at all. Round 2 filed this as "a
correctness defect independent of validation" and assigned it to no stage; that
was wrong, and it is now Stage 0 requirement #7 with its own acceptance criterion
and its own decision in §9.7.

**And under a `min_mult` typo the scan formula is not merely inflated — it is
INVERTED.** With `lo = 5`, `lo + (1-lo)·frac` is monotonically *decreasing* in
conviction (verified: conviction 0 → 5.00, 10 → 4.00, 20 → 3.00, 40 → 1.00).
The strongest signal gets the smallest position. That is the same class of defect
as the inverted direction-conviction gate that motivated this entire plan.

An existing test already pins this multiplier and asserts an invariant the code
does not honour: `tests/test_stock_scan_regime.py:5-11`,
`test_conviction_mult_only_reduces`, is true for `min_mult <= 1` and **false**
for `min_mult > 1`. Stage 0's tests must reference it — its name is a claim.

One asymmetry worth noting for Stage 0: `stock_scan.py:143` guards its division
(`if full else 0.0`); `auto_trader.py:130` does **not**, so
`full_conviction_pct: 0` is an uncaught `ZeroDivisionError` on the fire path.

### 2.3 — Stage 0, rewritten

Round 1's Stage 0 ("replace the `except: return {}` with a hard failure") is
necessary but nowhere near sufficient. Stage 0 must:

0. **Own the startup call site and the `config_health` holder.** Round 2 put
   these in Stage 4 while Stage 0's acceptance said "rejected at startup", so
   Stage 0 could not meet its own criterion on its own branch. They move here.
   Stage 4 then adds only the endpoint and the frontend. **The call must run
   BEFORE any scheduler starts** — the scan scheduler starts at
   `main.py:172-177`, early in the lifespan body (`lifespan` is defined at
   `:132-133`, its startup section runs `:134-268`, `yield` at `:269`), so a
   call placed after it lets a scheduled scan fire against an unpopulated
   holder.
1. **Validate value ranges, not just parseability**: `0 < min_mult <= 1.0`,
   `full_conviction_pct > 0`. This is what stops §2.1, and no amount of
   exception re-routing does. Both bounds matter: `min_mult: -2` yields a
   negative `dollar_risk`, and `_position_size` (`stock_scan.py:684`) returns
   `max(1, int(negative))` = 1 share — another silent wrong number.
2. **Clamp at the point of use — and RECORD the clamp.** A silent clamp is this
   plan's own thesis failure introduced by its own remedy: with the startup
   check bypassed (Kenneth edits without restarting — §9.5's unguarded case), a
   bare clamp turns `min_mult: 5` into a plausible `mult = 1.0` and nothing
   anywhere says the config was ignored. So the clamp must clamp **both bounds**
   and write into `config_health`, log at ERROR, and mark the affected card, so
   a clamped run is never indistinguishable from a correct one.
3. **Distinguish parse failure from `regime_sizing` absent** — both currently
   return `{}` and are indistinguishable at the return site.
4. **Fail closed on the fire path** rather than firing unsized (§9.1).
5. **Fix C3**: the bare indexes at `stock_scan.py:141-142` must not be able to
   empty a scan through the per-symbol handler.
6. **Account for §1 A1b**: a file that *parses* to a wrong, `None` or partial
   value is cached in all six readers, so a "fixed" YAML does not revive
   anything without a restart. (A1a's restart-free recovery applies only to
   files that fail to parse.)
7. **Unify the two formulas**, per §2.2 — this is the item that fixes a wrong
   number on a broker order today, independent of any config edit. Which formula
   is canonical is Kenneth's decision, §9.7.

**Size:** not the ~20 lines round 1 estimated, nor the ~120/~200 round 2 gave
before the call site and the formula unification were added. Two consumers, two
formulas, a range validator, a recording clamp, the startup holder, and a test
with a mocked broker on the armed path: realistically **~180 source, ~280 test**.
**This is at `audit_rule`'s ~500-line batch ceiling and should be split** into
0a (formula unification + clamp, the money fix) and 0b (startup validation +
holder).

**Acceptance** — each clause checkable on Stage 0's own branch:
- `min_mult: 5` and `min_mult: -2` are both rejected at startup naming
  `regime_sizing.min_mult`, with the holder populated before any scheduler runs.
- A value reaching the arithmetic is clamped to `0 < mult <= 1.0` on both paths
  **and the clamp is visible** — in `config_health`, in the log at ERROR, and on
  the affected card. A clamped run is never indistinguishable from a correct one.
- Both paths return the **same** multiplier for the same conviction on the
  shipped config (the §2.2 table collapses to a single column).
- `test_conviction_mult_only_reduces` holds for every value the range validator
  admits.
- `full_conviction_pct: 0` raises no `ZeroDivisionError` on either path.
- `min_mult` absent does not empty a scan (C3).

**Branch:** `claude/yaml-integrity-stage0-regime-sizing`.
**Rollback:** the clamp and range check are additive; revert restores today's
behaviour exactly.

---

## 3. What this plan deliberately does NOT do

`audit_rule` names batch size as the root cause of non-converging audits: one
change, one layer, ~500 lines. A single "validate all config" change would span
15 reader modules and five YAML files and would not converge. So this is **five
stages** (0, 1, 4, 2, 3 — see §8 for the order), each its own branch, each with
its own adversarial round.

**Stages are NOT independent. Round 1 claimed "any stage can ship alone and is
useful alone"; that is false and is withdrawn.** The real dependency graph:

- **Stage 0** — standalone **because it now carries its own startup call site
  and holder** (§2.3 item 0). Round 2 claimed it was "genuinely standalone"
  while its acceptance depended on a call site Stage 4 owned; that was the
  contradiction. Note the honest limit: Stage 0's startup rejection is visible
  in the log and in the holder, but not on screen until Stage 4 — the same
  caveat §3 applies to Stages 1 and 2. Stage 0 ships first anyway because its
  *other* half, the formula unification, fixes a live wrong number with no
  surface required.
- **Stage 4 (surface)** — must precede 1, 2 and 3 to give them a surface. It
  adds the endpoint and frontend on top of Stage 0's holder.
- **Stage 1** — output is a better `ValueError` message. Shipped before Stage 4,
  it is invisible: the message dies in `RunScanButton`'s `.catch(() => …)`.
- **Stage 2** — output is a staleness signal. Shipped before Stage 4, it is a
  log line nobody reads, which is the plan's own stated failure mode.
- **Stage 3** — depends on Stage 4's call site and Stage 1's tuple-path walker.

Out of scope for all stages, by one criterion applied consistently: **a file is
out of scope when the app writes it**, because there the hazard is Mode D
(overwrite/corruption), not A/B/C (silent misread), and Mode D needs a different
remedy.

- `settings.yaml` — **12** reader modules (round 1 said 22; not checked).
- The six schedule stores — they write their own YAML.
- `strategy_params.yaml` — machine-written by `strategy_param_store.adopt()`
  (`yaml.safe_dump` at `:157`, `os.replace` at `:158`).

By that criterion `risk_rules.yaml` is **also** app-written, so its place as
breadth target #2 is a genuine decision, not an oversight — §9.3. Verified for
contrast: nothing under `backend/app/` writes `scoring_rules.yaml` or
`contract_rules.yaml`.

---

## 4. Stage 4 — surface the verdict (must ship before 1, 2 and 3)

Round 1 added this stage but left it unable to work: it served a verdict no stage
produced, and a `stale` field owned by a stage scheduled after it.

**4.1 — The holder and call site come from Stage 0; Stage 4 adds the endpoint.**
`main.py`'s lifespan startup section (`:134-268`, `yield` at `:269`) calls no
validator today, and no `config_health`-shaped endpoint exists anywhere.

**What the call validates, and what `ok` therefore means.** The only validator
in the tree is `_validated_direction_conviction_blocks` (`config_loader.py:131`),
which checks `direction_conviction` placement and nothing else. Stage 3 adds the
rest, last. So through Stages 0, 4, 1 and 2 the banner would be structurally
green for every Mode C hazard — the very thing this plan is named for — while
reporting `ok: true`. §4.3 refuses to hardcode `stale: false` on exactly this
reasoning; the same reasoning binds here.

**So `ok` is scoped, and the payload must say so:** `{ ok, checked: [<family>…],
errors, stale }`, and the banner renders "checks passing: direction_conviction,
regime_sizing" rather than a bare green. An unscoped `ok` is an assertion the
system cannot make.

**4.2 — The endpoint re-parses and re-validates from disk; a `stat` alone
cannot answer.** `GET /api/config/health` →
`{ ok, checked, errors: [{file, path, message}], stale }`.

Round 2 said the endpoint "must `stat` the file on every read". A `stat` tells
you the mtime moved; it **cannot produce `ok` or `errors[]` for the new bytes** —
that needs a re-parse and a re-run of the validator against a file the six
`lru_cache`s are not holding. So: `stat` as the cheap pre-filter, and on change
re-parse and re-validate from disk, outside the caches.

That creates a **third state**, which the payload must carry rather than
flattening into `true`/`false`: *disk is valid but differs from what this process
is running* — the A1b case, where the fix is a restart, not an edit. A
stale-green banner is worse than no banner (§9.5).

**4.3 — `stale` ownership.** The field is populated by Stage 2. Until Stage 2
ships, Stage 4 serves `stale: null` (unknown), not `false`. A hardcoded `false`
would be an assertion the system cannot make.

**4.4 — The unattended path, and why the last-run error is not enough.**
Scheduled scans run at `scan_schedule_scheduler.py:150-156` →
`_execute_stock_scan_core`, recorded via `record_scheduled_scan_run`
(`:163`/`:170`). An error notifier already exists end to end
(`_notify_scan_schedule_error` → `notify_enabled_channels`, `:87-98`) — round 2's
framing that a failed overnight scan is invisible was not accurate for the case
it covers.

**But that path only fires when an exception ESCAPES, and C3 does not escape.**
A missing `min_mult` becomes a per-symbol rejection at `stock_scan.py:1030-1032`,
so the run completes, records `status="success"`, and
`_notify_scan_schedule_success` (`:101-108`) emails Kenneth
"**0 candidate(s) found**". The unattended path reports success on a scan the
config silently emptied — this plan's thesis failure, inside the remedy round 2
chose for it.

**So the scheduled-run record and the health payload carry a mass-rejection
signal**: candidate count plus a rejection-reason histogram. A run where every
symbol failed for the same reason is unhealthy regardless of its status field.

**4.5 — Frontend.** Per CLAUDE.md conventions (own folder, `index.tsx` +
`.module.css`, atoms→molecules→organisms, no card shadows):
- `configHealthStore` — ephemeral, not persisted (server state).
- `ConfigHealthBootstrap` **atom**, mounted in `app/(frame)/layout.tsx`
  alongside `EventThresholdsBootstrap` (`layout.tsx:31`). Round 1 omitted the
  atom entirely, which CLAUDE.md forbids.
  **It must NOT simply mirror `EventThresholdsBootstrap`.** That component is,
  in full, `useEffect(() => { fetch(); }, [fetch])` — one fetch on mount, no
  interval — and `(frame)/layout.tsx` is a persistent shell that does not
  remount across route changes. Mirroring it means **there is no poll**, so
  §4.2's re-validate-on-read is never read a second time and "the banner clears
  on the next poll" describes a mechanism that does not exist. This was round
  2's remedy for §9.5 answering itself with nothing.
  **Specify: a 60s interval, plus an immediate refetch on scan submit.** The
  interval bounds how long a stale-green banner can persist; the submit refetch
  makes the check land at the moment it matters.
- `ConfigHealthBanner` organism.
- `RunScanButton`'s catch changed from `.catch(() => …)` to `.catch((err) => …)`
  surfacing `err.message`. **Say what Kenneth actually reads:** `lib/api.ts:64`
  throws `` `API ${path} → ${res.status}: ${detail}` ``, so a raw pass-through
  would toast `API /api/stock-scan → 500: misplaced direction_conviction block
  in scoring_rules.yaml: found at …`. Functional but wrong for an alert toast —
  strip the transport prefix and render the detail, with the full string kept
  for the banner. Today (`RunScanButton/index.tsx:171-181`) it discards
  the error and toasts "Scan failed — backend unreachable", so a malformed YAML
  sends Kenneth to debug the wrong thing entirely — while `lib/api.ts:45-65`
  carefully extracts the `json.detail` it throws away.

**Size:** ~70 backend + ~60 backend test; ~140 frontend + CSS + ~80 frontend
test. (Round 1 budgeted no tests for this stage.)

**Acceptance:**
- With a deliberately broken YAML, the banner names the file and the path.
- After fixing the file *without restarting*, the banner reflects the new state
  within one interval (≤60s) — this is what 4.2's re-validate plus 4.5's poll
  buy together; neither alone is sufficient.
- A file that is valid on disk but differs from what the process is running
  renders as the third state (restart needed), not as green.
- A scheduled scan returning zero candidates because of config surfaces as
  unhealthy, not as success.
- The banner never renders a bare "ok" — it names which families were checked.

**Branch:** `claude/yaml-integrity-stage4-surface`.
**Rollback:** the banner is additive; reverting leaves today's behaviour.

---

## 5. Stage 1 — close the `direction_conviction` defects (Mode B)

Below-gate by `audit_rule`'s definition (see §8 and §9.6), but it is where the
next edit Kenneth makes actually lands.

**1.1 — Path as a tuple, not a joined string.** `_walk_direction_conviction_paths`
yields `tuple[str, ...]`; `legal_paths` becomes a set of tuples; comparison is
tuple equality. A `.` inside a key can then never synthesise a separator. Error
text still renders via `".".join(path)`. Fixes B1.

**1.2 — Skip non-positional holders.** Treat a mapping key beginning `_` as a
holder and skip it. Fixes B2.

**1.3 — Bound the recursion — and NOT with a global `id()` set.** PyYAML merge
keys share object identity (verified:
`horizons._defaults.direction_conviction is horizons.swing.direction_conviction`
→ `True`), so a global id-keyed seen-set visits one occurrence and silently skips
its siblings, making B2's verdict depend on dict insertion order. **The code
comment must forbid it explicitly.** Use a depth limit or a path-scoped cycle
set. Fixes B3.

**1.4 — Never name a path that is not in the file.** Fixes B3b.

**Inline repros** — all four re-derived against the running validator. Round 1's
B1 snippet did **not** reproduce B1 (it raised on the missing `horizons:`
mapping, so a test written from it would have passed today and pinned nothing),
and round 1 printed one snippet under two contradictory labels. Corrected:

```yaml
# B1 — validation PASSES and the 99 is never read.
# load_direction_conviction_min_trend('Bearish','Position') returns 40.0.
# The real horizons: block is REQUIRED — without it the validator raises on
# `horizons` being absent and B1 is not what you are testing.
horizons:
  swing:    {direction_conviction: {bullish_min_trend: 30, bearish_min_trend: 30}}
  position: {direction_conviction: {bullish_min_trend: 40, bearish_min_trend: 40}}
  intraday: {direction_conviction: {bullish_min_trend: null, bearish_min_trend: null}}
horizons.position:
  direction_conviction: {bearish_min_trend: 99}

# B3 — RecursionError (NOT ValueError). The cycle must contain NO
# direction_conviction key.
horizons: &h
  swing: {weights: {trend: 0.3}}
  loop: *h

# B3b — ValueError naming horizons.loop.swing.direction_conviction,
# a path that does not exist in the file. Cycle DOES contain the key.
horizons: &h2
  swing: {direction_conviction: {bullish_min_trend: 30}}
  loop: *h2

# B2 — currently raises ValueError naming horizons._defaults.direction_conviction.
# After 1.2 it must raise NOTHING (the holder is skipped).
horizons:
  _defaults: &d
    direction_conviction: {bullish_min_trend: 30, bearish_min_trend: 30}
  swing:
    <<: *d
```

**Tests — enumerated with expected outcome, because they are not all the same
shape** (round 1's "all five repros raise the named `ValueError`" was untestable:
there were three repros, and B2 must raise nothing under 1.2):

| Case | Expected after Stage 1 |
|---|---|
| B1 | `ValueError` naming `horizons.position` as a forged flat key |
| B2 | **no raise** — holder skipped |
| B3 | `ValueError` (not `RecursionError`) |
| B3b | `ValueError` naming only paths present in the file |
| `str(k)` guard, `config_loader.py:200` | two unknown keys of *mixed type* → named `ValueError`, not `TypeError` |
| Intraday | **contract undecided — see §9.4** |

The `str(k)` guard is genuinely untested today:
`test_direction_conviction_rejects_a_misspelled_key` (`:248-256`) uses string
typos only, so `sorted()` never sees mixed types.

**Intraday is a trading-semantics question, not an implementation detail**, and
round 1 routed it to nobody. `_DIRECTION_CONVICTION_DEFAULTS` omits intraday
(`config_loader.py:101-103`) and `test_shipped_yaml_and_code_defaults_agree`
(`test_config_loader.py:355`) asserts YAML and code defaults agree on null-ness, so a numeric intraday
threshold would be honoured by the resolver *and fail that existing test*. §9.4.

**Also note a third call site:** `stock_scan.py:704` resolves the gate inside
`_process_stock` but deliberately *outside* the per-symbol try (see the comment
at `:696-703`), so direct callers screen on the real gate. Round 1 said "only two
consult the gate", which is true at endpoint level but misleading here — any
change to what the resolver raises must account for `:704`.

**Size:** ~70 source, ~200 test.
**Branch:** `claude/yaml-integrity-stage1-direction-conviction`.
**Rollback:** pure `config_loader.py` change, no boot impact.

---

## 6. Stage 2 — staleness detection (Mode A1b)

**2.1 — Scope honestly: this stage detects A1, NOT A2.** Round 1 asserted the
opposite ("a per-cache stash would … miss A2 entirely") and had it backwards.
A2 is "two caches hold *different versions at the same time*". A single global
stash records one byte-hash and compares it to disk; it can answer "does disk
differ from what was first loaded?" (A1) but never "do the caches disagree with
each other", because it never records what each cache holds. **Per-cache hashes
compared pairwise are the only construction that sees A2** — round 1 forbade the
only thing that works. Given six caches and Kenneth's restart discipline, A2
detection is deferred, not solved; recorded as a known gap.

**2.1b — What is hashed, and against what reference.** Round 2 never said.
**Scope: `scoring_rules.yaml` only** (Stage 3's breadth order brings the other
two later). **Reference point: the bytes read by the startup validation in Stage
0b**, not "first load" — with six caches populating lazily at six different
moments there is no single first load, so "what was first loaded" was undefined
and 2.2's rule could not be implemented as written. The startup read is the one
moment all six are guaranteed not yet populated.

**2.2 — Which signal wins.** `mtime` is the cheap pre-filter; the byte hash is
authoritative. A changed `mtime` with an unchanged hash is not a divergence and
must not warn — false alarms are how a warning gets ignored. **Caveat now that
A2 is out of scope:** in the edit-then-revert case this check reports clean while
a cache may still hold the intermediate version. That is the A2 gap, stated
plainly rather than papered over.

**2.3 — Two different questions, both kept.** Round 1 contradicted itself on the
check point. They are distinct: *is the loaded config valid?* (startup, Stage 4)
versus *does the file on disk still match what was loaded?* (per scan request and
per health poll, Stage 2).

**2.4 — No reload endpoint, no auto-reload**, per §9.2. Auto-reload is
additionally forbidden because reloading six caches at six moments mid-scan is
the torn read, deliberately induced.

**2.5 — Cost.** A `stat` per scan is free; the hash is read only on `mtime`
change.

**Honest value statement.** Given §9.2 (he restarts after every edit), the hash
trivially matches on the ordinary path — this check is a no-op exactly when
Kenneth follows his own stated workflow. Round 1 called Mode A "the most likely
way an edit fails to hold" and then demoted it; that framing was incoherent and
is withdrawn. Mode A is **low-likelihood under his workflow, high-consequence
when it fires** — and §9.5 is the argument for building it anyway.

**Size:** ~50 source, ~80 test.
**Acceptance:** editing the file mid-process makes the next health poll and the
next scan request report divergence naming the file; an identical-bytes rewrite
does not.
**Branch:** `claude/yaml-integrity-stage2-staleness`.
**Rollback:** detection-only; revert.

---

## 7. Stage 3 — path-shaped schema for more families (Mode C1)

Round 1 replaced a name-based rule with a path-shaped one after the collision
table showed name-matching cannot work here. **Round 2 verified the collision
table and the redesign — both are correct and this section survived review.**

Collisions in the shipped file (verified programmatically): `event`, `vol`,
`trend`, `pullback`, `trigger` = 6 paths each (a block at `horizons.<h>.<name>`
*and* a scalar at `horizons.<h>.weights.<name>`); `atr_period` = 6; `enabled` = 4;
`swing`/`position`/`intraday` = 3 each; `cautionBelow`/`rejectBelow` = 2 each.
(The two largest are `strong` = 8 and `weak` = 7; they do not change the
conclusion, but the table is illustrative, not exhaustive.)
A name-based rule either rejects the shipped file on day one or must enumerate
every legal path — at which point the typo it exists to catch (indenting
`trend:` into `weights`) is indistinguishable from the legal `weights.trend`.

**3.1 — Schema is PATH-SHAPED, walked from the root.** A key's legality is
decided by where it sits, never by what it is called. `horizons.<h>.weights.trend`
and `horizons.<h>.trend` are simply two declared paths, neither teaching the
other.

**3.2 — Scope.** Families that gate a trade, smallest first:
`stock_score_thresholds`, `confidence_gate`, `regime_gate`, `fundamentals_gate`.
`horizons.<h>.*` spans lines 43-445 and is its own stage. **`regime_sizing` is
NOT here** — it is gate-level and belongs to Stage 0.

**3.3 — Do not police the file, but DO close a declared family's subtree.**
Round 2 left this ambiguous, and the ambiguity decides whether Stage 3 catches
anything at all. Two different rules were being conflated:

- **Undeclared top-level families: OPEN.** An unrecognised family is ignored, so
  an additive edit cannot 500 the scan. Cost: a misspelled *family*
  (`regime_gates:` for `regime_gate:`) is silently skipped forever — this plan's
  own hazard, accepted as a false negative. §9.6.
- **Inside a DECLARED family: CLOSED.** An undeclared key within a family the
  schema owns is an error naming the key and its family. **Without this, Stage 3
  catches nothing that can actually happen to three of its four target
  families** (see the acceptance table below), and C1 goes unsolved. §9.8.

**Size and splitting.** `horizons` alone is ~400 YAML lines. Per family, roughly:
`stock_score_thresholds` ~40 source/~60 test; `confidence_gate` ~30/~50;
`regime_gate` ~30/~50; `fundamentals_gate` ~40/~60; `horizons.<h>.*` ~150/~250
and probably a further split. Five branches, `claude/yaml-integrity-stage3-<family>`.

**Acceptance, per family.** Round 2's criterion — "a key indented one level
wrong inside that family raises a `ValueError`" — is **unwritable for three of
the four targets**, because they are flat blocks of scalars with no nesting to
indent into (verified against the shipped file):

| Family | Shape | Realistic typo |
|---|---|---|
| `stock_score_thresholds` | flat: `pass`, `caution` | misspelled key |
| `confidence_gate` | flat: `enabled`, `cautionBelow`, `rejectBelow` | misspelled key |
| `regime_gate` | flat: 4 scalars | misspelled key |
| `fundamentals_gate` | **nested**: `safety`, `weights`, `thresholds`, `quality_label_thresholds` + 6 scalars | misspelled key **or** mis-indent |

So the criterion is per shape:
- **Flat families:** `cautionbelow:` for `cautionBelow:`, or
  `headwind_reject_pt:` for `headwind_reject_pct:`, raises a `ValueError` naming
  the key and the family. This is the closed-subtree rule in 3.3, and it is the
  only thing that makes Stage 3 useful for these three.
- **Nested families (`fundamentals_gate`, `horizons.<h>.*`):** both the
  misspelled-key case and the mis-indent case raise, naming where the key was
  found and where it belongs.
- Every family: its shipped block validates clean; an unknown *sibling family*
  is ignored.

The whole-file criterion ("shipped `scoring_rules.yaml` validates clean") is
checked on the **last** family branch only.

**Rollback:** the validator is invoked from Stage 4's single-line call site, so
reverting a family's schema cannot affect boot.

---

## 8. Order

0a. **Formula unification + recording clamp.** Gate-level, fixes a live wrong
   number (§2.2) with no surface required. Ships first.
0b. **`regime_sizing` range validation + startup holder and call site.**
   Gate-level. Split from 0a to stay under `audit_rule`'s batch ceiling.
0c. **D2 — atomic writes.** Gate-level, ~20 source / ~40 test. See below.
1. **Stage 4 — surface.** Moved ahead of 1/2/3: until it exists, every other
   stage's message dies in a log. It builds on Stage 0b's holder.
2. **Stage 1 — `direction_conviction` defects.** Where the next edit lands.
3. **Stage 2 — staleness (A1b).**
4. **Stage 3 — path-shaped schema**, per family, scoring → risk → contracts.

The three gate-level items (0a, 0b, 0c) ship before any below-gate work, per
`audit_rule`. 0a first because it is the only one fixing a wrong number that is
live today with no config edit at all.

**D2 (= 0c) is gate-level and is now assigned its own change.** All
three non-atomic writers (`risk_settings.py:40-43` and `:24-29`,
`notification_settings.py:25-28`) convert to tmp + `os.replace`, matching the
nine writers that already do. ~20 source, ~40 test. `settings.yaml` being out of
scope for *validation* does not exempt its writers from this. §9.3b.

**PROJECT_STATE registration.** `direction_conviction_gate_audit.hard_cap_note`
records that the three-round hard cap "did not fire automatically" for this line
of work, for want of a phase record. Each
stage gets a phase entry with a PRESENCE `verify` probe before it is built —
**a `verify` key is mandatory**, since `scripts/state.py:625-627` calls
`probe(ph["verify"])` unconditionally and `probe` dereferences `v["path"]`
(`:89`), so a phase entry without one raises `KeyError` and breaks the
SessionStart hook. With a probe present, `state.py:634` only flags drift when
`declared_shipped != actual_shipped`, so a `status: planned` phase whose probe
does not yet match is clean.

Note the record this plan quotes is itself stale: `hard_cap_note` says
`active_phase` is null, but the shipped `PROJECT_STATE.json` has it set to
`"STATE-PROBE-TARGET-SCOPING …"`. Do not act on the null claim.

**On the adversarial gate — classify PER CHANGE, not per stage.** `audit_rule`
says a finding blocks *only* at the gate and that the brief must instruct the
reviewer not to report anything else. Round 2 applied that as a blanket
per-stage rule ("Stages 1-4 are below-gate"), which is an excuse rather than an
argument in at least two places:

- **Gate-level:** Stage 0 in full; D2; **Stage 4's banner correctness** — it
  renders a verdict to Kenneth, and §4.2's own words are "a stale-green banner
  is worse than no banner", i.e. a wrong thing in front of a user; and
  **Stage 3's false-POSITIVE behaviour** — rejecting a good config refuses a
  scan Kenneth should have had.
- **Below-gate:** a validator's false-NEGATIVE behaviour (failing to catch a
  typo that was already going uncaught) leaves an existing wrong number, it does
  not create one. That covers Stage 1 in full and Stage 3's miss cases.

Below-gate work is audited against its stated acceptance criteria; gate-level
work gets a true `audit_rule` round. A clean gate round over below-gate work
certifies nothing and must not be reported as though it did.

---

## 9. Decisions for Kenneth

### Settled 2026-09-16 and unaffected by any round

**9.2 Staleness:** he never edits while the backend runs; he always restarts.
No reload endpoint, no auto-reload.

**9.3 Breadth order:** `scoring_rules.yaml` first, `risk_rules.yaml` second,
`contract_rules.yaml` last. Scoring decides WHICH NAMES he sees; risk decides HOW
MUCH MONEY goes into a trade.

**Failure posture:** a bad config must restrict the scan and **never refuse to
boot**. Everything runs in one process — scan scheduler, EDGAR prefetch, strategy
watch evaluator, portfolio alert monitor (`main.py`, lifespan startup `:134-268`) — so refusing to
boot over a scan-threshold typo would kill alerting on live positions.

The two statements about his behaviour are compatible and round 1 never noticed
it made both: §9.2 says he restarts after editing; the posture says he edits
while holding open positions. Both are true together — he edits, then restarts,
*while positions are open*. That is exactly why "never refuse to boot" is the
requirement: a restart that does not come back up leaves open positions
unmonitored.

One correction to this section's own evidence: `main.py` wraps each scheduler so
a failure warns and the app survives — true of eleven `try`/`except Exception` blocks in the lifespan startup
(`main.py` lines 148, 167, 172, 186, 195, 217, 231, 240, 249, 258, 264) but
**not** of `:179-184`, where `run_portfolio_alert_monitor`, `run_regime_monitor` and
`run_chart_alert_scheduler` start with bare `asyncio.create_task` outside any
`try`. The portfolio alert monitor — the thing the posture says must never be
killed — is the unwrapped one. Not this plan's job to fix, but it must not be
cited as precedent.

**Scope table — "block the scan" is not one thing.** Six scan-ish entry points
(all verified): `POST /analyze-stock` (`stock_scan.py:608`), `POST /stock-scan`
(`:1051`), `POST /scan/fib-pullback` (`:1259`), `POST /scan/prebreakout`
(`:1386`), `POST /stocks/first-passage` (`:1530`), `POST /scan` (`scan.py:1729`).

| Family | Blocked surface | Behaviour on invalid |
|---|---|---|
| `horizons.<h>.direction_conviction` | `POST /scan`, `POST /stock-scan` | refuse, **500** (§9.5) |
| `stock_score_thresholds` | `POST /stock-scan`, `/analyze-stock` | refuse, 500 |
| `confidence_gate` | `POST /stock-scan` | refuse, 500 |
| `regime_gate` | `POST /scan` | refuse, 500 |
| `fundamentals_gate` | `POST /stock-scan` | refuse, 500 |
| `regime_sizing` | **`POST /stock-scan` AND the auto-trade fire path** | Stage 0 — §9.1 |
| `entry_quality`, `confidence_backtest`, `regime` | unpoliced initially | unchanged |

Left running on an invalid config: pre-breakout and fib-pullback scans,
first-passage, exit-plan, and every monitor and scheduler.

### 9.7 CONFIRMED (ramp). 9.10 and 9.11 added and confirmed 2026-09-17.
### The rest still await Kenneth.

**9.1 — Does a config failure disarm auto-trade?** The posture says restrict the
scan and nothing else, decided on the belief that nothing outside the scan
touches money. §2 shows `regime_sizing` does, on **both** paths. Recommendation:
**fail closed** — refuse to fire and alert, rather than fire unsized or
mis-sized. This amends a decision Kenneth made, so it is flagged, not assumed.

**9.2b — Stage ordering vs the repo's own gate.** `audit_rule` defines the gate
as wrong-number-on-an-order or corrupt-persisted-data. `direction_conviction_gate_audit`
records B1/B2/B3 as "3 below-gate defects plus 1 coverage hole, all LOGGED not
fixed". So Stage 1 is entirely below-gate while the gate-level hazards (§2, D2)
were in no stage at all. Recommended order is §8.

**9.3b — `risk_rules.yaml` is app-written, with a gate-level non-atomic write.**
D2 (truncating write, no `os.replace`) blocks under `audit_rule`; D1 (comment
loss) does not. Options: (a) keep the §9.3 breadth order and fix D2 plus add
comment-preserving writes (`ruamel.yaml` round-trip); (b) fix D2 now as its own
change and defer D1; (c) accept comment loss explicitly. **Recommendation: (b)
then (a)** — D2 is gate-level and ~15 lines; D1 is cosmetic and can wait. Note
round 1 inflated D1's case by claiming hand-added keys are lost; they are not.

**9.4 — NEW. The Intraday gate contract.** Is Intraday permanently un-gated, or
gated-if-specified? This is a trading-semantics question — it decides when a
bullish/bearish intraday scan is screened at all — and it must be answered before
Stage 1's test is written, because either answer contradicts an existing test or
the shipped config.

**9.5 — NEW. 500 vs 400, and whether restart discipline counts as a control.**
Round 1's scope table specified `400`. Both shipped call sites raise **500**,
with the rationale in code: `stock_scan.py:1132-1147` — *"500, not 4xx: the
request is fine, the SERVER's YAML is broken and no request can succeed until it
is fixed, so this must not be confused with the genuine 4xx this endpoint already
raises for a bad user override"* (same at `scan.py:1426-1430`). The table above
now says 500. **Flagged because reversing it was round 1's silent decision, and
because a 400 tells the frontend the request was bad — which is how this class of
bug gets misdiagnosed.**

Related and more important: the posture validates **at startup only**, which
makes "Kenneth restarts" the sole detection mechanism. If he edits without
restarting, the validator never runs and the banner reports the last boot's
verdict — **green, on a file that is now broken**. §4.2's re-stat-on-read is the
fix, and it is why Stage 2 should not be demoted as far as §9.2's reasoning
suggests. Confirm: re-stat on every health poll.

**9.7 — NEW (round 3). WHICH SIZING FORMULA IS CANONICAL?** §2.2 shows the scan
path and the fire path size the same setup up to 50% apart on today's shipped,
valid config. Unifying them is Stage 0 requirement #7, but *which* survives is a
position-sizing decision, not an implementation detail:
- `auto_trader`'s `max(lo, min(1, f))` — a **step floor**: full size at/above
  full conviction, floor below it, nothing in between.
- `stock_scan`'s `lo + (1-lo)·f` — a **linear ramp** from floor to full.

The ramp is the smoother behaviour and is what the scan card has shown all
along; the step is what has actually sized live auto-trades. **CONFIRMED BY KENNETH 2026-09-17: THE LINEAR RAMP.** Both paths unify on
`lo + (1.0 - lo) * frac`. `auto_trader`'s step floor is what changes, not the card.

HE WAS TOLD THE COST AND TOOK IT, recorded here so it does not surface later as a
surprise: the ramp makes live auto-trades BIGGER at mid conviction — 0.500 to
0.750 at conviction 20, a 50% increase in position size on those fires. The step
is what produced his auto-trade history to date. The ramp wins because it is what
the card has shown him all along, and because the step gives no gradation at all
between floor and full size (conviction 10 and 20 size identically).

TWO LIVE BUGS IN THE SAME CODE JOIN THIS CHANGE, both from §2.2: the card's
formula INVERTS when `min_mult > 1` (strongest signal, smallest position — the
same shape as the inverted direction-conviction gate that started this plan), and
`full_conviction_pct: 0` is an uncaught `ZeroDivisionError` on the fire path
(`auto_trader.py:130`) that the card already guards (`stock_scan.py:143`).

**9.8 — NEW (round 3). Is a declared family's subtree CLOSED to undeclared
keys?** §7 3.3 now says yes, and it has to for Stage 3 to be worth building:
three of its four target families are flat scalar blocks where the only possible
typo is a misspelled key. But closing a subtree means a key Kenneth adds
deliberately inside a declared family becomes an error until the schema learns
it. **Recommendation: closed**, with the error naming both the key and how to
declare it.

**9.9 — NEW (round 3). Is a silently clamped multiplier acceptable?** §2.3 item 2
now requires the clamp to record itself — log at ERROR, mark the card, write to
`config_health` — precisely so a clamped run is not mistaken for a correct one.
The alternative is to refuse the scan outright on an out-of-range `min_mult`.
**Recommendation: clamp and record**, matching the never-refuse-to-boot posture;
refusing would restrict more than the scan.

**9.10 — CONFIRMED 2026-09-17. AUTO-TRADE FIRING INTO A CONTRACT ALREADY HELD:
WARN, DO NOT BLOCK — AND FIX THE BOOKS FIRST.** Kenneth's call: show a popup and
allow the fire, because the price may legitimately differ and a second entry can
be intended. The popup must show the EXISTING position's size and entry price.

VERIFIED FROM THE CODE, not from any spec: there is no check at all today.
`auto_trader.py:149-152` — *"Auto-trade is structurally entry-only — arm()/fire()
have no existing-position lookup anywhere"* — with `effect="OPEN"` hardcoded. It
fires a second buy-to-open with nothing asked.

THE DUPLICATE IS THE SMALLER HALF, and this decides the order of work:
`auto_trader.py:48` — *"THE FIRE PATH CREATES NO PortfolioPosition TODAY."* Every
auto-trade fire is already absent from the portfolio, held contract or not, so
exposure is understated by the whole fired order on EVERY fire. A duplicate
warning over books that do not record the trade buys very little. Book the fired
position first; add the warning second.

**9.11 — CONFIRMED 2026-09-17. ALERTS ALWAYS FIRE; ONLY THE SCAN IS RESTRICTED;
THE BANNER NAMES THE PARAMETER.** Asked directly by Kenneth, and the answer has a
shape the payload must carry. `GET /api/config/health` returns `{ok, checked,
errors: [{file, path, message}], stale}` — `path` IS the parameter to edit (his
maturity level 2) and `file` says which YAML. The banner never renders a bare
green: it names WHICH CHECKS RAN ("checks passing: direction_conviction,
regime_sizing"), because until Stage 3 ships most families are unvalidated and an
unscoped green claims more than the system can check. The third state stands:
disk valid but different from what this process runs, where the fix is a restart.

**9.6 — NEW. A misspelled top-level family is undetectable, by design.** §7 3.3
tolerates unknown families so an additive edit cannot 500 the scan. The cost is
that `regime_gates:` for `regime_gate:` is silently ignored forever — this plan's
own subject, accepted as a false negative. Round 1 presented this as "a natural
property"; it is a trade-off and Kenneth should own it explicitly.

---

## 10. What this buys

Stage 0 stops a live broker order being multiplied by a decimal typo, on both
paths that read the block, and stops a missing key silently emptying a scan.
D2 stops a truncated write destroying the risk config. The rest buy that the
candidate list is built from the numbers Kenneth actually chose — and that when
it is not, the app says so, by name, on screen, while everything watching his
open positions keeps running.

---

## 11. Round 4 findings — RECORDED, NOT FIXED (the hard cap fired)

Fixing these is what the cap exists to stop, so they are logged instead. Two
classes: defects in **live code** (valuable regardless of what happens to this
document) and defects in **this document's staging** (which §12 discards).

### 11.1 — LIVE-CODE hazards found during the audits, verified by execution

These are not plan defects. They are true of `main` today and survive any
rewrite of this document.

- **GATE — the options scan has a C3 twin, and Stage 0 never covered it.**
  `scan.py:593` and `:682` bare-index `_load_scoring_cfg()["regime_gate"]` at
  function-body indentation inside `_process_symbol` with **no enclosing try**.
  Tasks are gathered with `return_exceptions=True` (`scan.py:1543`) and
  `:1550-1553` converts each exception to
  `RejectedCandidate(symbol, reason=str(result))`. So a `regime_gate` block
  missing a key makes **every symbol in an options scan** reject with
  `reason: "'regime_gate'"` — HTTP 200, zero candidates, nothing naming the
  file. Same shape as C3 on the stock path, on `POST /scan`, unassigned.
  `stock_scorer.py:58` (`["stock_score_thresholds"]`) is reachable the same way
  via `scan.py:586`/`:671`.

- **GATE — a stocks-mode scan failure is completely silent on screen.**
  `lib/stockScan.ts:103-105` is `catch { store.setScanState('FAILED'); return
  null; }` — **no error binding at all**. `RunScanButton` returns early at
  `index.tsx:90` (`void runStockScan(...)`) for stocks mode, so its toast never
  runs on that path. `POST /stock-scan` is the endpoint §9.5's scope table
  assigns to four of six families. Two further submit sites are also
  unaddressed: `step-5-strategy/page.tsx:247-248` (raw `String(e)`, transport
  prefix included) and `step-4-prebreakout/page.tsx`.

- **GATE — the three threshold stores render fabricated numbers on a broken
  config, and this was diagnosed in §1 and assigned to no stage.** A malformed
  file 500s `/api/config/iv-thresholds`, `/stop-premium-thresholds` and
  `/event-thresholds`; `eventThresholdsStore.ts:37-39`, `ivThresholdsStore.ts:44`
  and `stopPremiumThresholdsStore.ts:63` each `catch { set({loaded:true}) }` over
  a module-level `FALLBACK`. The Step-5 UI then shows thresholds that are not in
  the file, silently — a wrong number in front of a user under `audit_rule`.
  **This is the same "diagnosed then orphaned" pattern round 3 caught with
  `regime_sizing`, repeated in the revision that called it out.**

- **NIT — `risk_rules.yaml` has 16 reader modules** (more than `settings.yaml`'s
  12), several bare-indexing (`config_loader.py:29,38,50,59` do `full["<block>"]`
  with no guard), and it is the file D2 shows the app itself can truncate. §9.3
  calls it the file that decides "how much money", and no stage validates it.

### 11.2 — STAGING defects in this document (superseded by §12)

- 0a ships before 0b but requires `config_health`, which 0b creates — the
  inverted dependency is the same defect round 3 found, reintroduced by its fix.
- §2.3's eight requirements are assigned across 0a/0b for only four of them;
  items 3, 4, 5 and 6 belong to neither. One branch name and one size figure
  cover two branches; 0c has neither.
- §2.3 item 2's "mark the affected card" is a cross-layer change (wire type,
  frontend render, `tsc`) budgeted as backend-only, and the fire path has no
  card at all.
- §4's acceptance clauses 2 and 3 contradict each other: "fixed without
  restarting" IS "valid on disk but differs from what the process runs", and the
  two clauses demand opposite banner states for it.
- The third state is owned by Stage 4 and Stage 2 simultaneously, or by neither;
  §6 2.1b's reference point (Stage 0b's startup bytes) manufactures a false
  "restart needed" in the ordinary boot → edit → first-scan sequence, because
  the caches populate lazily from the NEW file.
- Nothing specifies the banner when `/api/config/health` itself fails.
- Stage 4 spans backend and frontend in one branch, breaking the one-layer half
  of the rule §3 invokes as its organising principle.
- §3 says "five stages (0, 1, 4, 2, 3)" while §8 orders 0a/0b/0c/4/1/2/3 and
  §7 declares five branches — the real change count is eleven. §3 and §7 still
  name "Stage 4's call site" after §2.3 moved it to Stage 0.
- §4.4's mass-rejection signal reinvents an existing funnel: `StockPipeline`
  already carries `scanned`, seven buckets and `other_rejected`
  (`schemas/stock_scan.py:232-246`), and `classify_stock_rejection`
  (`stock_scan.py:201`) already routes a config `KeyError` into `other_rejected`.
  The signal is `other_rejected / scanned` over a threshold, from existing
  `result_json`, no migration.
- §8 widens `audit_rule`'s gate (a refused scan and a wrong banner state are
  neither a wrong number nor corrupt data) inside a paragraph that quotes the
  rule, without saying it is doing so.
- §8's state.py requirements are partial: `state.py:640` also dereferences
  `audit_rounds` and `audit_clean`; `status: "planned"` is not in `STATUS_STYLE`
  (`:76-83`) — use `not_started`; and `audit_bookkeeping_drift` (`:481-541`)
  will compare this plan's "round N" commits against the current `active_phase`,
  which points at unrelated work.
- Line drift: `layout.tsx:32` (not `:31`) for `EventThresholdsBootstrap`;
  `api.ts:65` for the throw; `stock_scan.py:686` for `max(1, int(...))`;
  `risk_settings.py:26-30` and `:39-43`; there are five `*_schedule_store.py`
  files, not six (the sixth atomic writer is `strategy_watch_store.py`).
- §1 A1b's ", i.e. what D2 below can create" is false — D2's writers target
  `risk_rules.yaml` and `settings.yaml`; nothing writes `scoring_rules.yaml`.
  The truncation case stands on an editor crash, not on D2.

---

## 12. The split — what to do instead of a fifth round

`audit_rule`: *"BATCH SIZE is the root cause the gate merely exposes … Split work
so [it can audit clean]."* Three documents, each auditable alone, each with a
**shrinking** target from round 2 onward:

**A. `regime-sizing-fix` — gate-level, build first, one layer.**
Everything in §2 plus §11.1's options-path twin. Fixes a wrong number that is
live on the shipped config today with no config edit at all. Needs Kenneth's
§9.7 answer (which formula is canonical) before it can be written. Self-contained
in `auto_trader.py` and `stock_scan.py`; no frontend, no new endpoint, no holder.

**B. `atomic-yaml-writes` — gate-level, trivially auditable.**
The three non-atomic writers → tmp + `os.replace`, matching the nine that already
do it. ~20 source, ~40 test, no design decisions.

**C. `config-validation-and-surface` — everything else, and NOT one document.**
Rewrite from scratch rather than patching §3-§8. The staging defects in §11.2 are
symptoms of one cause: it tries to decide validation, staleness, failure posture,
HTTP semantics and a frontend surface in a single artefact. Sequence it as
separate plans, each written only after the previous one ships.

**Do not carry §3-§8 forward.** Carry §1, §2, §9 and §11 — the diagnosis and the
decisions. Those are verified and they are what the four rounds actually bought.

---

## 13. Round 5 (2026-09-28) — the last round, scoped to §1, §9, §11.1 — NOT CLEAN

Run at Kenneth's request as the one last round. Scoped per §12: §3–§8 were NOT
re-audited. The reviewer checked each claim against main `7d7159b` by reading the
code and running Python. **Auditing of this document stops here**: the phase is
past the hard cap, and the findings below go into the fresh Document C plans.

### 13.1 Gate-level findings (none reachable on the shipped config; each needs a hand edit)

- **G1 — a missing or misspelled money block reads as OFF.**
  `conviction_sizing.resolve_sizing(None)` returns `None`, so the multiplier is 1.0.
  `stock_scan.py:1466-1486` and `auto_trader.py:470` both treat an absent
  `regime_sizing` as "sizing off". `scan.py:658` and `stock_scan.py:1143` read
  `regime_gate` with `.get`, so a missing block means no gate
  (`stock_scorer.py:989`). Consequences:
  - `regime_sizng:` fires auto-trades at full size where they should be 0.30x,
    a 3.3x larger order.
  - `regime_gates:` removes the headwind REJECT on both scans and on the fire path.
  - Both blocks sit at the end of the file (`scoring_rules.yaml:457,463`), so a
    truncated file drops them and still parses cleanly.
  This is Mode C1 and the concrete cost of §9.6.
- **G2 — the options scan fails OPEN on a broken `regime.<horizon>` block.**
  - The read is now inside a try (`scan.py:591-592`); the handler at `:644-645`
    only logs a warning.
  - `_regime_signal` stays `None`, so the regime gate has no signal, and names
    the enabled gate would REJECT or CAUTION show as PASS.
  - The stock path does the opposite: `stock_scan.py:141-142` indexes the block
    directly, so every symbol is rejected.
  - This supersedes §11.1 item 1.
- **G3 — Step 5 can show thresholds that differ from the backend's.**
  - `eventThresholdsStore.ts:25-40` and `ivThresholdsStore.ts:31-46` fall back to
    a hardcoded `FALLBACK` on any fetch failure.
  - They fetch once and never re-fetch.
  - The fallback equals the shipped YAML today; any edit to those thresholds
    breaks that.
  - This is §11.1 item 3, still true.

### 13.2 Status of §1 and §11.1 today

| Item | Status |
|---|---|
| A (six caches) | Still true; accepted under §9.2 |
| A1a | Fixed |
| B1, B3, B3b | Fixed (Q3B) |
| B2 | Raises by design (Q3B) |
| C1 | Still true (G1) |
| C2 | Partly true: bare `KeyError` in `routers/config.py:31,58`, `stock_scorer.py:58`, `signal_confidence.py:30,34` |
| C3 | Fixed for `regime_sizing`; still reachable for `regime` and `regime_gate` (empties the scan, no wrong number) |
| D1 | Still true |
| D2 | Fixed (`atomic_yaml.py`) |
| §11.1 #2 | Fixed (SCAN-FAILURE-REASON) |
| §11.1 #4 | Still true, below the gate |

### 13.3 §9 as of round 5

| Decision | Status |
|---|---|
| 9.1 | ANSWERED: fail closed (SIZING-FAIL-CLOSED) |
| 9.9 | ANSWERED: refuse (A7C-MIN-MULT-REFUSAL-CONFIRMED-2026-09-24) |
| 9.2b | MOOT |
| 9.4 | Answered by code as "gated if specified"; waiting for Kenneth to ratify |
| 9.3b | (b) done; D1 remainder live |
| 9.5 | 500 settled; re-stat on every poll live (only if Document C builds `config_health`) |
| 9.6 | LIVE |
| 9.8 | LIVE |

The questions on the live items were put to Kenneth on 2026-09-28.
