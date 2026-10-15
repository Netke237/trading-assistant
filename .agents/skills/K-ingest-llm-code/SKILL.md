---
name: K-ingest-llm-code
description: Use when a parallel LLM worktree is ready to merge — reviewing a PR from an implementer LLM before it touches main. Covers file ownership, typecheck, interface compliance, design-system compliance, API contracts, and post-merge coordinator actions.
---

# K-ingest-llm-code — Multi-LLM Cohesion Review

## Overview

When parallel LLMs implement independent workstreams, each one only sees its own context doc.
This skill is the coordinator's gate: **nothing merges without passing all 6 checks in order.**

Core principle: *The context doc is the contract. The PR is the delivery. This review verifies delivery matches contract.*

---

## The 6 checks — run in order, stop on first failure

### Check 1 — File ownership

```bash
git diff --name-only main...<branch>
```

Compare output against the **Owned Files** table in the workstream's context doc.

| Verdict | Condition |
|---|---|
| PASS | Every changed file is listed in the Owned Files table |
| REJECT | Any file outside the table was modified |

**No exceptions.** A file listed as "read-only" being modified is an automatic reject — even if the change looks harmless.

---

### Check 2 — Typecheck gate

```bash
cd frontend && npm run typecheck
```

| Verdict | Condition |
|---|---|
| PASS | Zero errors |
| REJECT | Any error, any warning treated as error |

For backend workstreams:
```bash
cd backend && python -m mypy app/ --ignore-missing-imports
```

---

### Check 3 — Interface compliance

Verify no shared contracts were changed without coordinator approval.

```bash
# Check shared store files were not modified
git diff --name-only main...<branch> | grep "frontend/lib/"

# Check domain types were not modified
git diff --name-only main...<branch> | grep "types/domain.ts"
```

**Allowed:** A workstream reads from a shared store (imports only).
**Not allowed:** A workstream modifies a shared store interface or `types/domain.ts`.

If the context doc says "Zero conflict" — any shared file in the diff is a reject.
If the context doc says "Medium conflict" — only the explicitly named shared file is allowed.

Also check: did the LLM invent new TypeScript types not defined in `types/domain.ts` or the context doc?

```bash
git diff main...<branch> -- "*.tsx" "*.ts" | grep "^+.*interface \|^+.*type .* ="
```

Review each new type against the context doc's "Domain types" section. Undeclared types → reject.

---

### Check 4 — Design system compliance

```bash
# Hardcoded hex colors (auto-reject)
git diff main...<branch> -- "*.tsx" "*.ts" "*.css" | grep "^+" | grep -E "#[0-9A-Fa-f]{3,6}\b"

# Tailwind classes (auto-reject)
git diff main...<branch> -- "*.tsx" | grep "^+" | grep -E "className.*\b(flex|grid|p-|m-|text-|bg-|border-)[0-9a-z]"

# Inline style objects (flag for review — allowed only for computed one-offs)
git diff main...<branch> -- "*.tsx" | grep "^+" | grep "style={{" 
```

| Finding | Verdict |
|---|---|
| Hardcoded hex color | REJECT |
| Tailwind class | REJECT |
| `style={{}}` with a literal value | REJECT |
| `style={{ width: \`${n}px\` }}` (computed) | PASS |

---

### Check 5 — API contract compliance

Only applies to workstreams that add or modify API endpoints.

Verify the response shape in the implementation matches the contract specified in the context doc's "Integration constraints" section:

- Field names match exactly (camelCase on frontend, snake_case on backend — check `api.ts` mapping)
- No extra fields added without coordinator approval
- No fields removed
- TypeScript return type of the `api.*` function matches the Python response model

If there is a mismatch between what the frontend `api.ts` calls and what the backend router returns — **reject and document the delta** so the context doc can be corrected before re-implementation.

---

### Check 6 — Functional spot-check

Run the dev server and navigate to the affected page/step.

```bash
cd frontend && npm run dev
```

Verify:
- [ ] Page renders without console errors
- [ ] The acceptance criteria in the context doc's "Task spec" section are met (verify each one)
- [ ] Navigation away and back preserves state (if the workstream involved store wiring)
- [ ] No visual regressions on obviously adjacent pages

---

## Post-merge actions (coordinator only)

After a clean merge, the coordinator must:

1. **Update `LLM_CONTEXT.md`** — move the workstream from "What still needs to be done" to "What is done". Update any interface descriptions if new files were created.

2. **Check wave gate** — if this was the last workstream in the current wave, all Wave N workstreams are now merged. Update `IMPLEMENTATION_PLAN.md` wave status and write context docs for Wave N+1.

3. **Scan downstream context docs** — if the merged workstream introduced a new file, a new store, or a new type, check if any Wave N+1 context doc references it. If it does, verify the inline spec in that doc matches the actual implementation. Correct if needed before dispatching.

4. **Delete the worktree** — clean up the merged branch's worktree.

```bash
git worktree remove <worktree-path>
git branch -d <feature-branch>
```

---

## Auto-reject red flags (stop review immediately)

| Red flag | Why |
|---|---|
| File outside owned-files table was modified | Breaks parallelism — may conflict with another workstream |
| `npm run typecheck` fails | Integration boundary is broken |
| `types/domain.ts` modified without coordinator approval | Ripples to every file in the project |
| Hardcoded hex color in new code | Design system drift — invisible at first, catastrophic at scale |
| New shared store interface method added | Other workstreams built against the old interface |
| API response shape diverges from context doc contract | Frontend and backend desync silently |

---

## Cohesion hierarchy

When in doubt about what takes precedence:

```
LLM_CONTEXT.md  (master — never contradicted)
    ↓
Context doc for this workstream  (scoped spec)
    ↓
types/domain.ts  (type contracts)
    ↓
Implementation
```

If the implementation contradicts the context doc → reject.
If the context doc contradicts LLM_CONTEXT.md → the context doc was wrong; fix it and re-implement.

---

## Quick reference

```
1. git diff --name-only  →  owned files only?
2. npm run typecheck     →  zero errors?
3. grep shared lib/      →  interfaces untouched?
4. grep hex / tailwind   →  design system clean?
5. api.ts ↔ router       →  contract aligned?
6. npm run dev           →  acceptance criteria met?
→ merge + update LLM_CONTEXT.md + check wave gate
```
