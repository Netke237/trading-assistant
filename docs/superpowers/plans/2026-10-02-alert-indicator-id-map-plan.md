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
  keys series by chart **id**, so a label never matches and **no** UI-built indicator
  condition fires in the browser, ever.
- `IndicatorConditionIn` is dead code: `ConditionGroupIn.conditions` is an untyped `list`,
  so nothing validates an indicator condition at POST/PUT.
- The dry-run `POST /alerts/rules/{id}/test` takes indicator series from the caller;
  `api.testAlertRule` has no caller in the frontend. Out of scope (see Non-goals).

Chart ids (`ema-20`, `ema-50`, `rsi-14`, `vol`) may still exist in rules written by an
older builder or by hand; the mapping Kenneth asked for is kept.

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
- `canonical_indicator(name: object) -> str | None`: `name.strip().lower()` looked up in
  `INDICATOR_ALIASES`; non-str or unknown → `None`.
- `compute_indicators_for_conditions` dispatches on `canonical_indicator(name)` (a `match`
  on the canonical name replaces the alias tuples) and still keys the result by the **raw**
  stored name, because `_evaluate_condition` looks up `indicators.get(condition.indicator)`.
  Behaviour for every name matched today is unchanged (same canonical → same calc; the
  `macd_signal` dispatch stays exact). `.strip()` is new: `' ema20'` now matches.
- `unsupported_indicators(conditions) -> list[str]`: the raw names (deduplicated, in order)
  of `kind == 'indicator'` conditions (dicts or objects) whose `canonical_indicator` is None;
  a missing/non-str `indicator` reports as `''`.

`frontend/lib/alertIndicators.ts` mirrors it: `ALERT_INDICATOR_OPTIONS` (canonical value +
human label, in display order), `INDICATOR_ALIASES` (same object literal, one
`'alias': 'canonical',` per line), `canonicalIndicator(name)`, `unsupportedIndicators(rule)`.
A backend test (`test_alert_indicator_names.py`) parses the TS file (regex over the literal)
and asserts both alias maps and the canonical/option set are identical — the same
cross-tree pattern as `test_reprice_horizon_agreement.py`.

### 2. Save time — builder (`AlertRuleBuilder`)

