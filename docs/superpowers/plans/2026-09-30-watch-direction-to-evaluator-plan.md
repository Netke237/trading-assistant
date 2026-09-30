# WATCH-DIRECTION-TO-EVALUATOR — plan (r0)

- **Phase:** `WATCH-DIRECTION-TO-EVALUATOR` (PROJECT_STATE.json). Origin: decision
  `WATCH-RULE-BAR-PARITY-Q-I-LEGACY-WATCH-DIRECTION-2026-09-28` ("drop the fallback and log it") and
  COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD plan Q10d; both deferred it, neither owned it.
- **Branch:** `ccr-2fe3aef8-jpt3lz` (reset to `origin/main` at `285d88e`).
- **First step done (phase note):** Kenneth ran the count on his live `backend/config/strategy_watches.yaml`
  on 2026-09-30 — composite watches with `trigger_def.direction` not Bullish/Bearish AND `direction ==
  "Bearish"`: **0**. Kenneth chose to build anyway ("take it"): the fix guards future API/YAML-created
  watches, it changes no live watch today.
- **Scope decision (Kenneth, 2026-09-30, `WATCH-DIRECTION-SCOPE-2026-09-30`):** the watch's direction is the
  fallback for **both** the OMM direction and the strategy-confirmation direction in `evaluate_scheduled`.

## 1. What is true on main (285d88e)

1. `composite_trigger_evaluator.omm_direction(trigger_def)` (`:55-63`): the trigger's `direction` when exactly
   `"Bullish"`/`"Bearish"`, else `"Bullish"`.
2. `evaluate_scheduled` OMM line (`:706`): `compute_omm(closes, direction=omm_direction(td))` — the phase's
   defect marker. `compute_omm` raises `ValueError` on any value other than Bullish/Bearish.
3. `evaluate_scheduled` strategy-confirmation gate (`~:786`): `direction = td.get("direction") or "Bullish"`,
   passed raw to `_check_strategy_signals` (a truthy but malformed value such as `"bearish"` passes through).
4. The watch caller `strategy_watch_evaluator._eval_composite_watch` (`:399`) reads
   `wdir = w.get("direction", "Bullish")` and passes it to `describe_match(direction=wdir)` (the alert text's
   strategy list) and to the event, but **not** to `evaluate_scheduled`. So a watch whose `trigger_def` has no
   direction and whose own direction is Bearish **decides** Bullish (OMM and strategies) but **describes**
   Bearish strategies.
5. The watch's `direction` is validated to Bullish/Bearish on create (`routers/composite_watch.py:50-51`);
   the store default is `"Bullish"` (`strategy_watch_store.py:119`). A hand-edited YAML can hold anything.
6. The rule path (`chart_alerts.py:1227`, `omm_direction(_td)`) has no separate direction — out of scope,
   unchanged.

## 2. Design

1. `omm_direction(trigger_def, fallback=None) -> str`: the trigger's direction when exactly Bullish/Bearish;
   else `fallback` when exactly Bullish/Bearish; else `"Bullish"`. Never raises (non-dict trigger_def,
   non-str fallback → as today). Existing one-argument calls unchanged.
2. `evaluate_scheduled(..., *, fallback_direction: str | None = None)` — keyword-only, default None, so every
   other caller and every test stub is unchanged.
   - OMM line: `compute_omm(..., direction=omm_direction(td, fallback_direction))`.
   - Strategy gate: `direction = td.get("direction") or omm_direction(None, fallback_direction)`, i.e. a
     truthy trigger direction is used **exactly as today** (no normalisation change for existing triggers);
     only a missing/empty/None trigger direction falls back to a valid watch direction, else Bullish.
3. `_eval_composite_watch` passes `fallback_direction=wdir`.
4. Not touched: `describe_match` (already receives `wdir`), momentum (`momentum_match` reads each
   confirmation's own `direction`), the rule path, the frontend.

**Stated consequence.** A trigger whose own direction is present but malformed (e.g. `"bearish"`, `"Neutral"`)
now judges OMM in the watch's direction instead of Bullish (it was never a valid value; the create path writes
exactly Bullish/Bearish or null). The strategy gate keeps passing such a value raw, as today.

## 3. Tests (each with the mutation it must kill)

1. `omm_direction`: trigger Bearish + fallback Bullish → Bearish (trigger wins); trigger None/missing/`""`/
   `"bullish"`/`"Neutral"` + fallback Bearish → Bearish; fallback `None`/`"bearish"`/`"any"`/`5` → Bullish;
   non-dict trigger_def → fallback rule. Mutations: fallback wins over trigger; fallback not validated.
2. `evaluate_scheduled` OMM: a spy on `compute_omm` records `direction` — trigger without direction +
   `fallback_direction="Bearish"` → `"Bearish"`; no fallback → `"Bullish"`; trigger Bullish + fallback Bearish
   → `"Bullish"`; `fallback_direction="bullish"`/`"Neutral"`/`None` → `"Bullish"`, never raises.
   Mutation: ignore `fallback_direction` on the OMM line.
3. `evaluate_scheduled` strategy gate: a spy on `_check_strategy_signals` records `direction` — trigger without
   direction + fallback Bearish → `"Bearish"`; trigger `"Bullish"` + fallback Bearish → `"Bullish"`; trigger
   `"bearish"` (raw, truthy) → `"bearish"` as today. Mutation: fallback overrides a present trigger direction;
   gate ignores the fallback.
4. Watch path: `_eval_composite_watch` on a Bearish watch whose `trigger_def` has no direction → the spy sees
   `fallback_direction="Bearish"`; a Bullish/default watch → `"Bullish"`. Mutation: caller does not pass it.
5. End-to-end OMM decision: a Bearish legacy watch whose OMM conviction clears `conviction_min` only in the
   Bearish reading fires; the same watch judged Bullish does not. Mutation: drop the fallback.
6. Existing suites unchanged: full backend run.

## 4. Ownership

`backend/app/services/composite_trigger_evaluator.py` (`omm_direction`, `evaluate_scheduled` two lines +
signature), `backend/app/services/strategy_watch_evaluator.py` (one call-site argument), one new test file,
PROJECT_STATE.json (phase `verify` switched from the defect marker to a presence probe on
`omm_direction(td, fallback_direction)`), this plan.

## 5. Loop

Plan round → build + mutation checks → code round → state record → merge only with Kenneth's approval.
