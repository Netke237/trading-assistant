# Stage C matched production performance evidence

Final source `a12086fa6510c94592bda600b98e87e4acaaaa68` meets the <=200ms p95 interaction budget, no explanation-related >100ms long-task budget, and <=20% median rendering/interaction regression budget on this environment. The delivered baseline is `ac39b841`; before-feature baseline is `1c8b94ff`. This report does not change code-audit counters or certify the separately owned ranking-page/layout evidence.

AMD EPYC 9V74; 5 exposed vCPUs with a4CPU quota;32GiB memory limit. Node22.23.3, Python3.11.16, Chromium151.0.7922.173, Next15.5.23 optimized production builds. Viewport1440x1000. Browser and production source copies are matched. Root kept competing CPU-heavy work idle during accepted timings. Root completed this final capture after the independent evidence agent was interrupted by model usage limits; this runtime capture is not an independent code-audit verdict. Five fresh contexts per state; p95 is nearest-rank(maximum of five). Values are milliseconds.

The temporary source-copy patch forces all20 groups open; the product continues to open one symbol. Every measured state contains200 contract rows. All0/1/200 explanation-region counts are asserted, and every open region contains a valid explanation rather than an unavailable placeholder. Clean traces disable Playwright DOM snapshots. See the method and raw JSON for fixtures, assertions and measurement limits.

| Open panels | Interaction | Baseline median/p95 | Final median/p95 | Median change |
|---:|---|---:|---:|---:|
| 0 | sort | 75.9/79.6 | 77.8/82.9 | +2.5% |
| 0 | pick | 31.0/34.8 | 32.7/32.8 | +5.5% |
| 0 | toggle | 45.8/54.8 | 51.8/52.7 | +13.1% |
| 1 | sort | 83.0/102.6 | 84.1/87.8 | +1.3% |
| 1 | pick | 27.3/32.8 | 27.6/39.1 | +1.1% |
| 1 | toggle | 33.3/45.4 | 38.2/40.8 | +14.7% |
| 200 | sort | 400.1/422.6 | 97.1/108.5 | -75.7% |
| 200 | pick | 72.2/81.8 | 19.4/19.9 | -73.1% |
| 200 | toggle | 121.9/128.6 | 32.7/44.1 | -73.2% |

Maximum final explanation-interaction long task:76ms; maximum task while preparing200 open panels:60ms. Every accepted run has exactly20 chain requests, zero rescue requests and **zero API calls during explain/sort/pick**. The separate final rescue test matches exactly20 normal chains plus20 identical expiry/strike rescue calls and220 mounted rows on both delivered baseline and final build.

Cached render supplement starts after delivery of the20th fixture chain fetch response, then waits inside the browser for200 rows and two animation frames. It excludes chain request latency; includes response processing and initial React rendering. The before-feature page lacks the new sort select, so it activates its existing VOL header to perform the same descending volume sort. The final page activates the volume select.

| Cached0-panel metric | Delivered median/p95 | Before-feature median/p95 | Final median/p95 | Change vs delivered | Change vs feature baseline |
|---|---:|---:|---:|---:|---:|
| cachedMount | 123.1/136.3 | 139.0/159.1 | 123.5/134.9 | +0.3% | -11.2% |
| sort | 75.7/76.4 | 91.3/97.5 | 84.5/86.1 | +11.6% | -7.4% |
| pick | 27.6/34.6 | 36.9/41.1 | 31.9/40.2 | +15.6% | -13.6% |

Final offscreen verification mounted200 valid regions, scrolled the last panel into view and verified its actual content painted (height422.5px and visible child text). Keyboard Enter closed199/reopened200 panels; a star action preserved200; explicit refresh issued exactly20 new chains and preserved200 expanded regions. A last-panel screenshot and representative functional trace are retained. Star and refresh have their expected explicit API calls; the zero-HTTP requirement applies to explanation/sort/pick interactions.

The first DOM-snapshot-instrumented results are retained as diagnostic raw JSON and excluded from acceptance. An independent clean CPU/timeline profile on the pre-performance-fix source still demonstrated sort435.9ms and a327ms long task: full-document Layout186.4ms (54,726 layout objects,42,908 dirty), UpdateLayoutTree71.9ms (23,600 elements). This justified the root agent's detail memoization and CSS offscreen containment. Final clean5-run evidence verifies the resulting improvement; no claim rests on the instrumented traces.

Mock transport latency is separate: the initial matched rescue probe recorded40 request completions/build, median108.4ms baseline and81.3ms pre-performance-fix source (max153.0/156.7ms). These are local mock delivery timings, not provider latency, and are excluded from all cached interaction/render statistics. The final matched rescue-count probe is separately recorded. All chain/rescue requests were intercepted by the deterministic fixture; live provider or broker integrations were not measured.

Retained evidence is about1.8MB: all raw5-run JSON, environment/method, portable helpers, clean diagnostic CPU profile/summary, representative performance traces plus the functional trace and last-panel screenshot. Other snapshots/ZIPs and raw timeline diagnostics were preserved outside the checkout in the local benchmark archive. No earlier tracked measurements or screenshots were overwritten.

Limits: this is browser-dispatched event-to-paint responsiveness, not physical input/field INP; five samples give a coarse p95; live-chain latency and ranking-page/viewport layout acceptance belong to separate evidence. The smallest final interaction budget margin is a+14.7% delivered-baseline median change in a low-panel interaction, so a materially different device needs its own measurement. No performance gate remains open for this measured environment.

Final code merges upstream main6cce7364 in2ef6c900. Step6 rendering, summary helper and containment source are identical to the accepted a12086fa stress capture; merged cross-page/API interactions have a separate independent review and production browser run. Final raw acceptance is `TAKEOVER_PRODUCTION_release_RESULTS.json`, cached supplement is `release_cached`, and offscreen/keyboard/refresh is `release_functional`; earlier final labels remain historical captures.
