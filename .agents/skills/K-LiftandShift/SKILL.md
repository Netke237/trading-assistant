---
name: K-LiftandShift
description: Creates a production-ready, reusable repository bootstrap for disciplined multi-agent software delivery. Invoke whenever the user types "K-LiftandShift", asks to bootstrap a multi-agent project, wants a new project environment with orchestrated agents, mentions "lift and shift" in a project setup context, wants OpenCode or Oh My OpenCode compatibility, needs a structured multi-agent delivery framework with strict routing and scoped specialists, or wants a /K-* command model. Also trigger when user asks to set up specialist agents with role-to-model assignments, wants auditable multi-agent execution, or requests a neutral repo structure for disciplined delivery.
---

# K-LiftandShift Bootstrap Generator

## Your Role

You are acting as a senior staff engineer, technical program manager, and AI agent workflow architect.

## Core Intent

Build a neutral repository structure that works with both Codex and OpenCode. Add an Oh My OpenCode compatibility layer without making the repo depend exclusively on it. Preserve: strict routing, scoped specialists, low-drift execution, auditable completion, evidence-based acceptance, and controlled escalation. Prefer deterministic and practical workflows over cleverness.

**Default assumption:** If project type is not specified, assume a moderately complex full-stack web application with backend, frontend, automated tests, and documentation.

---

## Step 1 — State the Core Purpose

Before writing any files: infer and briefly state in one paragraph the core purpose of this bootstrap.

---

## Step 2 — Generate These Artifacts (in order)

| # | File | Rule |
|---|------|------|
| 1 | `PRD.md` | What and why — not how |
| 2 | `IMPLEMENTATION_PLAN.md` | How, sequencing, dependencies, role ownership, escalation, Superpower placement |
| 3 | `ACCEPTANCE_CRITERIA.md` | Objective and testable only |
| 4 | `TASK_MATRIX.md` | Only if it materially preserves owner/fallback routing — otherwise omit |
| 5 | `AGENTS.md` | Project rules, agent operating constraints, skill usage policy |
| 6 | `opencode.jsonc` | Generic portable config with role-to-model mapping |
| 7 | Repository folder structure | Proposed tree including skill directories |
| 8 | `README_BOOTSTRAP.md` | How to start with Codex and with OpenCode |
| 9 | Role-to-model assignment table | Exact assignments + brief justification, no changes |

### Document Policy

- Minimal document set. No redundancy. No extra artifacts unless they eliminate ambiguity or materially improve execution control.
- `TASK_MATRIX.md` exists **only if** it meaningfully preserves owner/fallback routing. Do not generate it to fill space.
- Do not invent implementation details not supported by the PRD.

---

## Step 3 — Agent Design

### Required Role Names (use exactly)

```
orchestrator  builder-a  builder-b  builder-c  builder-d
reviewer      tester-1   tester-2   tester-3   tester-4   docs
```

### Role Behaviors

| Role | Behavior |
|------|----------|
| `orchestrator` | Controls routing, task distribution, escalation, and final arbitration |
| `reviewer` | Validates evidence and acceptance rigor; jointly approves acceptance with orchestrator |
| `docs` | Documentation ownership + librarian-style retrieval and synthesis |
| `builder-*` | True specialists, parallelizable — not generic clones |
| `tester-*` | True specialists, parallelizable — not generic clones |

### Builder Specialization (exact)

| Role | Specialization |
|------|----------------|
| `builder-a` | Frontend / UI implementation |
| `builder-b` | Backend / API implementation |
| `builder-c` | Data / schema / integration implementation |
| `builder-d` | Platform / tooling / refactor / cross-cutting implementation |

### Tester Specialization (exact)

| Role | Specialization |
|------|----------------|
| `tester-1` | Unit and component verification |
| `tester-2` | Integration and API verification |
| `tester-3` | End-to-end and UI verification with Playwright |
| `tester-4` | Regression, nonfunctional, and observability verification |

### Model Assignment Table — PRESERVE EXACTLY, DO NOT MODIFY

| Role | Model |
|------|-------|
| `orchestrator` | Kimi K2.6 |
| `reviewer` | GLM-5.1 |
| `builder-a` | Qwen3.6 Plus |
| `builder-b` | DeepSeek V4 Flash |
| `builder-c` | DeepSeek V4 Pro |
| `builder-d` | Kimi K2.6 |
| `tester-1` | DeepSeek V4 Flash |
| `tester-2` | GLM-5.1 |
| `tester-3` | Kimi K2.6 |
| `tester-4` | Qwen3.6 Plus |
| `docs` | MiniMax M2.7 |

These assignments must appear in: `AGENTS.md`, `opencode.jsonc` (where generically expressible), and the role-to-model section.

Do not substitute, rebalance, normalize, or reinterpret these assignments. If an assignment cannot be expressed generically in `opencode.jsonc`, preserve it in documentation and compatibility notes — do not change it.

---

## Step 4 — Core Constraints

- Orchestrator controls all task distribution.
- Specialist agents are role-scoped and must not exceed assigned scope.
- All completion claims must be backed by runtime evidence:
  - exact command
  - relevant output summary
  - artifact path where applicable
- UI acceptance requires Playwright runtime proof.
- Builders load only skills needed for their assigned task.
- If a skill is missing, locked, or ambiguous: **escalate — do not improvise**.
- Agents must not silently change product requirements.
- If ambiguity is encountered: **stop and escalate**.
- Only `reviewer` and `orchestrator` may approve final acceptance.

---

## Step 5 — Skill Matching Rules

When defining agents and workflows:

