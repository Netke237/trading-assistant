# ALERT-INDICATOR-ID-MAP — plan

Covers open_questions logged by MACD-EMA-LAG on 2026-10-02: (a) UI-built indicator
conditions never reach the backend dispatch; (b) an empty indicator is not rejected at
save. Kenneth's decisions (2026-10-02, not re-asked): fix both sides; the builder writes
backend names and offers only what the backend computes; the backend maps the four
default chart ids; unrecoverable stored names are surfaced as "unsupported"; empty/unknown
indicators are rejected (builder blocks Save, the API returns 422) without locking users
out of editing or deleting legacy rules.

## What the code actually does today (corrects the logged question)

The logged question says the builder stores the chart **id**. It does not:
`AlertRuleBuilder` renders `<option key={o.value} value={o.label}>`, so the stored
`indicator` is the option **label** `${type}(${Object.values(params).join(',') || 'default'})`:
`EMA(20)`, `EMA(50)`, `VOL(default)`, `RSI(14)`, `MACD(12,26,9)`, `BB(20,2)`, `VWAP(default)`,
`ATR(14)`, `SMA(20)`, `EMA(<n>)` for an edited period, and labels for overlay types
(`MASUITE(9,21,50,200)`, ...). Effects:

- Backend (`compute_indicators_for_conditions`, lowercased match): `ema(20)`, `ema(50)`,
  `ema(9)`, `sma(20)`, `sma(50)`, `rsi(14)`, `atr(14)` already match and fire. `vol(default)`,
  `macd(12,26,9)`, `bb(20,2)`, `vwap(default)`, other periods and overlay labels never fire.
- Browser (intraday rules, `browserJudgesInterval`): `ChartWorkspace.getIndicatorPoints`
  keys series by chart **id**, computed with the chart's *current* params. A label never
  matches, so no label-stored condition fires in the browser. A rule stored with an EMA,
  SMA, RSI, ATR or MACD chart id (`ema-20`, `rsi-14`, `macd-<ts>`) DID fire in the browser
  while that indicator was drawn (`getIndicatorPoints` has no VOL/BB/VWAP branch, so `vol`
  never fired anywhere), at whatever period the
  chart had (`updateIndicator` edits params without changing the id).
- Intraday rules are judged by BOTH sides: `chart_alert_scheduler._tick` evaluates every
  enabled (symbol, interval) pair through `evaluate_and_notify_for_symbol` (intraday
  included), the chart WS does too (`chart.py`, `if not daily_alerts`), and the browser
  judges intraday rules and POSTs history (which notifies). Only the cooldown separates the
  two judges.
- `IndicatorConditionIn` is dead code: `ConditionGroupIn.conditions` is an untyped `list`,
  so nothing validates an indicator condition at POST/PUT.
- The dry-run `POST /alerts/rules/{id}/test` takes indicator series from the caller;
  `api.testAlertRule` has no caller in the frontend. Out of scope (see Non-goals).

Chart ids (`ema-20`, `ema-50`, `rsi-14`, `vol`) may still exist in rules written by an
older builder or by hand; the mapping Kenneth asked for is kept.

## Round log

- Plan r1: 1 blocking, 6 should-fix, 9 nits — all applied (v2): browser no longer judges
  indicator rules (dual-judge), no rewrite on seed, canonical duplicate check, name-only
  validation, total helper, logic-dependent warning, ASCII-only normalisation, plain 422
  text, rollout note.
- Plan r2: 0 blocking, 7 should-fix, 4 nits — all applied (v3): per-condition (multiset)
  grandfathering, edit collision only for collisions the edit introduces, threshold-aware
  warning, split rollout note, scheduler-fire toast regression named, malformed legacy
  rows hardened in `_deserialize_rule` / compute, PUT-divergence residual named, wording.
- Plan r3: 0 blocking, 4 should-fix, 3 nits — all applied (v4): sustain test asserts the
  raw name survives, N_OF_M `need` uses the backend's `or 1`, `vwap` offered on intraday
  only (daily VWAP is an unanchored running total), grandfather map holds seeded
  INDICATOR conditions only, builder keyed per rule, non-string names rendered as
  `(none)`, `activeIndicators` dropped from the alert effect's deps.
