# DOCC-4 — backend config-health surface + the risk_rules comment-loss header

Document C, plan 4 of the YAML-CONFIG-INTEGRITY split (§12 of
`2026-09-16-yaml-config-integrity-plan.md`). Written fresh; nothing from that
plan's §3–§8 is carried. Backend only, one layer. The frontend banner is
DOCC-5, planned only after this ships.

**Implements:** decision `DOCC-4-5-SLICING-2026-09-30`, which builds on
`DOCC-9.4-9.5-RATIFIED-RESTAT-2026-09-28` (re-stat on every poll),
`DOCC-9.6-MONEY-BLOCKS-REQUIRED-2026-09-28` (unknown top-level families WARN via
a health line), `DOCC-9.8-CLOSED-MONEY-SUBTREES-2026-09-28` (the horizons tree
is warn-only) and `DOCC-9.3B-D1-ACCEPT-COMMENT-LOSS-2026-09-28` (a header line,
no ruamel.yaml). Payload shape from §9.11 of the old plan (confirmed
2026-09-17): `{ok, checked, errors: [{file, path, message}], stale}`, with
`warnings` added by `DOCC-4-5-SLICING`.

---

## 1. What is true on main `96763b2` (verified by reading the code, not recalled)

### 1.1 Nothing reports the config's state

- No `config_health` symbol exists anywhere under `backend/` or `frontend/`.
- A bad `scoring_rules.yaml` is found only when a scan or a fire runs, as a
  named 500 (DOCC-1/DOCC-2). Nothing surfaces it before then.
- Unknown top-level families are logged at WARNING once per process
  (`money_config._warn_unknown_top_level`). Nobody reads the log.
- Nothing checks the `horizons` tree beyond `direction_conviction`'s
  positional validator (`config_loader._validated_direction_conviction_blocks`).

### 1.2 The files are cached, per reader, lazily

| File | Cached readers (`lru_cache(maxsize=1)`) | Uncached readers |
|---|---|---|
| `scoring_rules.yaml` | `config_loader.load_scoring_cfg`, `stock_scan._load_full_scoring_cfg`, `auto_trader._load_scoring_doc`, `stock_scorer._load_config`, `entry_quality._load_config`, `signal_confidence._cfg` | — |
| `risk_rules.yaml` | `config_loader.load_reward_risk_cfg`, `load_exit_plan_cfg`, `load_reprice_horizon_cfg`, `load_first_passage_cfg`; `portfolio_risk._load_config`; `alert_generator._load_risk_config`; `AutoTrader._max_arm_age_minutes`, `AutoTrader._risk_config` | `regime_monitor._load_risk_config`, `risk_settings._load_risk` |
| `contract_rules.yaml` | `contract_validator._load_config` | — |

Each cache fills the first time it is called, not at boot. So after a hand
edit, some readers can hold the old file and some the new one (Mode A2 of the
old plan). §9.2 still holds: Kenneth restarts after editing. This plan
**detects** a pending edit. It does not reload anything.

### 1.3 The one in-app writer of these three files

`POST /settings/risk` (`routers/risk_settings.py:159`) runs `_load_risk()`,
patches `reward_risk.{premium_stop_pct,target_t1..t3_pct}` and
`portfolio.{…}`, then `_save_risk(cfg)`. That is `atomic_write_yaml`, a full
`yaml.dump`. It then clears three caches: `portfolio_risk._load_config`,
`alert_generator._load_risk_config` and `scan_router._rr_cfg` (which is
`load_reward_risk_cfg`).

- Every reader of the keys it writes goes through one of those three caches
  (grep for `"portfolio"` / `"reward_risk"` over `app/`: `portfolio_risk:68`,
  `config_loader:30`, `alert_generator:31`, `stock_scan:2396` via
  `portfolio_risk._load_config`, and `risk_settings` itself, which is uncached).
  So the save's **own** change reaches every reader.
- The other four cached risk readers (`exit_plan`, `reprice_horizon`,
  `first_passage`, the two `AutoTrader` ones) are **not** cleared. So a hand
  edit to those sections, made before the save, is merged into the file by the
  save and stays invisible to the running process.