- Prefer reusable skills over embedding large task instructions into agent prompts.
- Check for relevant existing skills before expanding agent instructions.
- Use **Superpower-related skills** for: planning, decomposition, routing, evidence, escalation, implementation-control.
- Use **Vercel-related skills** for: frontend, deployment, platform, preview, web application tasks.
- Agents load only skills directly relevant to their assigned task.
- If a relevant skill is missing or ambiguous: use `find-skills` first; if still unresolved, escalate.

The repo structure must include:
```
.opencode/skills/
.Codex/skills/
.agents/skills/         (optional)
```

`AGENTS.md` must document: how skills are discovered, when to load them, and which roles may use which skill families.

---

## Step 6 — Escalation Rules

The orchestrator escalates to the user **only** at:

1. Scope ambiguity
2. Destructive changes
3. Architecture-affecting design choices
4. Unavailable or blocked required capability
5. Final sign-off

---

## Step 7 — Slash Command Model (`/K-*`)

All commands start with `/K`. Define them as repo conventions in `AGENTS.md` and `README_BOOTSTRAP.md`:

| Command | Purpose |
|---------|---------|
| `/K-plan` | Initialize planning; orchestrator distributes tasks from PRD + IMPLEMENTATION_PLAN |
| `/K-build` | Trigger builder agents for assigned tasks |
| `/K-test` | Trigger tester agents for assigned test scope |
| `/K-review` | Trigger reviewer for evidence validation |
| `/K-docs` | Trigger docs agent for documentation or retrieval |
| `/K-escalate` | Surface a blocked or ambiguous case to orchestrator/user |
| `/K-accept` | Orchestrator and reviewer jointly sign off on acceptance criteria |
| `/K-sync` | Refresh task context; re-read TASK_MATRIX.md and current state |

---

## Step 8 — Oh My OpenCode Compatibility Layer

Create a compatibility layer section that explains how the neutral repo maps to Oh My OpenCode:

| Neutral Role | Oh My OpenCode Concept |
|---|---|
| `orchestrator` | Main orchestrator / lead agent |
| `builder-*` | Specialist delegation |
| `tester-*` | Specialist delegation (verification) |
| `reviewer` | Review and evidence validation step |
| `/K-*` commands | Command-oriented usage |
| Parallelizable builder/tester tasks | Background work |

Rules:
- Do not rename roles.
- Keep Oh My OpenCode assumptions isolated and clearly marked optional.
- The repo must be fully functional without Oh My OpenCode.
- Explain explicitly whether generic portability reduces any Oh My OpenCode convenience.

---

## Step 9 — opencode.jsonc Requirements

- Generic and portable — avoid hardcoding a single provider or plugin.
- Support broad LLM/provider usage.
- Include exact role-to-model mapping wherever expressible in neutral OpenCode-compatible form.
- Document (in comments) any assignments that cannot be expressed generically.
- Mark Oh My OpenCode-specific assumptions as clearly optional sections.

---

## Step 10 — TASK_MATRIX.md (if included)

If generated, each row must contain:

| Field | Requirement |
|-------|-------------|
| `task_id` | Unique identifier |
| `description` | What the task does |
| `owner` | Primary agent role |
| `fallback` | Fallback agent if owner is blocked |
| `inputs` | Required inputs |
| `outputs` | Expected outputs |
| `done_criteria` | Objective completion test |
| `escalation_rule` | When and to whom to escalate |

Do not duplicate the full implementation plan inside the matrix.

---

## Step 11 — Required Examples

Include **all six** of the following examples (in `README_BOOTSTRAP.md` or a dedicated `EXAMPLES.md`):

1. **Orchestrator feature split** — How `orchestrator` splits one feature into two builder tasks with explicit routing
2. **Tester escalation** — How a tester escalates a blocked or ambiguous case
3. **Playwright acceptance rule** — A concrete Playwright-based acceptance rule for a UI task
4. **Runtime proof (non-UI)** — A runtime proof requirement for a non-UI task (exact command, output summary, artifact path)
5. **Oh My OpenCode mapping** — How the neutral role model maps into the Oh My OpenCode compatibility layer with a concrete example
6. **End-to-end `/K-*` workflow** — Full run from `/K-plan` through `/K-accept` for one feature

---

## Step 12 — Output Structure

Present in this exact order:

**A. Executive Summary** — Core purpose, one paragraph
**B. Repository Structure** — Full proposed folder tree
**C. File-by-File Content** — Full content of each generated file
**D. Agent Design** — Role table, specializations, model assignment table
**E. Compatibility Strategy** — Oh My OpenCode compatibility layer
**F. Permission Strategy** — Who can do what, with what scope
**G. Escalation Strategy** — All escalation points and decision flow
**H. Bootstrap Instructions** — Step-by-step: starting with Codex; starting with OpenCode
**I. Superpower Placement** — Exactly where Superpower methodology lives in `IMPLEMENTATION_PLAN.md`
**J. Exact Changes Made** — Deltas only (Added / Removed / Changed) — not a rewrite

---

## Style Requirements

- Concrete, opinionated, self-consistent, practical.
- No generic best practices unless converted into actual files, rules, or commands.
- File contents concise but production-ready.
- Markdown for all spec documents.
- Minimize redundancy.
- Do not invent details not supported by the PRD.
- Do not provide implementation code for the target project — generate governance structure only.

---

## Neutral Repo Principle

The generated repository must be:
- Fully usable without Oh My OpenCode
- Fully understandable through its documents and `opencode.jsonc`
- Governed neutrally — not dependent on a single orchestration plugin
- Process truth lives in `IMPLEMENTATION_PLAN.md`, not in any plugin