- Plan r4: 0 blocking, 2 should-fix, 4 nits — all applied (v5): builder key distinguishes
  edit/duplicate, extra option whenever the stored name is not OFFERED at this interval
  (daily `vwap`), `vol` never fired anywhere, golden-pin gap covered, `need` mirrors `or 1`
  exactly (no clamp), validation keyed on `rule_type != 'composite'`.
- Plan r5: 0 blocking, 1 should-fix, 3 nits — all applied (v6): grandfather map built from
  the id-assigned `conditions` state (id-less legacy rows), extra option / Save block keyed
  on the CURRENT value at the CURRENT interval (chart interval switched while open), toast
  residual and "unchanged" bullet widened/qualified, over-count N_OF_M noted.

## Design

### 1. One vocabulary, two mirrors (backend source of truth)

`backend/app/services/indicator_compute.py`:

- `CANONICAL_INDICATORS`: the names the builder writes —
  `ema9, ema20, ema50, sma20, sma50, rsi, macd, macd_signal, atr, bb_upper, bb_mid,
  bb_lower, vwap, volume, close`.
- `INDICATOR_ALIASES: dict[str, str]` lowercased alias → canonical. Contains every name the
  dispatch accepts today (`ema`, `ema(20)`, `ema(9)`, `ema(50)`, `sma`, `sma(20)`, `sma(50)`,
  `rsi(14)`, `macd_line`, `atr(14)`, `bollinger_upper/lower/mid`, each canonical to itself)
  plus the legacy forms:
  - chart ids (Kenneth): `ema-20→ema20`, `ema-50→ema50`, `rsi-14→rsi`, `vol→volume`;
  - stored builder labels with the backend's own parameters: `vol(default)→volume`,
    `vwap(default)→vwap`, `macd(12,26,9)→macd` (the chart's MACD series was the MACD line,
    `getIndicatorPoints` used `m.macd`), `ema(20)`, `ema(50)`, `ema(9)`, `sma(20)`,
    `sma(50)`, `rsi(14)`, `atr(14)` (already matched).
  - NOT mapped: `bb(20,2)` (which band is unknowable), any other period/params, overlay
    labels, `<type>-<timestamp>` ids, `''`. These are *unsupported*.
- `canonical_indicator(name: object) -> str | None`: non-str → None; any non-ASCII
  character → None (so Python and JS case-folding cannot disagree); else strip ASCII
  whitespace (`' \t\n\r\f\v'`), ASCII-lowercase, look up in `INDICATOR_ALIASES`; unknown → None.
  The TS mirror implements exactly the same steps.
- `compute_indicators_for_conditions` only collects `str` names into `needed` (a `None`,
  list or dict `indicator` on a legacy row raised `AttributeError`/`TypeError` today and
  skipped every rule of the pair); it dispatches on `canonical_indicator(name)` (a `match`
  on the canonical name replaces the alias tuples) and still keys the result by the **raw**
  stored name, because `_evaluate_condition` looks up `indicators.get(condition.indicator)`.
  Behaviour for every name matched today is unchanged (same canonical → same calc; the
  `macd_signal` dispatch stays exact). Stripping is new: `' ema20'` now matches. The
  existing golden pin `test_composite_momentum_match.py` (`_STANDARD_NAMES` sha256) guards
  `ema, ema9, ema50, sma, sma50, rsi, atr, bb_*, vwap, volume, close`; a new test pins
  `ema20 == ema`, `sma20 == sma`, `macd == macd_line` and `macd_signal` equal to today's
  signal output (golden list untouched); the new tests also add the `(n)` forms (`ema(20)`, `ema(9)`, `ema(50)`,
  `sma(20)`, `sma(50)`, `rsi(14)`, `atr(14)`) and `macd_line`, `bollinger_*`.
- `_deserialize_rule` (chart_alerts.py) reads an indicator condition's name with
  `c.get('indicator')`, non-str → `''`, so a legacy row missing the key no longer raises
  `KeyError` inside the list comprehension that builds every rule of the (symbol, interval)
  — today one such row silences all its sibling rules. `operator`/`value` `KeyError`s on
  any condition kind are pre-existing and out of scope.
