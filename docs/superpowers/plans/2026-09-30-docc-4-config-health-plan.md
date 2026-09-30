# DOCC-4 — backend config-health surface + the risk_rules comment-loss header

Document C, plan 4 of the YAML-CONFIG-INTEGRITY split (§12 of
`2026-09-16-yaml-config-integrity-plan.md`). Written fresh; nothing from that
plan's §3–§8 is carried. Backend only, one layer. The frontend banner is
DOCC-5, planned only after this ships.

**Implements:** decision `DOCC-4-5-SLICING-2026-09-30`. It builds on:
- `DOCC-9.4-9.5-RATIFIED-RESTAT-2026-09-28`: re-stat on every poll;
- `DOCC-9.6-MONEY-BLOCKS-REQUIRED-2026-09-28`: unknown top-level families WARN
  on a health line;
- `DOCC-9.8-CLOSED-MONEY-SUBTREES-2026-09-28`: the horizons tree is warn-only;
- `DOCC-9.3B-D1-ACCEPT-COMMENT-LOSS-2026-09-28`: a header line, no ruamel.yaml.

The payload shape comes from §9.11 of the old plan (confirmed 2026-09-17):
`{ok, checked, errors: [{file, path, message}], stale}`, plus `warnings`, which
`DOCC-4-5-SLICING` adds.

**Revision 2 (after plan round 1, NOT CLEAN, 3 gate-level).** Section §7 lists
every round-1 finding and where each one was resolved. The biggest change:
staleness is no longer "disk vs a boot snapshot". It is "disk vs **what each
running cache actually holds**", compared loader by loader (§2.2). §7
explains why this is a deliberate deviation from the decision's wording.

**Revision 3 (after plan round 2, NOT CLEAN, 6 gate-level).** Section §8 lists
every round-2 finding and its resolution. The biggest change: instead of a
digest recorded inside each loader at load time (`note_load`) and dropped on a
Settings save (`forget_loads`), the poll reads **each cache's live value** and
compares it with the same projection of the disk file (§2.2). Both
`note_load` and `forget_loads` are gone. This stays inside decision
`DOCC-4-REV2-APPROVED-2026-09-30` (per-cache judgement, no boot snapshot,
holder in `config_health.py`, nothing in `main.py`); §8 flags it for Kenneth.

**Revision 4 (after plan round 3, NOT CLEAN, 3 gate-level).** Section §9 lists
every round-3 finding. The mechanism is unchanged. Fixes: the class name
(`AutoTradeService`), `AutoTradeService` projections that copy their loaders'
catch-all `except`, and direction_conviction scopes that include Analysis.

---

## 1. What is true on main `96763b2` (verified by reading the code)

### 1.1 Nothing reports the config's state

- No `config_health` symbol exists anywhere under `backend/` or `frontend/`.
- A bad `scoring_rules.yaml` is found only when a scan or a fire runs, as a
  named 500 (DOCC-1/DOCC-2).
- Unknown top-level families are logged at WARNING once per process
  (`money_config._warn_unknown_top_level`), and nobody reads the log.
- The `horizons` tree is not checked beyond `direction_conviction`
  (`config_loader._validated_direction_conviction_blocks`, which is positional
  only, plus the value checks in `load_direction_conviction_min_trend`).

### 1.2 Fifteen cached readers over the three files, each filled lazily

`grep -rn lru_cache app/` restricted to readers of the three files. **The build
re-runs this grep. T16 pins the list.**

| File | Cached reader (`lru_cache(maxsize=1)`) | What it keeps |
|---|---|---|
| scoring_rules | `config_loader.load_scoring_cfg` | whole doc |
| scoring_rules | `stock_scan._load_full_scoring_cfg` | whole doc |
| scoring_rules | `auto_trader._load_scoring_doc` | whole doc (validated) |
| scoring_rules | `stock_scorer._load_config` | whole doc |
| scoring_rules | `entry_quality._load_config` | whole doc |
| scoring_rules | `signal_confidence._cfg` | whole doc |
| risk_rules | `config_loader.load_reward_risk_cfg` | `reward_risk` |
| risk_rules | `config_loader.load_exit_plan_cfg` | `exit_plan` |
| risk_rules | `config_loader.load_reprice_horizon_cfg` | `reprice_horizon` |
| risk_rules | `config_loader.load_first_passage_cfg` | `first_passage` |
| risk_rules | `portfolio_risk._load_config` | whole doc |
| risk_rules | `alert_generator._load_risk_config` | whole doc |
| risk_rules | `AutoTradeService._max_arm_age_minutes` | `auto_trade` (one key) |
| risk_rules | `AutoTradeService._risk_config` | `auto_trade` |
| contract_rules | `contract_validator._load_config` | whole doc |

Uncached readers re-read on every call, so they are always live:
`regime_monitor._load_risk_config` and `risk_settings._load_risk`. No config is
read at import time (round 1 verified this).

Each cache fills on its first call, not at boot. After a hand edit, some
readers can hold the old file and some the new (Mode A2 of the old plan). §9.2
still holds: Kenneth restarts after editing. This plan **detects**. It never
reloads anything.

### 1.3 The one in-app writer of these three files

`POST /settings/risk` (`routers/risk_settings.py:159`):
1. runs `_load_risk()`;
2. patches `reward_risk.{premium_stop_pct,target_t1..t3_pct}` and
   `portfolio.{…}`;
3. saves with `_save_risk(cfg)`, which is `atomic_write_yaml`, a full
   `yaml.dump`;
4. clears three caches: `portfolio_risk._load_config`,
   `alert_generator._load_risk_config` and `scan_router._rr_cfg`, which is
   `load_reward_risk_cfg`.

Round 1 independently verified that every reader of the keys it writes goes
through one of those three caches or is uncached. `ArmedStrategy.portfolio_value`
is an arm-time snapshot, not config.

The other **five** cached risk readers (`exit_plan`, `reprice_horizon`,
`first_passage` and the two `AutoTradeService` ones) are not cleared. None of them
reads a key the save writes, but a hand edit to their sections that was pending
at save time is merged into the file and still is not live.
`scoring_rules.yaml` and `contract_rules.yaml` have no in-app writer.

### 1.4 Comment loss (D1)

`risk_rules.yaml` has **35** full-line comments today, and `yaml.dump` drops
every one on the first Settings → Risk save. Decision 9.3B accepts that loss and
adds a header line. A header written only into the file would be erased by the
first save it warns about, so `_save_risk` must write the header too.

## 2. What changes

### 2.1 New module `backend/app/services/config_health.py`

This module holds the process-wide holder (`config_health = ConfigHealth()`) and
every check.

**Where the holder lives, a deliberate deviation.** The decision says the holder
is "in backend/app/main.py". It lives in a service module instead, because 15
loaders across 9 modules register with it (§2.2) and importing `main` from them
would be circular. `main.py` gains no boot call: the poll-time comparison
replaces the boot snapshot (§7, finding 1). The phase probe therefore pins
`config_health.watch` in `config_loader.py` (§2.7).

