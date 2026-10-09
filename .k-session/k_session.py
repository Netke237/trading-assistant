#!/usr/bin/env python3
"""k_session.py - model-agnostic session handoff for git repositories.

Lets any coding agent (Claude, Copilot, Codex, Gemini, ...) in any container
save the state of an interrupted task into the repo and lets another agent,
user or container resume it. Standard library only; requires python3 + git.

State lives on the work branch:
  .k-session/K-SESSION.md   human/agent readable narrative (goal, done, next, ...)
  .k-session/state.json   machine readable state (lock, commits, session log)
  .k-session/k_session.py   vendored copy of this script (so agents without the
                        skill installed can still run it)

Run `python3 .k-session/k_session.py help` for commands.
"""
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys

TOOL_VERSION = "1.0.0"
SCHEMA_VERSION = 1
DIR = ".k-session"
STATE = os.path.join(DIR, "state.json")
DOC = os.path.join(DIR, "K-SESSION.md")
VENDORED = os.path.join(DIR, "k_session.py")
LOCK_STALE_HOURS = 2
BLOCK_BEGIN = "<!-- k-session-reconciliation:begin -->"
BLOCK_END = "<!-- k-session-reconciliation:end -->"
POINTER_FILES = ["AGENTS.md", "CLAUDE.md", "GEMINI.md", ".github/copilot-instructions.md"]

POINTER_BLOCK = """{begin}
## Session handoff (all agents)

This repo uses a model-agnostic handoff protocol so an interrupted task can be
continued by any agent, user or container.

- **Before doing anything**, if `.k-session/K-SESSION.md` exists on your branch:
  run `python3 .k-session/k_session.py resume`, read `.k-session/K-SESSION.md`,
  summarize goal / done / next steps / blockers to the user and **wait for
  confirmation** before continuing.
- While working: keep `.k-session/K-SESSION.md` current and run
  `python3 .k-session/k_session.py checkpoint -m "<what changed>"` after each
  meaningful step (it commits WIP and pushes).
- Before stopping: update K-SESSION.md, then `python3 .k-session/k_session.py release`.
- Never write secrets, emails, personal names, absolute container paths or
  chat transcripts into `.k-session/`. Use repo-relative paths.
- Follow the *Conventions* section of K-SESSION.md regardless of which model you are.
- When the task is complete: `python3 .k-session/k_session.py finish`.
{end}"""

DOC_TEMPLATE = """# K-Session: {goal}

> Shared state for an agent-agnostic task. Keep it short, factual, current.
> Written for the *next* agent, who has none of your context.
> No secrets, emails, names, absolute paths or transcripts.

## Goal
{goal}

## Status
in-progress — just initialised

## Done
<!-- One line per completed step. Reference commits (short sha) so the next agent can verify. -->

## Next steps
<!-- Ordered. The first unchecked item is where the next agent starts. -->
- [ ]

## Blockers / open questions

## Decisions
<!-- Decision - reason. Prevents the next agent from re-litigating. -->

## Conventions
- Commit messages: Conventional Commits (`feat:`, `fix:`, `chore:`, `wip(k-session):` for checkpoints)
- Branch: `{branch}` (base: `{base}`); integrate base with `git merge`, never rebase/force-push a shared branch
- Tests/lint to run before pushing: <!-- fill in -->

## Notes for the next agent
"""

