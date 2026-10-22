# Browser storage follow-up — evidence child #393

This supplements the frozen `880c8441841cc22d5090cdc5f984e4cf7e3d9a8d`
controls/settings evidence. This run uses source
`4b1f6b86e8137f499da0c4c430f23b9c250fd8de`; it is a new capture, not a
replacement for or replay of the original 312 controls observations. No product
files, calibration, original captures, or review counters changed here.

## Reproduction and isolation

With the existing isolated Next dev server at `http://127.0.0.1:3027`, run from
repository root:

```sh
node docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/followup/storage/browser.cjs
node docs/superpowers/audits/app-audit/APP-AUDIT-SETTINGS-PROFILES/followup/storage/manifest.cjs
```

Browser execution requires local socket permission. Playwright uses
`/usr/bin/chromium`; versions are captured in `output.json.versions` and the
manifest. All `/api/` requests are fulfilled locally, all WebSockets are closed
by Playwright, and other origins are blocked. Captured API paths are mock
requests, never evidence of backend/provider execution. No backend process,
jobs, order submissions, notification sends, or credentials are used.

Each failure case gets a fresh browser context containing a synthetic profile
copied from the committed export, with a fixed audit ID/name. Settings prior
values are established through the actual UI. Failures are **injected** by
temporarily overriding `Storage.prototype.setItem`, only for the exact named
localStorage key (or the profile backup prefix), to throw a DOMException named
`QuotaExceededError` or `SecurityError`. Reads and unrelated writes remain native.
The script records every attempted target write and the error name. This tests
the application's response to those exceptions; it does not fill a disk quota
or certify browser privacy-policy behavior, and does not simulate a failing
`localStorage` getter or `getItem`.

`output.json.cases` records raw saved bytes before/after/reload, UI observations,
targeted fault attempts, page errors, and import exceptions. These values are
synthetic and contain no supplied credentials. Settings bytes are read back
after a real Chromium process closes and a new process reopens the same
temporary persistent user-data directory. The temporary directory is removed
afterwards. The source and artifact hashes are in `hashmanifest.json`; source
files are compared against both recorded source commits.

The harness waits for React event props before interacting after navigation;
an earlier development attempt clicked server-rendered Settings tabs before
hydration and timed out. The completed output is the authority; that harness
timeout is not a product failure.

## Results

88 assertions: **65 pass / 23 fail**, 20 independent capture cases, no fatal
harness error. Assertions overlap; 23 failures are not 23 distinct defects.

| Boundary | Pass / fail | Observation |
| --- | --- | --- |
| Profile save/update/rename/delete, both exception types | 24 / 8 | Each injected write is reached, exact prior saved bytes survive, and reload reads those bytes. All eight UI/in-memory mutations remain despite failure. Update is verified by reapplying the in-memory profile: Bearish is applied while saved bytes remain Bullish. |
| Restore import, backup write and primary write failures, both types | 20 / 0 | Error reaches caller and prior raw main key survives. Backup-write failure creates no backup; primary-write failure preserves an exact backup of the prior bytes. Import does not claim success. |
| Local Settings theme, Markov lookback, confidence threshold, both types | 18 / 12 | All six fault injections reach the key; prior bytes survive and reload restores old UI values. Every failed edit remains visible in memory, and every case's Save changes button falsely shows Saved. |
| Unknown future profile version | 0 / 1 | Opening a synthetic version9999 store rewrites it to version5 and removes an unknown state sentinel without user action. |
| Same-origin Settings browser-process restart | 3 / 0 | Exact Settings and theme bytes and UI light/35-bar lookback/63% caution values survive an actual process close/reopen. |
| Cross-tab theme and stale Settings writer | 0 / 2 | Native storage events arrive, but the other tab stays light after dark is saved. A stale tab's confidence edit silently restores its older 35-bar lookback over the newer 55-bar value. |

The in-memory rollback assertions express the integrity requirement that a
failed save must not be represented as committed data. A UI could instead keep
a clearly identified unsaved draft; this implementation exposes changed
profile options and settings values without such a persistence status. Settings
additionally presents explicit success through its Save button. Error names in
the browser console/uncaught event do not establish a successful persisted save.

## Scope and residual states

- **Pass:** exact prior bytes under the targeted write failures; import failure
  and backup preservation; same-origin process restart for theme, Markov, and
  confidence Settings. These are browser-local Settings, not server Settings.
- **Fail:** profile memory/disk divergence; local Settings memory/disk divergence
  and false Saved; future-version downgrade/data loss; advertised theme sync;
  stale-tab Settings overwrite. `findings.md` separates the mechanisms.
- **Normal multi-tab UI flow:** the lost update uses only Settings controls in
  two same-origin tabs, with no external importer or injected storage writes.
  One tab changes Markov lookback; a confidence edit in the other overwrites
  that unrelated saved field. General multi-tab merging is not advertised, but
  silently losing saved data through ordinary controls is an integrity defect.
  The separate theme promise is explicit in
  `frontend/app/(frame)/settings/page.tsx:225`:
  `hint="Persisted in localStorage; synced across tabs"`. The Appearance intro
  and ThemeProvider store-to-DOM comments are not the basis of that finding.
- **Existing defect extensions:** S2 extends #371 with browser-local write
  failures and S3 extends #381's unknown-future-version acceptance boundary.
  They should not become duplicate defect issues.
- **Not run:** real quota exhaustion, privacy-policy/getter/read failures,
  asynchronous storage adapters, OS crash/power loss, mobile browsers, alternate
  browser engines, real backend or provider behavior. Unknown-version coverage
  uses one structurally valid synthetic future payload with an unknown field;
  it does not certify arbitrary future schemas. Theme/Markov/confidence are
  representative local setters, not a repeat of every Settings control.
- **N/A:** server restart for these browser-only keys; HTTP loading/cancel states
  for synchronous localStorage writes. No cancellation action exists for these
  setters. Backend persistence/restart remains in the original `settings/`
  evidence and the separate follow-up settings-family ticket.

Fresh independent delta review belongs to the coordinator. This evidence is
not itself a qualifying review and does not mark application correctness clean.
