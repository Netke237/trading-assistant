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
running cache actually loaded**", compared section by section (§2.2). §7
explains why this is a deliberate deviation from the decision's wording.

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
| risk_rules | `AutoTrader._max_arm_age_minutes` | `auto_trade` (one key) |
| risk_rules | `AutoTrader._risk_config` | `auto_trade` |
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
`first_passage` and the two `AutoTrader` ones) are not cleared. None of them
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
loaders across 7 modules call into it (§2.2) and importing `main` from them
would be circular. `main.py` gains no boot call: the load records replace the
boot snapshot (§7, finding 1). The phase probe therefore pins
`config_health.note_load` in `config_loader.py` (§2.7).

**Module paths are read at call time.** `ConfigHealth` reads the module global
`CONFIG_DIR` inside each method, never in `__init__` or a default argument, so
tests can monkeypatch it. The checks call `money_config.money_block_errors` and
the other validators through their **module attribute**
(`from app.services import money_config` and then
`money_config.money_block_errors(...)`), so T13 can patch them.

### 2.2 Staleness: what the process runs vs what is on disk

**Load records.** Each of the 15 cached loaders in §1.2 calls this
**immediately before its successful `return`**. A loader that raises after
parsing (for example `_load_scoring_doc` on a failed `validate_money_blocks`)
therefore records nothing, just as `lru_cache` caches nothing:

```python
config_health.note_load(file="risk_rules.yaml", loader="config_loader.load_exit_plan_cfg",
                        doc=full, section=("exit_plan",))   # section=() means the whole doc
```

`note_load` stores `{(file, loader): (section, digest)}` under a
`threading.Lock`. `digest` is the sha256 of
`json.dumps(<the subtree at section>, sort_keys=True, default=repr)`, a
canonical form of the **parsed** values. Comment-only and whitespace edits
therefore never read as stale. A missing section digests as the JSON `null`.

- `note_load` **never raises**. A failure inside it is caught and logged once,
  and the loader goes on returning its value exactly as today. The loader's
  own behaviour is unchanged: same file, same parse, same return, same
  exceptions.
- A loader whose parse raises records nothing, and `lru_cache` caches nothing
  either, so there is nothing running to compare.

**The comparison, on every poll (decision 9.5).**
1. Re-read each watched file from disk and parse it.
2. For every load record, digest the same section of the disk doc.
3. Any mismatch → one `stale` entry per (file, section):
   `{file, path: "<section dotted, or empty for whole>", message: "disk differs from running config (<loader names>) -- restart"}`.
   If the disk file does not parse now, every record for that file is stale.

What this catches, where the boot snapshot did not:
- **Edit, then revert (the ABA case, round-1 finding 1).** A cache that loaded
  the edited bytes keeps a digest that the reverted disk no longer matches, so
  it is stale until restart. A scan that cached a **broken** doc, and keeps
  500ing after the file was fixed, shows as stale too, because its digest is
  of the broken values.
- **Torn state.** Two loaders of one file holding different versions: at most
  one of them can match disk, so the other is reported.

What it deliberately does **not** report:
- A file that nothing has loaded yet. Nothing is running it, and the first
  load will read the disk. This removes revision 1's accepted false positive.

**Settings save (§1.3) needs no baseline.** The save:
1. writes the file;
2. clears its three caches;
3. calls `config_health.forget_loads("risk_rules.yaml", loaders=(<the three>))`
   right after the `cache_clear()`s, so their old records go with them.

The five uncleared loaders keep their records, and each compares only its own
section:
- the save does not touch `exit_plan`, `reprice_horizon`, `first_passage` or
  `auto_trade`, so after a normal save they still match and the check is clean;
- a hand edit to one of those sections, pending at save time, keeps that
  loader stale, which is correct;
- a hand edit racing the save is judged the same way, so revision 1's race is
  gone.

**`forget_loads` with the wrong names.** A loader named in `forget_loads` that
has no record is ignored. T17 pins that the three names in `risk_settings`
equal the `loader=` strings in those three functions.

