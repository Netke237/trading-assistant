---
name: K-adversarial-audit-loop
description: 'Write (or take) an implementation plan, code diff, or feature, spawn an independent subagent that runs the bmad-review-adversarial-general skill against it, fix every finding, then re-audit with a fresh subagent — repeating until an audit round comes back clean. Use whenever Kenneth says things like "audit this with bmad adversarial", "spawn a subagent with bmad adversarial and fix iteratively until no more errors", "have this reviewed adversarially", or asks for a plan/change to be audited and fixed until clean. Two modes: audit-only (default — stops after the plan or diff is clean and reports back) and audit-and-implement (also runs subagent-driven-development to build the clean plan, then loops a second adversarial audit over the resulting code until that is clean too). Trigger this instead of manually re-explaining the loop every time.'
---

# K-Adversarial Audit Loop

Kenneth (non-coder, high IT affinity) has one recurring quality-gate workflow across his projects: nothing ships — plan or code — until an adversarial subagent has run out of things to complain about. This skill is that workflow, packaged so it doesn't need to be retyped.

**Why a subagent, not you directly:** the `bmad-review-adversarial-general` skill asks the reviewer to be "a cynical, jaded reviewer with zero patience." You wrote (or are fixing) the content, so you're the wrong reviewer for that role — you already believe it's right. A fresh subagent with no investment in the work, spawned via the `Agent` tool, can actually play the skeptic. Spawn a **new** subagent each round, not a reused one — a subagent that already saw round 1's findings and watched you fix them is primed to rubber-stamp round 2.

## Two modes

- **Audit-only** (default): audit whatever content exists (a plan you write, or a diff/branch/feature Kenneth points at), fix findings, repeat until clean, then stop and report. Use this when Kenneth just wants the plan or change validated, not built.
- **Audit-and-implement**: run the audit-only loop on a plan first, then hand the clean plan to `subagent-driven-development` (or implement directly if the plan is small enough that spinning up that skill is overkill) to build it, then run a **second** audit-only loop over the resulting diff before declaring done. This matches Kenneth's heavier sessions where he explicitly asks for plan review *and* a post-implementation pass.

If Kenneth doesn't say which mode, ask — it's the difference between "tell me if this plan is sound" and "build this and don't stop until it's solid," and guessing wrong wastes a full loop.

## The audit loop (core mechanic, used by both modes)

**Task metadata:** In this repository, follow `docs/agents/task-ratings.md` before publishing audit findings as tasks or starting remediation. Every phase/defect/build ticket needs exactly one `size:*` label, one `complexity:*` label, and a completion percentage tied to recorded milestones. Include the estimate rationale and evidence in tracking updates; re-estimate after the plan review or a material scope change. Discovery and a clean evidence audit do not count as implementing the fixes. Preserve existing claims, audit counters and merge gates.

1. **Establish the content.** Either write the implementation plan yourself (use `writing-plans` if it applies) or identify the existing artifact Kenneth means — a diff, branch, uncommitted changes, or a described feature. Don't start round 1 until you can point to something concrete.

2. **Spawn an audit subagent.** Use the `Agent` tool, `run_in_background: false` (you need the findings before you can act on them). Prompt it explicitly to invoke the `bmad-review-adversarial-general` skill via the `Skill` tool, point it at the exact content (file paths, plan text, or `git diff` scope), and ask it to return findings as a markdown list. Give it enough standalone context to actually review — it has no memory of this conversation.

3. **Read the findings.**
   - If the subagent reports zero findings, that's a HALT condition per the adversarial skill itself — it's suspicious on a first pass. Sanity-check that the subagent actually reviewed the right content (wrong file scope is the usual cause) before treating it as genuinely clean. A later round coming back clean after real fixes is expected and fine.
   - Otherwise, fix every finding you agree with. If a finding is wrong or out of scope, don't silently drop it — note briefly why you're not fixing it (you'll want this if Kenneth asks later).

4. **Re-audit with a fresh subagent.** Spawn a new one, same instructions, pointed at the updated content. Don't reuse the previous subagent's context.

5. **Repeat until a round returns clean** (real clean, per the sanity check in step 3) or until you and the findings stop changing meaningfully round over round — if the same class of issue keeps reappearing after two fix attempts, stop and flag it to Kenneth rather than looping indefinitely.

6. **Report the loop, not just the outcome.** Kenneth's sessions consistently end with a tally like "3 rounds, 10 issues found → 6 fixed, 4 deferred (reason)." Give him that shape: rounds run, findings per round, what got fixed, what got deferred and why.

## Audit-and-implement: chaining in the build

Once the plan passes the loop above:

1. Hand off to `subagent-driven-development` (or implement directly for a small, low-risk plan — use judgment, don't invoke a whole skill to change three lines) to build what the plan describes.
2. Run the **same audit loop** again, this time pointed at the resulting diff (`git diff` against the branch point, or the specific changed files) instead of the plan text.
3. Only report done once *this second loop* also lands on a clean round. A plan can be flawless and the implementation still drift from it — that's exactly what the post-implementation pass catches.

## Notes from how this has actually played out

- Kenneth often runs this on both a plan-in-progress and, separately, on "the last changes" (an already-implemented diff) — read his request carefully for which one he means; don't assume plan when he means diff.
- When multiple independent tasks are being planned in parallel, it's fine to run more than one audit loop concurrently (separate `Agent` calls) rather than serializing them — but keep each loop's fix work scoped to its own content so fixes don't collide.
- If the content under audit spans both a plan doc and existing project code (e.g., a plan that touches `backend/app/scoring/`), tell the audit subagent about both so it can check the plan against real code, not just for internal consistency.
