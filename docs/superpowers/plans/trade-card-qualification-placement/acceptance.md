# Qualification placement acceptance

Phase `TRADE-CARD-QUALIFICATION-PLACEMENT`, board item #617, build ticket #618. User screenshot amendment supersedes the older G4 contract-qualification placement.

## Verified presentation

At 1366 pixels in light and dark themes, 23 assertions per theme passed with zero page errors: one stock and one contract panel inside the identity, adjacent Contract Details → Stock Qualification → Contract Qualification, both default collapsed, both independently expandable with all ten original score bars. Toggling them made no Monte Carlo/Arithmetic calculation or save/order attempt. Existing regression coverage retains captured stock/contract evidence, independent saved disclosure preferences and unchanged input data.

- [Light, collapsed](1366-light-identity-collapsed.png)
- [Dark, collapsed](1366-dark-identity-collapsed.png)
- [Light, expanded](1366-light-qualifications-expanded.png)
- [Dark, expanded](1366-dark-qualifications-expanded.png)

The whole Contract Qualification JSX block is byte-identical to base 1f861cbf and appears exactly once (SHA256 409c0863e3a5a33be7cffeff6eef88f7fe5b1692bbe6933a2e0163e8d32f877a). No content, score binding, tooltip, badge or CSS changed. Alternative Contracts remains after Decision & execution. No numerical, broker, exit, or persistence-schema code changed.

## Reproduce browser acceptance

Start an isolated frontend dev server on port 3099; then from the repository root:

```sh
node docs/superpowers/plans/trade-card-qualification-placement/capture-placement.cjs --repo-root "$PWD" --output /tmp/qualification-browser --base-url http://127.0.0.1:3099 --browser /usr/bin/chromium --widths 1366 --themes light,dark
```

The wrapper reuses the existing guarded mocked capture harness and stops after qualification checks. All API calls are mocked in the browser; it never uses the live application's port. Browser evidence records capture-time source hashes; source identity against the committed application is separately verified.

## Validation

Application commit `1c15c200382d415fa88159dbf5b082523f9f2a96`.

- Expected RED: amended placement regression failed because Contract Qualification was outside the identity.
- Frontend typecheck passed.
- Full Jest: 343/345 suites, 6363/6365 tests passed; two 5000-ms timeouts under parallel load (edited-fields-sync and submission-review), no assertion mismatch.
- Unchanged serial rerun of both failed suites: 2/2 suites and 40/40 tests passed, with original timeouts. Across the full run plus isolated rerun, every suite passed. Exact-head CI remains a separate merge requirement.
- Browser: 2 themes × 23 assertions, zero page errors; source pins match committed application byte-for-byte.
- Moved disclosure byte-identical, exactly one instance. All other application files unchanged.

No backend files changed; backend tests are delegated to the existing exact-head CI gate. Independent code audit pending; this record proves acceptance, not audit/merge completion.

QUALIFICATION-PLACEMENT-VERIFIED
