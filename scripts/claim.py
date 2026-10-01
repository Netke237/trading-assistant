#!/usr/bin/env python3
"""Task claims — tell every other agent "I am working on X" before you start.

Kenneth runs many sessions across two accounts and several agents (Claude,
Copilot, Gemini, Codex). Each session is its own fresh clone, so nobody can see
anybody else's unpushed work, and two sessions starting from the same `main`
used to pick the same open item and build it twice.

The fix is a tiny shared ledger, `claims.json`, on its own branch `claims`
(never `main`, never a feature branch). Writing to it is a plain,
non-forced `git push`, which git accepts only if nobody pushed in between —
so two agents claiming the same task at the same moment cannot both win: the
loser's push is rejected, it re-fetches, sees the claim, and backs off.

Claims are ADVISORY: nothing stops an agent that ignores them. They expire
(default 3h) unless renewed, so a session that died or ran out of tokens stops
blocking its task on its own; `take --force` hands it over immediately.

    python3 scripts/claim.py                    # list active claims (short)
    python3 scripts/claim.py take TASK -m "what I'm doing"
    python3 scripts/claim.py take TASK --force  # take over someone else's claim
    python3 scripts/claim.py renew              # extend all claims of this branch
    python3 scripts/claim.py release TASK       # done, or giving up

TASK is a short id — use the PROJECT_STATE.json phase/finding id when one
exists. The claimant is the current git branch (override with --branch), so a
successor can `git fetch origin <branch>` and continue from the pushed work.

Stdlib only, touches neither the working tree nor the index (it builds the
commit with git plumbing), so it is safe to run mid-change.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

REMOTE = os.environ.get("CLAIMS_REMOTE", "origin")  # override for tests
BRANCH = "claims"
FILE = "claims.json"
DEFAULT_TTL_H = 3.0
MAX_TRIES = 5


class GitError(RuntimeError):
    pass


def git(*args: str, input: str | None = None, check: bool = True,
        env: dict | None = None) -> subprocess.CompletedProcess:
    # Bytes in, bytes out. With text=True, Windows rewrites "\n" as "\r\n" on
    # stdin, so mktree names the file "claims.json\r" and every reader then
    # sees an empty ledger (and the next write drops everybody's claims).
    p = subprocess.run(["git", *args],
                       input=None if input is None else input.encode("utf-8"),
                       capture_output=True, env=env, timeout=60)
    p.stdout = p.stdout.decode("utf-8", "replace")
    p.stderr = p.stderr.decode("utf-8", "replace")
    if check and p.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p


def now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def remote_ref() -> str:
    return f"refs/remotes/{REMOTE}/{BRANCH}"


def fetch() -> str | None:
    """Fetch the claims branch. Returns its commit, or None if it doesn't exist yet."""
    ls = git("ls-remote", REMOTE, f"refs/heads/{BRANCH}")
    if not ls.stdout.strip():
        return None
    git("fetch", "-q", REMOTE, f"+refs/heads/{BRANCH}:{remote_ref()}")
    return git("rev-parse", remote_ref()).stdout.strip()


def load(commit: str | None) -> dict:
    if commit is None:
        return {"claims": []}
    # An unfixed Windows client names the file "claims.json\r"; read it
    # anyway. Never treat an unreadable ledger as empty: the next write would
    # then erase every other session's claims.
    repair = (f"repair by hand: re-commit the newest readable {FILE} from "
              f"`git log {REMOTE}/{BRANCH}` on top of {commit[:8]} and push")
    blob = None
    for e in git("ls-tree", "-z", commit).stdout.split("\0"):
        meta, sep, name = e.partition("\t")
        if sep and name in (FILE, FILE + "\r") and meta.split()[1] == "blob":
            blob = meta.split()[2]
            if name == FILE:
                break
    if blob is None:
        raise GitError(f"{FILE} missing from claims commit {commit[:8]}; {repair}")
    try:
        data = json.loads(git("cat-file", "blob", blob).stdout)
        claims = data["claims"]
        assert isinstance(claims, list)
        for c in claims:
            for k in ("task", "branch", "claimed_at", "expires_at"):
                assert isinstance(c[k], str)
            parse(c["claimed_at"]), parse(c["expires_at"])
    except (ValueError, KeyError, TypeError, AssertionError) as e:
        raise GitError(f"{FILE} in claims commit {commit[:8]} is not a valid "
                       f"ledger ({type(e).__name__}: {e}); {repair}")
    return data


