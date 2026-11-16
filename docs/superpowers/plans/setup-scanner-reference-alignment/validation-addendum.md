# Browser-width correction on resumed validation

The independently reviewed plan's 1200px scanner matrix assumption came from the generic repository guidance and standalone reference. Actual current `frontend/components/MinWidthGate/index.tsx` uses 1280px for Setup Scanner; 1200px is a route-specific exception for Options/Stocks terminal cards. The first resumed browser run was correctly blocked by that existing gate at 1200px, before interacting with the scanner.

Preserve the shell and gate unchanged. Test real scanner interaction at **1280/1366/1920px**, dark/light, in all three modes. Also assert that a 1200px scanner viewport still exposes the existing Desktop required guard. Do not hide the gate or force pointer events through it.

This corrects validation coordinates only. No scanner thresholds, financial numbers, request/data ownership, persistence, UI gate or approved information-flow behavior changes. Original plan round 1 remains recorded against its exact SHA256 `bce5c617c733bedcb34b69094d8dedb08e1c07de630964eb534e36dc7dcc1441`; no audit counters are reset or incremented for a coordinator source check. The independent phase-wide code auditor must consider this addendum alongside the original plan and real source.

The earlier stopped browser runs are not reported as passes: the original run exposed an ambiguous shared/submode selector, and the resumed run exposed the unsupported-width test assumption. Final acceptance must report the corrected completed run separately.