- `unsupported_indicators(conditions: object) -> list[str]`: TOTAL, never raises. Non-list
  input → `[]`; non-dict / non-object items skipped. The raw names (deduplicated, in order)
  of `kind == 'indicator'` conditions whose `canonical_indicator` is None; a missing or
  non-str `indicator` reports as `''`.

`frontend/lib/alertIndicators.ts` mirrors it: `ALERT_INDICATOR_OPTIONS` (canonical value +
human label such as `EMA 20`, `MACD line (12,26,9)`, in display order), `INDICATOR_ALIASES`
(same object literal, one `'alias': 'canonical',` per line), `canonicalIndicator(name)`,
`indicatorLabel(name)` (catalog label for a supported name, else the raw name),
`unsupportedIndicators(conditions)`.
A backend test (`test_alert_indicator_names.py`) parses the TS file (regex over the literal)
and asserts both alias maps and the canonical/option set are identical — the same
cross-tree pattern as `test_reprice_horizon_agreement.py`.

### 2. Save time — builder (`AlertRuleBuilder`)

- The indicator `<select>` offers `ALERT_INDICATOR_OPTIONS` (fixed, independent of the
  chart's active indicators — a rule must not depend on what is drawn) and writes the
  canonical value. Exception: `vwap` is offered only when the builder's interval is
  intraday — on 1D/1W `_calc_vwap` keeps its unanchored running total (a function of how
  many bars were loaded, per its own docstring), so a new daily VWAP rule is not offered.
  `vwap` stays a supported name on every interval for the API and existing rules (see the
  rollout note). The `useChartStore().activeIndicators` read goes.
- Seeding from `editRule`/`duplicateFrom`: stored names are NOT rewritten. A rewrite on
  a rename-only edit would change `rule_json` (so `replace_rule` wipes `condition_state`,
  i.e. in-progress sustain clocks) and could trip the duplicate check against another rule.
  A condition's name changes only when the user picks a new option. When the condition's
  CURRENT name is not among the options OFFERED at the builder's CURRENT interval (not a
  catalog value at all, or `vwap` on 1D/1W), the select gets one extra option for it,
  value = the raw name:
  - `vwap` on 1D/1W: enabled, label `VWAP (daily, unanchored)`;
  - mappable (`EMA(20)`, `ema-20`, `VOL(default)`): enabled, label
    `"<catalog label> (stored as <raw>)"`;
  - unsupported (`macd-1712345`, `BB(20,2)`): disabled, label `"<raw> — unsupported"`;
  - `''`: no extra option, the existing `Select...` placeholder (value `''`) shows.
  - non-string (`null`, `[]`, missing — malformed legacy rows): rendered as `''` (the
    placeholder shows, no extra option); the condition object itself is left untouched, so
    an unchanged save stays multiset-equal on the server. `indicatorLabel` and the Alerts
    summary render a non-string as `(none)`.
- The Alerts page renders the builder with
  `key={editingRule ? 'edit:' + editingRule.id : duplicatingRule ? 'dup:' + duplicatingRule.id : 'new'}`
  (a duplicate keeps the source rule's id, so the prefix is what separates Edit A from
  Duplicate A), so opening another rule or mode remounts it: the seed state and the grandfather map are always the opened rule's (all builder state
  comes from `useState` initialisers).
- Duplicate detection: `conditionsEqual` (used by the builder's edit collision check and by
  `addRule`) compares indicator conditions by `canonicalIndicator(name) ?? name`, so
  `ema-20 > 100` and `ema20 > 100` are the same condition. Today two such rules can coexist
  (raw comparison). So that this cannot lock a legacy rule out of editing, the builder's
  edit collision check is skipped when the edited conditions are `conditionsEqual` to the
  seeded `editRule` conditions — only a collision the edit itself introduces is refused.