SECRET_PATTERNS = [
    (r"AKIA[0-9A-Z]{16}", "AWS access key"),
    (r"gh[pousr]_[A-Za-z0-9]{30,}", "GitHub token"),
    (r"github_pat_[A-Za-z0-9_]{30,}", "GitHub token"),
    (r"sk-[A-Za-z0-9_\-]{20,}", "API secret key"),
    (r"xox[abpr]-[A-Za-z0-9\-]{10,}", "Slack token"),
    (r"AIza[0-9A-Za-z_\-]{35}", "Google API key"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key"),
    (r"(?i)\b(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*['\"]?[^\s'\"<]{8,}", "credential assignment"),
]
PRIVACY_PATTERNS = [
    (r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", "email address"),
    (r"(?<![\w.])/(home|root|Users|tmp|var/folders|workspaces?|mnt)/[^\s)`'\"]*", "absolute container path"),
    (r"[A-Za-z]:\\\\Users\\\\", "absolute Windows path"),
    (r"(?im)^\s*(human|user|assistant)\s*:", "chat transcript line"),
]


# --------------------------------------------------------------------------- helpers
def die(msg, code=1):
    print(f"k-session: error: {msg}", file=sys.stderr)
    sys.exit(code)


def git(*args, check=True, capture=True):
    r = subprocess.run(["git", *args], text=True,
                       stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.PIPE if capture else None)
    if check and r.returncode != 0:
        die(f"git {' '.join(args)} failed: {(r.stderr or '').strip()}")
    return (r.stdout or "").strip()


def git_ok(*args):
    return subprocess.run(["git", *args], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def now():
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def parse_ts(s):
    try:
        return _dt.datetime.fromisoformat(s)
    except Exception:
        return None


def root():
    r = git("rev-parse", "--show-toplevel", check=False)
    if not r:
        die("not inside a git repository")
    return r


def branch():
    return git("rev-parse", "--abbrev-ref", "HEAD")


def head():
    return git("rev-parse", "--short", "HEAD", check=False) or None


def detect_agent():
    if os.environ.get("KSESSION_AGENT"):
        return os.environ["KSESSION_AGENT"]
    env = os.environ
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude"
    if any(k.startswith("CODEX") for k in env):
        return "codex"
    if any(k.startswith("GEMINI_CLI") for k in env):
        return "gemini"
    if env.get("COPILOT_AGENT_ACTION") or env.get("GITHUB_COPILOT_API_TOKEN") or env.get("COPILOT_AGENT_RUNTIME_VERSION"):
        return "copilot"
    if env.get("CURSOR_TRACE_ID"):
        return "cursor"
    return "unknown-agent"


def detect_handle():
    # Deliberately NOT git user.name/email: identities stay out of the repo.
    return os.environ.get("KSESSION_HANDLE", "anon")


def detect_location():
    if os.environ.get("CLAUDE_CODE_REMOTE") or os.environ.get("CODESPACES") or os.environ.get("GITHUB_ACTIONS"):
        return "cloud"
    return os.environ.get("KSESSION_LOCATION", "local")


def load_state():
    if not os.path.exists(STATE):
        return None
    with open(STATE, encoding="utf-8") as f:
        st = json.load(f)
    if st.get("schema_version", 0) > SCHEMA_VERSION:
        die(f"state.json schema {st['schema_version']} is newer than this tool "
            f"(supports {SCHEMA_VERSION}). Use the vendored script: python3 {VENDORED}")
    return st


def save_state(st):
    st["schema_version"] = SCHEMA_VERSION
    st["tool_version"] = TOOL_VERSION
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2, sort_keys=False)
        f.write("\n")


def log_event(st, event, note=None):
    entry = {"at": now(), "agent": detect_agent(), "handle": detect_handle(),
             "location": detect_location(), "event": event, "commit": head()}
    if note:
        entry["note"] = note
    st.setdefault("log", []).append(entry)
    st["log"] = st["log"][-50:]


def ver_tuple(v):
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0,)


def self_path():
    return os.path.realpath(__file__)


def vendor_self():
    """Copy this script into .k-session/ unless the vendored copy is newer."""
    dst = VENDORED
    if os.path.realpath(dst) == self_path():
        return
    if os.path.exists(dst):
        m = re.search(r'TOOL_VERSION = "([\d.]+)"', open(dst, encoding="utf-8").read())
        if m and ver_tuple(m.group(1)) >= ver_tuple(TOOL_VERSION):
            return
    shutil.copyfile(self_path(), dst)
    os.chmod(dst, 0o755)
    print(f"k-session: vendored tool v{TOOL_VERSION} -> {dst}")


def upsert_pointer_blocks():
    block = POINTER_BLOCK.format(begin=BLOCK_BEGIN, end=BLOCK_END)
    changed = []
    for path in POINTER_FILES:
        existing = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
        if BLOCK_BEGIN in existing and BLOCK_END in existing:
            new = re.sub(re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END), lambda _: block,
                         existing, flags=re.S)
        else:
            new = (existing.rstrip() + "\n\n" if existing.strip() else "") + block + "\n"
        if new != existing:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
            changed.append(path)
    return changed


