# Handoff protocol reference

## state.json (schema_version 1)

```json
{
  "task_id": "add-oauth-login-202609241930",
  "goal": "Add OAuth login",
  "branch": "feature/oauth",
  "base": "main",
  "created_at": "2026-09-24T19:30:00+00:00",
  "updated_at": "2026-09-24T20:10:00+00:00",
  "saved_commit": "a1b2c3d",
  "lock": {"holder": "codex@anon/local", "since": "...", "heartbeat_at": "..."},
  "log": [
    {"at": "...", "agent": "claude", "handle": "anon", "location": "cloud",
     "event": "checkpoint", "commit": "a1b2c3d", "note": "tests green"}
  ],
  "schema_version": 1,
  "tool_version": "1.0.0"
}
```

- `saved_commit`: HEAD when K-SESSION.md was last deliberately saved. Commits after it
  are work the narrative may not describe yet, so reconcile them on resume.
- `lock`: a soft lock. It counts as stale when `heartbeat_at` is more than 2h old.
  `null` means free.
- `log`: the last 50 events (init, save, checkpoint, resume, release).
- `task_id`: shared by branches working on the same task. `scan` and `resume` use it
  to detect parallel sessions.

Unknown keys must be preserved by any tool that rewrites the file. Bump
`schema_version` only for incompatible changes.

## Exit codes
- 0: ok
- 1: error
- 2: nothing to resume on this branch
- 3: locked by a live session (rerun with `--take-over` after confirming)
- 4: merge conflict during `sync`

## Per-agent notes

| Agent | Where it learns the protocol | Notes |
|---|---|---|
| Claude Code (local/cloud) | this skill + `CLAUDE.md` block | skill installed in `~/.claude/skills` |
| GitHub Copilot coding agent | `.github/copilot-instructions.md`, `AGENTS.md` | runs `python3 .k-session/k_session.py` in its Actions runner; pushes to its own `copilot/*` branch, so expect **parallel sessions** and merge them |
| Codex CLI | `AGENTS.md` | set `KSESSION_AGENT=codex` if not detected |
| Gemini CLI | `GEMINI.md` | set `KSESSION_AGENT=gemini` if not detected |
| Others (Cursor, Aider, …) | `AGENTS.md` | any agent that can run a shell command works |

## Manual fallback (no python3)
Read `.k-session/K-SESSION.md`, follow its Next steps, and edit it by hand. In
`state.json`, update `updated_at`, append a `log` entry and set `lock`.
Commit with `wip(k-session): …` and push.
