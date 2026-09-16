# YAML config integrity — an edit either takes effect, or fails loudly

**Status:** DRAFT, revised after adversarial round 1 (24 findings, 15 gate-level).
Kenneth's decisions from 2026-09-16 are in §7; §7.7 lists the three that round 1
invalidated and that he must re-confirm before anything is built.
**Goal, in one sentence:** when Kenneth maintains a config YAML, the change he
made is the change the app runs — or the app tells him, by name, that it is not.

**Why now.** The direction-conviction gate ran BACKWARDS for three months
(2026-06-18 → 2026-09-16) and nothing on screen or in a log said so. That was a
code bug, not a config bug, but it exposed the same class of hazard: this app
can run on a number nobody intended and give no sign. The next threshold change
Kenneth makes will be to the bearish floors in `scoring_rules.yaml`, by hand,
based on scan evidence. That edit must hold.

**What round 1 changed.** Three load-bearing facts were wrong in the first
draft, and they move the plan's centre of gravity:
1. `scoring_rules.yaml` is read by **five independent caches**, not one.
2. A malformed `scoring_rules.yaml` makes the auto-trader fire at a **larger
   size than intended** — so this work does touch a broker order, which the
   first draft explicitly denied.
3. The "banner" the whole failure posture rests on **has no frontend anywhere
   in the plan**, and the frontend code that would show it currently throws the
   backend's error message away.

---

## 1. The failure modes — there are FOUR, not one

### Mode A — STALENESS, across five caches, with a torn-read variant

`scoring_rules.yaml` is loaded by five separate `@lru_cache(maxsize=1)` readers,
each with its own path constant, none going through a common loader:

| Reader | Location | Reads |
|---|---|---|
| `load_scoring_cfg` | `services/config_loader.py:15` | whole file |
| `_load_scoring_config` | `services/auto_trader.py:97` | `regime_sizing` only |
| `_load_config` | `scoring/stock_scorer.py:46` | whole file |
| `_load_config` | `scoring/entry_quality.py:16` | whole file |
| `_cfg` | `scoring/signal_confidence.py:23` | whole file |

**No `cache_clear()` for any of them exists anywhere under `backend/app/`**
(verified). So:

- **A1 — uniform staleness.** Edit the file while the server runs and nothing
  changes, with no error, until a restart. The dangerous part is the conclusion
  it invites: "I changed the floor and the scan looks identical" reads as "the
  floor does not matter" — the opposite of the truth.
- **A2 — TORN READ (new in this revision, not in the first draft).** The five
  caches populate lazily, at first call, which is five *different moments*. An
  edit landing between two of those moments leaves the process holding two
  versions of the same file at once: a single scan can score trend from the old
  `stock_scorer` copy and confidence from the new `signal_confidence` copy. That
  is strictly worse than a uniformly stale read, because the resulting numbers
  correspond to no file that ever existed on disk.

The repo already solves the uniform case elsewhere: `routers/risk_settings.py:159-161`
clears three caches on `POST /settings/risk`. The pattern exists; it was never
applied to the scoring config.

### Mode B — MISPLACEMENT. The edit is read, but not from where it sits.

`direction_conviction` has a positional validator with three logged holes. All
three are real; all three were re-derived against the running code this round.
Repros are inline (§4) so they do not depend on a dead session's context.

- **B1 — a flat dotted key forges a legal path.** `_walk_direction_conviction_paths`
  joins segments with `"."` (`config_loader.py:124`), so a top-level key spelled
  `"horizons.position":` yields exactly the path `legal_paths` accepts.
  Validation passes and the operator's value is never read: with a `99` in that
  forged block, `load_direction_conviction_min_trend('Bearish','Position')`
  still returns `40.0`. This is precisely the silent-ignore the validator exists
  to stop. **Live hazard.**
- **B2 — a `_defaults: &anchor` holder carrying a block raises `ValueError`**
  naming `horizons._defaults.direction_conviction`, although the round-3
  docstring (`config_loader.py:153-159`) names that holder as the shape the
  positional rewrite unblocked. The existing test (`test_config_loader.py:403-423`)
  covers the *empty* holder only. **Not a live hazard** — the shipped
  `scoring_rules.yaml` contains no anchors or merge keys at all (verified: no
  `&`, no `<<:`). B2 is a defect in a docstring's promise, and it is listed
  second rather than alongside B1 for that reason.
