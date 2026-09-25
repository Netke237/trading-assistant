---
name: k-session-reconciliation
description: Save, resume, harmonize and hand off an interrupted coding task between agents (Claude, Copilot, Codex, Gemini, any other), users and containers (local or cloud) through a model-agnostic `.k-session/` state kept on the git branch. Use this whenever the user wants to continue/resume/pick up a previous or interrupted session, "where did we stop", take over another agent's or colleague's work, checkpoint progress before stopping, hand a task over, or when a `.k-session/` folder or K-SESSION.md exists in the repo — even if they don't say "handoff" or "reconciliation".
---

# K-Session-Reconciliation

Tasks get interrupted: a container is reclaimed, a model hits a limit, a
different person continues on another machine with a different agent. This
skill keeps the task's state **in the repository, on the work branch**, in a
format any agent can read, so the next session can pick it up without guessing
and without breaking what the previous one did.

Everything is driven by one standard-library Python script. On `init` and
`resume` it copies itself into `.k-session/k_session.py`, so Copilot, Codex,
Gemini or any other agent can run it later even without this skill.

```
.k-session/K-SESSION.md   narrative for the next agent (goal, done, next, decisions, conventions)
.k-session/state.json   machine state: task id, branch/base, lock, saved commit, session log
.k-session/k_session.py   vendored tool
AGENTS.md, CLAUDE.md, GEMINI.md, .github/copilot-instructions.md
                      get a marked pointer block telling every agent the protocol
```

Set `T` to the tool path: use `python3 .k-session/k_session.py` if it exists in the
repo, otherwise `python3 ~/.claude/skills/k-session-reconciliation/scripts/k_session.py`.
Run `$T help` to see every command.

Identity rule: the tool records `agent@handle/location`, for example
`claude@anon/cloud`. It never reads git user.name or email. Export
`KSESSION_AGENT` or `KSESSION_HANDLE` (a pseudonym) if detection is wrong.

## Decide which flow you're in

1. `.k-session/state.json` exists on the current branch → **Resume**.
2. It doesn't exist, but the user talks about continuing earlier work → run
   `$T status`. It lists remote branches that carry handoff state. Check out
   the right branch with the user, then **Resume**.
3. The user is starting or already doing a task that may be interrupted, or asks
   to save or checkpoint → **Start/Save**.
4. The task is done and about to be merged → **Finish**.

## Resume (and harmonize)

1. `$T resume`. It fetches, fast-forwards a clean branch that is behind,
   refreshes the vendored tool and pointer blocks, takes the lock, and prints
   the status plus K-SESSION.md.
   - Exit code 3 means another session holds a lock with a heartbeat under 2h.
     Show the holder and heartbeat to the user. Rerun with `--take-over` only if
     they confirm the other session is dead. Two live agents on one branch
     produce conflicting pushes, so don't take over silently.
   - If it reports **PARALLEL SESSIONS**, other branches carry the same task.
     Inspect each one (`git log HEAD..<ref>`, `git show <ref>:.k-session/K-SESSION.md`).
     Propose merging them (`git merge <ref>`) and combine their Done, Next and
     Decisions sections into one K-SESSION.md. Don't drop the other side's
     decisions.
2. **Reconcile the handoff against reality.** K-SESSION.md is what the last agent
   *believed*. Git is what actually happened. Check each "Done" item against
   `git log` and the code. Look at the "since save" commits the status lists,
   because work after the last save isn't described yet. Look at uncommitted
   changes too. Fix K-SESSION.md where it's wrong and tell the user what drifted.
3. **Sync with base when it makes sense**: `$T sync` merges the remote branch
   and then the base branch. It uses merge commits, never rebase or force-push,
   so other people's checkouts stay valid. If it reports conflicts, resolve them
   while keeping both sides' intent, commit, then run it again. Run the
   project's tests/lint listed under Conventions afterwards.
4. **Normalize conventions.** Read the *Conventions* section and follow it,
   whatever your own defaults are: commit style, test commands, tooling. This is
   what keeps a Copilot → Claude → Codex chain consistent. If Conventions is
   empty, work out the conventions from the repo (CONTRIBUTING, recent commit
   messages, package scripts) and write them in.
5. **Summarize, then ask.** Give the user:
   - the goal
   - the status
   - what's verified done
   - what drifted
   - the next step you'd take (the first unchecked item)
   - blockers or open questions

   Wait for their go before changing code. The previous session might have
   stopped for a reason that isn't written down.
6. `$T checkpoint -m "resume: reconciled handoff"` if you changed anything.

## Start / save while working

- New task: `$T init --goal "<one line>" [--base main]`. Then fill in K-SESSION.md:
  concrete Next steps, and Conventions with the real test and lint commands.
- Keep K-SESSION.md current **as you go**, not only at the end. Interruptions
  come without warning, so the file should always be good enough for a
  stranger to continue from.
- After each meaningful step (a test passes, a sub-feature works, before a risky
  refactor, and at least every ~30 minutes of work), update K-SESSION.md and run
  `$T checkpoint -m "<what changed>"`. This saves state, makes a
  `wip(k-session): …` commit of all changes, and pushes. Pushing is the part that
  makes the work survive the container.
- A `pre-commit` hook, which the tool installs and chains with any existing
  hook, adds a heartbeat to state.json on every commit and blocks commits whose
  `.k-session/` contains secrets.
- Before you stop: update K-SESSION.md, run `$T release`, then
  `$T checkpoint -m "release"`.

### Writing K-SESSION.md well

Write for a reader who has none of your context and may be a different model.
- **Done**: one line per step with its short commit sha, so it can be verified.
- **Next steps**: an ordered checklist. The first unchecked item is where the
  next agent starts. Make it specific: file, function, expected outcome.
- **Decisions**: "X, because Y". This stops the next agent from undoing choices.
- **Blockers / open questions**: anything waiting on the user.
- Keep it distilled. **Never** include:
  - secrets or tokens
  - emails, real names or usernames
  - absolute paths like `/home/...` or `/root/...` (use repo-relative paths)
  - hostnames
  - pasted chat transcripts

  The file is committed and shared, and `$T lint` (run automatically on save)
  rejects these.

## Finish

When the work is complete and the PR is ready: `$T finish`. It deletes
`.k-session/`, commits and pushes, so the base branch stays clean. The pointer
blocks in AGENTS.md and the other files stay. They only act when `.k-session/`
exists, so they're harmless and help the next task.

## Compatibility rules (why the tool behaves as it does)

- State format is versioned (`schema_version`). An older tool refuses a newer
  schema, and the vendored copy is only ever upgraded, never downgraded. Mixed
  agent versions can't corrupt the state.
- Pointer blocks sit between `<!-- k-session-reconciliation:begin/end -->` markers and
  are replaced in place. Content around them is never touched.
- If a hook manager (`core.hooksPath`: husky, lefthook) is in use, the tool
  doesn't install hooks. It prints the line to add instead.
- Don't rewrite history on a shared branch. Use merge, not rebase or amend
  after a push.

See `references/protocol.md` for the state.json schema and a per-agent note.