def write(parent: str | None, data: dict, message: str) -> bool:
    """Commit `data` on top of `parent` and push. False if someone pushed first."""
    body = json.dumps(data, indent=2, sort_keys=True) + "\n"
    blob = git("hash-object", "-w", "--stdin", input=body).stdout.strip()
    tree = git("mktree", input=f"100644 blob {blob}\t{FILE}\n").stdout.strip()
    # Last line of defence: never push a tree whose only entry is not exactly
    # claims.json (any newline translation would make readers see no ledger).
    names = git("ls-tree", "-z", "--name-only", tree).stdout
    if names != FILE + "\0":
        raise GitError(f"refusing to push a claims tree named {names!r}")
    # A fixed identity keeps personal names/emails out of the ledger and works
    # in containers with no user.name configured.
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "claims-bot", "GIT_AUTHOR_EMAIL": "claims@localhost",
           "GIT_COMMITTER_NAME": "claims-bot", "GIT_COMMITTER_EMAIL": "claims@localhost"}
    args = ["commit-tree", tree, "-m", message]
    if parent:
        args += ["-p", parent]
    commit = git(*args, env=env).stdout.strip()
    # Deliberately NOT --force: a non-fast-forward rejection is the lock.
    p = git("push", "-q", REMOTE, f"{commit}:refs/heads/{BRANCH}", check=False)
    if p.returncode == 0:
        git("update-ref", remote_ref(), commit, check=False)
        return True
    if "rejected" in p.stderr or "fetch first" in p.stderr or "non-fast-forward" in p.stderr:
        return False
    raise GitError(f"push failed: {p.stderr.strip()}")


def current_branch() -> str:
    b = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if b == "HEAD":
        raise GitError("detached HEAD — pass --branch")
    return b


def active(claims: list[dict], at: datetime) -> list[dict]:
    return [c for c in claims if parse(c["expires_at"]) > at]


def find(claims: list[dict], task: str) -> dict | None:
    t = task.strip().lower()
    return next((c for c in claims if c["task"].lower() == t), None)


