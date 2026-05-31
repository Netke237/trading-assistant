# Bamendjou Stabilization Plan

This document defines **all allowed actions** for the LLM (DeepSeek) when working on the Bamendjou project.  
DeepSeek must **not** perform actions outside this document.

## Global Guardrails

- Do **not** change more than required for each explicit task.
- Do **not** upgrade to Next.js 16 or change the major version of any dependency unless explicitly allowed.
- Do **not** introduce new libraries or tools without asking.
- Do **not** run destructive shell commands such as:
  - `taskkill` (except when explicitly allowed for investigation with no side effects),
  - `rm -rf` outside `node_modules`,
  - any command that kills the LLM’s own host process or developer shells.
- Always show a **unified diff** (`git diff`) of all changed files at the end of each task.
- Prefer small, incremental, reversible changes.
- If anything is ambiguous, ask a **clarification question** instead of guessing.
- Use existing `package.json` scripts where possible.
- Assume `npm` and `Playwright` are available in the environment.

DeepSeek must follow the **phases below in order**.  
After each phase, stop and show:
- A short summary (3–5 bullets),
- The relevant `git diff`,
- The key command outputs.

## Superpowers / Skills Usage

- When available, consider using Superpowers / MCP skills that match the current phase:
  - Use planning / debugging skills for analysis and design.
  - Use execution skills for editing files and running commands.
  - Use verification skills to confirm work is complete before claiming success.
- Always keep the phase structure in this document as the *top‑level authority*.
  - A skill may add internal steps but may not skip or reorder phases.
- When a verification or “finish” skill is used, you must:
  - Run the commands requested in this phase (e.g. `npm ci`, `npm run build`, `npx playwright test`),
  - Paste the actual command output,
  - Then show `git diff` before saying the phase is complete

---

## Phase 0 – Baseline Inspection (Read‑Only)

**Goal:** Understand current state without changing anything.

Steps:

1. Detect project layout:
   - Identify where the Next.js frontend lives (e.g. project root, `/frontend`, etc.).
   - Identify where Playwright config and tests live.

2. Report:
   - Path to the main `package.json` that contains the `next` dependency.
   - Path to the main lockfile (`package-lock.json`, `pnpm-lock.yaml`, or `yarn.lock`).
   - Path(s) to Playwright config file(s) and any global test setup file(s).

3. Inspect versions:
   - Read `package.json` and report the current values of:
     - `next`
     - `react`
     - `react-dom`
   - Read the lockfile and confirm which exact `next` version is currently resolved.

4. Output:
   - A concise report of the above (no changes yet).
   - Confirm that you are ready for Phase 1.

**Constraints:**  
No file modifications, no commands that change the working tree.

---

## Phase 1 – Stabilize and Pin Next 15.x

**Goal:** Stay on Next 15.x, but move to a stable, pinned minor/patch (e.g. `15.5.18`) and ensure reproducible builds.

### Phase 1 Tasks

1. Choose target versions:
   - Determine the latest safe Next.js **15.x** version (for example `15.5.18`).
   - Confirm that it is compatible with the existing React major version (likely React 18).

2. Update `package.json`:
   - In the Next.js app `package.json`, update dependencies so that:
     - `next` is set to an **exact** 15.x version (no `^` or `~`, e.g. `"next": "15.5.18"`).
     - `react` and `react-dom` are also exact versions compatible with that Next version.
   - Do **not** change major versions (stay on the same React major).

3. Regenerate lockfile:
   - Delete only the frontend lockfile (e.g. `package-lock.json`) if necessary.
   - Run:
     - `npm install`
   - This regenerates the lockfile using the new exact versions.

4. Verify reproducible build:
   - Remove `node_modules` for the frontend (allowed destructive command):
     - `rm -rf node_modules`
   - Run:
     - `npm ci`
     - `npm run build`
     - `npm run typecheck` (if defined)
   - Collect outputs and note any errors.

5. Output:
   - Summarize:
     - previous and new versions of `next`, `react`, `react-dom`,
     - build/typecheck results.
   - Show a unified diff of:
     - `package.json`
     - the lockfile
   - Then **stop** and wait for human confirmation before continuing to Phase 2.

**Constraints:**

- Do not upgrade to Next 16.x.
- Do not touch other dependencies unless required to fix build/type errors.
- If build fails due to incompatible versions, explain the error and propose a minimal adjustment.

---

## Phase 2 – Fix Playwright Teardown / EXIT:1

**Goal:** Ensure Playwright can exit with code 0 when tests pass, without killing the parent shell.

### Phase 2 Tasks

1. Locate destructive teardown:
   - Search the repo for:
     - `taskkill`
     - other process‑killing commands in tests or Playwright helpers.
   - List all occurrences with file paths and line numbers.

2. Analyze and plan:
   - For each occurrence, explain its likely purpose (e.g. “cleanup dev server”).
   - Decide whether it is still needed and how to replace it with a safer mechanism.

3. Refactor teardown:
   - In Playwright configs or test utilities:
     - Remove calls that kill `cmd.exe` or the parent shell.
     - If a dev server needs shutting down, use:
       - controlled Node child process handling, or
       - Playwright’s built‑in fixtures (e.g. `webServer` config).
   - Ensure tests still have any required setup/teardown, but without forcing EXIT:1.