- `scoring_rules.yaml` and `contract_rules.yaml` have no in-app writer
  (grep `atomic_write_yaml` over `app/`: only `risk_settings.py` (risk_rules,
  settings) and `notification_settings.py` (settings)).

### 1.4 Comment loss (D1)

`risk_rules.yaml` has 28 comment lines today. `yaml.dump` drops every one on the
first Settings → Risk save. Decision 9.3B: accept that loss and add a header
line. **A header line written only into the file would be erased by the first
save it warns about.** So `_save_risk` has to write the header too.

## 2. What changes

### 2.1 New module `backend/app/services/config_health.py`

This module owns the holder and every check. `main.py` owns only the boot call
(§2.3).

```python
WATCHED_FILES = ("scoring_rules.yaml", "risk_rules.yaml", "contract_rules.yaml")
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"

class ConfigHealth:
    """Boot-time hashes of WATCHED_FILES, plus the checks a poll runs."""
    def capture_boot_baseline(self) -> None
    def rebaseline_after_app_write(self, name: str, pre_write_hash: str | None) -> None
    def file_hash(self, name: str) -> str | None       # sha256 of bytes; None if unreadable
    def report(self) -> dict                           # the endpoint payload

config_health = ConfigHealth()                         # the process-wide holder
```

- **Hashing.** sha256 of the file's bytes. `None` when the file cannot be read.
  The files are small (the largest is `scoring_rules.yaml`, about 20 KB), so
  every poll hashes all three (decision 9.5: re-stat on every poll). There is
  no mtime shortcut: mtime can move without a content change (a `touch`, a
  checkout) and can stay put through one (sub-second edits on some
  filesystems). The hash is the truth, and hashing is cheap enough to always
  do.
- **Baseline.** `{name: hash_or_None}`, taken once in the lifespan. It sits
  behind a `threading.Lock`, because the endpoint runs in the threadpool and
  the Settings save runs on the event loop.

### 2.2 `report()`: the payload

```json
{
  "ok": false,
  "checked": ["scoring_rules.yaml: parses", "scoring_rules.yaml: money blocks",
              "scoring_rules.yaml: regime blocks", "scoring_rules.yaml: direction_conviction",
              "scoring_rules.yaml: top-level families", "scoring_rules.yaml: horizons keys",
              "risk_rules.yaml: parses", "contract_rules.yaml: parses",
              "staleness: scoring_rules.yaml, risk_rules.yaml, contract_rules.yaml"],
  "errors":   [{"file": "scoring_rules.yaml", "path": "regime_gate", "message": "is missing — …"}],
  "warnings": [{"file": "scoring_rules.yaml", "path": "regime_gates", "message": "unknown top-level key, ignored — did you mean 'regime_gate'?"}],
  "stale":    [{"file": "risk_rules.yaml", "path": "", "message": "disk differs from running config -- restart"}]
}
```

- **`ok` is true only when `errors`, `warnings` and `stale` are all empty.** The
  banner (DOCC-5) shows whenever the config is not clean, and a warning is not
  clean: it is a key the operator believes does something and does not. The
  three lists keep the severity. `ok` is only the "anything to show?" bit.
- **`checked` lists what actually ran** (§9.11: never an unscoped green). A
  check that could not run is left out of `checked`. For example, the money
  blocks cannot be checked when the file does not parse. The parse failure is
  the error that says why.