- **B3 — a self-referential anchor raises `RecursionError`, not `ValueError`,**
  escaping both routers as a bare 500 with no detail. **The first draft
  mis-stated the trigger:** this happens only when the cycle contains no
  `direction_conviction` key. When the cycle *does* contain one, the walker
  yields a path like `horizons.loop.swing.direction_conviction` and
  `config_loader.py:171` raises a normal `ValueError` — naming a path **that
  does not exist in the file**, which is its own level-2 message defect and is
  logged here for the first time as **B3b**.

### Mode C — NO VALIDATION for everything else, failing in TWO different ways

`scoring_rules.yaml` has NINE top-level families (verified, all nine):
`stock_score_thresholds`, `confidence_gate`, `confidence_backtest`, `horizons`,
`entry_quality`, `regime`, `regime_gate`, `regime_sizing`, `fundamentals_gate`.
Exactly ONE sub-key of ONE family (`horizons.<h>.direction_conviction`) is
positionally validated.

The first draft claimed "everywhere else the read pattern is `.get(key, default)`."
That is false, and the distinction matters because the two halves need different
remedies:

- **C1 — silently defaults.** A misspelled or misplaced key falls through to a
  code-side default, silently, forever. This is the hazard the plan is named for.
- **C2 — bare 500, no detail.** Several readers index bare and raise `KeyError`:
  `routers/config.py:31,60,84`, `routers/scan.py:593,682`,
  `scoring/stock_scorer.py:58`, `scoring/entry_quality.py:23`,
  `scoring/signal_confidence.py:34`. These fail loudly but uselessly — they do
  not silently default, so a validator that only prevents silent-default does
  nothing for them. They need a *message*, not a *check*.

**C2 has a consequence outside the scan that the failure posture must cover.**
Because `routers/config.py` indexes bare, a malformed file 500s
`/api/config/iv-thresholds`, `/stop-premium-thresholds` and `/event-thresholds`.
Per CLAUDE.md those three feed `ivThresholdsStore`, `stopPremiumThresholdsStore`
and `eventThresholdsStore`, all of which are **fetch-with-hardcoded-fallback**.
So a bad config already makes the Step-5 UI display thresholds that are not in
the file, silently — this plan's own thesis failure, on a path §7.4 promises not
to touch.

### Mode D — MACHINE OVERWRITE (new in this revision)

The edit is read correctly, then destroyed by the app. `routers/risk_settings.py:157`
calls `_save_risk(cfg)`, which at `:43` does
`yaml.dump(data, f, default_flow_style=False, sort_keys=False)` over the whole
file. `risk_rules.yaml` carries **28 comment lines** today; the first
Settings→Risk save erases all of them, and any hand-added key the Pydantic model
does not know about.

This matters directly because §7.3 makes `risk_rules.yaml` breadth target #2.
A plan that validates a hand-edit to a file the UI will silently rewrite is
solving the wrong half of the problem.

---

## 2. THE GATE-LEVEL HAZARD — auto-trade fires larger on a broken config

**This is new, it is the most serious finding of round 1, and the first draft
contained the opposite claim.** The first draft's closing line read "None of the
three can put a wrong number on a broker order." That is false.

`auto_trader.py:97-106`:

```python
@functools.lru_cache(maxsize=1)
def _load_scoring_config() -> dict:
    try:
        with open(_SCORING_CONFIG_PATH) as f:
            return yaml.safe_load(f).get("regime_sizing", {})
    except Exception as exc:
        logger.warning("... vol sizing disabled: %s", exc)
        return {}
```

On a malformed `scoring_rules.yaml` this returns `{}`. Then `_apply_vol_sizing`
(`:110-140`) hits `if not cfg.get("enabled", False): return strategy` and returns
the strategy **unmodified**.

Volatility sizing only ever scales *down* — `mult = max(min_mult, min(1.0, directional_conv / full_conviction))`
is bounded above by `1.0`. So a broken config does not disable a safety feature
neutrally: it **always produces a position at least as large as intended, and
usually larger than the conviction warrants**, on a live broker order, while
logging a single `warning` nobody is reading at 02:00.