4. Run tests:
   - From a clean state (you may re‑use `npm ci` from Phase 1):
     - `npx playwright test`
   - Report:
     - test suite names,
     - number of tests,
     - final **exit code**,
     - any unexpected failures.

5. Output:
   - Short explanation of what changed in teardown.
   - Unified diff of all modified Playwright/test files.
   - Stop and wait for human confirmation to proceed to Phase 3.

**Constraints:**

- Do not add or remove Playwright test cases.
- Do not change assertions or business logic of tests, only teardown/setup as required.

---

## Phase 3 – Make Playwright Fail on Critical React Console Errors

**Goal:** Harden E2E so serious React runtime errors (like infinite loops) fail tests.

### Phase 3 Tasks

1. Locate Playwright global setup:
   - Find any global setup code:
     - `playwright.config.*`,
     - `tests/setup.*`,
     - custom fixtures.
   - Show/describe how pages are currently created and configured.

2. Implement console‑error hook:
   - Introduce a centralized mechanism so that for each test page:
     - A listener is attached via `page.on('console', ...)`.
     - If the console message text includes any of:
       - `"Maximum update depth exceeded"`
       - `"getServerSnapshot"`
       - `"React error"`
     - Then the test should **fail** (e.g. by throwing an error or using Playwright’s `expect` to fail).
   - Keep this mechanism:
     - small,
     - well‑documented (comments),
     - opt‑out capable (e.g. a flag or helper) if a specific test truly needs to ignore it.

3. Re‑run Playwright:
   - `npx playwright test`
   - Record:
     - how many tests fail due to these React console errors,
     - sample error messages.

4. Output:
   - Explanation of where and how console monitoring was added.
   - Unified diff of modified Playwright configuration/setup files.
   - Stop and wait for human confirmation to proceed to Phase 4.

**Constraints:**

- Do not modify application code in this phase.
- Only modify Playwright setup/configuration.

---

## Phase 4 – Fix React Toast / Alert Infinite Loop

**Goal:** Resolve the React “Maximum update depth exceeded” / `getServerSnapshot` warnings from the alert/toast system, without changing observable behavior.

### Phase 4 Tasks

1. Locate the problematic code:
   - Open the dashboard page indicated by the error (e.g. `app/(frame)/dashboard/page.tsx`).
   - Find lines that use something like:
     ```ts
     const toasts = useAlertStore((s) => s.toasts.filter((t) => !t.dismissed));
     ```
   - Also find the implementation of `useAlertStore` and related toast/alert store logic.

2. Analyze the cause:
   - Explain why the current usage triggers an infinite update or repeated re‑renders, such as:
     - creating a new array every render, causing store subscriptions to fire,
     - state updates inside render functions, etc.

3. Propose a minimal refactor:
   - Adjust the store or selector so that:
     - the selector is stable,
     - filtering happens in a way that does not create an infinite loop,
     - the external API of the store and the page remains as close as possible to current behavior.

   Examples of acceptable patterns (pick the one that best fits the existing code):
   - Move the filtering into the store and expose `visibleToasts` as derived state.
   - Use memoization or `useMemo` in the component if appropriate, ensuring no state changes in render.
   - Avoid selectors that allocate new objects on every call if that triggers updates.

4. Implement the fix:
   - Modify only the relevant store and page files.
   - Keep changes minimal and well‑commented.

5. Verify behavior:
   - Run the dev server:
     - `npm run dev`
   - Manually verify:
     - the dashboard loads,
     - toasts/alerts appear and dismiss as expected,
     - no React infinite loop or `getServerSnapshot` error appears in the console.

6. Run tests:
   - `npm run typecheck`
   - `npx playwright test`
   - Ensure the console‑error checks from Phase 3 do **not** fail now.

7. Output:
   - Explanation of the fix in 3–5 bullet points.
   - Unified diff of all modified app/store files.
   - Stop and wait for human confirmation to proceed to Phase 5.

**Constraints:**

- Do not refactor unrelated parts of the state management layer.
- Keep API changes as small as possible.

---

## Phase 5 – Final Stabilization Report (No Code Changes)

**Goal:** Provide a clear summary and verification of the stabilized state.

### Phase 5 Tasks

1. List modified files:
   - Generate a list of all files changed across Phases 1–4.

2. Summarize changes:
   - For each file, give a one‑sentence explanation of what changed and why.

3. Run full verification from clean state:
   - Commands (in order, in the frontend root):
     - `rm -rf node_modules`
     - `npm ci`
     - `npm run build`
     - `npm run typecheck`
     - `npx playwright test`
   - Record whether each command succeeded or failed, with high‑level error descriptions if any fail.

4. Suggest a release tag:
   - Propose a semantic version tag name for this stabilized state (for example, `v1.0.0-next15-stable`).

5. Output:
   - Summary section containing:
     - list of changed files,
     - brief change descriptions,
     - verification command results,
     - proposed tag.
   - **Do not modify any files in this phase.**

---

## End of Plan

DeepSeek must stop after Phase 5 and wait for explicit human instructions for any further changes (e.g. upgrading to Next 16, adding new features, or refactoring larger parts of the codebase).