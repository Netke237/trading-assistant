# YAML config integrity — an edit either takes effect, or fails loudly

**Status:** DRAFT, revised after adversarial round 2 (25 findings, 16 gate-level;
round 1 was 24/15). Not yet clean. §9 lists the six decisions Kenneth must
re-confirm before anything is built.
**Goal, in one sentence:** when Kenneth maintains a config YAML, the change he
made is the change the app runs — or the app tells him, by name, that it is not.

**Why now.** The direction-conviction gate ran BACKWARDS for three months
(2026-06-18 → 2026-09-16) and nothing on screen or in a log said so. That was a
code bug, not a config bug, but it exposed the same class of hazard: this app
can run on a number nobody intended and give no sign. The next threshold change
Kenneth makes will be to the bearish floors in `scoring_rules.yaml`, by hand,
based on scan evidence. That edit must hold.

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
(verified — the only four in the tree are `risk_settings.py:159-161`, for the
risk config).

**A1 — uniform staleness, and `lru_cache` inverts it for the broken-file case.**
Round 1 modelled this as "cached, so an edit does not take effect until a
restart". That is right for a *valid* edit and **wrong for an invalid one**:
`functools.lru_cache` does not cache exceptions (verified — a raising cached
function re-executes on every call). So the five non-catching readers **re-read a
broken file on every call**, and fixing the YAML takes effect with no restart.

`auto_trader._load_scoring_config` is the exception, and the asymmetry is the
hazard: it catches and returns `{}` (`auto_trader.py:103-106`), and **`{}` is
cached permanently**. Fix a broken YAML without restarting and every scan
recovers while auto-trade stays silently unsized for the life of the process.
Stage 0 must account for this; round 1's design did not mention it.

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
  silently (new in this revision).** `stock_scan.py:140-141` bare-indexes
  `sizing["full_conviction_pct"]` and `sizing["min_mult"]` inside
  `_conviction_mult`, which is called at `:968` — **inside `_process_stock`'s
  try** (`:706`), whose handler at `:1030-1032` is
  `except Exception as exc: return {"symbol": symbol, "reason": str(exc)}`.
  So a `regime_sizing` block missing `min_mult` makes **every symbol in the
  universe return `reason: "'min_mult'"`** — an empty scan, no error, no 500,
  nothing naming the file. This is the plan's own thesis failure, on a path
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
- **D2 — NON-ATOMIC WRITE, and this is gate-level.** No tmp-then-`os.replace`.
  A crash or full disk mid-write leaves `risk_rules.yaml` truncated — position
  sizing and max-loss config, gone. Under `audit_rule`'s "**CORRUPT PERSISTED
  DATA**" clause this blocks. It is the **only** YAML writer in the repo that
  does this: all six schedule stores and `strategy_param_store` use
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

`auto_trader.py:129-131`:

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

That flows into `_position_size(...)` (`:970`) → the share count on
`StockPositionCard` → `StockSendDialog` → broker.

And it is a **different formula over the same block** (`stock_scan.py:138-144`):
`lo + (1.0 - lo) * frac`, versus auto_trader's `max(lo, min(1.0, frac))`. Both
inflate when `lo > 1`, but by different amounts. **The same `regime_sizing`
block means two different things depending on which path reads it.** A
config-integrity plan that never noticed its two readers disagree on the meaning
of the config has missed its own subject. Logged here as its own item; it is a
correctness defect independent of validation.

One asymmetry worth noting for Stage 0: `stock_scan.py:142` guards its division
(`if full else 0.0`); `auto_trader.py:130` does **not**, so
`full_conviction_pct: 0` is an uncaught `ZeroDivisionError` on the fire path.

### 2.3 — Stage 0, rewritten

Round 1's Stage 0 ("replace the `except: return {}` with a hard failure") is
necessary but nowhere near sufficient. Stage 0 must:

1. **Validate value ranges, not just parseability**: `0 < min_mult <= 1.0`,
   `full_conviction_pct > 0`. This is what stops §2.1, and no amount of
   exception re-routing does.
2. **Clamp at the point of use** as a belt-and-braces second line, so a value
   that somehow reaches the arithmetic cannot exceed 1.0.
3. **Distinguish parse failure from `regime_sizing` absent** — both currently
   return `{}` and are indistinguishable at the return site.
4. **Fail closed on the fire path** rather than firing unsized (§9.1).
5. **Fix C3**: the bare indexes at `stock_scan.py:140-141` must not be able to
   empty a scan through the per-symbol handler.
