# YAML config integrity — an edit either takes effect, or fails loudly

**Status:** DRAFT with Kenneth's decisions folded in (section 6), not yet
audited. Written and amended 2026-09-16.
**Goal, in one sentence:** when Kenneth maintains a config YAML, the change he
made is the change the app runs — or the app tells him, loudly, that it is not.

**Why now.** The direction-conviction gate ran BACKWARDS for three months
(2026-06-18 → 2026-09-16) and nothing on screen or in a log said so. That was a
code bug, not a config bug, but it exposed the same class of hazard: this app
can run on a number nobody intended and give no sign. The next threshold change
Kenneth makes will be to the bearish floors in `scoring_rules.yaml`, by hand,
based on scan evidence. That edit must hold.

---

## 1. The problem is THREE failure modes, not one

The three logged `config_loader` defects are only the second of these. Scoping
the work to them would leave the likeliest real-world failure untouched.

### Mode A — STALENESS. The edit is correct and never read.

`load_scoring_cfg()` is `@lru_cache(maxsize=1)` (`config_loader.py:15`), and
**no `cache_clear()` for it exists anywhere under `backend/app/`.** The file is
read once per process. Edit `scoring_rules.yaml` while the server is running and
nothing changes, with no error, until a restart.

This is the most likely way an edit fails to hold in practice, and it is the
most dangerous, because the natural conclusion from "I changed the floor and the
scan looks identical" is "the floor does not matter" — the opposite of the truth.

The repo already solves this elsewhere: `routers/risk_settings.py:159-161`
clears three caches on `POST /settings/risk`. The pattern exists; it was never
applied to the scoring config.

### Mode B — MISPLACEMENT. The edit is read, but not from where it sits.

`direction_conviction` has a positional validator. It has three known holes,
all logged, two reproduced directly:

- **B1 — a flat dotted key forges a legal path.** `_walk_direction_conviction_paths`
  joins segments with `"."` (`config_loader.py:123`), so a top-level key spelled
  `"horizons.position":` yields exactly the path `legal_paths` accepts.
  Validation passes and the operator's value is never read. This is precisely the
  silent-ignore the validator exists to stop.
- **B2 — a `_defaults: &anchor` holder carrying a block hard-500s both scan
  endpoints**, although the round-3 docstring names that holder as the shape the
  positional rewrite unblocked. The test covers the empty holder only.
- **B3 — a self-referential anchor raises `RecursionError`, not `ValueError`**,
  escaping both routers as a bare 500 with no detail and destroying the
  naming-the-offending-key guarantee.

### Mode C — NO VALIDATION AT ALL for everything else.

`scoring_rules.yaml` has NINE top-level families: `stock_score_thresholds`,
`confidence_gate`, `confidence_backtest`, `horizons`, `entry_quality`, `regime`,
`regime_gate`, `regime_sizing`, `fundamentals_gate`. Exactly ONE sub-key of ONE
family (`horizons.<h>.direction_conviction`) is positionally validated.

Everywhere else the read pattern is `.get(key, default)`. A misspelled or
misplaced key falls through to a code-side default, silently, forever. The
gate that burned us got a validator *because* it burned us; nothing else has one.

---

## 2. What this plan deliberately does NOT do

`audit_rule` is explicit that batch size is the root cause of non-converging
audits: one change, one layer, roughly 500 lines. A single "validate all config"
change would span 15 reader modules and five YAML files, and would not converge.

So this plan is **three independent stages, each its own branch, each with its
own adversarial round.** Any stage can ship alone and is useful alone. Stage 3 is
explicitly flagged as possibly needing a further split.

Out of scope for all three stages:
- `settings.yaml` (22 reader modules) — user-facing, UI-written, different problem.
- The schedule stores (`scan_schedule_store`, `ingestion_schedule_store`,
  `edgar_schedule_store`, `tuning_schedule_store`, `sp500_schedule_store`,
  `strategy_watch_store`) — these WRITE their own YAML via `yaml.dump`; a
  hand-edit hazard does not apply the same way.
- `strategy_params.yaml` — machine-written by `strategy_param_store.adopt()`
  (`:157`, `yaml.safe_dump`). Any validation here must not fight the writer.
  Called out because an earlier claim in this repo's history — "nothing writes
  the YAML" — is true of `scoring_rules.yaml` ONLY, and must not be generalised.

---

## 3. Stage 1 — close the three known defects (Mode B)

Smallest, most provably correct, closes what is already logged.

**1.1 — Path as a tuple, not a joined string.** `_walk_direction_conviction_paths`
yields `tuple[str, ...]`; `legal_paths` becomes a set of tuples; comparison is
tuple equality. A `.` inside a key can then never synthesise a separator.
Error messages keep rendering with `".".join(path)` so operator-facing text is
unchanged.

**1.2 — Resolve YAML merge keys before validating position.** A
`direction_conviction` reached only through a `<<:` merge from an anchor holder
must be legal where it lands. Minimum fix: treat a mapping key beginning `_` as
a non-positional holder and skip it, matching the `_defaults` convention the
docstring already names. Its block is still shape-checked wherever it is merged.

**1.3 — Bound the recursion.** A depth limit (or a `seen` set of `id()`s) so a
self-referential anchor raises the module's named `ValueError` rather than
`RecursionError`. The naming-the-offending-key guarantee then holds for every
input `yaml.safe_load` will accept.

**Tests:** one per defect, each written to FAIL against today's code first
(B1 and B3 already have reproductions from this session to lift directly).
Plus the two guards logged as untested — `str(k)` at `:200` (two unknown keys of
mixed type must raise the named `ValueError`, not `TypeError`) and a numeric
Intraday threshold being honoured, which no test asserts today.

