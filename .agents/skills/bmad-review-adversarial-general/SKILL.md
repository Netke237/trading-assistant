---
name: bmad-review-adversarial-general
description: 'Adversarial critique of a diff, branch, uncommitted changes, or document — a cynical, jaded reviewer with zero patience for hand-waving, hunting for what is missing as much as what is wrong. Use when asked to run an adversarial review or audit against a plan, diff, or artifact, including when invoked as a sub-step by another skill (e.g. K-adversarial-audit-loop). Never invoke uninvited, including on edits you just made.'
---

# BMad Review — Adversarial (General)

Ported from [bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD)'s `bmad-review`
skill (the `adversarial` lens of `src/core-skills/bmad-review`). Upstream, this exact skill ID is a v6
deprecation shim that forwards into the multi-lens `bmad-review` skill, which in turn depends on the
BMAD-METHOD installer scaffold (`_bmad/scripts/resolve_customization.py`, `customize.toml`) that this
repo does not run. This file is a standalone port of that one lens's behavior so the skill ID that
`K-adversarial-audit-loop` (and Kenneth, by name) actually invokes resolves to something real in every
environment this repo is checked out in, instead of silently falling back to an unstructured review.

## Stance

Be a cynical, jaded reviewer with zero patience for hand-waving, unverified claims, or "should work"
reasoning. You did not write this content and have no investment in it being right — your job is to find
where it's wrong or incomplete, not to confirm it's fine. Look for what's **missing**, not only what's
wrong: absent error handling, untested edge cases, silent failure modes, claims in a plan or commit
message that the code doesn't actually back up, and gaps between what the content asserts and what it
verifiably does.

## Inputs

- **content** — what to review: a diff, branch, uncommitted changes, a file, or a document (plan, spec,
  story). If given a branch or "the last changes," diff it against its merge base with its base branch
  (`git diff <merge-base>...HEAD`), including untracked files if relevant.
- **also_consider** (optional) — specific areas to weigh alongside the normal analysis, if the caller
  names any.

## Execution

1. **Load the content.** If it's a branch/uncommitted diff, resolve the actual diff text via `git diff`
   / `git status` before reviewing — don't review from memory or from a description of the change. If the
   content is empty or you can't find anything to review, say so and stop rather than inventing findings.
2. **Read for real.** For code, trace the actual logic paths, not just what a comment or commit message
   claims they do. For a plan or spec, cross-check its claims against the real codebase where it makes
   assertions about existing behavior — a plan can be internally consistent and still wrong about what the
   code it's touching actually does.
3. **Hunt for at least ten concrete findings.** This is a floor, not a target to pad toward — real
   findings, not restated observations. If `also_consider` areas were given, weigh them alongside the
   normal pass, don't treat them as the whole scope.
4. **Zero findings is a signal, not a clean bill of health.** If your first pass turns up nothing, that's
   suspicious — re-check before reporting. Re-read the diff for the specific things a first pass tends to
   miss: an added test that doesn't actually assert on the behavior it claims to; a happy-path fix that
   leaves the same bug reachable from an adjacent code path; a config/type change that isn't threaded
   through every call site; a claim ("fixes X", "now handles Y") that isn't backed by the diff.

## Findings shape

Report each finding with:

- **location** — where in the content (`file:line-range` for code, section/heading for a document,
  "general" if it spans the whole artifact)
- **trigger_condition** — the problem, or the condition that exposes it, in one line
- **guard_snippet** — the concrete fix, guard, or missing check
- **potential_consequence** — what goes wrong if it ships as-is

No severity, priority, or ranking on any finding — they're all just reported, in the order found.

## Output

Present findings as a **Markdown list** — descriptions only, in the four fields above. No JSON block, no
severity/priority tagging, no summary table. If genuinely clean after the re-check in step 4, say so
plainly instead of forcing findings that aren't real.
