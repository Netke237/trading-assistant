# Lane A inventory evidence

Independent plan2/code2 review is clean for Lane A report/tooling delivery, and PR [#405](https://github.com/Netke237/trading-assistant/pull/405) is verified merged. Exact scopes and the corrected coverage finding are in [independent-review.md](independent-review.md). Application arithmetic/persistence/presentation acceptance remains with B–J; rail defects395 remain open.

Start with [report.md](report.md). `reconciliation.json` records the eight discovery dispositions and historical/current source boundary. `semantic-classification.json` provides normalized JSX bindings, conditional capabilities, native classifications and state-entry contracts. `supplemental-capability-contracts.json` adds identified source-backed capability/route/state requirements for the four HOC/renderless bindings; join its capability IDs to the semantic overlay and its route IDs to `inventory.json`, the generated structural index. `findings.json` links both UI rail defects to separate remediation phase [#395](https://github.com/Netke237/trading-assistant/issues/395).

Original `runtime/` evidence remains at application SHA `27fe5182a90ae1b40bee53bdf01484b92dab136c`; new `integrated-evidence/` executes changed UI at `00b4ab54069e2a43e0a66cd1f183f5fa2347f336`. Original runtime tooling and artifacts are immutable. The final verifier loads the historical inventory from commit `6309c063` when checking those records, avoiding silent baseline relabeling.

Reproduce from the repository root:

```powershell
node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/generate-source-inventory.cjs --check
node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/verify-source-inventory.cjs
node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/classify-source.cjs --check
node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/test-capability-contracts.cjs
node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/verify-final.cjs
```

To replay the new UI, first start this worktree's frontend on isolated loopback port3017, then run `node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/runtime/integrated-probe.cjs`. Browser/loopback execution requires environment approval. The harness creates an isolated Chrome context, mocks synthetic API traffic, denies unmatched backend/external/mutation requests and closes every websocket before connecting upstream. It never runs backend jobs. Agent-browser CLI was unavailable, so the existing Playwright harness was used under the browser/testing skill guidance.

Source regeneration is intentionally separate from browser execution. `reconcile-final.cjs` refreshes annotations/reconciliation from pinned commits; `classify-source.cjs` creates normalized semantic classifications. Regenerate source after reconciliation so its annotation hash matches. `integrated-attempt-1/` preserves three unavailable prototype attempts (ambiguous mode selector, incomplete row fixture, consequent route error boundary); these are harness diagnostics, not application findings.

Ticket397 corrects supplemental state discovery only. Contracts include exact caller props/entry conditions, HOC content-state inheritance, chart handle availability, per-kind visibility, drawing diff/replacement and teardown, and shared caller recovery states. Native JSX resolves to its declaration/caller contract; supplemental native JSX inherits identified state IDs. The supplement adds source requirements, without changing base inventory IDs or historical observations. Regenerate both overlays with `classify-source.cjs` (without `--check`). The final verifier checks complete joins and canonical source-backed generation; nine omission mutations exercise its rejection paths. Fresh independent review remains required.
