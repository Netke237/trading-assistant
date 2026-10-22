# Settings remaining local states — follow-up for #394 / #350

Audit/report only on exact source `4b1f6b86e8137f499da0c4c430f23b9c250fd8de`. Original captures remain untouched and retain their original source SHA. This supplement does not clear application acceptance or the lane review gate. Coordinator owns publication/review counters.

Run from repository root, with local socket permission for Chromium:

```sh
node docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/followup/settings-states/browser.mjs
PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/followup/settings-states/verify_contracts.py
PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/python docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/followup/settings-states/schedule_yaml.py
```

`browser.mjs` uses the shared Next development server at `127.0.0.1:3027`, isolated incognito contexts, `/usr/bin/chromium`, and explicit deny-by-default business HTTP interception. Only the Settings document and Next static assets pass through. Every WebSocket is closed without connecting upstream. Observed: **261 intercepted HTTP requests, 13 intercepted WebSockets, zero unknown HTTP routes, zero page errors, zero forbidden actions**. Requests and responses include full fixed/loop CRUD bodies and mock ledger GET readbacks. No run-now, job, scheduler, broker/probe, notification/send/test or adoption endpoint is invoked. Fixtures use exported options profiles plus explicitly synthetic stocks/unsupported/incomplete profiles; these are not real user records.

Runtime: Chromium `151.0.7922.173`, Node `24.19.0`, Next `15.5.23`, Playwright `1.62.1`, backend Python `3.11.16`. Source/config/package hashes are in `source-hashes.json`; final artifact hashes in `manifest.json`. Local `backend/config/settings.yaml` is absent: its committed example is hashed. No actual backend settings, credentials, database or shared scheduler was modified.

`output.json`: **42 browser assertions:33 PASS,9 FAIL**. These are assertion counts, not unique defects or total control permutations. Four IV numeric assertions pass. Fourteen browser persistence assertions yield11 pass/3 fail; those failures are MA0, breakout1, and UI-upper-bound breakout4. The first two are also refused by the real downstream schema; breakout4 is schema-valid and only a below-gate range/UI observation. Twenty-four UI assertions yield18 pass/6 fail. Thus two browser persistence failures demonstrate schema-invalid persisted overrides, while all seven remaining browser failures are presentation/feedback/range observations.

`schema-output.json`: **15 PASS/0 FAIL** for direct Pydantic validation. Twelve captured schedule POST/PUT request bodies agree with their mock200/422 outcomes. Additional direct stock-schema probes independently confirm MA lookback0 and breakout multiplier1 are rejected; multiplier4 is accepted. These probes modify a captured valid request offline; they do not claim a fresh browser scan request or executed scan.

`yaml-output.json`: **12 real temporary-store assertions:9 PASS,3 FAIL**. Three failures are variants of one preservation problem: invalid schedule YAML silently yields an empty store, and subsequent ordinary upsert replaces those original bytes without refusal or backup. Valid legacyv1 migration, exact original backup, horizon mapping, strategy-override removal, fresh store-instance readback, missing file, malformed rows, upsert/delete readback all pass as individually recorded. This is a fresh store-instance restart; it does not claim a separate process or database restart. Unknown entry extension fields survive migration; unknown top-level metadata is dropped and is recorded as an observation, without inventing a compatibility contract.

| Original boundary / requested state | New runtime evidence | Residual limitation |
|---|---|---|
| `iv-error-reset` | Initial pending fetch: blank/disabled; fetched-record Reset before Apply; Reset after Apply across section remount; failed refetch clears record and disables Apply | No Step5/7 score/gate recomputation in this supplement |
| `timezone-load-error` | Initial503 exposes misleading default without error; pending initial GET resolves after section unmount; fresh remount reads current fixture | No real scheduler timezone/time conversion certification; pending PUT/cancel not run |
| `scheduled-row-runtime` | Options and synthetic Stocks create; fixed label/time/weekdays update; profile replacement and resolved request direction; loop defaults/cadence/window update; false enabled; delete; full payloads plus ledger GET;422/500 preservation and missing feedback | All HTTP CRUD is mocked. No execution, DB run records, scheduler, next-run arithmetic, concurrency, loaded success/error run histories, or full strategy variants |
| `strategy-other-boundaries` | MA lookback0 and breakout1/4 captured in browser localStorage; real offline request schema checks corresponding values | Other strategy/backtest bounds and actual scan execution remain unrun here |
| `confighealth-nonclean` | Checking; clean scope popover/Escape/outside-close; warning/error/disk-stale/unknown tiers with matching chip/banner, expanded/collapsed and chip focus/expand | Multiworker detection, actual restart,70s report aging, polling races and provider-health correctness remain unrun |
| `request-unmount-cancel` | Timezone GET pending on section unmount, old reply resolved, remount GET uses current fixture | Only this section/GET transition; no actual request abortion or save cancellation claim |
| `legacy-malformed-schedule` | Real isolated YAML missing/malformed syntax/wrong root/invalid version/mixed rows; valid v1 stock migration plus backup; source-byte preservation on load and subsequent write; store-instance readback | UI legacy profiles and YAML legacy migration are separate tests. No real configured YAML, API invalid-row filtering, DB, scheduler, concurrency or process-restart claim |
| `appearance-theme-sync`, `browser-process-restart` | Owned by separate storage follow-up | Not run by these scripts |
| `scan-consumer-trace`, `regime-computation` | Owned by other lane evidence | Not run here |
| `broker-save-failure`, `risk-enforcement` | Cross-lane F | Not run; no credentials/probes/orders |
| `notifications-delivery` | Cross-lane G | Not run; no sends or tests |
| `data-job-provider`, `real-scheduler` | Cross-lane H | Not run; no job/scheduler/provider execution |
| `tuning-job-proposals` | Cross-lane D | Not run; no optimizer/job/adopt actions |
| `multiworker-concurrent-settings` | Cross-lane/runtime integration boundary | Not run |

42+15+12 gives69 listed assertions,57 pass/12 fail, with overlaps and distinct boundaries described above. This total must not replace the original settings output or imply all18 old not-run entries are complete. New numeric/persistence observations are in `findings.md`, separately from UI observations. No product fix was made.