**Size:** ~60 lines of source, ~150 of test. One layer. Converges in one round.

---

## 4. Stage 2 — make staleness impossible to miss (Mode A)

The highest-value stage, and independent of Stage 1.

**2.1 — Record what was loaded.** On first load, stash the file's `mtime` and a
hash of its bytes alongside the cached dict.

**2.2 — Detect divergence at the point of use.** On each scan request, compare
the file's current `mtime`/hash against what is cached. On mismatch the app is
running a config the file no longer contains.

**2.3 — Kenneth answered this: he does NOT edit a config while the backend is
running.** He always restarts. So Stage 2 shrinks to one safety net rather than a
reload mechanism: if the file on disk differs from what is loaded, say so. It
costs almost nothing and it covers the day he forgets, or a long-running process
holding an old copy. Auto-reload is explicitly NOT built — a scan that reloads
mid-flight would score half its candidates on one threshold and half on another.

**2.4 — Give the operator an explicit reload**, following the
`risk_settings.py:159-161` precedent: a small endpoint that clears the scoring
caches, so a hand-edit can be applied without a full restart.

**Size:** ~80 lines of source, ~120 of test. One layer.

---

## 5. Stage 3 — one positional schema for every validated family (Mode C)

Generalises Stage 1's tuple-path machinery from one key to a declared set.

**3.1 — Declare the schema.** A module-level map of legal paths for the families
worth policing. Start with the ones that gate or size a trade:
`stock_score_thresholds`, `confidence_gate`, `regime_gate`, `regime_sizing`,
`fundamentals_gate`, and `horizons.<h>.*`. Descriptive families (`regime`'s
state definitions, `confidence_backtest`) can stay unpoliced initially.

**3.2 — One walk, many families.** Reuse Stage 1's walker: every key whose NAME
appears in the schema must sit at one of its declared paths. This catches the
misspelled-parent and wrong-level cases across all listed families at once.

**3.3 — Do not police the file.** The lesson from the round-3 over-correction
stands and must be stated in the code: this schema owns the keys it declares, not
the `scoring_rules.yaml` namespace. An unrecognised family carrying none of the
declared key names is nobody's business, or a harmless additive edit becomes a
hard 500 on both scan endpoints.

**Size:** the largest stage and the one most likely to need splitting. If the
first audit round returns more than a handful of gate-level findings, split it
per family rather than running a second round.

---

## 6. Kenneth's decisions — ANSWERED 2026-09-16, these are settled

**6.1 Scope: ALL THREE STAGES.** Stage 3 last and splittable.

**6.2 Staleness: he never edits while the backend runs.** Stage 2 shrinks to the
disk-vs-loaded warning in 2.3. No reload endpoint, no auto-reload.

**6.3 Breadth, in this order: `scoring_rules.yaml` first, `risk_rules.yaml`
second, `contract_rules.yaml` last.** Note the correction that produced this
order: scoring decides WHICH NAMES he sees; risk decides HOW MUCH MONEY goes
into a trade. A silent typo in risk sits closer to his money than one in a
scoring floor, so risk is not an afterthought — it is second only because
scoring is where the next edit is actually going.

**6.4 FAILURE POSTURE — THE MOST IMPORTANT ENTRY HERE, AND IT OVERRIDES AN
EARLIER DRAFT OF THIS PLAN. A bad config must restrict THE SCAN AND NOTHING
ELSE.**

Kenneth first agreed to "fail at start", then corrected it on being shown the
consequence, and the correction is the requirement: he DOES edit config while
holding open positions — that is the normal case, not an edge case. He changes a
threshold to run a new scan while positions are live.

Everything in this app runs in ONE process: the scan scheduler, the nightly EDGAR
prefetch, the strategy watch evaluator, the portfolio alert monitor
(`main.py:177-268`). Refusing to boot on a bad config would therefore kill
ALERTING on live positions because of a typo in a scan threshold. That is a far
worse outcome than the one it defends against, and it is forbidden.

SO THE DESIGN IS:
- **Validate at startup** — he restarts after every edit, so this is the moment
  he finds out, and finding out early is the whole point.
- **NEVER refuse to boot, and never let validation touch anything but scanning.**
  Alerts, monitors and every scheduler keep running on a bad config. This also
  keeps faith with `main.py`'s existing design, where each scheduler is wrapped
  so one failure warns and the app survives.
- **Block the SCAN only**, with the reason attached.
- **Surface it as a message/banner**, which is what he asked for. Not a buried
  traceback. The failure he must never have is one he does not notice.

**6.5 MESSAGE QUALITY — KENNETH'S TWO MATURITY LEVELS, and we build to level 2.**
- **Level 1:** it fails, with a message.
- **Level 2:** the message names the parameter to edit.

Level 2 is already within reach rather than aspirational: the existing validator
carries a naming-the-offending-key guarantee, and defects B1 and B3 are logged
precisely because they BREAK it (B3 escapes as a bare 500 with no detail). So
Stage 1 is not only a bug fix — it is what makes level 2 true.

## 7. Order, and what it buys

1. **Stage 1 first.** Kenneth never edits while running, so staleness is not his
   live risk — and Stage 1 is what delivers his level-2 message, because the two
   defects that break the name-the-key guarantee are in it.
2. **Stage 2 next**, now just the disk-vs-loaded warning. Small.
3. **Stage 3 last**, scoring → risk → contracts, split further if its first
   audit round returns more than a handful of gate-level findings.

None of the three can put a wrong number on a broker order: these gates filter
which names reach a list. What they buy is that the list is built from the
numbers Kenneth actually chose — and that when it is not, the scan says so, by
name, while everything watching his open positions keeps running.