**More than one worker (round-1 finding 4).** When `WEB_CONCURRENCY > 1`,
`report()` adds one permanent `stale` line: "multiple workers: each has its own
caches, so staleness cannot be judged from one of them -- run with --workers
1". `main.py` already logs this setup as unsupported.

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
                  "risk_rules.yaml and contract_rules.yaml contents"],
  "errors":   [{"file": "scoring_rules.yaml", "path": "regime_gate", "message": "is missing — …", "blocks": "every scan, Analysis and every auto-trade fire"}],
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
      `blocks`: "every scan, Analysis and every auto-trade fire".
    - `conviction_sizing.resolve_sizing(doc.get("regime_sizing"))`, catching
      `SizingConfigError` → one error at `regime_sizing` carrying its
      message. This is the same call the stock scan and the fire make, so a
      value they refuse (for example `min_mult: 2`) is red here too.
      Skipped when `money_block_errors` already reported `regime_sizing`.
      `blocks`: "the stock scan and every auto-trade fire".
    - `money_config.regime_block_errors(doc, (h,))` **per horizon**, so each
      error's `blocks` names its scope. The scans and the fire check only the
      requested or armed horizon, and Analysis checks all three. So a broken
      `regime.intraday` gives `blocks: "Analysis, and Intraday scans and
      fires"`, and the banner does not claim that every scan is blocked
      (round-1 finding 10).
    - direction_conviction: `_validated_direction_conviction_blocks(cfg=doc)`
      (positional), then, **when that passes**,
      `direction_conviction_value_errors(cfg=doc)` (new and pure, §2.5) for
      all three horizons × both directions, which is what every scan calls
      today. Errors carry `.path` from the new `ConvictionConfigError`, never
      a path parsed out of the message (§2.5). `blocks`: "both scans".
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
  over the config it reports on.
- **Memoised by content (round-1 finding 11).** Each file's parse and its
  error and warning results are cached against the sha256 of its bytes, and
  re-parsed only when the bytes change. A poll therefore costs three file
  reads, three hashes and the stale-digest comparison. The lock is held only
  while copying the load-record dict and the memo, never across I/O, parsing
  or validation.

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
- `money_config.unknown_top_level_keys(doc) -> list[(str_key, hint)]`: pure.
  `_warn_unknown_top_level` uses it and keeps its once-per-process set.
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

### 2.6 `risk_settings` and `atomic_yaml`: forget, and the header

- **Forget.** After the three `cache_clear()`s, `save_risk_settings` calls
  `config_health.forget_loads("risk_rules.yaml", RISK_SAVE_CLEARED_LOADERS)`.
  The tuple is a module constant naming the three loaders. The call runs only
  after a successful save; if `_save_risk` raises, it is not reached, as the
  `cache_clear()`s are not reached today.
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

### 2.7 PROJECT_STATE

- `DOCC-4-CONFIG-HEALTH`'s probe is re-pointed from `capture_boot_baseline` in
  `main.py` (revision 1, which no longer exists) to `config_health.note_load`
  in `backend/app/services/config_loader.py`, in the same commit that re-points
  it.
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
  clears the load records and the memo **on the singleton**. Tests never swap
  the object, because `routers/config.py` and `risk_settings.py` hold
  `from … import config_health` bindings.
- Tests that go through a real loader also monkeypatch that loader's path
  constant to the same `tmp_path` and clear its `lru_cache` in setup and
  teardown.
- An autouse fixture resets the singleton after every test, so order never
  matters. `test_risk_limits_endpoint.py`, which POSTs to the real file, cannot
  leave records behind for later tests.

**Tests.**
- **T1**: shipped files, nothing loaded → `ok: true`; `checked` and
  `not_checked` equal their literals.
- **T2**: the ABA case. Load via `load_scoring_cfg` → clean. Edit a value on
  disk → stale for `load_scoring_cfg`. Revert the bytes → **still stale** (the
  cache holds the edited values). `cache_clear()` + `forget_loads` → clean.
- **T3**: a cache loaded a broken money block, then the file was fixed → the
  loader is stale, and `errors` is empty.
- **T4**: torn state. `load_scoring_cfg` loads version A, the file changes,
  `stock_scorer._load_config` loads version B → exactly one stale entry,
  naming `load_scoring_cfg`.