- The indicator `<select>` offers `ALERT_INDICATOR_OPTIONS` (fixed, independent of the
  chart's active indicators — a rule must not depend on what is drawn) and writes the
  canonical value. The `useChartStore().activeIndicators` read goes.
- Seeding from `editRule`/`duplicateFrom`: an indicator that canonicalizes is rewritten to
  its canonical name (`EMA(20)`→`ema20`, `ema-20`→`ema20`), so the select shows it and the
  next save stores the backend name. One that does not stays raw and the select shows it
  as an extra disabled option `"<raw> — unsupported"` (or `"(none)"` for `''`).
- `handleSave` validation, per indicator condition, before the name check passes:
  - canonical → OK;
  - else, **editing** (`editRule`) and the raw name is one the rule being edited already
    carried unsupported → allowed (grandfathered, mirrors the backend PUT exemption); the
    rule keeps its visible "unsupported" warning;
  - else → `setError('Condition N: pick an indicator')` for `''`, or
    `'Condition N: indicator "X" is not supported — pick one from the list'`; no save.
  A duplicate is a new rule (POST, no exemption), so nothing is grandfathered there.
- Why grandfather instead of forcing a fix on edit: Kenneth's "the 422 must not lock users
  out of editing". A user can rename / change cooldown / change other conditions of a
  legacy rule without first rebuilding a condition whose meaning is unknowable; the warning
  stays until they replace or remove it. Delete (DELETE) and enable/disable (PATCH
  `{enabled}`, P4a A3) carry no conditions and are never validated.

### 3. API — validation (`routers/chart_alerts.py`)

- `IndicatorConditionIn` gets a `field_validator('indicator')` that raises
  `ValueError` unless `canonical_indicator(v)` is not None (message names the value and the
  accepted canonical names). It becomes live: a helper `indicator_condition_error(group)`
  runs `IndicatorConditionIn.model_validate(c)` over each `kind == 'indicator'` dict in
  `body.group.conditions` and returns the first error text (non-dict condition → error too).
- `create_rule` (standard rules only): after the existing 409 id check (so `syncRules`
  re-POSTing a rule the server already holds still gets 409 → 'ok'), a non-None error →
  `HTTPException(422, detail=...)`.
- `replace_rule` (standard body): refused with 422 only when the body introduces an
  unsupported name the stored row does not already carry:
  `set(unsupported(body)) - set(unsupported(stored row's conditions))` non-empty. Stored
  composite rows contribute an empty set. Same exemption shape as `_stored_momentum`.
- No change to PATCH or DELETE. Composite rules have no indicator conditions; untouched.
- Known, unchanged: `putRuleToAPI` swallows non-2xx, so a 422 on PUT is invisible in the
  UI. The builder applies the same rule first, so the UI cannot produce that 422.
  `syncRules` re-POSTs local-only rules: a local-only rule holding an unsupported name now
  gets 422 and shows the existing "Not saved to server: <detail>" line (visible).

### 4. Unsupported — the visible mechanism (decision 1, third bullet)

- **API**: `_rule_to_dict` adds `unsupported_indicators: list[str]` to every rule
  (`[]` for composite and for clean rules) — computed on read from `rule_json`, never
  stored. GET /rules, GET /rules/{id}, POST/PUT responses all carry it.
- **UI**: the Alerts page rules table shows, under the rule name, a caution line
  `Never fires: unsupported indicator "<raw>" — edit the rule to pick a supported one`
  (`(none)` for `''`), computed with the frontend mirror `unsupportedIndicators(rule)` so it
  is correct for local-only and freshly edited rules too. `AlertRule` gets the optional
  `unsupported_indicators?: string[]` field (typed, not read by the page).
- The evaluator still returns "not met" for these (no behaviour change there); the
  silence is replaced by the warning above.

### 5. Browser evaluator (intraday rules)

Without this, rules the builder now writes (`ema20`, ...) would still never fire in the
browser, which judges every intraday interval. `ChartWorkspace` replaces
`getIndicatorPoints(candles, activeIndicators)` for alert evaluation with
`alertIndicatorPoints(candles, alertRules)` (in `lib/alertIndicators.ts`): for each indicator
condition name that canonicalizes, compute the series with the frontend calcs at the
backend's parameters (EMA/SMA/RSI/ATR periods, MACD 12/26/9 line or signal, BB 20/2
upper/middle/lower, VWAP, volume, close) keyed by the **raw** name; unsupported names get
no series (not met, as today). `getIndicatorPoints` is deleted if this was its only caller.
Independent of the chart's active indicators, like the backend.

## Tests

Backend (pytest):
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
  composite rules.
- Parity: the TS mirror equals the backend vocabulary.

Frontend (Jest):
- Builder: options are the fixed catalog; picking writes the canonical value; Save with an
  empty indicator is blocked with the error; editing a rule seeded with `EMA(20)` saves
  `ema20`; editing a legacy `'macd-1712345'` rule shows the unsupported option and saves
  (grandfathered); duplicating it is blocked; adding a new unsupported is impossible via the
  select (no option).
- `alertIndicators.ts`: `canonicalIndicator`, `unsupportedIndicators`, `alertIndicatorPoints`
  (keys by raw name; `ema-20` and `ema20` give equal series; unsupported absent).
- Alerts page: a rule with an unsupported indicator shows the warning; a clean one does not.
- Existing builder / chartAlertEngine / alerts tests updated where they assumed chart-id
  options.

## Non-goals

- The dry-run endpoint keeps taking caller-computed series (no frontend caller).
- No data migration of stored rows: mappable names fire through the alias map and are
  rewritten to canonical on the next edit; unmappable ones are flagged, never guessed.
- No new periods (e.g. EMA(30)) in the backend: the builder offers only what exists.
- `putRuleToAPI` error surfacing stays as is (pre-existing; see §3).
