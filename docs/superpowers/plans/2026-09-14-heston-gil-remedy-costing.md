# Heston calibration under scan concurrency: costing the three remedies

**Date** 2026-09-14
**Probe** `backend/scripts/heston_remedy_probe.py` (new; the diagnosis probe
`backend/scripts/heston_latency_probe.py` is unchanged and still the source of
the shared reference chain)
**Box** 4 cores, 2.1GHz Xeon, CPython 3.11.15, GIL enabled
**Status** MEASUREMENT ONLY. Nothing in `app/` is touched by this work. The
prototype that section 5 measures lives in the probe and is wired into nothing.

---

## 0. What this is, and what it is not

`TIMEOUT-DELETE-INNER-2026-09-13` deleted `heston_cache`'s inner 1.0s timeout
and, in doing so, measured why that changed nothing visible: calibration is
GIL-bound, `scan.py`'s `_HESTON_EXECUTOR` is a *thread* pool, and all 40
symbols of a realistic scan slice are abandoned at the 2.0s outer guard. That
finding is logged against main. It names three fix directions and says of all
three: **"none costed yet"**.

This document costs them. It decides nothing — every direction here is
Kenneth's call — but it replaces three arguments with three numbers.

It does **not** establish that any of this is worth doing. Section 8 lists what
is still open, including the one thing that would make the whole feature moot.

---

## 1. The precondition the open question raised — SETTLED, and the answer is no

The open question ends: *"WHAT KENNETH MUST CHECK FIRST, because it can
invalidate all of the above: the runtime. `scan.py`'s comments claim 3.14; the
venv measured here is 3.11. On a FREE-THREADED build (`sys._is_gil_enabled()`
False) the thread pool would parallelise and the picture changes completely."*

Checked, three independent ways, and it is not just this venv:

- `backend/.venv/bin/python` is **CPython 3.11.15**, and `sys._is_gil_enabled`
  **does not exist** on it. That attribute was added in 3.13, so its absence is
  *proof* of a GIL-enabled build rather than an inconclusive reading.
- `backend/Dockerfile` is `FROM python:3.11-slim`.
- `.github/workflows/ci.yml` pins `python-version: 3.11`.

So 3.11 is what runs in development, in the container and in CI. There is no
free-threaded escape hatch anywhere, and the three directions all stand.

`scan.py`'s comment at `_HESTON_SEMAPHORE` — "raises RuntimeError on Python
<=3.12; this project's runtime (3.14) tolerates it" — is therefore wrong, and
the version-specific relaxation it leans on does not hold on any interpreter
this project runs. Not fixed here (it is a comment, and production runs one
long-lived loop so the behaviour it describes is unreachable) — logged against
main instead.

---

## 2. The diagnosis, reproduced

`heston_latency_probe.py`, unmodified, on this box:

| measurement | recorded against main | this run |
|---|---|---|
| solo calibration, 45 shapes | — | median 0.548s, max 1.497s |
| 2 threads | 2.48–2.58x | **2.70x** |
| 4 threads | 5.43–5.54x | **5.46x** |
| 8 threads | 10.57–11.34x | **11.27x** |
| 40-symbol slice, 2.0s guard | 40/40 abandoned | **40/40 abandoned**, median 2.049s |

The finding reproduces. Nothing below rests on the earlier numbers.

---

## 3. Direction (a) — a process pool

Same 8 identical-shape jobs through a thread pool and a `spawn` process pool.
"1.00x" is perfect parallelism against one un-pooled call (0.481s); "N.00x" is
full serialisation.

| workers | threads | processes |
|---|---|---|
| 2 | 1.275s — 2.65x | 0.569s — **1.18x** |
| 4 | 2.739s — 5.69x | 0.588s — **1.22x** |
| 8 | 5.404s — 11.22x | 1.266s — **2.63x** |

**It works.** Four concurrent calibrations cost 1.22x one calibration instead
of 5.69x — the GIL is the whole of the thread pool's problem, and processes
remove it. Eight workers on four cores cost 2.63x against an ideal 2.00x
(eight jobs, four cores), i.e. a 32% oversubscription penalty and still 4.3x
better than eight threads.

Costs measured alongside it, neither fatal:

- **Pool warmup** 1.2s / 1.5s / 3.0s for 2 / 4 / 8 workers — every spawned
  worker importing scipy. Paid once at process start, not per scan, so it is
  excluded from the timings above and reported separately.
- **Pickling** `CalibrationResult` and `HestonParams` are plain dataclasses and
  round-trip unchanged; the chain is a `list[dict]` of floats. Verified, not
  assumed.