**Import direction (round-2 below-gate 3).** The loader modules import
`config_health` at top level, so `config_health.py` must never import a loader
module at top level. It imports `money_config`, `conviction_sizing` and
`config_loader` **inside** the check functions that use them. T16 imports
`app.main` from a fresh interpreter, which catches a cycle.

**Module paths are read at call time.** `ConfigHealth` reads the module global
`CONFIG_DIR` inside each method, never in `__init__` or a default argument, so
tests can monkeypatch it. The checks call `money_config.money_block_errors` and
the other validators through their **module attribute**
(`from app.services import money_config` and then
`money_config.money_block_errors(...)`), so T13 can patch them.

### 2.2 Staleness: what the process runs vs what is on disk

**Revision 3 (round-2 findings 1, 2, 5; below-gate 6, 7).** Revision 2 recorded
a digest inside each loader (`note_load`) and dropped records on a Settings
save (`forget_loads`). Round 2 showed four holes in that: the two `AutoTradeService`
loaders cache a fallback and so recorded nothing; the digest failed on parsed
YAML with mixed-type keys and silently recorded nothing; a load racing a save
could leave an old value cached with its record forgotten; and a record taken
at load time cannot see a cached dict that was changed in place. All four come
from judging a **copy** of what was cached. Revision 3 judges **the cached
value itself**, at poll time. There are no records, and there is no
`forget_loads`.

**Revision 4 (round-3 findings).** The class is `AutoTradeService`
(`auto_trader.py:2202`); revision 3 wrote `AutoTrader`, which would have been a
`NameError` at import. Loader names are `<module>.<qualname>` with the
package prefix dropped, for example `auto_trader.AutoTradeService._risk_config`
(below-gate 9).

**Registration.** Each of the 15 cached loaders in §1.2 is registered once, at
import of its own module, directly after its definition (after the class body
for the two `AutoTradeService` staticmethods):

```python
config_health.watch(
    file="risk_rules.yaml",
    loader="config_loader.load_exit_plan_cfg",
    fn=load_exit_plan_cfg,                  # the lru_cache wrapper itself
    project=lambda doc: doc["exit_plan"],   # what this loader returns, from a parsed doc
)
```

- `watch` stores `{loader: (file, fn, project, on_unreadable)}` under a
  `threading.Lock`. A second `watch` under the same name **replaces** the
  entry, so `importlib.reload` of a loader module leaves the registry
  pointing at the live wrapper (round-3 below-gate 13, T17). It never raises: a bad registration is logged and becomes a permanent `stale`
  line, "loader <name> is registered wrongly, so it cannot be judged".
- **The loaders' bodies do not change.** They read the same file, parse it the
  same way, return the same value and raise the same exceptions. Registration
  adds one statement after each definition and nothing inside it.
- `project` mirrors the loader's own return expression on a parsed doc:
  - identity for the eight whole-doc loaders;
  - `doc["<section>"]` for the four `config_loader` section loaders;
  - for the two `AutoTradeService` loaders, which wrap their **whole body**,
    read and parse included, in `except Exception` and return a fallback
    (`auto_trader.py:3052-3072`), the projection copies the body and its
    `try`/`except` exactly (round-3 finding 2):
    ```python
    def _project_risk_config(doc):          # loader: cfg.get("auto_trade", {}); except → {}
        try:
            return doc.get("auto_trade", {})
        except Exception:
            return {}
    def _project_max_arm_age(doc):          # loader: int(cfg.get(...).get(..., 30)); except → 30
        try:
            return int(doc.get("auto_trade", {}).get("max_arm_age_minutes", 30))
        except Exception:
            return 30
    ```
    and they register `on_unreadable={}` and `on_unreadable=30`: the value the
    loader itself returns when the file cannot be read or parsed. Every other
    loader registers `on_unreadable=RAISES` (the default), because it lets
    that exception out and `lru_cache` caches nothing.

  T24 pins each projection against its real loader on the shipped files, on
  edited files that change the section, and on the fallback inputs (below).

**The comparison, on every poll (decision 9.5).** **Order (round-3 below-gate
8): all live values are read first, then the three files.** An edit landing
between the two reads can give one poll a stale line that the next poll clears.
It can never give a false green for a value loaded **before** the disk read,
because disk is read last. §5 states the one-poll window. For each registered
loader:
1. If `fn.cache_info().currsize == 0`, skip it. Nothing is running it, and its
   first call will read the disk. This removes revision 1's false positive for
   files nothing has loaded.
2. Otherwise call `fn()`. On a cache hit this returns the cached object without
   running the body, which is how every consumer reads it. The call runs
   outside the registry lock.
   - Suppose a Settings save clears the cache between step 1 and step 2. The
     call then does a real load from disk, and that value matches disk, which
     is true: the next consumer gets the same thing.
   - If that load raises (for example `_load_scoring_doc` on a refused money
     block), `lru_cache` cached nothing. The loader is skipped, and the
     refusal is already an `error` from §2.3.
3. Compute the value a restart would load, from the file's memoised disk
   parse (§2.3). **The rule: stale unless the loader's own code, run on
   today's disk, would produce the same value, including through its except
   path.**
   - Disk unreadable or unparseable: the expected value is `on_unreadable`.
     For a `RAISES` loader, it is stale (a restart would fail, not reproduce
     the cached value).
   - Otherwise `project(disk_doc)`. If that raises (the section is gone), it
     is stale for the same reason. The two `AutoTradeService` projections
     never raise, because they carry the loader's own `except`.
4. Compare the two with `canonical(x) == canonical(y)`. `canonical` is a small
   recursive encoder in `config_health.py`:
   - every value is tagged with its type name, so `1`, `"1"`, `True` and
     `1.0` all stay distinct;
   - mapping keys are encoded, then sorted by their encoding, never by the raw
     key, so `{"a": 1, True: 2}` (a YAML `yes:` key) encodes;
   - lists keep their order;
   - floats encode as `("float", repr(x))`, never by value, so `.nan` equals
     itself and `-0.0` differs from `0.0` (round-3 below-gate 5);
   - scalars other than `str`, `int`, `float`, `bool` and `None` (for
     example `datetime`, which `safe_load` produces) encode as `(type name,
     repr)`;
   - it has a node budget (100 000 nodes). Shared aliases are re-expanded,
     so an alias-heavy doc could otherwise cost exponential CPU on every poll.
     Going over the budget raises `CanonicalError` (round-3 below-gate 7);
   - it tracks the ids of containers on the current path, so a recursive
     alias raises `CanonicalError` instead of looping.
5. A mismatch → one `stale` entry per (file, loader):
   `{file, path: "<section dotted, or empty for whole>", message: "disk differs from running config (<loader>) -- restart"}`.
   A `CanonicalError` on either side → a `stale` entry with the message
   "running config cannot be compared with disk (<reason>) -- restart", never
   silence (round-2 finding 2).