HOOK_MARK = "# k-session-reconciliation pre-commit"


def install_hooks():
    if git("config", "--get", "core.hooksPath", check=False):
        print("k-session: core.hooksPath is set (husky/lefthook?) - not touching hooks. "
              "Add `python3 .k-session/k_session.py hook-precommit` to your hook manager manually.")
        return
    hooks = git("rev-parse", "--git-path", "hooks")
    os.makedirs(hooks, exist_ok=True)
    hook = os.path.join(hooks, "pre-commit")
    if os.path.exists(hook):
        body = open(hook, encoding="utf-8").read()
        if HOOK_MARK in body:
            return
        os.replace(hook, hook + ".local")
    script = f"""#!/bin/sh
{HOOK_MARK}
if [ -x "$(git rev-parse --git-path hooks)/pre-commit.local" ]; then
  "$(git rev-parse --git-path hooks)/pre-commit.local" "$@" || exit $?
fi
if [ -f .k-session/k_session.py ] && command -v python3 >/dev/null 2>&1; then
  python3 .k-session/k_session.py hook-precommit || exit $?
fi
exit 0
"""
    with open(hook, "w", encoding="utf-8") as f:
        f.write(script)
    os.chmod(hook, 0o755)
    print("k-session: installed pre-commit heartbeat hook")


def scan_text(text, include_privacy=True):
    findings = []
    pats = SECRET_PATTERNS + (PRIVACY_PATTERNS if include_privacy else [])
    for pat, label in pats:
        for m in re.finditer(pat, text):
            line = text.count("\n", 0, m.start()) + 1
            findings.append((line, label, m.group(0)[:12] + "…"))
    return findings


def lint_handoff(quiet=False):
    bad = []
    for path in (DOC, STATE):
        if os.path.exists(path):
            for line, label, snip in scan_text(open(path, encoding="utf-8").read()):
                bad.append(f"{path}:{line}: {label} ({snip})")
    if bad and not quiet:
        print("k-session: privacy/secret check FAILED:", file=sys.stderr)
        for b in bad:
            print("  " + b, file=sys.stderr)
    return not bad


def lint_staged_diff():
    diff = git("diff", "--cached", "-U0", "--no-color", check=False)
    added = "\n".join(l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    return scan_text(added, include_privacy=False)


def remote_exists():
    return bool(git("remote", check=False))


def upstream():
    return git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False) or None


def ahead_behind(a, b):
    out = git("rev-list", "--left-right", "--count", f"{a}...{b}", check=False)
    if not out:
        return None
    left, right = out.split()
    return int(left), int(right)


def lock_info(st):
    lock = st.get("lock") or {}
    if not lock.get("holder"):
        return None, False
    ts = parse_ts(lock.get("heartbeat_at") or lock.get("since") or "")
    stale = ts is None or (_dt.datetime.now(_dt.timezone.utc) - ts).total_seconds() > LOCK_STALE_HOURS * 3600
    return lock, stale


def me():
    return f"{detect_agent()}@{detect_handle()}/{detect_location()}"


def acquire_lock(st):
    st["lock"] = {"holder": me(), "since": now(), "heartbeat_at": now()}