Two things (a) does *not* fix, both of which matter:

1. `_run_calibration`'s `lru_cache` becomes **per worker**, so a cache that
   already "rarely helps" (slowness investigation, finding #6) helps 1/N as
   often.
2. It buys a **4x throughput ceiling on a 4-core box** and nothing more. Section
   6 shows what 4x is and is not enough for.

---

## 4. Direction (b) — serialise deliberately

`_HESTON_CONCURRENCY = 1`. There is no measurement to make beyond section 6's
row: with one worker a calibration costs its solo time (0.15–1.50s) instead of
5.5x it, so the symbols that *do* get a worker are priced honestly, and the
rest queue behind them at roughly 0.55s each. On a 40-symbol slice the 40th
symbol is ~22s behind the first, so the guard discards it either way.

(b) is not a remedy on its own. It is only interesting combined with (c), where
it appears in section 6 as a row.

---

## 5. Direction (c) — a cheaper pricer

Measured through a prototype in the probe (`_vec_prices`, `_calibrate_vec`),
**not a merge candidate**. It changes two things and nothing else:

1. **A composite Gauss-Legendre rule** instead of scipy's adaptive QUADPACK, so
   the nodes are known in advance and the integrand is one numpy array op
   instead of a few hundred Python callbacks.
2. **The characteristic function is computed once per (expiry, parameter set)
   and reused across every strike.** This is the actual headroom.
   `_heston_char_fn` folds the strike in as the single factor
   `exp(i·φ·ln(S/K))` — the complex sqrt, the two logs and the exp all depend
   only on φ, T and the five parameters. The shipped code recomputes every one
   of them per strike, so a 40-strike chain does 40x the work it needs to.

Everything else is held identical: same adaptive cutoff `upper`, same
`0.5 + p/π`, same `S·P1 − K·e^{−rT}·P2`, same put-call parity tail, same
`max(price, 0)` clamp, same solved `v0` seed, same two-rung grid, same
relative-RMSE objective, same flat-BS baseline gate, same three labels.

### 5.1 Accuracy first

Deviation from the shipped `heston_price` over 48 parameter sets (the 16
shipped grid combinations x three `v0` seeds) x 10 expiries x a 13-rung
moneyness ladder:

| panels | nodes | max abs $ | max rel | worst at |
|---|---|---|---|---|
| 4 | 96 | 27.341209 | 2.73e+03 | T=1e-6 |
| 16 | 384 | 17.121687 | 1.71e+03 | T=1e-6 |
| 64 | 1536 | 0.002704 | 2.70e-01 | T=1e-6 |
| **adaptive** | varies | **0.000114** | **1.14e-02** | T=1e-6 |

### 5.2 The node count cannot be fixed — and that is the finding of this section

Every one of those worst cases is at **T = 1e-6 years**, and a fixed rule is
catastrophic there. The reason is structural: the integrand carries the strike
as `exp(i·φ·ln(S/K))`, so its phase runs to `upper · max|ln(S/K)|` — about 110
radians (18 oscillations) on any expiry a real chain carries, and about 4500
radians (**710 oscillations**) at T=1e-6. No fixed node budget spans both.

**That regime is reachable and it lands on a card.** The chain, verified end to
end: `trade_plan.py:119` computes `reprice_years = display_reprice_years(...)`
and passes it to `estimate_rr` / `estimate_targets`, which set
`dte_at_target = reprice_years` and call `heston_price(..., dte_at_target, ...)`
for the exit premium (`reward_risk.py:131`, `:222`).
`display_reprice_years` is `remaining_years_at_barrier(dte,
resolve_reprice_days(...))`, whose `floor_years` default is **`1e-6`** — not
the `7/365` that `_default_reprice_years` floors at, which applies only when no
`reprice_years` is supplied. So whenever the resolved holding horizon reaches
expiry, T is `1e-6`, and a fixed 512-node rule would put a **$0.24 error into
the exit premium** — the numerator of `rr_ratio` on a card that reads "Heston
repriced". Any real version of direction (c) must
scale its rule with the oscillation count. The probe's rule does:

| T (years) | DTE | nodes | max abs $ | max rel |
|---|---|---|---|---|
| 1.000e-06 | 0.0004 | 8544 | 0.000114 | 1.14e-02 |
| 6.850e-04 | 0.2500 | 1152 | 0.000000 | 1.03e-05 |
| 2.740e-03 | 1.0000 | 576 | 0.000000 | 6.74e-10 |
| 1.918e-02 | 7 | 240 | 0.000000 | 7.65e-11 |
| 5.753e-02 | 21 | 216 | 0.000000 | 1.44e-09 |
| 8.219e-02 | 30 | 216 | 0.000000 | 4.39e-11 |
| 1.233e-01 | 45 | 216 | 0.000000 | 6.21e-10 |
| 2.466e-01 | 90 | 216 | 0.000000 | 4.15e-07 |
| 4.932e-01 | 180 | 216 | 0.000014 | 7.42e-07 |
| 1.000e+00 | 365 | 216 | 0.001249 | 4.73e-05 |

Two residuals to hold against it rather than wave past:

- **T=1e-6 is still $0.000114 out.** The shipped pricer is not a clean
  reference there — it emits `IntegrationWarning: maximum number of
  subdivisions (200) has been achieved` on those cells, and `heston.py`'s own
  cutoff comment concedes the 20000 cap is "NOT sufficient below about T=1e-5".
  So at that one expiry the table compares two under-integrated answers, and
  F1's separate measurement of the shipped one against a high-accuracy
  reference (worst $0.00042) is the number that bounds the real error.
- **365 DTE is $0.001249 out**, worse than the 3.5e-9 a fixed 512-node rule
  reached there, because the adaptive rule spends only 216 nodes on it. An
  eighth of a cent on a $26 option, and halving the panel width would close it
  — but it is a residual the shipped adaptive quadrature does not have, and a
  merge candidate would need to justify it rather than inherit it from here.

### 5.3 Speed

Whole calibration, grid search plus baseline gate, shipped vs prototype:

| DTE | strikes | shipped | prototype | speedup |
|---|---|---|---|---|
| 30 | 15 | 0.267s | 0.067s | 4.0x |
| 45 | 25 | 0.451s | 0.104s | 4.3x |
| 180 | 40 | 0.895s | 0.182s | 4.9x |
| 365 | 40 | 0.967s | 0.184s | 5.3x |

Labels and rel-RMSE agree on every one of the 15 shapes measured, to four
decimal places.

### 5.4 What becomes the bottleneck next — and it is not the pricer

Once the grid search is vectorised, it stops being the cost:

| DTE | strikes | grid | baseline | seed | total | baseline share |
|---|---|---|---|---|---|---|
| 30 | 40 | 0.012s | 0.143s | 0.028s | 0.183s | **78%** |
| 180 | 40 | 0.004s | 0.146s | 0.027s | 0.177s | **83%** |
| 365 | 40 | 0.015s | 0.150s | 0.032s | 0.197s | **76%** |

`_flat_bs_baseline` — 47 volatility evaluations x every strike, each two
`scipy.stats.norm.cdf` calls — is now 65–83% of the remaining time. It
vectorises trivially, over the same array, and it comes out **bit-identical**.
The speedup scales with chain width, because the vectorised version costs the
same at any width (**55x at 15 strikes, 95–100x at 25, 136–180x at 40**); the
40-strike rows are shown:

| DTE | strikes | shipped | vectorised | speedup | Δσ | Δrel-RMSE |
|---|---|---|---|---|---|---|
| 30 | 40 | 0.1362s | 0.0010s | 136x | 0 | 5.6e-17 |
| 180 | 40 | 0.1581s | 0.0010s | 157x | 0 | 1.1e-16 |
| 365 | 40 | 0.1853s | 0.0010s | **180x** | 0 | 0 |

**But the gate's 136–180x is on the *function*, not on a calibration**, and the
distinction decides the sequencing. Against the *shipped* pricer the grid
search still dominates, so vectorising the gate alone barely moves the total:

| DTE | strikes | shipped | step 1 only | speedup |
|---|---|---|---|---|
| 30 | 40 | 0.773s | 0.619s | 1.25x |
| 45 | 40 | 0.718s | 0.615s | 1.17x |
| 180 | 40 | 0.898s | 0.752s | 1.19x |
| 365 | 40 | 1.008s | 0.883s | 1.14x |

**1.03–1.25x across all 12 shapes**, labels and rel-RMSE unchanged. That is why
section 6's gate-only row is 4–6/40 rather than anything better: the gate is
65–83% of what is left *after* the pricer is vectorised, and only then.

With both halves vectorised, against the shipped calibration:

| DTE | strikes | shipped | both | speedup |
|---|---|---|---|---|
| 30 | 40 | 0.773s | 0.033s | **23.5x** |
| 45 | 40 | 0.789s | 0.034s | 23.3x |
| 180 | 40 | 0.930s | 0.043s | 21.8x |
| 365 | 40 | 0.981s | 0.042s | 23.3x |

Labels and rel-RMSE agree on all 12 shapes. **~20x, not ~5x** — and the cheap
half of that (the gate) is the half that is bit-identical and the smaller
change.

What is left after both is `_seed_v0`: a bracketed `brentq` per strike,
0.010–0.032s, now the majority of a 0.033s calibration. It is the next floor
and is deliberately untouched here.

---

## 6. The same 40-symbol slice under every arrangement

One slice of 40 symbols, built once and reused, driven through the same
harness `scan.py` uses — fetch stagger under `_SCAN_CONCURRENCY`, the fetch
semaphore released *before* the calibration block (as `_process_symbol` does),
`asyncio.wait` with the real 2.0s guard, no cancellation on timeout.
"priced" counts symbols returning `heston_grid` inside the guard, which is the
only label `scan.py` accepts and so the only one that reaches a card.

| arrangement | wall | median wait | max | priced, 4 runs | coverage |
|---|---|---|---|---|---|
| **threads x5 (TODAY)** | 4.8–4.9s | 2.00–2.01s | 2.04–2.05s | **0 / 0 / 0 / 0** of 40 | **0%** |
| (b) serialised, threads x1 | 4.8s | 2.01s | 2.01–2.04s | 4 / 4 / 4 / 4 | 10% |
| (a) processes x4 | 4.7s | 1.64–1.73s | 2.00s | 22 / 22 / 22 / 22 | 55% |
| (a) processes x5 | 4.7s | 1.77–1.94s | 2.00–2.01s | 24 / 22 / 22 / 23 | 55–60% |
| (c) **step 1 only** — gate | 4.8–4.9s | 2.01–2.02s | 2.05–2.10s | 5 / 4 / 6 / 5 | 10–15% |
| (c) **step 2 only** — pricer | 4.7s | 2.00s | 2.01–2.02s | 8 / 8 / 8 / 8 | 20% |
| **(c) BOTH, threads x5** | **2.7s** | **0.04–0.08s** | **0.21–0.30s** | **40 / 40 / 40 / 40** | **100%** |
| (c)+(b) prototype, threads x1 | 4.5–4.7s | 1.12–1.43s | 1.85–2.01s | 40 / 40 / 32 / 34 | 80–100% |
| (c)+(a) prototype, processes x4 | 2.8s | 0.11–0.12s | 0.20–0.23s | 40 / 40 / 40 / 40 | 100% |

Four runs, because a single run cannot separate these rows: the marginal
arrangements move by up to 8 of 40 between runs — `(c)+(b)` came out 40, 40,
32 and 34 — while the two that decide the question do not move at all.
**0/40 today** and **40/40 for (c) with both halves** are identical on every
run, so every "this beats that" claim below survives the spread rather than
resting on one draw.

Four things this table says that the individual measurements do not:

1. **Neither half of direction (c) is a remedy on its own.** The gate alone is
   4–6/40 and the pricer alone 8/40 — because whichever half is left unchanged
   is still scalar Python and still GIL-serialised, so it simply becomes the
   new bottleneck. Only the **pair** reaches 40/40. Shipping either half by
   itself would read in production as a fix that did not work.
2. **(c) done fully needs neither (a) nor (b).** 40/40 at a 0.04–0.08s median
   and a 0.21–0.30s worst case leaves a 25–50x margin against the 2.0s guard —
   on the thread pool that exists today, with no process pool, no
   serialisation, and no change to `_HESTON_CONCURRENCY` or
   `_HESTON_CALIBRATION_TIMEOUT_S`.
3. **With (c) in, (a) becomes a net cost.** `(c)+(a)` has a 0.11–0.12s median
   against `(c)`'s 0.04–0.08s, on every run: once a calibration is ~0.03s, the
   IPC round trip is the larger number. A process pool is the right answer to
   the problem as it stands and the wrong answer to the problem (c) leaves
   behind.
4. **(a) alone caps at ~55%**, which is what a 4x throughput ceiling buys
   against this arrival rate. It is a real improvement over 0% and it does not
   get to 100% by adding workers — `processes x5` is 24/22/22/23 against x4's
   22/22/22/22, inside the noise.

Two asymmetries in the harness, stated because the first one flatters the
prototype and neither is large enough to change a row:

- The shipped rows go through `calibrate_cached`'s key construction
  (`json.dumps` + md5) and its `lru_cache` lookup; the prototype rows call the
  grid directly. Measured at 0.046–0.105ms per call, i.e. **0.3% of a 0.033s
  calibration** — and it is the shipped side that carries it.
- The prototype has no cache at all, so every one of its 40 symbols is a cold
  calibration. The chains are distinct, so the shipped side's cache never hits
  either; this favours neither in this slice.

---

## 7. What I would do, and what is Kenneth's to decide

**Recommendation: direction (c), both halves, or nothing.** The "or nothing"
is not rhetorical — section 6 measures each half alone at 4–6/40 and 8/40
against today's 0/40.

- It is the only arrangement that reaches 100% coverage without a process
  pool, and it does so with a 25–50x margin rather than a marginal one.
- Half of it is free of risk: vectorising `_flat_bs_baseline` is 55–180x on
  that function (width-dependent), bit-identical to the last float, and touches
  no Fourier arithmetic at all. It is worth little by itself (1.03–1.25x on a
  calibration), but it is the half that carries the cost *once the other half
  lands*, and it cannot change a number.
- It leaves `scan.py` alone entirely — no new pool, no new failure mode, no
  per-worker cache fragmentation, no `spawn` warmup in the request path.
- It makes the GIL finding moot rather than worked around.

**Sequence it as two changes, not one**, per the audit rule's batch-size
clause:

1. **The gate.** Vectorise `_flat_bs_baseline` only. Bit-identical output, one
   function, ~40 lines. On its own it is worth **1.03–1.25x** and moves
   coverage from 0/40 to 4–6/40 — i.e. almost nothing. It goes first because it
   is the change that cannot be wrong, not because it delivers anything alone.
2. **The pricer.** The `charexp` factorisation and the composite rule, with the
   oscillation-scaled node count section 5.2 shows is mandatory, plus the
   degenerate-input guard and the `except -> bs_price` tail the prototype does
   not reproduce. This one changes numbers at the 1e-9–1e-3 level and needs its
   own accuracy fixture.

**Kenneth's calls, none of which I have made:**

- Whether any of this is worth building at all, given section 8's first item.
- Whether the 365-DTE $0.001249 residual (5.2) is acceptable, or whether the
  panel width should be halved to remove it.
- Whether the two-change sequence is acceptable as an all-or-nothing
  commitment. It has to be: step 1 alone is 4–6/40 and step 2 alone is 8/40, so
  if only one of them is going to be built, neither should be.

---

## 8. What this document does NOT establish

- **Whether a Heston number should reach a card at all.** Logged against main
  by TIMEOUT-DELETE-INNER's round 2: a calibrated fit systematically
  *overprices* the candidate contract against its own chain mid (up to 1.36x at
  long DTE) and underprices the wings, which inflates `rr_ratio` on exactly the
  cards that say "Heston repriced". Every winning fit sat on 4 of 4 grid
  boundaries and violated Feller by 4.5x. **Fixing coverage makes that defect
  reach more cards, not fewer.** If that is not resolved first, direction (c)
  is a change that makes a known-biased number more prevalent, and the honest
  order is: fix the fit, then fix the coverage.
- **Any of this on Kenneth's box.** Every number here is 4 cores at 2.1GHz. The
  coverage figures in particular are a ratio of CPU throughput to arrival rate,
  and both halves differ on other hardware.
- **The prototype as shippable code.** It omits `heston_price`'s
  degenerate-input guard and its `except Exception -> bs_price` tail, drops the
  per-strike `except ... continue` in the grid loop, and has no tests. It is a
  measuring instrument.
- **Long-chain behaviour.** The widest shape this probe measures is **40
  strikes** (the diagnosis probe's solo sweep reaches 60). `heston.py`'s comment
  records a 163-strike 365-DTE chain at 5.070s on the shipped pricer, and
  nothing here says what the prototype does with one. It should be *more*
  favourable — the whole win is per-strike reuse, so it grows with strike count
  — but that is a prediction, not a measurement.
- **Real chains.** Every chain here is synthetic: the reference smile from the
  Phase F spec's section 7, on a $2.50 ladder. The accuracy sweep additionally
  uses a plain 13-rung moneyness ladder (0.85x–1.25x) rather than a
  delta-banded selection, and only three `v0` values. Nothing is measured
  against a Tradier chain.

---

## 9. Reproducing

```bash
cd backend
.venv/bin/python scripts/heston_latency_probe.py           # the diagnosis
.venv/bin/python -W ignore scripts/heston_remedy_probe.py  # this document
```

`-W ignore` matters for the second: the shipped pricer emits
`IntegrationWarning` at the sub-daily expiries section 5.2 sweeps, which buries
the tables. Individual measurements: `--only pools`, `--only pricer`,
`--only arrangements`; `--guard` re-budgets the outer ceiling; `--symbols`
resizes the slice.