- **Errors, all computed from the file ON DISK, not from the cached copy.** On
  a non-stale file the disk copy and the running copy are the same bytes. On a
  stale file the `stale` line already says "restart", and the errors describe
  what the restart will load. That is what the operator needs to fix before
  restarting. Reading the cached copies instead would mean picking one of six
  caches, and they can disagree (§1.2).
  - Each file: unreadable → error `path: ""`; YAML parse error → error
    `path: ""` with the parser's line/column; parses but not a mapping (for
    example an empty file → `None`) → error `path: ""`.
  - `scoring_rules.yaml` only, when it is a mapping:
    - `money_config.money_block_errors(doc)`. This is a new pure function; see
      §2.4. The pairs are the same ones `MoneyConfigError` carries.
    - `money_config.regime_block_errors(doc, REGIME_HORIZONS)`, already pure.
      Called for all three horizons, because the health check has no request
      horizon.
    - The `direction_conviction` positional validator, run on the disk doc
      (§2.4). A `ValueError` becomes one error whose `path` is taken from the
      message. The message already names the path; `path` is the block's
      dotted path when the validator reports one, else `horizons`.
  - `risk_rules.yaml` and `contract_rules.yaml`: parse + mapping only. No
    validator exists for them today. Writing one is outside this slice (§4).
- **Warnings** (`scoring_rules.yaml` only; they never refuse, and nothing that
  refuses today changes):
  - **Unknown top-level family (9.6).** Every top-level key not in
    `money_config.KNOWN_TOP_LEVEL`, with the `difflib` suggestion. This is the
    same rule as `_warn_unknown_top_level`, factored into a pure
    `unknown_top_level_keys(doc) -> list[(key, hint)]` that both use. The
    once-per-process log stays exactly as it is.
  - **Unknown key in the horizons tree (9.8, warn-only).** A new literal table,
    `HORIZON_KEYS`, in `config_health.py`: the closed spec of
    `horizons.<h>.*`, built from the shipped file's keys **plus every key a
    consumer reads with a default that the shipped file omits** (the build
    greps every `.get("…")` / `["…"]` on variables bound to a horizon block in
    `stock_scorer.py`, `entry_quality.py`, `routers/config.py`, `scan.py`,
    `stock_scan.py`, `config_loader.py` and `signal_confidence.py`, and lists
    the result in the commit message). The walk:
    - Horizon names other than `intraday`/`swing`/`position`: one warning,
      "unknown horizon, never read". **Exception: keys starting with `_`**
      (the `_defaults: &anchor` holder that the direction_conviction docstring
      names as legitimate) are skipped silently. A YAML merge key `<<` has
      already been resolved by the loader, so it never appears.
    - Inside a known horizon: any key not in `HORIZON_KEYS` at any depth → one
      warning each, dotted path, with the `difflib` suggestion among its
      siblings. A leaf where the spec has a subtree (or the reverse) → a
      warning, "expected a mapping" / "expected a value".
    - `direction_conviction` is **not** walked here. Its validator already
      refuses unknown keys in it, so it appears only in `errors`, never twice.
  - The value-level warnings are **not** in this slice. Nothing checks
    types or ranges here (§4).
- **Stale (9.5).** For each watched file, compare `file_hash(name)` with the
  baseline:
  - equal → nothing;
  - different (including readable ↔ unreadable) → `{file, path: "",
    message: "disk differs from running config -- restart"}`;
  - no baseline at all (the lifespan capture did not run or raised) → one
    `stale` line with `file: ""`: "no boot snapshot was taken, so staleness
    cannot be checked -- restart". `staleness` is then left out of `checked`.
    This is loud on purpose: a silent green is the failure this whole phase
    exists to prevent.

  **Known false positive, accepted.** Caches fill lazily (§1.2). A file edited
  after boot but before any reader's first call reads as `stale`, even though
  every cache would load the new file. Restarting resolves it, and restarting
  is the rule anyway (§9.2). The converse, a false green, cannot happen: any
  change to the bytes after boot is reported.
- **`report()` never raises.** Any unexpected exception inside one check is
  caught, becomes an `errors` entry
  `{file, path: "", message: "health check <name> crashed: <exc>"}`, and leaves
  that check out of `checked`. The endpoint must never 500 over the config it
  exists to report on.

### 2.3 `main.py`: the holder's boot call, and the endpoint

- **Lifespan, first statement after the `WEB_CONCURRENCY` check** (before any
  task or scheduler can fill a cache):
  ```python
  try:
      from app.services.config_health import config_health
      config_health.capture_boot_baseline()
  except Exception as _exc:
      logger.warning("config_health boot snapshot failed: %s", _exc)
  ```
  Never refuse boot (the posture, §9 of the old plan). A failed capture reports
  itself through the "no boot snapshot" stale line.