def push(br):
    if not remote_exists():
        print("k-session: no remote configured - skipping push")
        return True
    for delay in (0, 2, 4, 8, 16):
        if delay:
            import time
            time.sleep(delay)
        r = subprocess.run(["git", "push", "-u", "origin", br], text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if r.returncode == 0:
            return True
        err = r.stderr.strip()
        if "rejected" in err or "non-fast-forward" in err:
            print("k-session: push rejected (remote moved). Run `k_session.py sync`, then checkpoint again.",
                  file=sys.stderr)
            return False
    print(f"k-session: push failed: {err}", file=sys.stderr)
    return False


# --------------------------------------------------------------------------- commands
def cmd_init(args):
    goal = None
    base = None
    it = iter(args)
    for a in it:
        if a in ("--goal", "-g"):
            goal = next(it, None)
        elif a == "--base":
            base = next(it, None)
    if os.path.exists(STATE):
        die(f"{STATE} already exists - use `resume` or `save`")
    if not goal:
        die('usage: k_session.py init --goal "<one-line task goal>" [--base main]')
    br = branch()
    if not base:
        ref = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
        base = ref.split("/", 1)[1] if ref else "main"
    os.makedirs(DIR, exist_ok=True)
    with open(DOC, "w", encoding="utf-8") as f:
        f.write(DOC_TEMPLATE.format(goal=goal, branch=br, base=base))
    task_id = f"{re.sub(r'[^a-z0-9]+', '-', goal.lower()).strip('-')[:40]}-{_dt.datetime.now().strftime('%Y%m%d%H%M')}"
    st = {"task_id": task_id, "goal": goal, "branch": br, "base": base,
          "created_at": now(), "updated_at": now(), "saved_commit": head(), "log": []}
    acquire_lock(st)
    log_event(st, "init")
    save_state(st)
    vendor_self()
    changed = upsert_pointer_blocks()
    install_hooks()
    git("add", DIR, *changed)
    print(f"k-session: initialised task '{task_id}' on branch {br} (base {base})")
    print(f"k-session: fill in {DOC} (Next steps, Conventions), then run `checkpoint`.")


def cmd_status(args, st=None):
    st = st or load_state()
    if not st:
        print("k-session: no .k-session/ on this branch.")
        others = find_handoff_branches()
        if others:
            print("k-session: branches carrying handoff state:")
            for b, s in others:
                print(f"  {b}: {s.get('goal')} (updated {s.get('updated_at')}, lock {((s.get('lock') or {}).get('holder'))})")
        return
    br = branch()
    print(f"task      : {st.get('task_id')}")
    print(f"goal      : {st.get('goal')}")
    print(f"branch    : {br} (recorded: {st.get('branch')}, base: {st.get('base')})")
    if br != st.get("branch"):
        print(f"WARNING   : current branch differs from recorded branch {st.get('branch')}")
    print(f"updated   : {st.get('updated_at')}  tool v{st.get('tool_version')}")
    lock, stale = lock_info(st)
    if lock:
        print(f"lock      : {lock['holder']} since {lock.get('since')} "
              f"(heartbeat {lock.get('heartbeat_at')}){' STALE' if stale else ''}")
    else:
        print("lock      : free")
    up = upstream()
    if up:
        ab = ahead_behind("HEAD", up)
        if ab:
            print(f"remote    : {up} ahead {ab[0]} / behind {ab[1]}")
    base = st.get("base")
    if base and git_ok("rev-parse", "--verify", f"origin/{base}"):
        ab = ahead_behind("HEAD", f"origin/{base}")
        if ab:
            print(f"base      : origin/{base} is {ab[1]} commit(s) ahead of this branch")
    sc = st.get("saved_commit")
    if sc and git_ok("cat-file", "-e", f"{sc}^{{commit}}"):
        since = git("log", "--oneline", "--invert-grep", "--grep=^wip(k-session):", f"{sc}..HEAD", check=False)
        print(f"since save: {len(since.splitlines()) if since else 0} commit(s) after last K-SESSION.md save ({sc})")
        if since:
            for l in since.splitlines()[:20]:
                print(f"            {l}")
    dirty = git("status", "--porcelain", check=False)
    if dirty:
        print(f"worktree  : {len(dirty.splitlines())} uncommitted change(s)")
    print("recent log:")
    for e in st.get("log", [])[-5:]:
        print(f"  {e['at']} {e['event']:<10} {e['agent']}@{e['handle']}/{e.get('location')} {e.get('commit')} {e.get('note', '')}")


def find_handoff_branches():
    if not remote_exists():
        return []
    git("fetch", "--quiet", "origin", check=False)
    out = []
    for ref in git("for-each-ref", "--format=%(refname:short)", "refs/remotes/origin", check=False).splitlines():
        if ref.endswith("/HEAD"):
            continue
        raw = subprocess.run(["git", "show", f"{ref}:{STATE}"], text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
        if raw:
            try:
                out.append((ref, json.loads(raw)))
            except Exception:
                pass
    return out


def cmd_scan(args):
    st = load_state()
    found = find_handoff_branches()
    if not found:
        print("k-session: no remote branches carry handoff state")
        return
    tid = st.get("task_id") if st else None
    for ref, s in found:
        mark = " <- same task" if tid and s.get("task_id") == tid else ""
        print(f"{ref}: [{s.get('task_id')}] {s.get('goal')} updated {s.get('updated_at')} "
              f"lock={((s.get('lock') or {}).get('holder'))}{mark}")


def cmd_resume(args):
    take_over = "--take-over" in args
    if remote_exists():
        git("fetch", "--quiet", "--all", "--prune", check=False)
    st = load_state()
    if not st:
        cmd_status([])
        die("nothing to resume on this branch - check out one of the branches above", 2)
    if st.get("branch") and branch() != st["branch"]:
        print(f"k-session: WARNING current branch {branch()} != recorded {st['branch']}")
    # fast-forward to remote if we're behind and clean
    up = upstream()
    if up:
        ab = ahead_behind("HEAD", up)
        if ab and ab[1] and not ab[0] and not git("status", "--porcelain", check=False):
            git("merge", "--ff-only", up)
            print(f"k-session: fast-forwarded to {up}")
            st = load_state()
    lock, stale = lock_info(st)
    if lock and lock["holder"] != me() and not stale and not take_over:
        cmd_status([], st)
        print(f"\nhandoff: LOCKED by {lock['holder']} (heartbeat {lock.get('heartbeat_at')}). "
              f"Another session may still be active. Ask the user; if they confirm, rerun with --take-over.")
        sys.exit(3)
    prev = lock["holder"] if lock else None
    acquire_lock(st)
    log_event(st, "resume", f"took over from {prev}" if prev and prev != me() else None)
    save_state(st)
    vendor_self()
    changed = upsert_pointer_blocks()
    install_hooks()
    git("add", DIR, *changed)
    cmd_status([], st)
    same = [r for r, s in find_handoff_branches()
            if s.get("task_id") == st.get("task_id") and not r.endswith("/" + branch())]
    if same:
        print("\nhandoff: PARALLEL SESSIONS - these branches carry the same task:")
        for r in same:
            print(f"  {r}  (inspect: git log --oneline HEAD..{r}; git show {r}:{DOC})")
    print(f"\n----- {DOC} -----")
    print(open(DOC, encoding="utf-8").read())


def cmd_sync(args):
    st = load_state() or die("no handoff state")
    if git("status", "--porcelain", check=False):
        die("working tree not clean - checkpoint or stash first")
    if not remote_exists():
        die("no remote")
    git("fetch", "--quiet", "origin")
    up = upstream() or (f"origin/{branch()}" if git_ok("rev-parse", "--verify", f"origin/{branch()}") else None)
    for target in [up, f"origin/{st.get('base')}"]:
        if not target or not git_ok("rev-parse", "--verify", target):
            continue
        r = subprocess.run(["git", "merge", "--no-edit", target], text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            die(f"merge of {target} has conflicts - resolve them (keep both sides' intent), "
                f"`git commit`, then run sync again", 4)
        print(f"k-session: merged {target}: {r.stdout.strip().splitlines()[-1] if r.stdout.strip() else 'ok'}")


def cmd_save(args, event="save"):
    note = None
    if "-m" in args:
        note = args[args.index("-m") + 1] if args.index("-m") + 1 < len(args) else None
    st = load_state() or die("no handoff state - run init first")
    if not lint_handoff():
        die("fix the findings above (no secrets, emails, names, absolute paths, transcripts)")
    st["updated_at"] = now()
    st["saved_commit"] = head()
    lock, _ = lock_info(st)
    if lock and lock["holder"] == me():
        lock["heartbeat_at"] = now()
    elif not lock:
        acquire_lock(st)
    log_event(st, event, note)
    save_state(st)
    vendor_self()
    git("add", DIR)
    print(f"k-session: {event} recorded")
    return st


def cmd_checkpoint(args):
    msg = "checkpoint"
    if "-m" in args and args.index("-m") + 1 < len(args):
        msg = args[args.index("-m") + 1]
    git("add", "-A")
    findings = lint_staged_diff()
    if findings:
        for line, label, snip in findings:
            print(f"  staged diff: {label} ({snip})", file=sys.stderr)
        git("reset", "--quiet", check=False)
        die("possible secret in staged changes - nothing committed. Remove it or add the file to .gitignore.")
    cmd_save(["-m", msg], event="checkpoint")
    if git_ok("diff", "--cached", "--quiet"):
        print("k-session: nothing to commit")
    else:
        os.environ["KSESSION_SKIP_HOOK"] = "1"
        r = subprocess.run(["git", "commit", "-m", f"wip(k-session): {msg}"], env=os.environ)
        if r.returncode != 0:
            die("commit failed (see hook output above)")
    if "--no-push" not in args:
        push(branch())


def cmd_release(args):
    st = cmd_save(args, event="release")
    st["lock"] = None
    save_state(st)
    git("add", DIR)
    print("k-session: lock released. Commit + push (or run `checkpoint -m \"release\"`) so others see it.")


def cmd_finish(args):
    if not os.path.isdir(DIR):
        die("no .k-session/ to remove")
    git("rm", "-r", "-q", "--cached", DIR, check=False)
    shutil.rmtree(DIR)
    os.environ["KSESSION_SKIP_HOOK"] = "1"
    r = subprocess.run(["git", "commit", "-m", "chore(k-session): task complete, remove handoff state"], env=os.environ)
    if r.returncode != 0:
        die("commit failed")
    if "--no-push" not in args:
        push(branch())
    print("k-session: .k-session/ removed. Pointer blocks in AGENTS.md etc. stay (they are inert without .k-session/).")


def cmd_hook_precommit(args):
    if os.environ.get("KSESSION_SKIP_HOOK"):
        return
    st = load_state()
    if not st:
        return
    if not lint_handoff():
        die("commit blocked: .k-session/ contains secret/private data")
    st["updated_at"] = now()
    lock, _ = lock_info(st)
    if lock and lock["holder"] == me():
        lock["heartbeat_at"] = now()
    save_state(st)
    git("add", STATE)


def cmd_lint(args):
    sys.exit(0 if lint_handoff() else 1)


def cmd_pointers(args):
    changed = upsert_pointer_blocks()
    print("k-session: updated " + (", ".join(changed) if changed else "nothing (already current)"))


HELP = """usage: k_session.py <command> [options]

  init --goal "<goal>" [--base main]  start tracking a task on this branch
  resume [--take-over]                fetch, fast-forward, lock, print state + K-SESSION.md
  status                              show state, lock, divergence, commits since last save
  sync                                merge remote branch + base branch (stops on conflict)
  scan                                list remote branches carrying handoff state
  save [-m note]                      record K-SESSION.md edits (stages .k-session/)
  checkpoint -m "<msg>" [--no-push]   save + WIP commit of all changes + push
  release [-m note]                   save + free the lock (then commit/push)
  finish [--no-push]                  delete .k-session/ and commit (task done)
  lint                                privacy/secret check of .k-session/
  pointers                            (re)write agent pointer blocks
  install-hooks                       install the pre-commit heartbeat hook
  version

env: KSESSION_AGENT (claude|copilot|codex|gemini|...), KSESSION_HANDLE (pseudonym), KSESSION_LOCATION
"""


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "help"
    if cmd in ("help", "-h", "--help"):
        print(HELP)
        return
    if cmd == "version":
        print(TOOL_VERSION)
        return
    os.chdir(root())
    table = {"init": cmd_init, "resume": cmd_resume, "status": cmd_status, "sync": cmd_sync,
             "scan": cmd_scan, "save": cmd_save, "checkpoint": cmd_checkpoint, "release": cmd_release,
             "finish": cmd_finish, "lint": cmd_lint, "pointers": cmd_pointers,
             "install-hooks": lambda a: install_hooks(), "hook-precommit": cmd_hook_precommit}
    if cmd not in table:
        die(f"unknown command '{cmd}'\n{HELP}")
    table[cmd](args[1:])


if __name__ == "__main__":
    main()
