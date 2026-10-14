# SCREEN-LABELS-19-20 — implementation plan (board item #163)

Status: DRAFT v1, for plan-audit round 1. Branch `board/screen-labels-19-20-b7802f40`.
Cut from `board/screen-labels-19-20-156bd346` at `af780c6d` (discovery only). Audit counters start at zero.
No model, gate, score, or persistence change.

## 0. Decisions already made

Kenneth's untagged comment on #163 ("I agree with your recommendation") answers the question comment of 2026-10-11:

1. **B.** Keep the trailing missing-data sentence. The banner and the tooltip both distinguish **measured** deciding drivers from a **missing** volatility reading. An event-REJECT row with no IV reading still names only the event as the measured driver, and still discloses the missing reading.
2. **A.** Age is input bars. The average is transition strides. Show the stride size only when this response carries the lookback that `compute_omm` actually used (for example `≈5 strides of 20 bars`). No calendar-day conversion. A payload without that size gets no guessed size.

Sources: `.scratch/project-ticket-reconciliation-20261009/issues/19-ui-driver-labels.md` and `20-ui-duration-labels.md`. Reproduction: `docs/superpowers/plans/2026-10-10-screen-labels-19-20-discovery.md`.

## 1. What is wrong, traced to the calculation

### 1.1 Deciding drivers

`gateDrivers` (`frontend/lib/statusTooltips.ts`) is the classifier. Do not change it. For a non-PASS row, `iv` is true when the IV status equals the gate, `event` is true when the event status equals the gate, and `ivMissing` is `iv && !hasIv`.

Proven row: Swing, no IV reading, event in 30 days, reject window 21, caution window 45. Both sides are CAUTION, so the gate is CAUTION, and `gateDrivers` returns `iv`, `event`, and `ivMissing` all true.

The banner (`step-5-vol-events/page.tsx`) builds its cause list from measured drivers only (`iv && !ivMissing`, split by basis, plus `event`). That row contributes only the event. The missing reading is a separate trailing sentence (`missingReadingClause`). The tooltip's `gateDriverPhrase` puts `no volatility reading` in the same "Driven by" list as `event proximity`.

Those are two descriptions of one classifier. The statuses are already the same. Only the words disagree.

An event-REJECT row with no IV reading has `event` true and `iv` false, so `ivMissing` is false. The event is the only deciding driver. The trailing sentence still counts `!hasIv`. Keep that.

Overlap cue: `sum > driven`, where `driven` counts rows with a measured IV driver or an event driver. A missing-only row adds nothing to either side. Do not change this comparison.

### 1.2 Duration

`compute_omm` (`backend/app/services/regime_omm.py`) is unchanged:

- `regime_age_days` is `_regime_age`: consecutive trailing **input bars** in the current label. The field name says days. The value is bars. Every producer copies this field through (`regime.py`, `scan.py`, `stock_scan.py`).
- `avg_regime_duration` is `1 / (1 - p_stay)` after `build_transition_matrix_stride`. One sample is `lookback` bars apart. The unit is **strides**, already rounded to one decimal and capped at 9999. It is not a day count.
- Daily Step 1 passes the request `lookback` (query, `ge=5`, `le=252`, default 20) into `compute_omm`. Intraday passes the literal `26` (fifteen-minute bars per session). Stock-scan and analysis copies do not send that lookback on the payload.

Step 1 prints `Day {age} · avg ~{Math.round(average)} days`. `Math.round` can show 5 when the model returned 5.4. `MarketSentiment` appends `d`. The analysis page says `Day` and `days`. None of those words match the calculation.

## 2. Presentation

### 2.1 Drivers — exact words

Banner cause sentence (`causesSentence`): change only the prefix.

- Before: `Driven by${cue}: …`
- After: `Driven by measured checks${cue}: …`
- `cue` stays ` (a row can have more than one)` when `overlap` is true, else empty.
- `CAUSE_LABEL` values stay. The missing-reading sentence stays, including `MISSING_READING_CLAIM`.

`gateDriverPhrase` non-PASS branch, and nothing else in that function:

- A measured part is `ivNoun` when `iv && !ivMissing`, and `event proximity` when `event`. `ivMissing` is never a measured part.
- If there is at least one measured part, the phrase is `measured checks: ` plus those parts joined with ` and `.
- If there is no measured part, the phrase is `no measured check`.
- If `!hasIv`, append `. Missing volatility reading is not a measured driver` (no extra period; the tooltip caller still adds the final period).
- PASS branches stay byte-for-byte.