- `handleSave` validation runs AFTER the existing `Name is required` check and before the
  collision check, per indicator condition (numbered by position, 1-based):
  - canonical → OK;
  - `vwap` while the builder's interval is 1D/1W (not offered there) is treated like an
    unsupported name for this check only: allowed when grandfathered, else blocked with
    `Condition N: VWAP is not offered on 1D/1W`. This covers the chart builder, whose
    `interval` follows the live chart (no `editRule`), when the chart is switched to 1D
    after `vwap` was picked;
  - else, **editing** (`editRule`) and the condition is grandfathered: the builder captures
    at mount a `Map<id, rawIndicator>` of the seeded conditions whose `kind === 'indicator'`
    ONLY, built from the `conditions` STATE value (the id-assigned array — the seed step
    gives an id-less stored condition a fresh `makeId()`, so the map must read those same
    ids): `const [seededIndicators] = useState(() => new Map(conditions.filter(...).map(c => [c.id, c.indicator])))`
    declared right after the `conditions` `useState` (the `nOfMThreshold` pattern) (a seeded price/structure/regime row switched to Indicator is not in it, so its
    `''` is blocked); a condition is grandfathered when its `id` is in the map AND its
    current `indicator` is identical to the mapped value → allowed (mirrors the backend PUT exemption); the rule keeps its visible
    warning. Per CONDITION, not per name: on a legacy rule with `''`, a newly added `''`
    condition (fresh id) is blocked. The seeded ids are captured once at mount (the seed
    step already assigns an id to an id-less stored condition, and the kind-switch keeps
    the row id);
  - else → `setError('Condition N: pick an indicator')` for `''`, or
    `'Condition N: indicator "X" is not supported — pick one from the list'`; no save.
  A duplicate is a new rule (POST, no exemption), so nothing is grandfathered there.
- Why grandfather instead of forcing a fix on edit: Kenneth's "the 422 must not lock users
  out of editing". A user can rename / change cooldown / change other conditions of a
  legacy rule without first rebuilding a condition whose meaning is unknowable; the warning
  stays until they replace or remove it. Delete (DELETE) and enable/disable (PATCH
  `{enabled}`, P4a A3) carry no conditions and are never validated.

### 3. API — validation (`routers/chart_alerts.py`)

- Only the indicator NAME is validated; `operator`/`value` stay as unvalidated as today, so
  a legacy row with an odd `value` is not newly locked out. One function,
  `indicator_name_error(v) -> str | None` (plain text: `indicator "X" is not supported;
  use one of: ema9, ema20, ...` / `indicator is empty; pick one`), is used by
  `IndicatorConditionIn`'s `field_validator('indicator')` (raises `ValueError(text)`; the
  model stays otherwise unconstructed, as today, and gets a direct unit test) and to build
  the 422 detail. `unsupported_counts`/`unsupported_indicators` share its predicate
  (`canonical_indicator(...) is None`).
- The check applies to every body with `rule_type != 'composite'` (the router stores any
  other `rule_type` as a standard group), never `== 'standard'`.
