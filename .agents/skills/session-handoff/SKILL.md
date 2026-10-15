---
name: session-handoff
description: Use ONLY when the user explicitly says "session handoff", "wrap up session", "hand off", "handoff summary", "let's wrap up", or "summarize before I clear". Do NOT invoke automatically or proactively. Produces a structured end-of-session summary so a fresh agent can continue seamlessly after /clear.
---

# Session Handoff

Produce a repeatable end-of-session summary so the user can `/clear` and start a fresh agent without losing continuity. The next agent should be able to pick up by reading this summary alone.

This is a **context-handoff artifact**, not a status report. The audience is a future instance of you, not a stakeholder.

## How to produce the summary

1. **Review the full conversation**, not just the last few turns. Handoffs miss things when they only summarize recent context.
2. **Pull state from these sources (in order):**
   - Plan files referenced this session (look for a `.claude/plans/` directory relative to the project root if a plan was mentioned).
   - TodoWrite state — any in-progress or pending tasks. (Claude Code only — skip if this environment has no TodoWrite tool.)
   - Background processes started with `run_in_background` — shell/task IDs are load-bearing for the next agent. (Claude Code only — skip if this environment has no persistent shell.)
   - Files created or modified this session — you know what you touched; don't grep to re-discover.
   - Memory files written or updated (locate the Claude config/memory directory for this project rather than assuming a fixed path — it varies by machine and environment).
   - Unresolved questions — things you asked the user that never got a clear answer, or things the user asked that got deflected.
3. **Do NOT audit the filesystem.** This is synthesis of what happened in THIS session. No `git log`, no broad `Glob` sweeps. If you didn't touch it this session, it doesn't belong here.
4. **Produce the output in chat.** Do not write a file. Do not update memory. Chat-only.

## Output template — use exactly this structure, every time

```
# Session Handoff — <one-line title of what this session was about>

## Where it started
<2-3 sentences: what the user asked for, key framing or constraints that emerged>

## Decisions locked + what shipped
- <decision or change> — <why, and where it lives (absolute path if a file)>
- ...

## Key files for next session
- `<absolute path>` — <why the next agent should read this first>
- Plan file: `<path>` (if a plan drove the session)
- Memory files touched: `<paths>` (if any)

## Running state
- Background processes: <shell IDs + what they are + how to kill> — or "none"
- Dev servers / ports: <url + port> — or "none"
- Open worktrees / branches: <paths> — or "none"

## Verification — how to confirm things still work
- `<command>` — <expected outcome>
- ...

## Deferred + open questions
- Deferred: <item> — <why pushed to later>
- Open: <question needing the user's input> — <context>

## Pick up here
<1-2 sentences: the single most likely next action for a fresh agent>
```

## Hard rules

1. **Chat output only.** Never write the handoff to a file. Never update memory from this skill.
2. **Never invent state.** If a section has nothing to report, write "none" — do not omit the section. Structure stability is the whole point.
3. **Absolute paths always — resolved for the environment you're actually in.** The next agent may run on a different machine or in a cloud/virtual session with a different drive, home directory, or working directory than this one. Don't hardcode a path you saw in a previous session; state the real absolute path as it exists in the current session.
4. **If a plan file drove the session, name it first** in "Key files" so the next agent reads it before anything else.
5. **No emojis, no hype, no "great job" summaries.** Terse and concrete — paths, commands, shell IDs, decisions.
6. **Background process IDs are critical.** If you started any `run_in_background` shells, their IDs must appear in "Running state" with the kill command — the next agent cannot find them otherwise.

## Anti-patterns — do not do these

- Summarizing the last 3 turns and calling it a handoff.
- Listing files by relative path.
- Skipping the "Running state" section because "nothing is running" — write "none" instead.
- Writing the summary to any file. This is chat-only by design.
- Adding a "what went well / what went poorly" retrospective.
- Recommending next steps beyond the single "Pick up here" line.