- **Endpoint `GET /api/config/health`** in `routers/config.py`, which already
  carries the `/api/config` prefix and is already registered. It is a sync
  `def` (it does file I/O, so it runs in the threadpool like the file's other
  two handlers) and returns `config_health.report()`. The status is always 200:
  the payload carries the verdict, and a 500 here would make the banner unable
  to say *which* check failed.

### 2.4 Refactors that the checks need (behaviour unchanged at every existing call site)

- `money_config.money_block_errors(doc) -> list[(path, msg)]`: the body of
  `validate_money_blocks` minus the raise and minus the warning log.
  `validate_money_blocks` becomes `_warn_unknown_top_level(doc); errs =
  money_block_errors(doc); if errs: raise MoneyConfigError(errs)`. This is the
  same split DOCC-2 already made for `regime_block_errors` /
  `validate_regime_block`.
- `money_config.unknown_top_level_keys(doc) -> list[(key, hint)]`: pure.
  `_warn_unknown_top_level` uses it and keeps its once-per-process set.
- `config_loader._validated_direction_conviction_blocks(cfg=None)`: `cfg`
  defaults to `load_scoring_cfg()`, exactly as today. The health check passes
  the disk doc. No other change.

### 2.5 `risk_settings`: re-baseline, and the header

- **Re-baseline, only when it is true (§1.3).** In `save_risk_settings`, the
  first statement is `pre = config_health.file_hash("risk_rules.yaml")`, taken
  before `_load_risk()`. After `_save_risk(cfg)` and the three `cache_clear()`s,
  it calls `config_health.rebaseline_after_app_write("risk_rules.yaml", pre)`,
  which:
  - if `pre == baseline["risk_rules.yaml"]` (the file was clean): sets the
    baseline to the new file's hash. The save's own keys are live in every
    reader (§1.3), so "not stale" is true;
  - otherwise (a hand edit was already pending, or there is no baseline): leaves
    the baseline alone, so the file stays `stale` and still says restart. That
    is correct, because the hand edit the save just merged is not live in the
    four uncleared caches.

  Race: a hand edit between `pre` and the write is merged into the save; `pre`
  would still equal the baseline, so the re-baseline would hide it. The window
  is one request on one small file, while Kenneth is clicking Save in the app.
  Accepted and recorded in §5. Closing it would need a lock around the read and
  the write that hand editors cannot take.

  The re-baseline runs only on a **successful** save. A raise from
  `_save_risk` propagates as it does today, and the baseline is untouched.
- **Header (9.3B).** A module constant in `risk_settings.py`:
  ```python
  RISK_RULES_HEADER = (
      "# backend/config/risk_rules.yaml\n"
      "# Settings > Risk rewrites this whole file on save and DROPS EVERY COMMENT\n"
      "# except these header lines. Keep notes about these values elsewhere.\n"
  )
  ```
  `atomic_write_yaml` gains a keyword-only `header: str = ""`, written before
  the dump inside the same tmp file, so the header and the body are installed
  by the same `os.replace`. `_save_risk` passes `header=RISK_RULES_HEADER`. The
  shipped `risk_rules.yaml`'s first line (`# backend/config/risk_rules.yaml`)
  becomes these three lines. **No other comment in the file is removed by
  hand.** They are only lost on the first save, which is the accepted
  behaviour.
  - `header` must end with `\n` and every line must start with `#`.
    `atomic_write_yaml` raises `ValueError` otherwise, **before** creating the
    tmp file. A header that is not a comment would corrupt the YAML it prefixes.
  - `settings.yaml`'s two writers are untouched. They pass no header.

### 2.6 PROJECT_STATE

- New phase `DOCC-4-CONFIG-HEALTH`. Probe: `absent`, pattern
  `capture_boot_baseline`, path `backend/app/main.py`. It pins the boot call,
  which is the one line in `main.py` this slice adds.
