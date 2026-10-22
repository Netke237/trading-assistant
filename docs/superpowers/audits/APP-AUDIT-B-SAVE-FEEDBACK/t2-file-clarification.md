[codex · coordinator]

# T2 file-location clarification

During T2 inspection, the fresh implementer found that the approved IV dirty/Apply/Reset behavior lives in `frontend/app/(frame)/settings/IvThresholdsSection.tsx`, imported by the plan-named `page.tsx`. The coordinator extended T2 ownership to that existing component and its settings tests for minimal direct ledger integration. A DOM-inspection wrapper in the page would obscure the actual dirty and partial-Apply state.

This changes the file list only: approved channel `iv-thresholds`, dirty/discard lifecycle, validation, Apply/Reset semantics, and report-only footer remain the same. Refused fields remain dirty after partial Apply. No store shape, calculation, backend request or new behavior is added. The independently approved plan bytes and SHA256 are preserved. Integrated code audit must include this component along with all other phase application changes.

Phase20%, sizeL, complexity5; T2 task20%, sizeM, complexity5, implementation ongoing. No completion/audit claim is made by this clarification.
