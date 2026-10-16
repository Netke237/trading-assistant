# Lane A inventory evidence

Execution and source/runtime classification are ready for independent final review. The implementer has not cleared the shipping gate or certified application arithmetic/persistence.

Start with [report.md](report.md). `reconciliation.json` records the eight discovery dispositions and historical/current source boundary. `semantic-classification.json` provides normalized JSX bindings, conditional capabilities, native classifications and state-entry contracts. `inventory.json` is the generated structural index. `findings.json` links both UI rail defects to separate remediation phase [#395](https://github.com/Netke237/trading-assistant/issues/395).

Original `runtime/` evidence remains at application SHA `27fe5182a90ae1b40bee53bdf01484b92dab136c`; new `integrated-evidence/` executes changed UI at `00b4ab54069e2a43e0a66cd1f183f5fa2347f336`. Original runtime tooling and artifacts are immutable. The final verifier loads the historical inventory from commit `6309c063` when checking those records, avoiding silent baseline relabeling.

Reproduce from the repository root:

```powershell
node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/generate-source-inventory.cjs --check
node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/verify-source-inventory.cjs
node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/classify-source.cjs
node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/verify-final.cjs
```

To replay the new UI, first start this worktree's frontend on isolated loopback port3017, then run `node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/runtime/integrated-probe.cjs`. Browser/loopback execution requires environment approval. The harness creates an isolated Chrome context, mocks synthetic API traffic, denies unmatched backend/external/mutation requests and closes every websocket before connecting upstream. It never runs backend jobs. Agent-browser CLI was unavailable, so the existing Playwright harness was used under the browser/testing skill guidance.

Source regeneration is intentionally separate from browser execution. `reconcile-final.cjs` refreshes annotations/reconciliation from pinned commits; `classify-source.cjs` creates normalized semantic classifications. Regenerate source after reconciliation so its annotation hash matches. `integrated-attempt-1/` preserves three unavailable prototype attempts (ambiguous mode selector, incomplete row fixture, consequent route error boundary); these are harness diagnostics, not application findings.