6. **Account for the `lru_cache` asymmetry in §1 A1**: `{}` is cached forever,
   so a "fixed" YAML does not revive auto-trade sizing without a restart.

**Size:** not the ~20 lines round 1 estimated. Two consumers, two formulas, a
range validator, a clamp, and a test with a mocked broker on the armed path.
Realistically ~120 source, ~200 test — and it may need splitting between the
validation and the formula-divergence fix.

**Acceptance:** `min_mult: 5` is rejected at startup naming
`regime_sizing.min_mult`; if it somehow reaches the arithmetic, `mult <= 1.0` on
both paths; `full_conviction_pct: 0` raises no `ZeroDivisionError`;
`min_mult` absent does not empty a scan.

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

- **Stage 0** — genuinely standalone. Ships and is useful alone.
- **Stage 4 (surface)** — must precede 1, 2 and 3 to give them a surface. It
  also **owns the startup validation call site**, which round 1 accidentally
  placed in Stage 3's rollback note.
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

**4.1 — The startup call site lives HERE.** `main.py`'s lifespan (`:165-275`)
calls no validator today. Stage 4 adds the single-line call and the
module-level `config_health` holder it writes. Round 1 put this in Stage 3's
rollback note, which — with Stage 3 scheduled last — meant Stage 4's banner
would be structurally green until the final stage landed.

**4.2 — The endpoint re-stats on read.** `GET /api/config/health` →
`{ ok, errors: [{file, path, message}], stale }`. It must `stat` the file on
every read rather than serving the boot-time verdict verbatim, so the banner can
**never assert health about bytes it no longer matches** (§9.5). A stale-green
banner is worse than no banner.

**4.3 — `stale` ownership.** The field is populated by Stage 2. Until Stage 2
ships, Stage 4 serves `stale: null` (unknown), not `false`. A hardcoded `false`
would be an assertion the system cannot make.

**4.4 — The unattended path.** Round 1 promised "the banner reads off that
existing last-run record" and wired nothing. Scheduled scans
(`scan_schedule_scheduler.py:150-156` → `_execute_stock_scan_core`, recorded via
`record_scheduled_scan_run` at `:163`/`:170`) must either be surfaced by the
health payload carrying the last scheduled-run error, or the claim must be
dropped. **Decision: carry it** — a failed overnight scan Kenneth never sees is
exactly this plan's subject.

**4.5 — Frontend.** Per CLAUDE.md conventions (own folder, `index.tsx` +
`.module.css`, atoms→molecules→organisms, no card shadows):
- `configHealthStore` — ephemeral, not persisted (server state).
- `ConfigHealthBootstrap` **atom**, mounted in `app/(frame)/layout.tsx`,
  mirroring `EventThresholdsBootstrap` (`components/atoms/EventThresholdsBootstrap/index.tsx`,
  mounted at `layout.tsx:31-32`). Round 1 omitted this and would have skipped
  the atom level, which CLAUDE.md forbids.
- `ConfigHealthBanner` organism.
- `RunScanButton`'s catch changed from `.catch(() => …)` to `.catch((err) => …)`
  surfacing `err.message`. Today (`RunScanButton/index.tsx:171-181`) it discards
  the error and toasts "Scan failed — backend unreachable", so a malformed YAML
  sends Kenneth to debug the wrong thing entirely — while `lib/api.ts:45-65`
  carefully extracts the `json.detail` it throws away.

**Size:** ~70 backend + ~60 backend test; ~140 frontend + CSS + ~80 frontend
test. (Round 1 budgeted no tests for this stage.)

