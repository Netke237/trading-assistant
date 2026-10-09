# Production benchmark method and evidence scope

This independent evidence task changes no application source or audit counters. All measurement files beginning `TAKEOVER_PRODUCTION` belong to this task; earlier screenshots and Stage C measurements remain untouched.

Sources: delivered contracts commit `ac39b841`; numeric/layout correction frontend commit `d3d2657a73b05dca97dbd0dea78df28897457850`; final performance correction commit `3db610f58a9e686fd37b866b94c64d7c0c23b868`; final grid source `9a0ad23f8ba1df8db04516aa62547d43a0ed1bf3`; accepted final tooltip source `a12086fa6510c94592bda600b98e87e4acaaaa68`; before-feature commit `1c8b94ff`. Each is exported with `git archive` into a separate source copy, shares the installed frontend `node_modules` by symlink, and has an independent production `.next` build. Builds use Next 15.5.23 `next build`; servers use `next start` on ports 3102/3103. Root `.next` and port 3001 are untouched.

The sole benchmark source patch replaces `const isOpen = expanded === candidate.symbol` with `const isOpen = true` in each isolated copy. This deliberately mounts all 20 groups and their 200 contracts; the product retains one open symbol. Every run asserts exactly 200 contract rows, and 0/1/200 **valid** `Score explanation` regions rather than unavailable placeholders. The coherent fixture uses all five schema weight keys, including `iv_rank`, and an aggregate of 78.25 rounded to 78.

Browser-dispatched sort, pick, and explanation toggle events are timed inside the page until two requestAnimationFrame callbacks. Driver calls, auto-scroll, chain network time and page hydration are excluded. This measures cached event-to-next-paint responsiveness; it is not physical-device input latency or field INP. Five fresh browser contexts per state produce five samples; median is sample 3 after sorting, p95 is nearest rank 5 (the maximum).

The first `baseline`/`after` result sets use Playwright DOM snapshots and are **diagnostic only, excluded from acceptance**. CPU profiling identified snapshot `visitNode` overhead. Accepted matched timing sets must use the `clean` runner with Playwright snapshots disabled. The clean standalone CDP CPU/timeline profile is also diagnostic and excluded from timing statistics: its purpose is to identify expensive browser work.

The clean 200-panel profile on the correction source still measured sort 435.9ms and a 327ms main-thread long task. Its sort-triggered full document Layout traversed 54,726 layout objects (42,908 dirty) in 186.4ms; UpdateLayoutTree affected 23,600 elements in 71.9ms. This supports a DOM reorder/layout bottleneck. It does not justify claiming that one isolated JavaScript formatting function dominates.

Network assertions use the actual endpoint `/api/contracts?symbol=...`, not the obsolete assumption `/api/contracts/SYMBOL`. The normal 200-contract fixture expects exactly 20 chain requests, zero rescues, and zero interaction API calls. A separate matched rescue fixture omits every card contract from its normal chain: both builds must perform 20 chains plus the identical 20 strike/expiry rescue requests and mount 220 rows. Mock transport durations are recorded separately and are not live provider measurements.

Run from the prepared frontend environment, with Node 22 and Python 3.11 activated by `/workspace/setup/trading-env.sh`. The executable helper copies live in `/workspace/setup/production-benchmark`; saved runner files contain the exact commands, fixture and assertions used. Environment JSON records CPU, memory, cgroup quota, versions and viewport. No live backend is required because existing `setupApiMocks` plus deterministic chain routes intercept the APIs.

## Reproduce from any checkout

Activate Node22/Python3.11, install the frontend locked dependencies, and keep unrelated CPU-heavy work idle during timed runs. Chromium defaults to `/usr/bin/chromium`; set `CHROMIUM_PATH` for another installed Chromium. The saved scripts resolve their repository root from their own location; `REPO_ROOT` can override it. The prepare helper was executed successfully against the final source and its archive/patch was checked; the underlying production build/start commands were executed successfully for all three source copies.

