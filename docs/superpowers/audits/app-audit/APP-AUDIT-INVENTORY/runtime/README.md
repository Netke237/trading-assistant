# Lane A runtime evidence — Task 2 / #362

Application source is frozen at **27fe5182a90ae1b40bee53bdf01484b92dab136c**, source-inventory increment `6309c063`. This directory contains report tooling and synthetic browser evidence only. It does **not** certify domain arithmetic, production behavior, backend restarts, or all imported components/disclosure states. Task 3 must reconcile semantic reachability and the later main-branch integration delta before #349 can close. No application fix was made here.

## Read the evidence

- `runtime-summary.json`: counts, unavailable attempts, and handoff for each of the eight source-discovery questions. Counts include preserved diagnostics and repeated runs; they are observations, never unique components or correctness passes.
- `route-reconciliation.json`: all 45 source route/slot/layout/boundary entries receive evidence references and an explicit disposition. Slot DOM evidence does not distinguish identical QuickLook implementations without source binding.
- `observation-source-links.json`: explicit source surface/native IDs, fixture identities and normalized source state requirements where the actual route-instance exists. Raw DOM inventories in each observation are supporting readback; they do not claim every captured control has been independently semantically classified.
- `slot-history.json`: paired real Primary-link soft navigation and same-URL hard reload, source identity of distinctive retained rail content, expected target slot association, and storage/request evidence links. Back/forward observations are also preserved.
- `findings.json`: two demonstrated **UI/navigation** findings, Calendar and Settings retaining prior page rails on soft navigation. No wrong arithmetic was demonstrated. Fixes require separate claims. Related programme/tracking issues are #348/#349; implementer created no new GitHub issue.

Each evidence folder has `observations.json` (actual visible text/headings, controls, all aside texts, isolated local/session storage, operation-linked network indices), `network.json` (sanitized method/path/query-key metadata and disposition), `mock-payloads.json` (SHA256-addressed synthetic response/request bodies), `page-errors.json`, and `provenance.json`. Request query values, cookies, authorization headers and real credentials are never collected. Persisted values are from this new synthetic profile only.

`evidence/` is the route census; `interactive-evidence/` is the corrected detailed run; `followup-evidence/` contains focused selector/fixture corrections and additional populated disclosures. `interactive-attempt-1/`, `followup-attempt-1/` and `setup-launch-attempt.json` preserve earlier diagnostic attempts. Prototype runs were made while report tooling was being developed, so their harness bytes were not all pinned at start; they retain exact application baseline, fixture hashes and tool versions. The final focused run additionally records SHA256 of all harness modules at launch. Use the final corrected harness below to reproduce; earlier timing/selector/fixture failures are explicitly not application defects.

`primary-link-evidence/` finishes real Primary anchor clicks for Screener and Strategy Watch, supplementing the other nine destinations already reached through actual links. Run `node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/runtime/primary-link-proof.cjs` to reproduce those two actions.

## Scope actually exercised

Actual URL entries, three redirects, private `__test-crash` URL returning visible 404, developer gallery in development, standalone chart outside the Frame, ordinary empty/default pages, nine Settings section buttons, all three screener mode buttons with 7/6/4 logical step counts, Next and keyboard Back, all three setup submodes and parameter disclosures, REJECT confirmation/cancel/proceed with modal arrow suppression, browser back/forward/reload, and paired rail history are recorded. Default min-width is asserted at 1279/1280; both special Step7 workspaces are asserted at 1199/1200.

The real Frame error/reset was exercised with an intentionally malformed **mock** events response, then a valid response and Retry. This is boundary evidence, not an application defect. Real Frame loading was visibly asserted during an isolated delayed frontend RSC request. The unknown-route and private-source 404s use the actual root not-found page. These boundary outcomes must not be inferred from HTTP 200 alone.

Populated fixtures include distinct journal rows and row-selected edit form, alert-rule N-of-M and nested regime condition controls, a session-restored tuning proposal and two fold winners, frozen saved-report/raw-input/legacy disclosures, CSS hover tooltip, chart canvas interactions and indicator panel, and populated Stocks candidate navigation with nested summaries. Focused follow-up records which additional chart, setup/composite-alert and contract-chain disclosures succeed or remain unavailable. Reused repository options fixtures carry old expiry dates intentionally; they are disclosure fixtures, not current market/order fixtures.

## Safety and reproducibility

The frontend server is the pinned worktree's Next 15.5.23 dev server at `127.0.0.1:3017`. Browser: isolated installed Chrome channel, exact version in per-run provenance; Playwright 1.62.1, Node version recorded. Python 3.11.9 was verified; backend dependencies/tests were not needed. `frontend/node_modules` is a prepared dependency junction. No existing browser profile/storage was used, and context service workers were disabled.

All WebSockets close without connecting upstream. The context guard allows only GET navigation/assets to the exact isolated frontend origin, denying every other unmocked URL/method. Every repository fixture handler is wrapped: `route.continue()` is permitted only for that same safe frontend origin/GET/non-API condition and is aborted otherwise (the existing `/api/scan` GET fixture therefore cannot bypass the context guard). Synthetic mock fulfillments terminate inside the browser interception. No real backend requests, orders, notifications, scans, tuning jobs, credentials or shared writes were permitted. A synthetic setup button action, where reached, returns a local intercepted fixture and creates no backend job.

From the pinned repository root, with that server already running:

```powershell
node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/runtime/probe.cjs
$env:RUNTIME_STAGE = 'details'
node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/runtime/probe.cjs
$env:RUNTIME_STAGE = 'followup'
node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/runtime/probe.cjs
Remove-Item Env:RUNTIME_STAGE
node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/runtime/reconcile.cjs
node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/runtime/verify.cjs
npm --prefix frontend run typecheck
```

Browser/loopback execution required sandbox escalation in this environment. Initial default Playwright headless-shell launch was unavailable; the isolated installed Chrome channel resolved it without downloading a browser. Earlier fixed900ms navigation and direct localStorage mode seeding were unreliable: corrected redirect probes use URL waits and a one-shot next-document seed applied before hydration. Contract chain and indicator selectors are corrected in the final focused probes. Unavailability is always recorded, never converted into an asserted pass.

## Remaining handoff

Lane A supplied runtime navigation and shared-boundary evidence. Task 3 still owns whole-inventory semantic reconciliation, source/native binding beyond explicit probes, source delta after baseline, and independent evidence/tool audit. Domain lanes B–I own applicability and split zero/false/null/absent, failure/cancel/stale async, numeric/persistence and unsupported/legacy fixtures; J owns presentation. Real backend/DB restart and production exposure are untested. The portal-capable method selector exists in source, but the pinned Step7 page explicitly does not pass `decisionTarget`, so this page exercises its inline branch; alternate portal-target branches remain a named source requirement. A route body or source import count never closes these requirements.