**Acceptance:** with a deliberately broken YAML, the banner names the file and
path; after fixing the file *without restarting*, the banner clears on the next
poll (this is what 4.2's re-stat buys); a failed scheduled run surfaces.

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
(`:390`) asserts YAML and code defaults agree on null-ness, so a numeric intraday
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

## 6. Stage 2 — staleness detection (Mode A1 only)

**2.1 — Scope honestly: this stage detects A1, NOT A2.** Round 1 asserted the
opposite ("a per-cache stash would … miss A2 entirely") and had it backwards.
A2 is "two caches hold *different versions at the same time*". A single global
stash records one byte-hash and compares it to disk; it can answer "does disk
differ from what was first loaded?" (A1) but never "do the caches disagree with
each other", because it never records what each cache holds. **Per-cache hashes
compared pairwise are the only construction that sees A2** — round 1 forbade the
only thing that works. Given six caches and Kenneth's restart discipline, A2
detection is deferred, not solved; recorded as a known gap.

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

**3.3 — Do not police the file.** This schema owns the paths it declares, not the
namespace. With a path-shaped schema this is a natural property rather than a
rule fighting the mechanism. **But it has a cost that round 1 presented as a
feature:** a misspelled *family* (`regime_gates:`, `confidence_gates:`) is
silently skipped forever — the exact hazard this plan is named for, accepted as a
false negative. §9.6.

**Size and splitting.** `horizons` alone is ~400 YAML lines. Per family, roughly:
`stock_score_thresholds` ~40 source/~60 test; `confidence_gate` ~30/~50;
`regime_gate` ~30/~50; `fundamentals_gate` ~40/~60; `horizons.<h>.*` ~150/~250
and probably a further split. Five branches, `claude/yaml-integrity-stage3-<family>`.

**Acceptance, per family** (round 1's whole-file criterion was uncheckable on a
single-family branch): the family's shipped block validates clean; a key indented
one level wrong inside *that family* raises a `ValueError` naming where it was
found and where it belongs; an unknown sibling family is ignored. The whole-file
criterion ("shipped `scoring_rules.yaml` validates clean") is checked on the
**last** family branch only.

**Rollback:** the validator is invoked from Stage 4's single-line call site, so
reverting a family's schema cannot affect boot.

---

## 8. Order

1. **Stage 0 — `regime_sizing`.** Gate-level, standalone, ships first.
2. **Stage 4 — surface.** Moved ahead of 1/2/3: until it exists, every other
   stage's message dies in a log, and it owns the startup call site.
3. **Stage 1 — `direction_conviction` defects.** Where the next edit lands.
4. **Stage 2 — staleness (A1).**
5. **Stage 3 — path-shaped schema**, per family, scoring → risk → contracts.

**D2 (the non-atomic `risk_rules.yaml` write) is gate-level and is not yet
assigned a stage** — it belongs either in Stage 0 alongside the other gate work
or in its own ~15-line change. §9.3.

**PROJECT_STATE registration.** `direction_conviction_gate_audit.hard_cap_note`
records that this line of work has no phase record (`active_phase` is null) and
that the three-round hard cap "did not fire automatically" as a result. Each
stage gets a phase entry with a PRESENCE `verify` probe before it is built.
`scripts/state.py:625-639` only flags drift when `declared_shipped !=
actual_shipped`, so a `status: planned` phase with no probe is clean.

**On the per-stage adversarial gate — stated so a clean round is not mistaken
for evidence.** `audit_rule` says a finding blocks *only* at the gate and that
the brief must instruct the reviewer not to report anything else. Stages 1-4 are
classified below-gate, so a gate-only round over them is required by construction
to return nothing. **Stages 1-4 are therefore audited for correctness against
their stated acceptance criteria, not against the `audit_rule` gate.** Only
Stage 0 and D2 get a true gate audit.

---

## 9. Decisions for Kenneth

### Settled 2026-09-16 and unaffected by either round

**9.2 Staleness:** he never edits while the backend runs; he always restarts.
No reload endpoint, no auto-reload.

**9.3 Breadth order:** `scoring_rules.yaml` first, `risk_rules.yaml` second,
`contract_rules.yaml` last. Scoring decides WHICH NAMES he sees; risk decides HOW
MUCH MONEY goes into a trade.

**Failure posture:** a bad config must restrict the scan and **never refuse to
boot**. Everything runs in one process — scan scheduler, EDGAR prefetch, strategy
watch evaluator, portfolio alert monitor (`main.py:172-268`) — so refusing to
boot over a scan-threshold typo would kill alerting on live positions.

The two statements about his behaviour are compatible and round 1 never noticed
it made both: §9.2 says he restarts after editing; the posture says he edits
while holding open positions. Both are true together — he edits, then restarts,
*while positions are open*. That is exactly why "never refuse to boot" is the
requirement: a restart that does not come back up leaves open positions
unmonitored.

One correction to this section's own evidence: `main.py` wraps each scheduler so
a failure warns and the app survives — true of eight blocks but **not** of
`:179-184`, where `run_portfolio_alert_monitor`, `run_regime_monitor` and
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

### NEEDS RE-CONFIRMATION — six items, three new in round 2

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
with the rationale in code: `stock_scan.py:1133-1147` — *"500, not 4xx: the
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