What this catches:
- **Edit, then revert (round-1 finding 1).** The cache holds the edited
  values. The reverted disk does not match them, so the loader stays stale
  until restart.
- **A cache that holds a broken doc** (for example `load_scoring_cfg` caching
  a doc that the direction_conviction check then refuses, so every scan 500s),
  after the file was fixed: stale.
- **A cached fallback (round-2 finding 1).** `AutoTradeService._risk_config`
  caches `{}` ("risk limits disabled") when the file could not be read at
  first fire. After the file is fixed, `{}` differs from `doc["auto_trade"]`,
  so it is stale. `_max_arm_age_minutes` caching its fallback `30` reads stale
  only when disk yields something other than 30. That is the truth: the
  process runs 30. And a valid file on which the loader itself falls back
  (`auto_trade:` null, `max_arm_age_minutes: "abc"`, a list doc) yields the
  same fallback through the projection. So it is **not** stale: a restart
  would load the same thing. What those values mean is `risk_rules` contents,
  which is in `not_checked`.
- **Torn state.** Two loaders of one file holding different versions: at most
  one of them can match disk, so the other is reported.
- **A cached dict changed in place by a consumer** (below-gate 6). The live
  object is compared, so a change is visible as stale. Today's consumers copy
  before changing (`stock_scorer.py:1053`, `fundamentals_gate.py:26`,
  `contract_validator.py:400`, `scan.py:678`), so this should never fire.
- **Section scoping (below-gate 7).** Each loader is compared on its own
  projection. `_max_arm_age_minutes` is stale only when its one value
  differs.

**Settings save (§1.3) needs nothing new.** The save clears its three caches.
A cleared cache has `currsize == 0` and is skipped until the next load, which
reads the new file. Now suppose a load that read the **old** file finishes after
the clear, and `lru_cache` stores the old value. That is round-2 finding 5's
race. The poll then sees `currsize == 1`, calls `fn()`, gets the old value and
reports it stale, which is the truth. No timing can make a cached value and
the comparison disagree, because the comparison reads that exact value. The
five uncleared loaders are compared on their own projections, so a save that
does not touch their sections leaves them clean. A hand edit to their section
that was pending at save time leaves them stale.

**More than one worker (round-1 finding 4, round-2 finding 6).** Each worker
has its own caches, and a poll reaches one of them.
- When `WEB_CONCURRENCY > 1`, `report()` adds one permanent `stale` line:
  "multiple workers: each has its own caches, so staleness cannot be judged
  from one of them -- run with --workers 1".
- `uvicorn --workers N` does **not** set `WEB_CONCURRENCY`. A child process
  cannot reliably tell `--workers` from `--reload`, since both run the app in a
  spawned child. So this case is not detected. It is listed in `not_checked`
  ("single worker assumed; only WEB_CONCURRENCY is detected") and in §5.
- The payload carries `pid`, so a caller that sees the pid change between
  polls knows it is talking to more than one process. DOCC-5 can use this.
  This slice does not act on it.

### 2.3 `report()`: the payload

```json
{
  "ok": false,
  "checked": ["scoring_rules.yaml parses", "money blocks: presence, spelling, enabled",
              "regime_sizing values", "regime blocks (intraday, swing, position)",
              "direction_conviction: position and values", "top-level families",
              "horizons tree: unknown keys", "risk_rules.yaml parses",
              "contract_rules.yaml parses", "running config vs disk"],
  "not_checked": ["money blocks other than regime_sizing: values",
                  "required non-money sections and keys (horizons.<h>.*, stock_score_thresholds, confidence_backtest, risk_rules sections)",
                  "risk_rules.yaml and contract_rules.yaml contents",
                  "single worker assumed; only WEB_CONCURRENCY is detected",
                  "copies the frontend fetched at page load (event and IV thresholds)"],
  "pid": 12345,
  "errors":   [{"file": "scoring_rules.yaml", "path": "regime_gate", "message": "is missing — …", "blocks": "stock and options scans, Analysis and every auto-trade fire"}],
  "warnings": [{"file": "scoring_rules.yaml", "path": "regime_gates", "message": "unknown top-level key, ignored — did you mean 'regime_gate'?"}],
  "stale":    [{"file": "risk_rules.yaml", "path": "exit_plan", "message": "disk differs from running config (config_loader.load_exit_plan_cfg) -- restart"}]
}
```

- **`ok` is true only when `errors`, `warnings` and `stale` are all empty.** A
  warning is not clean: it is a key the operator believes does something and
  does not. The three lists keep the severity, and `ok` is only the "anything
  to show?" bit.
- **`checked` lists what ran, and `not_checked` is a fixed list of what this
  slice does not check** (§9.11: never an unscoped green). A check that could
  not run, for example because the file does not parse, is left out of
  `checked`. The parse error says why. `not_checked` is a literal constant,
  and T1 pins it, so DOCC-5 can say "green on what was checked". §4 is where
  the not-checked items are recorded.
- **Errors come from the file on disk.** On a non-stale file, disk and the
  running copy are the same values. On a stale one, the `stale` line already
  says restart, and the errors describe what the restart will load.
  - Each file: unreadable, does not parse (with the parser's line and
    column), or not a mapping (for example an empty file) → error with
    `path: ""`.
  - `scoring_rules.yaml`, when it is a mapping:
    - `money_config.money_block_errors(doc)`: new and pure, §2.5.
      `blocks`: "stock and options scans, Analysis and every auto-trade fire"
      (round-3 below-gate 4: `/scan/prebreakout` and `/scan/fib-pullback`
      do not read the money blocks).
    - `conviction_sizing.resolve_sizing(doc.get("regime_sizing"))`, catching
      `SizingConfigError` → one error at `regime_sizing` carrying its
      message. This is the same call the stock scan and the fire make, so a
      value they refuse (for example `min_mult: 2`) is red here too.
      Skipped when `money_block_errors` already reported `regime_sizing`.
      `blocks`: "the stock scan and every auto-trade fire".
    - Regime blocks (round-1 finding 10, round-2 below-gate 1):
      - **First, once:** if `regime` is missing or not a mapping, report the
        single error `regime_block_errors(doc, HORIZONS)` gives for it, with
        `blocks: "stock and options scans, Analysis and every auto-trade fire"`, and stop.
        This avoids the same error three times with a too-narrow scope each.
      - **Otherwise, per horizon:** `money_config.regime_block_errors(doc,
        (h,))`, so each error's `blocks` names its scope. The scans and the
        fire check only the requested or armed horizon, and Analysis checks
        all three. So a broken `regime.intraday` gives `blocks: "Analysis, and
        Intraday scans and fires"`, and the banner does not claim that every
        scan is blocked.
    - direction_conviction: `_validated_direction_conviction_blocks(cfg=doc)`
      (positional), then, **when that passes**,
      `direction_conviction_value_errors(cfg=doc)` (new and pure, §2.5) for
      all three horizons × both directions, which is what every scan calls
      today. Errors carry `.path` from the new `ConvictionConfigError`, never
      a path parsed out of the message (§2.5).
      - `blocks` (round-2 below-gate 2, round-3 finding 3). The callers of
        `load_direction_conviction_min_trend` are the stock scan
        (`stock_scan.py:1087`, `:1503`), the options scan (`scan.py:1612`)
        and Analysis (`_analyze_core`, `stock_scan.py:660`). Each resolves
        only the requested pair, but each validates every block first. So:
        - a shape or placement error from
          `_validated_direction_conviction_blocks` → "every stock and
          options scan, and Analysis";
        - a value error at `horizons.<h>.direction_conviction.<dir>_min_trend`
          → "<H> <Dir> stock and options scans and Analysis" (for example
          "Swing Bullish stock and options scans and Analysis").
      - Message parity (round-2 below-gate 8): the value checks are called
        with the title-case `Horizon` value (`'Swing'`), which is what the
        scans pass from `req.horizon`, so the message is byte-identical to
        the one a scan raises. T10 pins that.
  - `risk_rules.yaml` and `contract_rules.yaml`: parse and mapping only (see
    `not_checked`).