```bash
export REPO_ROOT="$(git rev-parse --show-toplevel)"
export BENCH_ROOT="$(mktemp -d)"
export PROOF="$REPO_ROOT/docs/superpowers/measurements/options-explanations"
python "$PROOF/TAKEOVER_PRODUCTION_PREPARE.py" --destination "$BENCH_ROOT/baseline" --commit ac39b841 --build
python "$PROOF/TAKEOVER_PRODUCTION_PREPARE.py" --destination "$BENCH_ROOT/final" --commit a12086fa6510c94592bda600b98e87e4acaaaa68 --build
python "$PROOF/TAKEOVER_PRODUCTION_PREPARE.py" --destination "$BENCH_ROOT/feature" --commit 1c8b94ff --build
```

In two separate terminals, start baseline on3102 and final on3103 from their copied frontend directories with `npm run start -- --port 3102` and `npm run start -- --port 3103`. Run the measurements from the original checkout's frontend directory:

```bash
cd "$REPO_ROOT/frontend"
export TS_NODE_COMPILER_OPTIONS='{"module":"CommonJS","moduleResolution":"node"}'
BENCH_LABEL=clean_baseline BENCH_PORT=3102 node -r ./node_modules/ts-node/register/transpile-only "$PROOF/TAKEOVER_PRODUCTION_CLEAN_RUNNER.ts"
BENCH_LABEL=clean_final BENCH_PORT=3103 node -r ./node_modules/ts-node/register/transpile-only "$PROOF/TAKEOVER_PRODUCTION_CLEAN_RUNNER.ts"
BENCH_LABEL=cached_baseline BENCH_PORT=3102 node -r ./node_modules/ts-node/register/transpile-only "$PROOF/TAKEOVER_PRODUCTION_CACHED_RENDER_RUNNER.ts"
BENCH_LABEL=cached_final BENCH_PORT=3103 node -r ./node_modules/ts-node/register/transpile-only "$PROOF/TAKEOVER_PRODUCTION_CACHED_RENDER_RUNNER.ts"
```

Stop only your baseline3102 server, then start the copied feature frontend on3102. Run:

```bash
BENCH_LABEL=cached_feature_baseline BENCH_PORT=3102 node -r ./node_modules/ts-node/register/transpile-only "$PROOF/TAKEOVER_PRODUCTION_CACHED_RENDER_RUNNER.ts"
BENCH_LABEL=final_functional BENCH_PORT=3103 node -r ./node_modules/ts-node/register/transpile-only "$PROOF/TAKEOVER_PRODUCTION_FUNCTIONAL_RUNNER.ts"
```

Switch3102 back to the delivered baseline server before running the matched rescue test:

```bash
node -r ./node_modules/ts-node/register/transpile-only "$PROOF/TAKEOVER_PRODUCTION_RESCUE_RUNNER.ts"
```

Runners write named result JSON and traces beside these files; use distinct `BENCH_LABEL` values for extra trials to preserve earlier results. Rescue output has a fixed name, so preserve an earlier result before rerunning. The supplemental cached mount metric starts at final fixture fetch-response delivery, then detects200 mounted rows and waits two frames inside the page; it includes JSON processing/React work while excluding chain request latency. This is separate from navigation load time.

The recorded feature-baseline run emitted unused candle-fixture path warnings because its fixture setup ran from the checkout root. Its request log confirms zero candle API requests, so these unused fixture responses did not contribute to the benchmark. The reproduction commands use the frontend directory and avoid those warnings.

Final-grid remeasurement also asserts successful volume ordering, selected-row state, and explanation-region count after each timed action; these checks occur after the timed interval. It records zero interaction HTTP across every endpoint, after waiting for font readiness. Earlier matched baseline records zero interaction API requests and exactly20 chain calls.

Final-source root capture used port3104 and labels `release`, `release_cached`, and `release_functional`; source and patch were otherwise identical. Independent evidence author was interrupted by model quota before this final capture. Final code independence comes from separate qualifying code reviewers, not this root-run benchmark.