- `create_rule` / `replace_rule` read `unsupported_indicators(body.group.conditions)`.
  The 422 `detail` is the plain text for the first offending name (no pydantic banner — it
  lands verbatim in the Alerts page's "Not saved to server: …" line).
- `create_rule` (`rule_type != 'composite'`): after the existing 409 id check (so `syncRules`
  re-POSTing a rule the server already holds still gets 409 → 'ok'), a non-None error →
  `HTTPException(422, detail=...)`.
- `replace_rule` (`rule_type != 'composite'` body): refused with 422 only when the body introduces an
  unsupported occurrence the stored row does not already carry — a MULTISET comparison:
  for some name, its count among the body's unsupported conditions exceeds its count among
  the stored row's (a second `''` on a legacy `''` rule is refused). So the helper used here
  is `unsupported_counts(conditions) -> Counter[str]` (total, same predicate);
  `unsupported_indicators` is its deduplicated key list. The stored set
  is computed totally: composite rows, unparseable `rule_json`, non-dict group → empty set.
  Same exemption shape as `_stored_momentum`. The check runs next to the composite checks,
  BEFORE any `row.*` mutation.
- No change to PATCH or DELETE. Composite rules have no indicator conditions; untouched.
- Residual, named (pre-existing mechanism): `putRuleToAPI` swallows network errors and
  non-2xx. The builder grandfathers against its LOCAL copy, the server against the stored
  row; these diverge only if an earlier PUT already failed silently. Then a grandfathered
  local save can get a 422 nobody sees, and since the browser no longer judges indicator
  rules, only the stale server version is evaluated. Surfacing PUT failures is out of scope
  (it affects every PUT, not just this one).
  `syncRules` re-POSTs local-only rules: a local-only rule holding an unsupported name now
  gets 422 and shows the existing "Not saved to server: <detail>" line (visible).

### 4. Unsupported — the visible mechanism (decision 1, third bullet)

Chosen mechanism: a field on every rule in the API response AND a caution line on the rule
in the Alerts page.

- **API**: `_rule_to_dict` adds `unsupported_indicators: list[str]` to every rule
  (`[]` for composite and for clean rules) — computed on read from `rule_json` with the
  total helper, so a parseable but malformed group yields `[]` rather than a new 500
  (unparseable `rule_json` already 500s at the existing `json.loads`; unchanged), never
  written to the DB. GET /rules, GET /rules/{id}, POST/PUT responses carry it. It is
  for API readers (curl, tests, future clients); the frontend does not type or read it
  (`syncRules` keeps server objects verbatim, so a copy can sit, unread and possibly stale,
  in the persisted store — harmless).
- **UI**: the Alerts page computes the warning from the rule's own conditions with the
  mirror `unsupportedIndicators(...)`, so it is right for local-only and freshly edited
  rules and cannot go stale in the persisted store. Let `ok` = number of conditions that
  are not unsupported indicators and `need` = all conditions for AND, 1 for OR,
  `n_of_m_threshold || 1` for N_OF_M — exactly the backend evaluator's `or 1` (a stored
  legacy 0 becomes 1; a stored legacy negative stays negative, the backend then fires on
  any bar, and `ok >= need` shows the "Never met" variant, which is true). The backend is
  the only judge of these rules. When any condition is
  unsupported:
  - `ok < need`: `Never fires: unsupported indicator <names> — edit the rule to pick one`;
  - else: `Never met: unsupported indicator <names> — the rule fires on its other
    conditions only`.
  `<names>` = each distinct raw name quoted, comma-separated; `''` renders as `(none)`.
  Accepted imprecision: a legacy N_OF_M row whose stored threshold exceeds its condition
  count always shows "Never fires" here — true, though the cause is the threshold too. Tone caution, under the rule name like the unsaved line.
- The conditions summary renders supported names through `indicatorLabel` (`EMA 20 > 100`
  rather than `ema20 > 100`). Backend reason/notification strings keep the raw name
  (unchanged).
- The evaluator still returns "not met" for these (no behaviour change there); the
  silence is replaced by the warning above.

### 5. Browser evaluator (intraday rules) — the backend is the only indicator judge

The backend already judges every enabled intraday pair (scheduler + chart WS). Teaching the
browser the new names would make the label rules that already fire server-side
(`EMA(20)`, `RSI(14)`, ...) fire twice — two history rows, two notifications, separated only
by a racy cooldown — and the two judges compute over different candle windows. So, the
same rule-level pattern as W2-STRUCT's structure skip (`chartAlertEngine.evaluateRules`):
an intraday rule with ANY indicator condition is skipped by the browser and left to the
backend, which pushes `alert_triggered` to the open chart. Rule level, for the same reason
as structure: an OR rule firing in the browser on its price condition would record the
indicator line as unmet.

- `ChartWorkspace` stops building indicator points for alerts: `getIndicatorPoints` (its only
  caller is the alert evaluation) is deleted, `evaluateRules` gets `{}`, and
  `activeIndicators` leaves that effect's dependency list. The engine's
  indicator branch stays (its tests run at `1D`, a path production never takes); a comment
  marks it as reachable only from tests and 1D/1W callers, which today are none.