- **Warnings** (`scoring_rules.yaml` only; they never refuse):
  - **Unknown top-level family (9.6).** `money_config.unknown_top_level_keys(doc)`:
    pure, returns `[(key, hint)]`, and uses the same `difflib` rule as today's
    log. The once-per-process log is kept and now uses it.
  - **Unknown key in the horizons tree (9.8, warn-only).** A literal table,
    `HORIZON_KEYS`, in `config_health.py`: the closed spec of `horizons.<h>.*`,
    built from the shipped file's keys **plus every key a consumer reads with a
    default that the shipped file omits**. The build greps
    `grep -rn 'horizons\|_horizon_cfg' app/`, which today covers
    `stock_scorer.py` (including the helper `_horizon_cfg` and the override
    writes at `:1071-1114`), `stop_cost.py`, `reprice_horizon.py`,
    `routers/config.py`, `scan.py`, `stock_scan.py`, `contracts.py`,
    `regime.py`, `auto_trade.py`, `config_loader.py` and `schemas`. It lists
    every key found in the commit message. T12 asserts the table contains
    every key that a `.get("<key>", …)` or `["<key>"]` on a horizon-bound
    variable reads (the grep output is pinned in the test as a literal set).
    The walk:
    - Horizon names other than `intraday`, `swing` and `position` → a warning,
      "unknown horizon, never read". **Keys starting with `_` are skipped**:
      this is the `_defaults: &anchor` holder that the direction_conviction
      docstring names as legitimate. `<<` is resolved by the loader, so it
      never appears.
    - Inside a known horizon: a key not in `HORIZON_KEYS` → a warning, with a
      `difflib` suggestion among its siblings. A leaf where the spec has a
      subtree, or the reverse → a warning.
    - The walk recurses only where `HORIZON_KEYS` has a subtree, so its depth
      is bounded by the spec's and a recursive alias cannot loop it.
    - `direction_conviction` is not walked here. Its own validator reports
      it, as an error.
  - Every key is passed through `str()` before it becomes `path` or reaches
    `difflib`. YAML parses `yes:`, `on:` and `1:` as bool or int (round-1
    finding 12).
- **`report()` never raises.** An unexpected exception inside one check
  becomes an error `{file, path: "", message: "health check <name> crashed:
  <exc>"}`, and that check is left out of `checked`. The endpoint never 500s
  over the config it reports on. **A crash result is never memoised**
  (round-3 below-gate 14): the next poll runs that check again, even on
  unchanged bytes.
- **Decoding (round-3 below-gate 6).** The loaders read in text mode with the
  locale encoding (`open(...)` or `read_text()` with no `encoding=`). On
  Kenneth's Windows machine that is cp1252 (`start-backend.bat` does not pass
  `-X utf8`). Health reads the bytes once, hashes them for the memo, then
  decodes with `locale.getpreferredencoding(False)`, which is the same codec
  the loaders get. A non-ASCII value therefore parses to the same string on
  both sides. A decode error is a file error, "cannot be decoded as <codec>",
  like a parse error. T28 pins parity with a non-ASCII value.
- **Memoised by content (round-1 finding 11).** Each file's parse, its
  error and warning results, and the `canonical` form of each registered
  loader's projection are cached against the sha256 of its bytes, and are
  recomputed only when the bytes change. A poll therefore costs three file
  reads, three hashes, and one `canonical` of each loaded cache's live value.
  The lock is held only while copying the registry and the memo, never across
  I/O, parsing, validation or a loader call.

### 2.4 Endpoint

`GET /api/config/health` in `routers/config.py`, which already carries the
`/api/config` prefix and is registered (`main.py:423`). It is a sync `def`, run
in the threadpool like that file's other handlers, and returns
`config_health.report()`. The status is always 200: the payload carries the
verdict.

### 2.5 Refactors the checks need (behaviour unchanged at every existing call site)

- `money_config.money_block_errors(doc) -> list[(path, msg)]`: the body of
  `validate_money_blocks`, without the raise or the log. `validate_money_blocks`
  becomes `_warn_unknown_top_level(doc); errs = money_block_errors(doc); if errs:
  raise MoneyConfigError(errs)`. This mirrors DOCC-2's
  `regime_block_errors`/`validate_regime_block` split.
- `money_config.unknown_top_level_keys(doc) -> list[(raw_key, hint)]`: pure,
  returning the **raw** key. `_warn_unknown_top_level` uses it, and keeps its
  once-per-process set and its `%r` log keyed on the raw key, so today's log
  lines stay byte-identical (`True` stays `True`, and `True` and `"True"` stay
  two warnings). Only the health warning applies `str()`, for `path` and
  `difflib` (round-3 below-gate 12).
- `config_loader`:
  - **`ConvictionConfigError(ValueError)`** with `.path` (a dotted string).
    Every `raise ValueError` in `_validated_direction_conviction_blocks`,
    `_walk_direction_conviction_paths` (the alias-cycle raise) and
    `load_direction_conviction_min_trend`'s value checks raises it instead,
    with the same message text. Because it is a `ValueError` subclass, every
    existing `except ValueError` still catches it, and every existing test
    that matches the message still passes.
    - The paths: the found path for a misplaced block;
      `horizons.<h>` for a non-mapping horizon;
      `horizons.<h>.direction_conviction` for a bad block or unknown keys;
      `horizons.<h>.direction_conviction.<dir>_min_trend` for a bad value;
      `horizons` for a non-mapping `horizons`;
      the cycle path for an alias cycle.
    - `load_direction_conviction_min_trend`'s "unknown horizon"/"unknown
      direction" raises (caller errors, not config errors) stay plain
      `ValueError`.
  - `_validated_direction_conviction_blocks(cfg=None)`: it uses
    `load_scoring_cfg()` when `cfg is None` (not `cfg or …`).
  - `direction_conviction_value_errors(cfg) -> list[(path, msg)]`: the value
    checks from `load_direction_conviction_min_trend`, moved into a helper
    `_resolve_min_trend(block, horizon_key, dir_key, horizon) -> float | None`
    that both functions call. `load_direction_conviction_min_trend` keeps its
    signature, its return values and its raises.