So the proven CAUTION row's tooltip tail is:

`Driven by: measured checks: event proximity. Missing volatility reading is not a measured driver.`

Its banner tail still starts `Driven by measured checks: 1 on an event inside this horizon's window.` and still has the existing missing-reading sentence.

The event-REJECT row with no IV reading says `measured checks: event proximity` and the same missing-reading disclosure. It does not say the missing reading decided the REJECT.

A missing-only CAUTION row says `no measured check. Missing volatility reading is not a measured driver.` The banner has no measured-cause sentence and keeps the trailing missing sentence.

### 2.2 Duration — exact words

New `frontend/lib/regimeDuration.ts`:

- `formatRegimeAge(ageBars)` → `${ageBars} bars`
- `formatRegimeAverage(avgStrides, strideBars?)` → the model's one-decimal value, with a trailing `.0` removed, never `Math.round` to an integer. Finite only. `≈5 strides` when `strideBars` is absent, null, or not an integer ≥ 1. `≈5 strides of 20 bars` when `strideBars` is that integer. `≈5.4 strides of 26 bars` stays 5.4.

Do not rename JSON fields. Old saved objects stay valid.

`OmmData` (backend schema and `frontend/types/domain.ts`) gains optional `duration_stride_bars`. `SentimentData` in `domain.ts` gains the same optional field. Absent means "do not invent a size".

`regime.py` sets it from the **same value** passed into that `compute_omm` call:

- daily: the `lookback` argument
- intraday: one module constant used both as `lookback=` and as `duration_stride_bars` (today's 26). Not a second copy of the number.

`sentimentFromRegime` copies `duration_stride_bars` onto the sentiment object when the regime OMM has it. Step 1's own `MarketSentiment` and the Stocks strategy strip (they share that object) then show the size. Scan-built sentiment has no size, so `MarketSentiment`, the position card, and the trade card show `≈N strides` and never `d` or a made-up `of K bars`.

Step 1's three OMM lines and the analysis page's two regime lines use the formatters. Analysis has no stride on its payload, so it shows bars and strides with no size. Do not infer 20, 26, or 50 from the horizon name.

`compute_omm` numbers, `p_stay`, stability, conviction, and gate statuses stay as they are.

## 3. Files

### Edit

- `frontend/lib/statusTooltips.ts` — `gateDriverPhrase` words only
- `frontend/app/(frame)/screener/step-5-vol-events/gateSummary.ts` — `causesSentence` prefix only
- `frontend/lib/regimeDuration.ts` — new
- `frontend/components/molecules/MarketSentiment/index.tsx` — average text. Shared by Step 1, the Stocks strategy strip, the stock position card, and the options trade card. No other behaviour.
- `frontend/types/domain.ts` — optional field and the false `// days` comment on `OmmData.avg_regime_duration`
- `frontend/app/(frame)/screener/step-1-regime/page.tsx` — the three duration lines and the sentiment copy. Do not change the chart, the fetch, or the regime status.
- `frontend/app/(frame)/analysis/page.tsx` — the two duration lines only
- `backend/app/schemas/__init__.py` — optional `duration_stride_bars` on `OmmData`; correct the `in days` comment. Field default `None`, so existing constructors stay valid.
- `backend/app/routers/regime.py` — set the echoed stride as in §2.2
- The tests named in the tasks

### Do not edit

Live claims already touch these. Another session owns them:

- `frontend/lib/api.ts`, `backend/app/routers/stock_scan.py`, `backend/app/schemas/stock_scan.py`, and everything under `frontend/app/(frame)/screener/step-4-prebreakout/` — claim `PREBREAKOUT-PRESENTATION-V2` on `board/prebreakout-presentation-v2-f78dd25f`
- `frontend/components/organisms/CandlestickChart/` — same claim. Step 1 may keep importing it.
- YAML loader and `scripts/state.py` — claim `YAML-DEPTH-BOUND`. This phase does not need them.

`getRegime` returns parsed JSON as `MarketRegime` from `domain.ts`. The new field arrives without an `api.ts` edit. Scan responses gain no stride field, so those screens must not invent one. That is the decision's rule for a payload without provenance, not a leftover to "fix" inside the claimed files.

Also out: `regime_omm.py` (the calculation), scoring, gates, order paths, Pre-Breakout behaviour, backtest maths, and the chart feature.

## 4. Tasks

The two tasks share no files. Run them one after another on this branch. Each task: tests that expect the new words first, run them, see them fail on the current words, then the smallest production change. A test that already passes is a plan defect — stop.

### Task 1 — measured drivers vs missing data

Files: `statusTooltips.ts`, `gateSummary.ts`, `frontend/lib/__tests__/gateDrivers.test.ts`, `frontend/lib/__tests__/statusTooltips.literal.test.ts`, `frontend/app/(frame)/screener/step-5-vol-events/__tests__/gateSummary.test.tsx`, `frontend/app/(frame)/screener/step-5-vol-events/__tests__/literalPins.test.tsx`.

Pins, by equality, not by a regex:

- CAUTION, no IV, event inside the caution window: tooltip contains `Driven by: measured checks: event proximity. Missing volatility reading is not a measured driver.` and does not contain `Driven by: no volatility reading and event proximity`. Banner contains `Driven by measured checks: 1 on an event inside this horizon's window.` and still contains the existing missing-reading sentence.
- REJECT on the event, no IV, IV side not at REJECT: measured text names event proximity only. It still discloses the missing reading. It does not say the missing reading is a measured driver.
- CAUTION from a missing reading only: `Driven by: no measured check. Missing volatility reading is not a measured driver.` Banner has no measured-cause sentence.
- Two measured causes on one row: the overlap cue is still present. A missing-only row beside overlapping measured rows does not remove the cue.
- PASS phrases unchanged, including the Intraday "does not gate on volatility" sentence.

Commit: `fix(step5): distinguish measured drivers from a missing volatility reading`

### Task 2 — regime duration units

Files: `frontend/lib/regimeDuration.ts`, `frontend/lib/__tests__/regimeDuration.test.ts`, `MarketSentiment/index.tsx`, `MarketSentiment.test.tsx`, `domain.ts`, `step-1-regime/page.tsx`, `analysis/page.tsx`, `backend/app/schemas/__init__.py`, `backend/app/routers/regime.py`, `backend/tests/test_regime_direction.py` (add one case; do not weaken the existing direction assertions).

Formatter tests:

- age 40 → `40 bars`. No `Day`, no `days`.
- average 5 with stride 20 → `≈5 strides of 20 bars`. Stride 26 → `of 26 bars`. Stride 50 → `of 50 bars`.
- average 5.4 is not shown as 5.
- omitted, null, 0, or non-integer stride → `≈5 strides` and the text has no `day` and no `of`.
- `MarketSentiment` with the existing fixture and no stride renders `State Bull · sticky 88% · ≈31.5 strides`. With `duration_stride_bars: 20` it renders `≈31.5 strides of 20 bars`. Conviction, alignment, and the empty state stay as they are.

Backend test, Python 3.11, mocked candles, `compute_omm` replaced by a stub that returns age 40 and average 5.0 and records `lookback`:

- `GET /api/regime?lookback=50` → daily `omm.regime_age_days == 40`, `avg_regime_duration == 5.0`, `duration_stride_bars == 50`, and the stub saw `lookback=50`.
- The intraday OMM, when the stub is reached with `lookback=26`, echoes `duration_stride_bars == 26`.
- `p_stay` on the response is the stub's `p_stay`.

Do not change `test_regime_omm.py` expectations. Those pin the calculation.

Commit: `fix(regime): label regime age in bars and duration in strides`

## 5. Checks and audit

After both tasks: `cd frontend && npm run typecheck && npm run test`. Backend, Python 3.11: `cd backend && pytest` because `regime.py` and the schema change. Then `python scripts/state.py`.

`git merge origin/main` immediately before code-audit round 1. Conflicts in `PROJECT_STATE.json` keep both sides' phase records. Any other conflict stops for a new code round if a resolution touches application code.

Plan audit, then these two tickets as sub-issues of #163, then the build, then the code audit on `origin/main..HEAD`. Cap three rounds per stage. Fresh auditor each round. Gate: a wrong number on screen or on an order, or corrupted saved data. A comment blocks only when it states the mechanism wrong.

Self-merge only when `docs/agents/board.md` step 7 all hold. Otherwise `waiting-merge` and stop.

## 6. Acceptance

- The proven CAUTION row's banner and tooltip both treat the event as the measured driver and the missing IV reading as a separate disclosure.
- The event-REJECT row with no IV reading names only the event as measured.
- Age is bars. Average is strides. Stride size appears only when the response echoes the lookback `compute_omm` used.
- No `Day` / `days` / trailing `d` remains on these duration readings.
- `compute_omm` output values and Step 5 statuses are unchanged.
- Typecheck, frontend tests, and backend tests are green. Plan audit and code audit are clean.