- Behaviour changes, named:
  - a legacy chart-id rule (`ema-20`) that fired in the browser at the chart's current
    period now fires on the backend at the fixed alias period (EMA 20), whatever the chart
    draws;
  - an intraday rule mixing an indicator with price/regime conditions moves wholly to the
    backend: its regime is judged by the backend's models and its price by the backend's
    candle source, not the chart's `regimeDataRef`/candles;
  - toast/history regression (the same residual W2-STRUCT already accepts): only the chart
    WS path pushes `alert_triggered`; when the scheduler judges the bar first (the intraday
    WS path does not use `_claim_candles_to_evaluate`, so the two race), the fire is
    persisted and notified (Gmail/Telegram) but the open chart shows no toast and the local
    history/`last_triggered_at` are not updated until a reload. This applies to any
    intraday rule with an indicator condition that the browser previously fired: chart-id
    rules, and OR / N_OF_M rules mixing a label indicator with a price or regime condition
    (the browser fired them on the other leg). Not fixed here. A rule that exists only in this browser (never accepted by the
  server — already shown as "Not saved to server") is no longer judged anywhere for its
  indicator conditions; its existing unsaved line already says it is not server-held.

## Rollout note (for the merge record)

Name this in the merge commit / state record so Kenneth can review his rules:
- start firing on EVERY interval (dead until now, thresholds set long ago): label rules
  `VOL(default)`, `MACD(12,26,9)`, `VWAP(default)`; chart-id `vol`; chart-id rules `ema-20`,
  `ema-50`, `rsi-14` on 1D/1W.
- move from browser to backend on intraday and change period semantics: chart-id rules
  `ema-20`, `ema-50`, `rsi-14` (were judged at the chart's current period, now the fixed
  alias period). Other `<type>-<timestamp>` ids that fired in the browser (`macd-<ts>`,
  `sma-<ts>`, ...) are unsupported and STOP firing; they show the warning.
- existing daily (1D/1W) `VWAP(default)` rules fire against an UNANCHORED running-total
  VWAP whose value depends on the loaded window; the builder no longer offers daily VWAP.
- unchanged: indicator-only label rules the backend already matched (`EMA(20)`, `RSI(14)`, `SMA(20)`, ...).
- canonically duplicate pairs (`ema-20 > 100` and `ema20 > 100` on the same symbol and
  interval) now both fire on the same bar: two notifications. The builder's duplicate
  check stops new pairs; existing ones remain until the user deletes one.

## Tests

Backend (pytest). Legacy rows (unsupported names) are seeded by inserting `AlertRuleModel`
directly — POST now refuses them.
- `canonical_indicator`: every alias → canonical; the four chart ids; `VOL(default)`,
  `MACD(12,26,9)`, `VWAP(default)`; case/whitespace; `''`, `None`, `'macd-1712345'`,
  `'BB(20,2)'`, `'EMA(30)'` → None.
- `compute_indicators_for_conditions`: `ema-20`, `rsi-14`, `vol`, `ema-50` produce the same
  series as `ema20`/`rsi`/`volume`/`ema50`, keyed by the raw name; unknown → absent.
- End-to-end evaluator: a stored rule with `indicator: 'ema-20'` fires on the live path
  (`evaluate_and_notify_for_symbol` with a fixture where EMA20 > threshold).
- POST: `''`, `'macd-1712345'`, `'EMA(30)'` → 422; `'ema20'`, `'ema-20'`, `'RSI(14)'` → 201.
  POST of an existing id with a bad indicator → 409 (not 422).
- PUT: legacy row with `'macd-1712345'` → PUT renaming it with the same condition → 200;
  PUT replacing it with `'ema20'` → 200; PUT adding a new `'sma-1712'` → 422; PUT changing
  a clean rule to `''` → 422. PATCH `{enabled}` and DELETE of the legacy row → 200/204.
- `_rule_to_dict` / GET: `unsupported_indicators` lists the raw names; `[]` for clean and
  composite rules; a row with malformed `rule_json` group (non-list conditions, non-dict
  items) → `[]` and GET /rules still 200.
- Malformed legacy rows on a pair with a sibling clean rule (`indicator` key missing;
  `indicator: null`; `indicator: []`): the sibling still fires; GET /rules still 200.