### 2.6 `risk_settings` and `atomic_yaml`: the header

- **No staleness hook.** `save_risk_settings` is unchanged apart from the
  header. Its three `cache_clear()`s are what §2.2 relies on (revision 3
  removed `forget_loads`).
- **Header (9.3B).** A module constant in `risk_settings.py`:
  ```python
  RISK_RULES_HEADER = (
      "# backend/config/risk_rules.yaml\n"
      "# Settings > Risk rewrites this whole file on save and DROPS EVERY COMMENT\n"
      "# except these header lines. Keep notes about these values elsewhere.\n"
  )
  ```
  - `atomic_write_yaml` gains a keyword-only `header: str = ""`. The write
    stays **one call**: `tmp.write_text(header + yaml.dump(data, **dump_kwargs))`.
    `test_atomic_yaml.py:50,79` monkeypatch `Path.write_text` to simulate a
    partial write, so a second write call would make those tests vacuous
    (round-1 finding 6).
  - `header` validation, done **before** the tmp file is created:
    - `""` is allowed, and the output is byte-identical to today's;
    - otherwise the header must end with `"\n"`, contain no `"\r"`, and every
      element of `header.splitlines()` must start with `"#"`;
    - anything else raises `ValueError`.
  - `_save_risk` passes `header=RISK_RULES_HEADER`. The shipped
    `risk_rules.yaml`'s first line (`# backend/config/risk_rules.yaml`) becomes
    those three lines. No other comment is removed by hand; they are lost only
    on the first save, which is the accepted behaviour.
  - `settings.yaml`'s two writers are untouched.
  - **One existing test changes (round-2 finding 4).**
    `test_atomic_yaml.py::test_save_risk_preserves_key_order` (`:213-223`)
    calls `_save_risk` and asserts that the non-blank lines are exactly the
    three keys. With the header there are three `#` lines first. The test
    becomes: the file starts with `RISK_RULES_HEADER`, and the non-blank,
    non-`#` lines are `["zebra", "apple", "mango"]`. That still pins key order.
    It is the only edit to an existing test in this slice. Every other test
    in that file runs unchanged.

### 2.7 PROJECT_STATE

- `DOCC-4-CONFIG-HEALTH`'s probe is today `absent` on `config_health.note_load`
  in `backend/app/services/config_loader.py`, which revision 3 no longer adds.
  The commit that records this revision re-points it to `absent` on
  `config_health.watch` in the same file. The build commit flips it to
  `present` (round-2 below-gate 9).
- `YAML-CONFIG-INTEGRITY`'s probe (`absent` on `config_health` in `main.py`)
  would stay absent forever, since this revision adds nothing to `main.py`. The
  build commit re-points it to DOCC-5's first frontend symbol when DOCC-5 is
  planned. Until then it becomes `absent` on `/api/config/health` in
  `frontend/lib/api.ts`. That is true today and becomes false when DOCC-5
  wires the poll.

## 3. Tests: `backend/tests/test_docc4_config_health.py`

**Isolation.**
- Every test monkeypatches `config_health.CONFIG_DIR` to a `tmp_path` copy of
  the three shipped files, and calls `config_health._reset_for_tests()`, which
  clears the memo **on the singleton**. It keeps the registry, which is filled
  at import. Tests never swap the object, because the loader modules and
  `routers/config.py` hold `from … import config_health` bindings.
- Tests that go through a real loader also monkeypatch that loader's path
  constant to the same `tmp_path` and clear its `lru_cache` in setup and
  teardown.
- An autouse fixture resets the memo and calls `cache_clear()` on every
  registered loader **before and after** every test (round-3 below-gate 10:
  a cache filled by an earlier test module must not decide T1), so order never matters and no cache
  pointing at a `tmp_path` outlives its test.

**Tests.**
- **T1**: shipped files, nothing loaded → `ok: true`; `checked` and
  `not_checked` equal their literals.
- **T2**: the ABA case. Load via `load_scoring_cfg` → clean. Edit a value on
  disk → stale for `load_scoring_cfg`. Load again (a cache hit, still the old
  values) and revert the bytes → clean. Now edit, `cache_clear()`, load (the
  edited values), revert → **stale** (the cache holds the edited values).
  `cache_clear()` → clean.
- **T3**: a cache loaded a broken money block, then the file was fixed → the
  loader is stale, and `errors` is empty.
- **T4**: torn state. `load_scoring_cfg` loads version A, the file changes,
  `stock_scorer._load_config` loads version B → exactly one stale entry,
  naming `load_scoring_cfg`.
- **T5**: section scoping. Load `load_exit_plan_cfg`, then edit `portfolio` on
  disk → clean. Edit `exit_plan` → stale, `path == "exit_plan"`.
- **T6**: a comment-only edit after a load → clean.
- **T7**: an unparseable file (tab-indented) → one error with the line number,
  and every filled loader of that file stale. The scoring-only checks are absent
  from `checked`; the other two files are still checked. An empty file → a
  "not a mapping" error.
- **T8**: `regime_gate` removed → error `path == "regime_gate"`, the **same
  (path, message) pair** `validate_money_blocks` raises on that doc.
  `regime_sizing.min_mult: 2` → an error with `resolve_sizing`'s message.
- **T9**: `regime.intraday.window` removed → an error at that path whose
  `blocks` names Intraday and Analysis only. Swing and Position report
  nothing.
- **T10**: direction_conviction:
  - a misplaced block (under `horizons.swing.vol`) → an error at
    `horizons.swing.vol.direction_conviction`;
  - `bullish_min_trend: 150` → an error at
    `horizons.swing.direction_conviction.bullish_min_trend`;
  - `bulish_min_trend` → an error at `horizons.swing.direction_conviction`,
    and no warning.
- **T11**: `regime_gates:` added → a warning suggesting `regime_gate`.
  `regime_sizng:` in place of `regime_sizing` → an error and a warning. A
  top-level `yes:` key → a warning with `path == "True"` (a string).
- **T12**: horizons:
  - `horizons.swing.trigger.rsi_flor` → a warning suggesting `rsi_floor`;
  - `horizons.positon` → an "unknown horizon" warning;
  - `horizons._defaults` → nothing;
  - `horizons.swing.weights: 0.3` → a warning;
  - the shipped file → no warnings;
  - `HORIZON_KEYS` ⊇ the literal set of consumer-read keys.
- **T13**: `report()` never raises. Patch `money_config.money_block_errors` to
  raise → a "crashed" error, and the money check is absent from `checked`.