- **T5**: section scoping. Load `load_exit_plan_cfg`, then edit `portfolio` on
  disk → clean. Edit `exit_plan` → stale, `path == "exit_plan"`.
- **T6**: a comment-only edit after a load → clean.
- **T7**: an unparseable file (tab-indented) → one error with the line number,
  and every record for that file stale. The scoring-only checks are absent
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
  `note_load` with an unserialisable doc does not raise, and the loader
  returns normally.
- **T14**: memo. Two polls on unchanged bytes parse once (spy on
  `yaml.safe_load` inside `config_health`). Changed bytes → re-parsed.
- **T15**: the endpoint. `GET /api/config/health` → 200, and the payload has
  the right keys and types, both clean and with an error.
- **T16**: coverage. Every `lru_cache` function under `app/` whose source
  names `scoring_rules`, `risk_rules` or `contract_rules` (found through
  `inspect` plus a list of the modules from §1.2) calls
  `config_health.note_load`. The table in §1.2 equals that set. A 16th cached
  reader added later fails this test.
- **T17**: `RISK_SAVE_CLEARED_LOADERS` equals the `loader=` names of the three
  functions `save_risk_settings` clears.
- **T18**: Settings save, clean path. Load all eight risk loaders, then `POST
  /settings/risk` → clean.
- **T19**: Settings save, dirty path. Load `load_exit_plan_cfg`, hand-edit
  `exit_plan`, `POST /settings/risk` → still stale at `exit_plan`.
- **T20**: `WEB_CONCURRENCY=2` → the permanent multi-worker stale line.
- **T21**: header:
  - after `POST /settings/risk` the file starts with `RISK_RULES_HEADER`
    exactly once, and still exactly once after a second save;
  - it parses to the dict that was saved;
  - the shipped `risk_rules.yaml` begins with `RISK_RULES_HEADER`.
- **T22**: `atomic_write_yaml(header=…)`:
  - a header with no trailing `\n`, one containing `\r`, or one with a non-`#`
    line → `ValueError`, and no tmp file is left;
  - `header=""` gives byte-identical output to today's;
  - the existing `test_atomic_yaml.py` is unchanged and green;
  - a simulated partial `write_text` with a header still leaves the target
    untouched.
- **T23**: refactor parity. `test_docc1_money_blocks.py`,
  `test_docc2_regime_block.py`, `test_config_loader.py` and
  `test_q3b_config_loader_hardening.py` run **unchanged** and pass. The
  `ConvictionConfigError` raised for each existing direction_conviction case
  has the documented `.path`.

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

## 5. Behaviour changes Kenneth should know about

1. `GET /api/config/health` exists. It is read-only and has no effect on any
   scan, fire or alert.
2. The 15 cached loaders now also record a digest of what they loaded. What
   they return, and when they raise, is unchanged.
3. After a Settings → Risk save, `risk_rules.yaml` starts with a three-line
   header saying comments are dropped on save. It is re-written on every save.
4. Health reports "restart" whenever a running cache holds values that differ
   from disk, **including after an edit that was reverted** (the cache kept the
   edited values). It no longer reports "restart" for a file nothing has read
   yet.
5. Under `--workers >1`, health always says staleness cannot be judged.
6. The direction_conviction validator raises a `ValueError` subclass carrying
   `.path`. The messages are unchanged.

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
- that T16's set really is every cached reader;
- that `forget_loads` cannot hide a live stale record, meaning a loader it
  forgets was actually cleared;
- that every `ValueError` → `ConvictionConfigError` change keeps each existing
  `except` and message.

## 7. Round 1 (2026-09-30): NOT CLEAN, 3 gate-level. Every finding and its resolution

| # | Finding | Resolution |
|---|---|---|
| 1 | GATE: edit then revert → false green against a boot hash; also re-baselined over | §2.2: load records per cache and per section replace the boot snapshot and the re-baseline. T2, T3, T4 |
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
edit-then-revert. The load records in §2.2 deliver the decision's intent ("disk
differs from running config -- restart") without that hole. They also remove the
boot snapshot's false positive and the save race. The holder is in a service
module, not `main.py`.
