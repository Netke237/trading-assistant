# llm-contexts/ — historical planning and task documents

These files are point-in-time task specs, plans, and context dumps written during earlier
development phases. **None of them are guaranteed current.** For the authoritative, maintained
description of this codebase, see `/CLAUDE.md` at the repo root. If a file here contradicts
CLAUDE.md, CLAUDE.md wins.

Three files in this directory are known to actively contradict each other and/or CLAUDE.md's
current architecture (kept for historical reference, not because they're accurate):
- `01-backend-fastapi.md` — describes a pre-database, fixture-only backend that no longer exists.
- `CONTEXT_FIX_STARTUP_AND_PERFORMANCE.md` — describes a Windows dev setup with `.bat` scripts
  that no longer exist; the real entrypoint is `backend/app/main.py`.
- `04-execution-params.md` calls Direction+Horizon "Step 2"; `05-step-reorder.md` (later, in the
  same directory) documents the reorder that moved it to Step 3, matching CLAUDE.md's current
  `step-3-direction`. If in doubt, `05-step-reorder.md` and CLAUDE.md are the more current ones.

`Bamendjou Stabilization Plan.md` is a separate case — not stale so much as written for a
different tool (DeepSeek, not Claude Code); see the note at the top of that file.