- **T13b**: `canonical` (round-2 finding 2):
  - `{"a": 1, True: 2}` encodes, and differs from `{"a": 1, "True": 2}`;
  - `1`, `"1"`, `True` and `1.0` encode four different ways;
  - a `datetime` encodes;
  - `float("nan")` equals itself, and `-0.0` differs from `0.0`;
  - a doc of more than 100 000 nodes (built with shared aliases) raises
    `CanonicalError`;
  - a self-referencing list raises `CanonicalError`.

  Then end to end: a scoring file with a top-level `yes:` key, loaded via
  `load_scoring_cfg` and then fixed on disk → stale for that loader. A cached
  value made self-referencing → a "cannot be compared" stale line, not
  silence.
- **T14**: memo. Two polls on unchanged bytes parse once (spy on
  `yaml.safe_load` inside `config_health`). Changed bytes → re-parsed.
- **T15**: the endpoint. `GET /api/config/health` → 200, and the payload has
  the right keys and types, both clean and with an error.
- **T16**: coverage (round-2 finding 3). The test does not look for file
  names in source.
  - It walks **every** `.py` file under `app/` with `ast` and collects every
    function or method decorated with `lru_cache`, `functools.lru_cache`,
    `cache` or `functools.cache` (bare or called), as `module.qualname`. Any
    other use of those names (for example `lru_cache(maxsize=1)(f)`) fails
    the test with its location.
  - In a fresh interpreter it imports `app.main`, so every loader module
    registers, then reads the registry.
  - Every collected function must be either registered with `watch` or in a
    literal allowlist in the test: `app.config.get_settings`,
    `app.models.heston_cache._run_calibration`,
    `app.data.sector_map._symbol_to_raw_sector`. Each allowlist entry's
    source must not contain `_rules` or `CONFIG_DIR`.
  - The registered names equal the §1.2 table.

  - **Name matching (round-3 below-gate 9):** the AST name is
    `app.<pkg>.<module>.<qualname>`. The registry name is the same with
    `app.<pkg>.` dropped. The test also asserts `fn.__module__ + "." +
    fn.__qualname__` equals the AST name for every registered `fn`.

  So a 16th `lru_cache`/`cache` reader, in any module, fails the test until it
  is either registered or allowlisted by a reviewer. A hand-rolled cache (a
  module dict, a TTL cache such as `strategy_param_store._CACHE`) is **not**
  seen by this test. None reads the three files today, and §4 records the
  limit.
- **T17**: registration. Every registered `fn` has `cache_info` and
  `cache_clear`, and is the object the module exposes under that name (so a
  later re-decoration cannot leave the registry holding a dead wrapper).
  `importlib.reload(config_loader)` → the registry holds the new wrappers, and
  the count is still 15.
- **T18**: Settings save, clean path. Load all eight risk loaders, then `POST
  /settings/risk` → clean.
- **T19**: Settings save, dirty path. Load `load_exit_plan_cfg`, hand-edit
  `exit_plan`, `POST /settings/risk` → still stale at `exit_plan`.
- **T19b**: the save race (round-2 finding 5), deterministic. Load
  `portfolio_risk._load_config` from file version A. Write version B,
  `cache_clear()`. Then store A back into the cache the way a late racing load
  would: point the loader's `CONFIG_PATH` at a copy holding A, call it, and
  point it back at the B file. → stale. Then `cache_clear()` → clean.
- **T20**: `WEB_CONCURRENCY=2` → the permanent multi-worker stale line.
  `not_checked` names the single-worker assumption, and `pid` equals
  `os.getpid()`.
- **T21**: header:
  - after `POST /settings/risk` the file starts with `RISK_RULES_HEADER`
    exactly once, and still exactly once after a second save;
  - it parses to the dict that was saved;
  - the shipped `risk_rules.yaml` begins with `RISK_RULES_HEADER`.
- **T22**: `atomic_write_yaml(header=…)`:
  - a header with no trailing `\n`, one containing `\r`, or one with a non-`#`
    line → `ValueError`, and no tmp file is left;
  - `header=""` gives byte-identical output to today's;
  - the existing `test_atomic_yaml.py` is green, with only
    `test_save_risk_preserves_key_order` edited as §2.6 says;
  - a simulated partial `write_text` with a header still leaves the target
    untouched.
- **T23**: refactor parity. `test_docc1_money_blocks.py`,
  `test_docc2_regime_block.py`, `test_config_loader.py` and
  `test_q3b_config_loader_hardening.py` run **unchanged** and pass. The
  `ConvictionConfigError` raised for each existing direction_conviction case
  has the documented `.path`.

- **T24**: projection parity. For each of the 15 registered loaders, on the
  shipped files, and again on a copy with that loader's section edited:
  `canonical(project(parsed disk doc)) == canonical(fn())` after a
  `cache_clear()`. A projection that drifts from its loader's return
  expression fails here. For the two `AutoTradeService` loaders, it also runs
  on each fallback input (round-3 finding 2): `auto_trade:` null,
  `max_arm_age_minutes: null`, `max_arm_age_minutes: "abc"`, a top-level list
  doc, and an unparseable file (compared with `on_unreadable`). After loading
  on each of these, the report has **no** stale line for that loader.
- **T25**: the `AutoTradeService` fallbacks (round-2 finding 1).
  `risk_rules.yaml` made unparseable → `AutoTradeService._risk_config()` returns `{}`
  → the file is fixed → stale at `auto_trade` for `AutoTradeService._risk_config`.
  Same for `_max_arm_age_minutes` with a fixed file whose value is `45` →
  stale. With a fixed file whose value is `30` → not stale, because the
  process really runs 30.
- **T26**: a loader whose section was removed from disk after it loaded →
  stale (the projection raises).