- `IndicatorConditionIn` direct: `''`/unknown raise `ValidationError`; `ema-20` accepted.
- `unsupported_indicators` / `canonical_indicator`: non-ASCII (`'ema２0'`, `'EMA\u212a'`) → None.
- 422 detail is the plain text (no "validation error for" banner).
- Sustain: POST a rule with `EMA(20)` (conditions carrying ids, as the builder sends), set
  its `condition_state` in the DB, PUT the identical body with a new name → `condition_state`
  kept, and GET after the POST and after the PUT both return `indicator == "EMA(20)"`
  verbatim (pins that nothing rewrites the name server-side). Pre-existing, unchanged: a stored
  condition WITHOUT an id gets one at builder seed time, so a rename of such a rule still
  changes `rule_json` and resets sustain.
- POST with `rule_type: "x"` and an unsupported indicator → 422.
- PUT multiset: legacy `''` rule + a second `''` condition → 422; legacy rule PUT with the
  same `''` condition and a new name → 200.
- Parity: the TS mirror equals the backend vocabulary.

Frontend (Jest):
- Builder: options are the fixed catalog; picking writes the canonical value; Save with an
  empty indicator is blocked with the error; editing a rule seeded with `EMA(20)` and only
  renaming it saves `EMA(20)` unchanged (extra option labelled "EMA 20 (stored as EMA(20))");
  editing a legacy `'macd-1712345'` rule shows the disabled unsupported option and saves
  (grandfathered); duplicating it is blocked; no extra option for `''` (placeholder only);
  on a legacy rule holding `''`, adding a second empty indicator condition blocks Save;
  Save with an empty name reports `Name is required` first; on a legacy rule, switching a
  seeded PRICE condition to Indicator without picking blocks Save; `vwap` is offered at
  `5min` and not at `1D`; a seeded `indicator: null` renders the placeholder and an
  unchanged save sends `null` back; opening Edit on rule B while A's builder is open shows
  B's conditions; editing a rule seeded with an id-LESS `macd-1712345` condition and only
  renaming it saves; picking `vwap` at 5min in the chart builder then switching the chart
  to 1D blocks Save; Edit A then Duplicate A remounts (name gets "(copy)"); a 1D rule seeded
  with `vwap` shows the enabled "VWAP (daily, unanchored)" option selected.
- `conditionsEqual`: `ema-20 > 100` equals `ema20 > 100`; `addRule` refuses that duplicate;
  editing rule A (`EMA(20) > 100`) to rename it while rule B (`ema20 > 100`) exists
  SUCCEEDS (the duplicate pre-existed); editing a third rule C (`close > 5`) to
  `ema20 > 100` is refused as a collision.
- `alertIndicators.ts`: `canonicalIndicator` (incl. non-ASCII → null), `indicatorLabel`,
  `unsupportedIndicators` (non-array input → []).
- `chartAlertEngine.evaluateRules`: an intraday rule with an indicator condition is skipped
  (no history), also under OR with a met price condition; a 1D rule path unchanged; an
  intraday price-only rule still fires.
- Alerts page: AND rule with an unsupported indicator → "Never fires…"; OR rule with a
  supported price condition → "Never met…"; OR rule whose conditions are all unsupported →
  "Never fires…"; N_OF_M 2-of-2 with one unsupported → "Never fires…"; N_OF_M 1-of-2 →
  "Never met…"; N_OF_M with a stored threshold 0 and one (only) unsupported condition →
  "Never fires…"; two distinct names both listed; a clean rule shows nothing; summary renders
  `EMA 20 > 100`.
- Existing builder / chartAlertEngine / alerts tests updated where they assumed chart-id
  options.

## Non-goals

- The dry-run endpoint keeps taking caller-computed series (no frontend caller).
- Backend/browser calc parity (EMA seed bar, zero-volume VWAP): moot once the browser no
  longer judges indicator conditions; not changed here.
- No data migration or rewrite of stored rows: mappable names fire through the alias map
  and change only when the user picks a new option; unmappable ones are flagged, never
  guessed.
- No new periods (e.g. EMA(30)) in the backend: the builder offers only what exists.
- `putRuleToAPI` error surfacing stays as is (pre-existing; see §3).
