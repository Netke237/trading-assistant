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
  matches, so no label-stored condition fires in the browser. A rule stored with a chart id
  (`ema-20`) DID fire in the browser while that indicator was drawn, at whatever period the
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
- `compute_indicators_for_conditions` dispatches on `canonical_indicator(name)` (a `match`
  on the canonical name replaces the alias tuples) and still keys the result by the **raw**
  stored name, because `_evaluate_condition` looks up `indicators.get(condition.indicator)`.
  Behaviour for every name matched today is unchanged (same canonical → same calc; the
  `macd_signal` dispatch stays exact). `.strip()` is new: `' ema20'` now matches.
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
  canonical value. The `useChartStore().activeIndicators` read goes.
- Seeding from `editRule`/`duplicateFrom`: stored names are NOT rewritten. A rewrite on
  a rename-only edit would change `rule_json` (so `replace_rule` wipes `condition_state`,
  i.e. in-progress sustain clocks) and could trip the duplicate check against another rule.
  A condition's name changes only when the user picks a new option. When the stored raw
  name is not itself a catalog value, the select gets one extra option for it, value = the
  raw name:
  - mappable (`EMA(20)`, `ema-20`, `VOL(default)`): enabled, label
    `"<catalog label> (stored as <raw>)"`;
  - unsupported (`macd-1712345`, `BB(20,2)`): disabled, label `"<raw> — unsupported"`;
  - `''`: no extra option, the existing `Select...` placeholder (value `''`) shows.
- Duplicate detection: `conditionsEqual` (used by the builder's edit collision check and by
  `addRule`) compares indicator conditions by `canonicalIndicator(name) ?? name`, so
  `ema-20 > 100` and `ema20 > 100` are the same condition.
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

- Only the indicator NAME is validated; `operator`/`value` stay as unvalidated as today, so
  a legacy row with an odd `value` is not newly locked out. One function,
  `indicator_name_error(v) -> str | None` (plain text: `indicator "X" is not supported;
  use one of: ema9, ema20, ...` / `indicator is empty; pick one`), is used by:
  - `IndicatorConditionIn`'s `field_validator('indicator')` (raises `ValueError(text)`), so
    the model states the rule (it stays otherwise unused, as today);
  - `unsupported_indicators` above (same predicate: `canonical_indicator(...) is None`).
- `create_rule` / `replace_rule` read `unsupported_indicators(body.group.conditions)`.
  The 422 `detail` is the plain text for the first offending name (no pydantic banner — it
  lands verbatim in the Alerts page's "Not saved to server: …" line).
- `create_rule` (standard rules only): after the existing 409 id check (so `syncRules`
  re-POSTing a rule the server already holds still gets 409 → 'ok'), a non-None error →
  `HTTPException(422, detail=...)`.
- `replace_rule` (standard body): refused with 422 only when the body introduces an
  unsupported name the stored row does not already carry:
  `set(unsupported(body)) - set(unsupported(stored conditions))` non-empty. The stored set
  is computed totally: composite rows, unparseable `rule_json`, non-dict group → empty set.
  Same exemption shape as `_stored_momentum`. The check runs next to the composite checks,
  BEFORE any `row.*` mutation.
- No change to PATCH or DELETE. Composite rules have no indicator conditions; untouched.
- Known, unchanged: `putRuleToAPI` swallows non-2xx, so a 422 on PUT is invisible in the
  UI. The builder applies the same rule first, so the UI cannot produce that 422.
  `syncRules` re-POSTs local-only rules: a local-only rule holding an unsupported name now
  gets 422 and shows the existing "Not saved to server: <detail>" line (visible).

### 4. Unsupported — the visible mechanism (decision 1, third bullet)

Chosen mechanism: a field on every rule in the API response AND a caution line on the rule
in the Alerts page.

- **API**: `_rule_to_dict` adds `unsupported_indicators: list[str]` to every rule
  (`[]` for composite and for clean rules) — computed on read from `rule_json` with the
  total helper (a malformed row yields `[]`, never a 500 that would break `syncRules` for
  every rule), never stored. GET /rules, GET /rules/{id}, POST/PUT responses carry it. It is
  for API readers (curl, tests, future clients); the frontend does not type or read it.
- **UI**: the Alerts page computes the warning from the rule's own conditions with the
  mirror `unsupportedIndicators(...)`, so it is right for local-only and freshly edited
  rules and cannot go stale in the persisted store. Text depends on the logic:
  - `AND`: `Never fires: indicator "<raw>" is not supported — edit the rule to pick one`;
  - `OR` / `N_OF_M`: `Condition never met: indicator "<raw>" is not supported — edit the
    rule to pick one` (the rule can still fire on its other conditions).
  `''` renders as `(none)`. Tone caution, under the rule name like the unsaved line.
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
  caller is the alert evaluation) is deleted and `evaluateRules` gets `{}`.
- Behaviour change, named: a legacy chart-id rule (`ema-20`) that fired in the browser at
  the chart's current period now fires on the backend at the fixed alias period (EMA 20),
  whatever the chart draws. A rule that exists only in this browser (never accepted by the
  server — already shown as "Not saved to server") is no longer judged anywhere for its
  indicator conditions; its existing unsaved line already says it is not server-held.

## Rollout note (for the merge record)

At deploy, stored rules whose names were dead and now map start being judged with
thresholds set long ago: `VOL(default)`, `MACD(12,26,9)`, `VWAP(default)`, `vol`, `ema-20`,
`ema-50`, `rsi-14`, and on intraday nothing new (those label rules already fired
server-side). Name this in the merge commit / state record so Kenneth can review his rules.

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
- `unsupported_indicators` / `canonical_indicator`: non-ASCII (`'ema２0'`, `'EMA\u212a'`) → None.
- 422 detail is the plain text (no "validation error for" banner).
- Sustain: a PUT re-sending a legacy `EMA(20)` rule unchanged except its name keeps
  `condition_state` (pins that nothing rewrites the name server-side).
- Parity: the TS mirror equals the backend vocabulary.

Frontend (Jest):
- Builder: options are the fixed catalog; picking writes the canonical value; Save with an
  empty indicator is blocked with the error; editing a rule seeded with `EMA(20)` and only
  renaming it saves `EMA(20)` unchanged (extra option labelled "EMA 20 (stored as EMA(20))");
  editing a legacy `'macd-1712345'` rule shows the disabled unsupported option and saves
  (grandfathered); duplicating it is blocked; no extra option for `''` (placeholder only).
- `conditionsEqual`: `ema-20 > 100` equals `ema20 > 100`; `addRule` refuses that duplicate;
  editing rule A (`EMA(20) > 100`) to rename it while rule B (`ema20 > 100`) exists is
  refused as a collision — by design, they are the same alert — and a rename of A alone
  (no B) succeeds.
- `alertIndicators.ts`: `canonicalIndicator` (incl. non-ASCII → null), `indicatorLabel`,
  `unsupportedIndicators` (non-array input → []).
- `chartAlertEngine.evaluateRules`: an intraday rule with an indicator condition is skipped
  (no history), also under OR with a met price condition; a 1D rule path unchanged; an
  intraday price-only rule still fires.
- Alerts page: AND rule with an unsupported indicator shows "Never fires…"; OR rule shows
  "Condition never met…"; a clean rule shows nothing; summary renders `EMA 20 > 100`.
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
