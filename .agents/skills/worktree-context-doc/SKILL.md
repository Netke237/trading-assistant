---
name: worktree-context-doc
description: Generate scoped LLM context documents for parallel worktrees. Use this whenever you need to split implementation work across multiple LLMs working simultaneously in separate git worktrees — e.g. "create context docs for each feature branch", "prepare parallel LLM work", "write a context document for [workstream]", "split this into parallel agents". Each generated document is fully self-contained (all values inline, no external references) and follows the cold-start briefing format so a fresh LLM can implement exactly one workstream without disrupting the shared framework.
---

# Worktree LLM Context Document

A scoped context document lets a fresh LLM implement one workstream of a larger project in a git worktree, without needing conversation history and without accidentally modifying shared infrastructure.

The critical property: **every value is inline**. No "see tokens.css for colors". The LLM reading this document needs no other file to understand the constraints — only the files it owns.

---

## Step 0: Read the master context first

Before writing any scoped document, read the project's master LLM context document (usually `LLM_CONTEXT.md` at the project root). That is the source of truth for tokens, primitives, types, and rules. Scoped documents derive from it — they do not contradict it.

---

## Required sections in every scoped document (in this order)

### 1. Mission
One paragraph: what this LLM builds + the single most important constraint ("do not touch `frontend/`" or "do not modify any shared store interface").

State the **conflict class**:
- **Zero conflict** — owns its own folder, modifies no shared files
- **Medium** — separate file in a shared parent folder (state: "do not add new exports to `[shared file]`")
- **Infrastructure** — touches shared tokens/stores (document merge strategy here)

### 2. Owned files
A table with three columns: `File path` | `Status (Create/Modify)` | `Purpose (one line)`.
Every file this LLM touches. Nothing outside this list. Be exhaustive — if a CSS module is needed, list it.

### 3. Read-only references
Files to read for context, never modify. Include path + one-line reason.

### 4. Integration constraints
The seam between this workstream and the rest of the codebase. Be surgical:
- Exact `import` statements for shared components/stores/types
- Prop shapes for components this workstream *consumes* (not owns)
- Store interfaces: which actions to call, what shape to read
- What the persistent frame already provides (TopBar, NavRail — don't recreate them)
- For backend workstreams: exact route paths + response field names + HTTP method

### 5. CSS tokens (full list)
Copy the complete token block from the master context. Never truncate — LLMs working in isolation need every hex value and every spacing variable inline.

### 6. Primitives & component reference
Copy the `<Text>`, `<Title>`, `<Data>` primitive specs and the key atoms/molecules/organisms table from the master context. Note which are directly relevant to this workstream.

### 7. Domain types (relevant subset)
Only the TypeScript interfaces this workstream uses. Preserve all fields, types, and JSDoc. Use the exact definitions from `types/domain.ts`.

### 8. Zustand stores (relevant stores only)
Interface + default seed values for each store this workstream reads or writes. Copy from the master context. If the workstream only reads a store, say so explicitly.

### 9. Mock data (exact values)
The actual fixture data for this workstream — symbol names, prices, dates, exact numbers. The LLM uses this to verify its UI renders correctly. Don't summarize; paste the values.

### 10. Task spec
What to build. Include:
- Acceptance criteria (testable, specific — "renders 10 rows" not "renders data")
- Column/grid layout if the workstream has a table (exact CSS grid-template-columns string)
- Known issues to fix if this is a polish workstream
- Edge cases to handle

### 11. Hard rules
Paste all rules from the master context (no Tailwind, no hardcoded colors, etc.) plus any workstream-specific additions. Rules that apply to all workstreams:
1. No Tailwind, styled-components, or CSS-in-JS.
2. No `style={{}}` except computed one-off values (e.g. `style={{ width: \`${pct}%\` }}`).
3. No hardcoded colors — always use CSS custom properties from `tokens.css`.
4. No invented Status labels — only `PASS | CAUTION | REJECT | PENDING | NO_DATA`.
5. No font-weight 600 on form labels — use `weight={400}`.
6. No card box-shadows — use `border: 1px solid var(--border-subtle)`.
7. Never skip component hierarchy: atom → molecule → organism.
8. `npm run typecheck` must be clean before every commit.
9. Do not touch `node_modules/` or `package-lock.json`.

### 12. Dev workflow
```bash
cd frontend          # (or backend for API workstreams)
npm run dev          # localhost:3001
npm run typecheck    # must be clean after every edit
```

### 13. Copy/paste prompt
The literal text the user can paste to the implementing LLM. Make it standalone — it should work even if the LLM hasn't seen this skill document.

```
Read `llm-contexts/<filename>.md` fully before writing any code. It is your single source of truth.

You are implementing [workstream name] for the Bamendjou options screener (Next.js 15, TypeScript strict).

Your owned files:
[exact file list from section 2]

Do not modify any file outside this list.

Task: [one sentence]

After every file edit, run `npm run typecheck` from `frontend/`. Must stay clean.
Commit after each file is complete.
```

---

## Completeness checklist (run before saving)

- [ ] Every CSS token hex value present — not "see tokens.css"
- [ ] Every TypeScript interface used is defined inline
- [ ] Integration constraints name exact `import` paths, not vague descriptions
- [ ] Mock data contains actual values (numbers, strings), not descriptions of values
- [ ] Owned-files table is exhaustive (includes CSS modules)
- [ ] Copy/paste prompt is actionable without reading any other file

---

## Output location

Save to `llm-contexts/<NN>-<slug>.md` at the project root, where `NN` is a zero-padded sequence number matching the workstream order.

---

## Quality bar

A scoped document passes review when: a completely fresh LLM, given only that file and the files it owns, would produce output that typechecks, matches the design system, and integrates without merge conflicts. That is the target. If any value is vague or missing, add it.
