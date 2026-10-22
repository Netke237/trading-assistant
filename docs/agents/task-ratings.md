# Task size, complexity and completion

Required by Kenneth on 2026-10-19. Apply to every new board phase and build ticket, including confirmed audit defects, and to existing tasks when resumed or re-scoped. This is reporting metadata; it does not change claims, dependencies, audit counters, acceptance criteria or merge gates.

## Two required labels

Apply exactly one `size:*` and one `complexity:*` label before publishing a new task or starting an existing one. Estimate the task's own scope; a build ticket does not automatically inherit its parent's size. Preserve unrelated labels, especially status and ownership labels. When re-estimating, replace only the superseded rating label on that issue, never delete the repository label. Record the reason in a tagged issue comment. Create missing label definitions once; do not silently skip them.

Size estimates engineering effort for the fix, regression coverage and required reviews. Exclude time waiting for dependencies, other agents or CI queues. These are planning ranges, not delivery promises; repository-wide test runtime may add elapsed time.

| Label | Estimated effort |
| --- | --- |
| `size:XS` | Up to 2 hours |
| `size:S` | More than 2, up to 4 hours |
| `size:M` | More than 4, up to 8 hours |
| `size:L` | More than 8, up to 16 hours |
| `size:XL` | More than 16 hours; consider splitting |

Complexity measures technical difficulty and uncertainty independently of effort, severity and priority.

| Label | Technical difficulty |
| --- | --- |
| `complexity:1` | Straightforward local change with an established solution |
| `complexity:2` | Small change with limited state or integration concerns |
| `complexity:3` | Several components or a validation/API contract to coordinate |
| `complexity:4` | Async races, persistence transactions, numerical units or legacy compatibility |
| `complexity:5` | Interacting concurrency/data-integrity mechanisms or substantial compatibility uncertainty |

Add a one-sentence rationale covering the relevant scope and risks. Recheck estimates after a clean plan review and whenever scope materially changes. A blocker alone does not increase size or complexity.

## Completion percentage

Report the highest fully evidenced milestone below. Percentages are fixed workflow markers, not estimates of code written or time spent, and they are not additive. Do not credit the original discovery audit as remediation work. If evidence is missing, report the last verifiable milestone and the missing record. Do not reset or repeat completed audit rounds to reconstruct progress.

| Completion | Required evidence |
| --- | --- |
| 0% | Queued; no concrete fix plan |
| 10% | Concrete fix plan drafted; clean independent approval pending |
| 20% | Exact plan independently approved and verdict recorded |
| 50% | Planned implementation exists; acceptance coverage still pending |
| 70% | Regression retests and all required local checks pass |
| 85% | Exact implementation independently audited clean |
| 95% | Exact PR head passes CI and all pre-merge conditions |
| 100% | Merge verified and required integrated/post-merge regression retests recorded |

Every issue update and stop report includes completion, size, complexity, current milestone, evidence and next unmet milestone. If later changes or failures invalidate a milestone, lower the percentage with a reason. For a phase split into build tickets, credit implementation/testing only once all required tickets meet that milestone. For an audit-only or documentation-only task, define applicable milestones and N/A reasons in its plan before reporting progress; never infer successful implementation or retests from N/A stages.

Report completed/total tasks separately from percentage. Do not average differently sized tasks into an overall percentage without an explicit weighting model. `100%` does not replace the authoritative shipped/audit/merge state.

## Publication checklist

1. Read the live issue, scope, blockers, existing labels and implementation/audit records.
2. Estimate size and complexity, with a rationale; derive completion from evidence.
3. Perform the board ownership check before each GitHub write. A coordinator may label its claimed phase's child issues as tracking metadata; this does not claim those phases or authorize their implementation.
4. Apply the two rating labels, preserving every unrelated label, and verify them by reading back the issue.
5. Publish a tagged progress comment and include the ratings in the phase's tracking summary. Continue the existing independent plan/build/code workflow.