- **T28**: decoding. A `risk_rules.yaml` value containing `é`, loaded via
  `load_exit_plan_cfg` → clean (health decodes with the loaders' codec).
- **T29**: poll order. Patch the disk read to edit the file just before it
  runs. The loader, filled from the pre-edit file, is reported stale in that
  same poll, never green.
- **T27**: regime scope (below-gate 1). `regime` removed → exactly one error at
  `regime`, `blocks` "stock and options scans, Analysis and every auto-trade fire".
- **T10** also asserts (below-gate 2, 8): the `bullish_min_trend: 150` error
  has `blocks == "Swing Bullish stock and options scans and Analysis"`, and its message
  equals the one `load_direction_conviction_min_trend("Bullish", "Swing")`
  raises on the same doc. The misplaced-block error has
  `blocks == "every stock and options scan, and Analysis"`.

`test_risk_settings.py` and `test_risk_limits_endpoint.py` must pass unchanged.

## 4. Out of scope, and where each item goes

- **The TopBar banner** → DOCC-5, planned after this merges.
- **Recorded in `not_checked`, so the green is honest about them** (§9.11). A
  later slice if Kenneth wants one:
  - value checks for `regime_gate`, `confidence_gate` and `fundamentals_gate`.
    The fire path's `regime_gate` value checks are inline in `auto_trader`
    (`:1176-1290`) and would need extracting;
  - required-presence checks for non-money sections: `horizons.<h>` and its
    keys read without a default, `stock_score_thresholds`,
    `confidence_backtest`, `stop_premium.pass_max_fraction`;
  - `risk_rules.yaml` contents: the `portfolio`, `reward_risk`, `exit_plan`,
    `first_passage`, `reprice_horizon` and `auto_trade` keys indexed without a
    default, including `max_daily_loss_pct`'s `float()`;
  - `contract_rules.yaml` contents.

  Every one of these already fails **loudly** when it is hit: a 500, a
  per-symbol `reason`, or a refused fire. None of them silently changes a
  number. What the health surface loses is advance notice, not safety.
- **`strategy_params.yaml`, `strategy_watches.yaml` and `settings.yaml`** are
  not watched. The decision names three files. These are app-written by their
  own stores and routers.
- **Reload or restart from the app**: §9.2, no reload endpoint.
- **YAML bombs**: `safe_load` does not guard against billion-laughs expansion.
  The files are local and hand-edited, and the memo parses once per content
  change. Below the gate, recorded here.
- **The unwrapped monitor tasks in the lifespan** are untouched.
- **`HORIZON_KEYS` is a snapshot (round-2 below-gate 5).** T12 pins a literal
  set of consumer-read keys taken from the build's grep. A consumer key added
  later is not detected automatically, and until someone adds it to
  `HORIZON_KEYS`, setting it gives a wrong "unknown key" warning (a false red,
  never a false green). Anyone adding a horizon key updates the table in the
  same commit. Extracting the keys with an AST walk is below the gate.
- **Hand-rolled caches.** T16 sees only `lru_cache`/`cache`. A module-dict or
  TTL cache of these three files would not be registered or checked. None
  exists today (round-3 below-gate 9).
- **Frontend copies (round-3 below-gate 15, inherited by DOCC-5).**
  `eventThresholdsStore` and `ivThresholdsStore` fetch scoring_rules values
  once at app start (`routers/config.py:31`, `:58`). After an edit and a
  backend restart, health is green while an open tab still holds the old
  thresholds until it reloads. Also listed in `not_checked`.
- **`uvicorn --workers N` without `WEB_CONCURRENCY`** is not detected (§2.2).
  It is in `not_checked`, and `pid` is in the payload.

## 5. Behaviour changes Kenneth should know about

1. `GET /api/config/health` exists. It is read-only and has no effect on any
   scan, fire or alert.
2. The 15 cached loaders are registered with the health check at import.
   Their bodies, what they return and when they raise are unchanged. A
   health poll calls each **already-filled** cache, which is a cache hit. In
   the rare case that a Settings save clears it at that moment, the poll does
   one real load from disk, exactly as the next scan would.
3. After a Settings → Risk save, `risk_rules.yaml` starts with a three-line
   header saying comments are dropped on save. It is re-written on every save.
4. Health reports "restart" whenever a running cache holds values that differ
   from disk, **including after an edit that was reverted** (the cache kept the
   edited values). It no longer reports "restart" for a file nothing has read
   yet.
5. A hand edit that lands in the middle of a poll can give that one poll a
   stale line that the next poll clears. It cannot give a false green (§2.2
   order).
6. With `WEB_CONCURRENCY > 1`, health always says staleness cannot be judged.
   `uvicorn --workers N` alone is not detected. The payload says so in
   `not_checked` and carries `pid`.
7. The direction_conviction validator raises a `ValueError` subclass carrying
   `.path`. The messages are unchanged.
8. `test_atomic_yaml.py::test_save_risk_preserves_key_order` is edited to skip
   the header lines (§2.6).


## 6. Audit notes for the reviewer

**Gate for this slice.** A finding blocks if it can put a wrong number in front
of a user or on a broker order, or corrupt persisted data (`audit_rule`). On the
health surface, that means:
- **a false "running config matches disk"**: the process runs values that the
  operator cannot see and believes are gone;
- **a check listed in `checked` passing on a file where the same check refuses
  in a scan or fire**;
- **header corruption of `risk_rules.yaml`**.

A refusal that `not_checked` names is **not** a false green. §9.11 decided the
surface names its scope.

**Verify independently:**
- that T16's AST walk really finds every cached function under `app/`;
- that no interleaving of a load, a `cache_clear()` and a poll can make the
  poll compare anything other than the value the cache actually holds (§2.2);
- that each `project` in §2.2 matches its loader's return expression,
  including the `AutoTradeService` fallbacks;
- that `canonical` cannot silently equate two different parsed values, and
  cannot fail silently;
- that every `ValueError` → `ConvictionConfigError` change keeps each existing
  `except` and message.

## 7. Round 1 (2026-09-30): NOT CLEAN, 3 gate-level. Every finding and its resolution

| # | Finding | Resolution |
|---|---|---|
| 1 | GATE: edit then revert → false green against a boot hash; also re-baselined over | §2.2: per-cache judgement replaces the boot snapshot and the re-baseline (records in rev 2, live values in rev 3, §8). T2, T3, T4 |
| 2 | GATE: green while scans refuse on values | §2.3 adds `resolve_sizing` and the direction_conviction value checks (both already existed as scan checks). The rest are listed in `not_checked`, and §6 restates the gate per §9.11 |
| 3 | GATE: missing required non-money sections read green | Listed in `not_checked` and §4. Each already fails loudly. §6 gate per §9.11 |
| 4 | Multi-worker poll can be green from the wrong worker | §2.2 permanent stale line. T20 |
| 5 | Re-baseline race windows | Gone with the baseline (§2.2). T19 |
| 6 | Header must be one `write_text`; validation details | §2.6. T22 |
| 7 | Test isolation mechanics | §2.1 (read globals at call time, module-attribute calls), §3 isolation block, `_reset_for_tests`, autouse reset. The `_RISK_PATH` rule is gone |
| 8 | Path parsed from messages | §2.5 `ConvictionConfigError.path` |
| 9 | `HORIZON_KEYS` grep named the wrong modules | §2.3 grep on `horizons\|_horizon_cfg`. T12 literal set |
| 10 | Regime errors over-report the scope | §2.3 per-horizon `blocks` field. T9 |
| 11 | Re-parse on every poll; lock scope | §2.3 memo by content hash; lock only around dict copies. T14 |
| 12 | Non-string `path` | §2.3 `str()` every key. T11 |
| 13 | Wrong counts (28 → 35 comments; "four" → five uncleared); holder location | §1.3, §1.4 corrected. §2.1 states the deviation |

**Deviation from `DOCC-4-5-SLICING` wording, flagged for Kenneth.** The decision
says "re-hashes … against the boot snapshot (re-baselined when Settings itself
saves)". Round 1 showed that mechanism gives a false green after an
edit-then-revert. The per-cache comparison in §2.2 delivers the decision's intent ("disk
differs from running config -- restart") without that hole. They also remove the
boot snapshot's false positive and the save race. The holder is in a service
module, not `main.py`.