def age(t: datetime, at: datetime) -> str:
    m = int(abs((at - t).total_seconds()) // 60)
    return f"{m}m" if m < 60 else f"{m // 60}h{m % 60:02d}m"


def mutate(fn, message: str) -> None:
    """Fetch → apply fn(data, now) → push, retrying when another agent won the race."""
    for _ in range(MAX_TRIES):
        head = fetch()
        data = load(head)
        at = now()
        data["claims"] = active(data.get("claims", []), at)  # purge expired
        result = fn(data, at)
        if result is None:  # fn decided there is nothing to write
            return
        if write(head, data, message):
            print(result)
            return
    raise GitError("claims branch kept moving — try again in a moment")


def cmd_list(a) -> int:
    try:
        head = fetch()
    except (GitError, subprocess.TimeoutExpired) as e:
        print(f"[claims] could not read claims ({str(e).splitlines()[0][:120]})")
        return 0 if a.quiet else 1
    try:
        data = load(head)
    except (GitError, subprocess.TimeoutExpired) as e:
        print(f"[claims] ledger unreadable ({str(e).splitlines()[0][:200]})")
        return 0 if a.quiet else 1
    at = now()
    claims = sorted(active(data.get("claims", []), at), key=lambda c: c["claimed_at"])
    if not claims:
        if not a.quiet:
            print("[claims] no active claims")
        return 0
    try:
        me = current_branch()
    except GitError:
        me = ""
    print(f"[claims] {len(claims)} active — do NOT start these unless Kenneth reassigns:")
    for c in claims:
        mine = "  (you)" if c["branch"] == me else ""
        note = f" — {c['note']}" if c.get("note") else ""
        print(f"  {c['task']}: {c['branch']}, {age(parse(c['claimed_at']), at)} ago, "
              f"expires in {age(parse(c['expires_at']), at)}{note}{mine}")
    return 0


def cmd_take(a) -> int:
    branch = a.branch or current_branch()

    def fn(data, at):
        claims = data["claims"]
        old = find(claims, a.task)
        exp = iso(at + timedelta(hours=a.ttl))
        if old and old["branch"] != branch and not a.force:
            raise SystemExit(
                f"[claims] {old['task']} is already claimed by {old['branch']} "
                f"(expires in {age(parse(old['expires_at']), at)}). "
                f"Pick another task, or --force only if Kenneth reassigned it.")
        if old and old["branch"] == branch:
            old["expires_at"] = exp
            if a.message:
                old["note"] = a.message
            return f"[claims] renewed {old['task']} until {exp}"
        entry = {"task": a.task.strip(), "branch": branch, "agent": a.agent,
                 "note": a.message or "", "claimed_at": iso(at), "expires_at": exp}
        if old:  # forced takeover — keep the trail so the successor finds the work
            claims.remove(old)
            entry["previous"] = (old.get("previous") or []) + [
                {"branch": old["branch"], "claimed_at": old["claimed_at"]}]
        claims.append(entry)
        taken = f" (taken over from {old['branch']} — `git fetch {REMOTE} {old['branch']}` to continue its work)" if old else ""
        return f"[claims] claimed {entry['task']} for {branch} until {exp}{taken}"

    mutate(fn, f"claim {a.task} ({branch})")
    return 0


def cmd_renew(a) -> int:
    branch = a.branch or current_branch()

    def fn(data, at):
        mine = [c for c in data["claims"] if c["branch"] == branch]
        if not mine:
            print(f"[claims] {branch} holds no active claims")
            return None
        exp = iso(at + timedelta(hours=a.ttl))
        for c in mine:
            c["expires_at"] = exp
        return f"[claims] renewed {', '.join(c['task'] for c in mine)} until {exp}"

    mutate(fn, f"renew ({branch})")
    return 0


def cmd_release(a) -> int:
    branch = a.branch or current_branch()

    def fn(data, at):
        c = find(data["claims"], a.task)
        if not c:
            print(f"[claims] {a.task} is not claimed")
            return None
        if c["branch"] != branch and not a.force:
            raise SystemExit(f"[claims] {c['task']} belongs to {c['branch']}, not {branch} (use --force)")
        data["claims"].remove(c)
        return f"[claims] released {c['task']}"

    mutate(fn, f"release {a.task} ({branch})")
    return 0


def main() -> int:
    # A Windows OEM console (cp437/cp850/cp932) cannot encode the em dashes in
    # --help and in the output; replace them rather than die mid-command.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("list", help="show active claims (default)")
    p.add_argument("--quiet", action="store_true", help="print nothing when empty; never fail")

    p = sub.add_parser("take", help="claim a task")
    p.add_argument("task")
    p.add_argument("-m", "--message", help="one line: what you are doing")
    p.add_argument("--force", action="store_true", help="take over another branch's claim")
    p.add_argument("--agent", default=os.environ.get("CLAIM_AGENT", "claude"),
                   help="agent kind (claude/copilot/gemini/codex…)")

    p2 = sub.add_parser("renew", help="extend every claim held by this branch")
    p3 = sub.add_parser("release", help="drop a claim (done or giving up)")
    p3.add_argument("task")
    p3.add_argument("--force", action="store_true", help="release another branch's claim")

    for q in (p, p2, p3):
        q.add_argument("--branch", help="claimant branch (default: current)")
    for q in (p, p2):
        q.add_argument("--ttl", type=float, default=DEFAULT_TTL_H, help="hours until expiry")

    a = ap.parse_args()
    try:
        if a.cmd in (None, "list"):
            if a.cmd is None:
                a.quiet = False
            return cmd_list(a)
        return {"take": cmd_take, "renew": cmd_renew, "release": cmd_release}[a.cmd](a)
    except (GitError, subprocess.TimeoutExpired) as e:
        print(f"[claims] error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