- `YAML-CONFIG-INTEGRITY`'s probe (currently `absent` on `config_health` in
  `main.py`) is re-pointed when DOCC-4 is built. It becomes
  `DOCC-5`'s first frontend symbol, or the phase is marked shipped once DOCC-5
  has shipped. The build does this in the same commit that adds the symbol, so
  `state.py` never drifts.

## 3. Tests: `backend/tests/test_docc4_config_health.py`

Every test points `CONFIG_DIR` at a `tmp_path` copy of the three shipped files
(monkeypatched on the module), so no test touches `backend/config/`.

- **T1**: shipped files, baseline captured → `ok: true`, all three lists
  empty, and `checked` contains every entry named in §2.2.
- **T2**: stale. Edit `scoring_rules.yaml` after capture (one value changed,
  still valid) → exactly one `stale` entry for it, `errors` empty, `ok: false`.
  Restore the bytes → clean again. That is the re-stat on every poll.
- **T3**: stale on each of the other two files, independently.
- **T4**: the file deleted after capture → `stale` for that file, **and** an
  `errors` entry (unreadable).
- **T5**: no baseline (a fresh `ConfigHealth()`, capture never called) → the
  "no boot snapshot" line, `staleness` absent from `checked`.
- **T6**: `scoring_rules.yaml` not parseable (a tab-indented line) → one error
  carrying the line number. The money, regime, direction_conviction and
  warnings checks are absent from `checked`. The other two files are still
  checked.
- **T7**: an empty file → error "not a mapping".
- **T8**: `regime_gate` removed → an `errors` entry with
  `path == "regime_gate"`, the **same (path, message) pair** that
  `validate_money_blocks` raises on the same doc. This pins that the health
  check and the scan refuse the same thing.
- **T9**: `regime.swing.window` removed → an error at `regime.swing.window`,
  the same pair `regime_block_errors` gives.
- **T10**: a misplaced `direction_conviction` (under `horizons.swing.vol`) → one
  error naming that path.
- **T11**: `regime_gates:` added → a warning with the suggestion
  `regime_gate`, `errors` empty. And `regime_sizng:` in place of
  `regime_sizing` → an error for the missing block **and** a warning for the
  unknown family.
- **T12**: horizons warnings. `horizons.swing.trigger.rsi_flor` → a warning at
  that path suggesting `rsi_floor`. `horizons.positon` → an "unknown horizon"
  warning. `horizons._defaults` → nothing. `horizons.swing.weights: 0.3` → an
  "expected a mapping" warning. `horizons.swing.direction_conviction.bulish_min_trend`
  → an error only, with no warning.
- **T13**: `HORIZON_KEYS` covers the shipped file. Walking the shipped file
  raises no warnings. This is also part of T1, but it is kept as its own test
  so its failure message names the key.
- **T14**: `report()` never raises. Monkeypatch `money_block_errors` to raise
  → the payload carries a "crashed" error, and the money check is absent from
  `checked`.
- **T15**: endpoint. `GET /api/config/health` → 200 and the payload's shape
  (keys and types), both clean and with an error.
- **T16**: re-baseline, clean path. The file is clean, then `POST
  /settings/risk` → the health check is clean afterwards (not stale).
- **T17**: re-baseline, dirty path. Hand-edit `exit_plan` in
  `risk_rules.yaml`, then `POST /settings/risk` → still `stale` afterwards.
- **T18**: re-baseline, failed save. `atomic_write_yaml` raises → the baseline
  is unchanged.
- **T19**: header. After `POST /settings/risk`, the file starts with
  `RISK_RULES_HEADER` exactly once. After a second save it is still there
  exactly once (the header is not duplicated, because `yaml.safe_load` drops it
  on read and `_save_risk` writes it once). The file still parses to the same
  dict that was saved.
- **T20**: `atomic_write_yaml(header=…)` rejects a header without a trailing
  newline, or with a non-`#` line, and leaves no tmp file. An empty header
  gives byte-identical output to today's. The existing `test_atomic_yaml.py`
  is unchanged and still green.