## 8. Round 2 (2026-09-30): NOT CLEAN, 6 gate-level. Every finding and its resolution

Round 2 confirmed that these hold: the 15-reader table, no config read at import
time, every reader of the keys the risk save writes going through a cleared
cache, the `yaml.dump` round trip, the router registration, and the
`ConvictionConfigError` subclassing.

| # | Finding | Resolution |
|---|---|---|
| G1 | `AutoTradeService._risk_config` / `_max_arm_age_minutes` cache a fallback, so `note_load` recorded nothing → green with risk limits off | §2.2: the live cached value is compared with a projection that mirrors the fallback. T25 |
| G2 | The `json.dumps` digest fails on mixed-type keys and alias cycles → silently no record; it also merges `1`/`"1"` | §2.2 `canonical`, type-tagged, sorted by encoding, cycle-checked; failure → a stale line, never silence. T13b |
| G3 | T16 found readers by file name in source → could not catch an unregistered one | §3 T16: AST walk of every cached function under `app/`, registry or literal allowlist |
| G4 | `test_atomic_yaml.py::test_save_risk_preserves_key_order` breaks with the header | §2.6: that one test is edited, and it is stated. T22 |
| G5 | `forget_loads` after `cache_clear()` races a concurrent load → old value cached, record gone | `forget_loads` removed. The poll reads the cache's own value (§2.2). T19b |
| G6 | `--workers N` does not set `WEB_CONCURRENCY` | §2.2 and §5: in `not_checked`, plus `pid` in the payload. T20 |
| B1 | Missing `regime` reported three times with a narrow scope | §2.3: checked once first. T27 |
| B2 | direction_conviction value errors over-report scope | §2.3 per-pair `blocks`. T10 |
| B3 | Import cycle `config_loader` ↔ `config_health` | §2.1: lazy imports in `config_health`; T16 imports `app.main` fresh |
| B4 | T17 tautological | Moot: `forget_loads` is gone. T17 now pins registration identity |
| B5 | T12 key set is a snapshot | §4: recorded as a known limit (false red only) |
| B6 | In-place mutation of cached dicts invisible | §2.2: the live object is compared |
| B7 | `_max_arm_age_minutes` scoped to all of `auto_trade` | §2.2: the projection is the one int |
| B8 | Message casing differs between health and the scans | §2.3: title-case horizon, as the scans pass. T10 |
| B9 | §2.7 stale text; `forget_loads` signature inconsistent | §2.7 rewritten; `forget_loads` gone |

**Flagged for Kenneth (still open).** Decision `DOCC-4-REV2-APPROVED-2026-09-30` approved
"per-cache load records". Revision 3 keeps it per cache, with no boot snapshot,
the holder in `config_health.py` and nothing in `main.py`. But it reads each
cache's **live value** at poll time instead of a digest recorded at load time,
because every round-2 staleness hole (G1, G2, G5, B6, B7) came from judging a
copy. The one new runtime effect: a poll calls filled caches (a hit), and in a
narrow race it does one real load (§5 item 2).

## 9. Round 3 (2026-09-30): NOT CLEAN, 3 gate-level. Every finding and its resolution

Round 3 confirmed that these hold:
- the 15-reader table and the three-entry allowlist (AST walk);
- only the three `risk_settings` caches are ever cleared;
- the header facts and test line numbers;
- the empty `__init__.py` files, so the lazy-import rule is enough;
- live-value soundness under every load, `cache_clear()` and poll
  interleaving.

| # | Finding | Resolution |
|---|---|---|
| G1 | The class is `AutoTradeService`, not `AutoTrader`: `NameError` at import | Renamed everywhere. §2.2 states the name format. T16 checks `__module__`/`__qualname__` |
| G2 | The `AutoTradeService` projections lacked the loader's catch-all `except`: a permanent "restart" a restart cannot clear | §2.2: projections copy the `try`/`except`, `on_unreadable` fallback values, and the rule "stale unless the loader's own code on today's disk gives the same value". T24 fallback inputs |
| G3 | direction_conviction `blocks` left out Analysis (`_analyze_core`, `stock_scan.py:660`) | §2.3 scopes name Analysis. T10 |
| B4 | "every scan" too broad for money/regime (pre-breakout and fib do not read them) | "stock and options scans, Analysis and every auto-trade fire" |
| B5 | Float encoding unspecified (NaN, -0.0) | `("float", repr(x))`. T13b |
| B6 | Health decoding could differ from the loaders' locale codec | §2.3 decodes with `locale.getpreferredencoding(False)`. T28 |
| B7 | Live `canonical` could be exponential on alias-heavy docs | 100 000-node budget → a "cannot be compared" stale line. T13b |
| B8 | Order of the live read and the disk read unspecified | Live values first, disk last. §5 item 5. T29 |
| B9 | T16 claim overstated; name mapping unstated | §3 T16 and §4 narrowed; mapping stated |
| B10 | Autouse reset only after each test | Before and after |
| B11 | T7 revision-2 wording | "every filled loader" |
| B12 | `unknown_top_level_keys` could change the existing log | Returns raw keys; `str()` only in the health warning |
| B13 | Duplicate `watch` undefined | Replace on the same name. T17 reload |
| B14 | Crash results memoised | Never memoised |
| B15 | Frontend threshold copies unrecorded | §4 and `not_checked` |

## 10. Round 4 (2026-09-30): CLEAN, zero gate-level findings. The plan stage is closed

This round ran by decision `DOCC-4-PLAN-CAP-2026-09-30`. It was gated: only a wrong number shown to the user or put on an order, or corrupt persisted data, counted. Its target shrank to revision 4's diff (`83a9855..ab15f87`) and that diff's interactions with the rest of the plan.

It verified each fix against main `96763b2`:
- **G1:** the name is `AutoTradeService` (`auto_trader.py:2202`). The T16 mapping follows `functools`' `__module__`/`__qualname__`.
- **G2:** each `AutoTradeService` projection matches its loader on every fallback input (`auto_trade` null, list or scalar; `max_arm_age_minutes` of `"abc"`, null, NaN or inf; missing, unparseable or undecodable file). Every stale line clears on restart. Every other loader raises, so `RAISES` is correct for them.
- **G3:** the callers of `load_direction_conviction_min_trend` are exactly `stock_scan.py:660` (Analysis), `:1087` and `:1503`, plus `scan.py:1612`. The fire path is correctly left out.
- **B4:** fib-pullback and pre-breakout read no money, regime or conviction check.
- **B8:** read order. A mid-poll edit gives at most one poll's transient line.
- **B6:** the codec matches the loaders.
- **B7:** the shipped docs are 685, 115 and 65 nodes, far under the budget.
- **B5, B12:** the float encoding and raw keys hold.

Next: build revision 4. The code stage gets its own cap of three rounds.