Under `PROJECT_STATE.json`'s own `audit_rule` — "a finding blocks only if it can
put a WRONG NUMBER in front of a user or on a broker order, or CORRUPT PERSISTED
DATA" — this is gate-level. It is the only gate-level item in this document.

**It also directly contradicts the posture in §7.4** ("never let validation touch
anything but scanning"), because "everything else keeps running" includes an
order router that treats a broken config as a feature toggle. See §7.7.1.

---

## 3. What this plan deliberately does NOT do

`audit_rule` is explicit that batch size is the root cause of non-converging
audits: one change, one layer, roughly 500 lines. A single "validate all config"
change would span 15 reader modules and five YAML files, and would not converge.

So this plan is **four independent stages, each its own branch, each with its own
adversarial round.** Any stage can ship alone and is useful alone.

Out of scope for all stages:
- `settings.yaml` (22 reader modules) — user-facing, UI-written.
- The six schedule stores (`scan_schedule_store`, `ingestion_schedule_store`,
  `edgar_schedule_store`, `tuning_schedule_store`, `sp500_schedule_store`,
  `strategy_watch_store`) — these WRITE their own YAML via `yaml.dump`.
- `strategy_params.yaml` — machine-written by `strategy_param_store.adopt()`
  (`:156`, `yaml.safe_dump`; `:157` is the `os.replace`).

**The exclusion criterion, stated once so it is applied consistently:** a file is
out of scope when the app writes it, because there the hazard is Mode D
(overwrite), not Mode A/B/C (silent misread), and Mode D needs a different
remedy. By that criterion `risk_rules.yaml` is **also app-written** and its
inclusion as breadth target #2 is therefore a genuine decision, not an
oversight — see §7.7.3. Verified for contrast: nothing under `backend/app/`
writes `scoring_rules.yaml` or `contract_rules.yaml`, so the earlier claim in
this repo's history that "nothing writes the YAML" is true of those two files
only and must not be generalised.

---

## 4. Stage 1 — close the known `direction_conviction` defects (Mode B)

Smallest, most provably correct, closes what is already logged. **Note it is
below-gate work by `audit_rule`'s definition** — see §8 for why it is still
scheduled early.

**1.1 — Path as a tuple, not a joined string.** `_walk_direction_conviction_paths`
yields `tuple[str, ...]`; `legal_paths` becomes a set of tuples; comparison is
tuple equality. A `.` inside a key can then never synthesise a separator. Error
messages keep rendering with `".".join(path)` so operator-facing text is
unchanged. Fixes B1.

**1.2 — Skip non-positional holders.** Treat a mapping key beginning `_` as a
holder and skip it, matching the `_defaults` convention the docstring already
names. Its block is still shape-checked wherever it is merged. Fixes B2.

**1.3 — Bound the recursion — and NOT with a global `id()` set.** The first
draft proposed "a depth limit (or a `seen` set of `id()`s)". **The `id()` variant
is actively wrong here and must be explicitly forbidden in the code comment:**
PyYAML merge keys share object identity (verified —
`horizons._defaults.direction_conviction is horizons.swing.direction_conviction`
→ `True`), so a global id-keyed seen-set visits one occurrence and silently skips
its siblings, making B2's verdict depend on dict insertion order. Use a **depth
limit**, or a cycle set scoped to the current path only. Fixes B3.

**1.4 — Never name a path that is not in the file.** Fixes B3b: a path reached
only through a cycle must not be reported as the operator's misplacement.

**Inline repros** (carried here so the test budget does not depend on a dead
session's context — all three re-derived against the running code this round):

```yaml
# B1 — validator passes; the 99 is never read.
# load_direction_conviction_min_trend('Bearish','Position') still returns 40.0
horizons.position:
  direction_conviction: {bearish_min_trend: 99}

# B2 — raises ValueError naming horizons._defaults.direction_conviction
horizons:
  _defaults: &d
    direction_conviction: {bullish_min_trend: 30, bearish_min_trend: 30}
  swing:
    <<: *d

# B3 — RecursionError (NOT ValueError); requires the cycle to contain
# no direction_conviction key
horizons: &h
  swing: {direction_conviction: {bullish_min_trend: 30}}
  loop: *h        # cycle containing direction_conviction -> ValueError naming
                  # a path not in the file (that is B3b)
```

**Tests:** one per defect above, each written to FAIL against today's code
first. Plus the two guards logged as untested:
- `str(k)` at `config_loader.py:200` — two unknown keys of *mixed type* must
  raise the named `ValueError`, not `TypeError`. Genuinely untested today:
  `test_direction_conviction_rejects_a_misspelled_key` (`:248-256`) uses string
  typos only, so `sorted()` never sees mixed types.
- **Intraday — resolve the contract BEFORE writing the test.** The first draft
  asked for "a numeric Intraday threshold being honoured". That is untested, but
  it also **contradicts an existing test**: `_DIRECTION_CONVICTION_DEFAULTS`
  deliberately omits intraday (`config_loader.py:101-103`) and
  `test_shipped_yaml_and_code_defaults_agree` (`:390`) asserts YAML and code
  defaults agree on null-ness. A numeric Intraday threshold would be honoured by
  the resolver and fail that test. Decide first: is Intraday
  permanently un-gated, or gated-if-specified? Then write the matching test.

**Size:** ~70 lines of source, ~170 of test. One layer. Converges in one round.

**Acceptance:** all five repros raise the named `ValueError` naming a path that
exists in the file; existing `test_config_loader.py` passes unchanged; backend
suite green.

**Branch:** `claude/yaml-integrity-stage1-direction-conviction`.
**Rollback:** pure `config_loader.py` change, no schema or boot impact — revert
the commit.

---

## 5. Stage 2 — staleness detection across all five caches (Mode A)

**2.1 — Record what was loaded.** On first load, stash the file's `mtime` and a
hash of its bytes. This must live **once, for the file**, not once per cache —
the five readers do not share a loader, so a per-cache stash would cover one
copy in five and miss A2 entirely.

**2.2 — Which signal wins.** `mtime` is the cheap pre-filter; the byte hash is
authoritative. A changed `mtime` with an unchanged hash is NOT a divergence
(a touch, a checkout, an editor rewriting identical bytes) and must not warn —
false alarms are how a warning gets ignored. A changed hash is a divergence
regardless of `mtime`.

**2.3 — Where it is checked, and how this differs from startup validation.**
The first draft contradicted itself here (§7.4 said "validate at startup", §5
said "on each scan request"). They answer **two different questions** and both
are kept:
- **At startup:** *is the loaded config valid?* → the verdict in §7.4.
- **At each scan request:** *does the file on disk still match what is loaded?*
  → a cheap `stat` + conditional hash. This is Mode A only.

**2.4 — No reload endpoint and no auto-reload.** Per §7.2. The first draft
retained a "2.4 — give the operator an explicit reload" bullet that directly
contradicted §7.2 and was left in by mistake; it is deleted. Auto-reload stays
forbidden for an additional reason A2 now supplies: reloading five caches at five
different moments mid-scan is the torn read, deliberately induced.

**2.5 — Cost on the unattended path.** The scheduled-scan path
(`scan_schedule_scheduler.py:150-156`) runs this check with no user present. A
`stat` per scan is free; the hash is read-only on `mtime` change, so the steady
state costs one syscall.

**Honest note on value:** given §7.2 (he restarts after every edit), the hash
trivially matches on the ordinary path, and this check is a no-op exactly when
Kenneth follows his own stated workflow. It earns its place on the day he
forgets, and on A2 — which restart discipline does *not* protect against if any
process outlives an edit. The first draft called Mode A "the most likely way an
edit fails to hold" and then demoted it to a safety net; that framing was
incoherent and is withdrawn. Mode A is **low-likelihood under his workflow,
high-consequence when it fires.**

**Size:** ~50 lines of source, ~80 of test (re-sized after deleting 2.4; the
first draft's ~80/~120 was computed for the cancelled reload version).

**Acceptance:** editing the file mid-process makes the next scan request report
divergence naming the file; an identical-bytes rewrite does not.

**Branch:** `claude/yaml-integrity-stage2-staleness`.
**Rollback:** detection-only, no behaviour change on the valid path — revert.

---

## 6. Stage 3 — positional schema for more families (Mode C1)

**The first draft's mechanism for this stage does not work and is replaced.**

It proposed: "every key whose NAME appears in the schema must sit at one of its
declared paths." Stage 1's machinery works because `direction_conviction` is
unique — it occurs at exactly 3 paths, all legal. The families Stage 3 would
declare are **systematically non-unique**. Walking the shipped file:

| Key name | Occurrences | Why it collides |
|---|---|---|
| `event`, `vol`, `trend`, `pullback`, `trigger` | 6 each | once as a block at `horizons.<h>.<name>`, once as a scalar at `horizons.<h>.weights.<name>` |
| `atr_period` | 6 | `confidence_backtest.<h>` and `horizons.<h>.pullback` |
| `enabled` | 4 | `confidence_gate`, `fundamentals_gate`, `regime_gate`, `regime_sizing` |
| `swing`/`position`/`intraday` | 3 each | `horizons`, `regime`, `confidence_backtest` |
| `cautionBelow`/`rejectBelow` | 2 each | `confidence_gate`, `fundamentals_gate` |

A name-based rule therefore either rejects the shipped file on day one, or must
enumerate every legal path — at which point the exact typo it exists to catch
(indenting `trend:` one level into `weights`) is **indistinguishable from the
legal `weights.trend`**. It also flags `regime.swing`, which §6.3 below
deliberately exempts, reproducing the round-3 over-correction.

**3.1 — Schema is PATH-SHAPED, walked from the root.** Declare a tree of legal
paths and walk the config against it top-down, so a key's legality is decided by
where it sits, never by what it is called. `horizons.<h>.weights.trend` and
`horizons.<h>.trend` are then simply two different declared paths, and neither
teaches anything about the other.

**3.2 — Scope, smallest useful first.** Start with the families that gate a
trade and have no collisions at their own level: `stock_score_thresholds`,
`confidence_gate`, `regime_gate`, `fundamentals_gate`. `horizons.<h>.*` spans
lines 43-445 and is a stage of its own. **`regime_sizing` is NOT in this stage**
— it is gate-level per §2 and belongs in Stage 0 (§7.7.1), not in a
below-gate breadth sweep.

**3.3 — Do not police the file.** This schema owns the paths it declares, not
the `scoring_rules.yaml` namespace. An unrecognised family is nobody's business,
or a harmless additive edit becomes a hard 500 on both scan endpoints. With a
path-shaped schema this is a natural property rather than a rule that fights the
mechanism, which is the second reason for the redesign.

**Size:** the largest stage. `horizons` alone is 400 lines of YAML. The first
draft's estimate assumed the name-based walker was reusable; it is not. **Split
per family from the start** rather than running one audit round over all of it.

**Acceptance:** the shipped `scoring_rules.yaml` validates clean; a key indented
one level wrong in each declared family raises a `ValueError` naming the path it
was found at AND the path it belongs at; an added unknown family is ignored.

**Branch:** `claude/yaml-integrity-stage3-<family>` (one per family).
**Rollback:** the validator is called at startup (§7.4) and must be revertible
without touching boot — keep the call site a single line.

---

## 7. Kenneth's decisions

### Settled 2026-09-16, unaffected by round 1

**7.1 Scope: all stages.** Stage 3 last and splittable.

**7.2 Staleness: he never edits while the backend runs; he always restarts.**
No reload endpoint, no auto-reload.

**7.3 Breadth order: `scoring_rules.yaml` first, `risk_rules.yaml` second,
`contract_rules.yaml` last.** Scoring decides WHICH NAMES he sees; risk decides
HOW MUCH MONEY goes into a trade. A silent typo in risk sits closer to his money
than one in a scoring floor, so risk is not an afterthought — it is second only
because scoring is where the next edit is actually going.

**7.4 FAILURE POSTURE: a bad config must restrict THE SCAN AND NOTHING ELSE.**

Kenneth first agreed to "fail at start", then corrected it on being shown the
consequence, and the correction is the requirement. Everything runs in ONE
process: the scan scheduler, the nightly EDGAR prefetch, the strategy watch
evaluator, the portfolio alert monitor (`main.py:172-268`). Refusing to boot on a
bad config would kill ALERTING on live positions because of a typo in a scan
threshold.

**The two statements about his behaviour are compatible, and the first draft
never noticed it made both.** §7.2 says he restarts after editing. §7.4 says he
edits while holding open positions. Both are true together: he edits, then
restarts, *while positions are open*. That is exactly why "never refuse to boot"
is the requirement — a restart that does not come back up leaves his open
positions unmonitored until he notices and fixes the YAML by hand. The
reconciliation strengthens 7.4 rather than weakening it.

So the design is:
- **Validate at startup** — he restarts after every edit, so this is the moment
  he finds out.
- **NEVER refuse to boot.** Alerts, monitors and every scheduler keep running.
- **Block the scan**, with the reason attached (scope table in §7.5).
- **Surface it as a banner** (mechanism in §7.6).

One correction to this section's own supporting evidence: the claim that
`main.py` wraps each scheduler so one failure warns and the app survives is true
of eight blocks but **not** of `main.py:179-184`, where
`run_portfolio_alert_monitor()`, `run_regime_monitor()` and
`run_chart_alert_scheduler()` are started with bare `asyncio.create_task` outside
any `try`. The portfolio alert monitor — the exact thing 7.4 says must never be
killed — is the unwrapped one. Not this plan's job to fix, but 7.4 must not cite
it as precedent.

**7.5 "Block the scan" needs a scope table — it is not one thing.**

There are six scan-ish entry points (verified): `POST /analyze-stock`
(`stock_scan.py:608`), `POST /stock-scan` (`:1051`), `POST /scan/fib-pullback`
(`:1259`), `POST /scan/prebreakout` (`:1386`), `POST /stocks/first-passage`
(`:1530`), and `POST /scan` (`scan.py:1729`). Only two consult the
direction-conviction gate today (`scan.py:1427`, `stock_scan.py:1144`).

| Family | Blocked surface | Behaviour on invalid |
|---|---|---|
| `horizons.<h>.direction_conviction` | `POST /scan`, `POST /stock-scan` | refuse, 400 with named path |
| `stock_score_thresholds` | `POST /stock-scan`, `/analyze-stock` | refuse, 400 |
| `confidence_gate` | `POST /stock-scan` | refuse, 400 |
| `regime_gate` | `POST /scan` | refuse, 400 |
| `fundamentals_gate` | `POST /stock-scan` (via `services/fundamentals_gate.py`) | refuse, 400 |
| `regime_sizing` | **auto-trade fire path, NOT a scan** | see §7.7.1 — open |
| `entry_quality`, `confidence_backtest`, `regime` | unpoliced initially | unchanged |

Surfaces deliberately left running on an invalid config: pre-breakout and
fib-pullback scans (they do not read the policed families), first-passage,
exit-plan, and every monitor and scheduler.

**Scheduled scans have no user to show a banner to.** `scan_schedule_scheduler.py:150-156`
calls `_execute_stock_scan_core` directly and records the outcome via
`record_scheduled_scan_run` (`:163`, `:170`). `stock_scan.py:1135-1137` already
documents that a `detail` survives to that recorder. So: **a config failure marks
the scheduled run failed with the named path as its error, and the banner reads
off that existing last-run record.** No new mechanism for the unattended case.

**7.6 MESSAGE QUALITY — level 2, and it needs a FRONTEND stage the first draft
did not contain.**
- **Level 1:** it fails, with a message.
- **Level 2:** the message names the parameter to edit.

Level 2 is within reach on the backend — the validator carries a
name-the-offending-key guarantee, and B1/B3/B3b are logged precisely because they
break it. **But it is false end-to-end today.**
`frontend/components/organisms/RunScanButton/index.tsx:171-181` catches the
scan failure and **discards the error object entirely**:

```ts
.catch(() => {
  console.error('[RunScanButton] scan failed, is backend running on port 8000?');
  ...
  addToast({ reason: 'Scan failed — backend unreachable' });
});
```

`frontend/lib/api.ts:47-65` does carefully extract `json.detail` into the thrown
message — and RunScanButton throws it away. So today a malformed
`scoring_rules.yaml` tells Kenneth **the backend is down**, sending him to debug
the wrong thing entirely. There is no banner component in `frontend/components/`
(only `ToastContainer`, `AlertToast`, `BellPanel`).

**Stage 4 — surface the verdict (new, and required for 7.4/7.6 to mean
anything):**
- Backend holds the startup verdict in a module-level `config_health` holder,
  served by `GET /api/config/health` → `{ ok, errors: [{file, path, message}], stale }`.
- Frontend `configHealthStore` (ephemeral, not persisted — it is server state)
  fetched at app start, same pattern as `eventThresholdsStore`.
- A `ConfigHealthBanner` organism in the `(frame)` layout.
- `RunScanButton`'s catch changed to `.catch((err) => ...)` surfacing
  `err.message`, so the detail `api.ts` already extracts reaches the screen.

**Size:** ~60 lines backend, ~120 frontend + CSS module, per CLAUDE.md component
conventions (own folder, `index.tsx` + `.module.css`, no card shadows).
**Branch:** `claude/yaml-integrity-stage4-surface`.

### 7.7 — INVALIDATED BY ROUND 1. Kenneth must re-confirm these three.

**7.7.1 — Does a config failure disarm auto-trade? §7.4 currently says no, and
§2 shows that answer sizes his orders up.** "Restrict the scan and nothing else"
was decided on the belief that nothing outside the scan touches money. §2 shows
`regime_sizing` does. The recommendation is to **fail closed**: if `regime_sizing`
is invalid and auto-trade is armed, refuse to fire and alert, rather than fire
unsized. This is a Stage 0 — it is the only gate-level item here, it is ~20 lines
(replace the `except: return {}` with a hard failure the fire path checks), and
it should ship before any below-gate stage. **But it is a direct amendment to a
decision Kenneth made, so it is flagged, not assumed.**

**7.7.2 — Stage ordering vs the repo's own gate.** `PROJECT_STATE.json`'s
`audit_rule` defines the gate as wrong-number-on-a-broker-order or
corrupt-persisted-data, and `direction_conviction_gate_audit` records B1/B2/B3 as
"3 below-gate defects plus 1 coverage hole, all LOGGED not fixed per audit_rule's
fixing clause." So **Stage 1 is entirely below-gate**, while the gate-level
hazard (§2) was in no stage at all. The first draft's §7 ordering rationale —
"Stage 1 first because it delivers the level-2 message" — survives only as far as
Stage 0. Recommended order: **Stage 0 (auto-trade, gate) → Stage 1 → Stage 4
(surface) → Stage 2 → Stage 3.** Stage 4 moves ahead of 2 and 3 because until the
banner exists, every other stage's message dies in a log.

**7.7.3 — `risk_rules.yaml` is app-written (Mode D), which the breadth order in
§7.3 did not account for.** The Settings→Risk page rewrites the whole file and
destroys its 28 comment lines. Validating hand-edits to it without addressing
that is half a solution. Options: (a) keep 7.3's order and add comment-preserving
writes (`ruamel.yaml` round-trip) to that stage; (b) demote `risk_rules.yaml`
behind `contract_rules.yaml`, which nothing writes; (c) accept comment loss
explicitly. **Recommendation: (a)** — 7.3's reasoning that risk sits closest to
his money is correct and should not be reversed on an implementation
inconvenience.

---

## 8. Order, and what it buys

Pending §7.7.2, the recommended order is:

1. **Stage 0 — auto-trade fails closed.** The only gate-level item. Smallest.
2. **Stage 1 — the `direction_conviction` defects.** Below-gate, but it is what
   makes the level-2 message true, and the next edit Kenneth makes lands exactly
   here.
3. **Stage 4 — surface the verdict.** Until this exists, the banner in 7.4 and
   the level-2 promise in 7.6 are not delivered by anything.
4. **Stage 2 — staleness detection.** Small, low-likelihood under his workflow.
5. **Stage 3 — path-shaped schema**, per family, scoring → risk → contracts.

**PROJECT_STATE registration.** `direction_conviction_gate_audit.hard_cap_note`
already records that this line of work has no phase record (`active_phase` is
null) and that the three-round hard cap "did not fire automatically" as a result.
Each stage above gets its own phase entry with a PRESENCE `verify` probe before
it is built, or this plan reproduces that gap five more times.

**What this buys.** One stage stops an oversized broker order on a broken config.
The rest buy that the candidate list is built from the numbers Kenneth actually
chose — and that when it is not, the app says so, by name, on screen, while
everything watching his open positions keeps running.