- **T21**: refactor parity. `validate_money_blocks` raises exactly as before
  on every T2–T9 doc of `test_docc1_money_blocks.py`. That file runs
  unchanged. The once-per-process WARNING (T10 there) still logs once.
- **T22**: the shipped `risk_rules.yaml` begins with `RISK_RULES_HEADER`. This
  pins the file and the constant together.

Plus: `test_risk_settings.py`'s existing tests must pass unchanged. They
monkeypatch `_RISK_PATH`. `config_health`'s own `CONFIG_DIR` points elsewhere
in those tests, so the build makes the re-baseline hash the path that
`_save_risk` actually wrote. **`rebaseline_after_app_write` and the `pre` hash
take the path from `risk_settings._RISK_PATH` only when it equals
`config_health`'s own path for `risk_rules.yaml`. Otherwise both are skipped**,
so a test that redirects `_RISK_PATH` can never move the real baseline.

## 4. Out of scope, and where each item goes

- **The TopBar banner** → DOCC-5, planned after this merges.
- **Validators for `risk_rules.yaml` and `contract_rules.yaml`** (types, ranges,
  required sections). Today there is parse + mapping only. A later slice, if
  Kenneth wants one.
- **Value-level checks in the horizons tree and in the money blocks** (a quoted
  `"-40"`). Logged against main in DOCC-1 §4, and still logged.
- **`strategy_params.yaml`, `strategy_watches.yaml`, `settings.yaml`** are not
  watched. The decision names three files. The first two are owned by stores
  that re-read or write them themselves, and `settings.yaml` is app-written by
  two routers and gitignored. Watching them would report every in-app save as
  "restart".
- **Reload or restart from the app.** §9.2: no reload endpoint.
- **The six-cache tear (Mode A2)** is detected (as stale), not fixed.
- **The unwrapped monitor tasks in the lifespan** (`asyncio.create_task`
  outside `try`, noted in old plan §9) are untouched.

## 5. Behaviour changes Kenneth should know about

1. `GET /api/config/health` exists. It is read-only and has no effect on any
   scan, fire or alert.
2. After a Settings → Risk save, `risk_rules.yaml` starts with a three-line
   header saying comments are dropped on save. It is re-written on every save.
3. If `risk_rules.yaml` was hand-edited and **then** saved from Settings without
   a restart in between, health keeps saying "restart" until he restarts. That
   is correct: parts of the hand edit are not live.
4. Editing any of the three files while the backend runs makes health say
   "restart" until he restarts, even when the edit was made before anything had
   read the file (§2.2, accepted false positive).
5. Race (§2.5): a hand edit landing inside the milliseconds of a Settings save
   can be re-baselined as clean. Accepted.

## 6. Audit notes for the reviewer

- Check §1.2's cache table against `grep -rn "lru_cache" app/` plus the
  three file names. A cached reader missing from the table does not change
  this design (staleness is by hash, not per cache), but a reader of a
  Settings-written key that is **not** among the three cleared caches would
  make the clean-path re-baseline (§2.5) a false green. That is the one thing
  in §1.3 to verify independently.
- Check that `HORIZON_KEYS` is not narrower than what consumers read. A key a
  consumer reads that is missing from it gives a false **warning**, never a
  refusal. That is below the gate, but it is a banner that never clears.
- Check that the refactor in §2.4 leaves every existing call site
  byte-for-byte equivalent in behaviour (T21).
- Check that `report()` cannot raise on any file content, including binary
  garbage, a YAML bomb (PyYAML's `safe_load` is not billion-laughs-safe by
  itself; the files are local and hand-edited, so that is below the gate, but
  record it), or a recursive alias. The `direction_conviction` walker already
  handles cycles (Q3B). The horizons walk recurses only where `HORIZON_KEYS`
  has a subtree, so its depth is bounded by the spec's, and a cycle cannot
  loop it. Confirm that.

Gate: a finding blocks only if it can put a wrong number in front of a user or
on a broker order, or corrupt persisted data. For this slice the gate-level
risks are: a **false green** (health says clean while the running config
differs from disk, or while a scan would refuse), and **header corruption** of
`risk_rules.yaml`.
