# backend/tests/test_claim_script.py
"""Tests for scripts/claim.py's ledger round trip on the `claims` branch.

The defect pinned here: git() ran subprocess in text mode, and on Windows
text-mode stdin rewrites "\\n" as "\\r\\n". `git mktree` therefore got
"...\\tclaims.json\\r\\n" and named the ledger file "claims.json\\r". load()
asked for "claims.json", found nothing and returned an empty ledger, so
`list` and `renew` reported no claims, and the next write from any session
dropped every claim. Six such commits reached origin/claims on 2026-09-30
(0346cdc5 .. 028fae17); 9e4470de then erased CONTRACT-LIQUIDITY-DTE.

The tests drive a REAL temporary bare remote rather than mocking subprocess,
because the bug was in the bytes that reached git. scripts/ is not a package,
so the module is loaded via importlib, matching test_state_audit_bookkeeping.py.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "claim.py"
_spec = importlib.util.spec_from_file_location("claim_script", _SCRIPT_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]


def _run(*args: str, cwd: Path, input: bytes | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, input=input, check=True,
                          capture_output=True).stdout.decode()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A work repo whose `origin` is an empty bare repo; cwd is the work repo."""
    _run("init", "-q", "--bare", "remote.git", cwd=tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    _run("init", "-q", cwd=work)
    _run("remote", "add", "origin", "../remote.git", cwd=work)
    monkeypatch.chdir(work)
    return tmp_path


def _tree_names(repo: Path) -> list[str]:
    out = _run("ls-tree", "-z", "--name-only", "claims", cwd=repo / "remote.git")
    return [n for n in out.split("\0") if n]


def _claim(task: str, branch: str) -> dict:
    return {"task": task, "branch": branch, "agent": "claude", "note": "",
            "claimed_at": "2026-09-30T20:15:10Z", "expires_at": "2099-01-01T00:00:00Z"}


def test_write_names_the_file_exactly_claims_json(repo):
    data = {"claims": [_claim("TASK-A", "feat-a")]}
    assert _mod.write(None, data, "claim TASK-A (feat-a)")

    assert _tree_names(repo) == ["claims.json"]
    blob = subprocess.run(["git", "show", "claims:claims.json"], cwd=repo / "remote.git",
                          check=True, capture_output=True).stdout
    assert b"\r" not in blob


def test_write_then_load_round_trips_and_a_second_write_keeps_the_first(repo):
    assert _mod.write(None, {"claims": [_claim("TASK-A", "feat-a")]}, "a")
    head = _mod.fetch()
    data = _mod.load(head)
    assert [c["task"] for c in data["claims"]] == ["TASK-A"]

    data["claims"].append(_claim("TASK-B", "feat-b"))
    assert _mod.write(head, data, "b")
    assert [c["task"] for c in _mod.load(_mod.fetch())["claims"]] == ["TASK-A", "TASK-B"]


def test_load_reads_a_ledger_an_unfixed_windows_client_wrote(repo):
    """Older worktrees keep the unfixed script until they rebase on main, so a
    fixed reader must still see the claims they write."""
    remote = repo / "remote.git"
    body = json.dumps({"claims": [_claim("TASK-OLD", "feat-old")]}, indent=2) + "\n"
    blob = _run("hash-object", "-w", "--stdin", cwd=remote,
                input=body.replace("\n", "\r\n").encode()).strip()
    tree = _run("mktree", cwd=remote,
                input=f"100644 blob {blob}\tclaims.json\r\n".encode()).strip()
    commit = _run("commit-tree", tree, "-m", "legacy", cwd=remote).strip()
    _run("update-ref", "refs/heads/claims", commit, cwd=remote)
    assert _tree_names(repo) == ["claims.json\r"]

    assert [c["task"] for c in _mod.load(_mod.fetch())["claims"]] == ["TASK-OLD"]


def test_load_refuses_a_ledger_commit_without_the_file(repo):
    """Reading "no file" as "no claims" is what let one bad commit wipe the
    whole ledger on the next write; it must fail loudly instead."""
    remote = repo / "remote.git"
    blob = _run("hash-object", "-w", "--stdin", cwd=remote, input=b"x\n").strip()
    tree = _run("mktree", cwd=remote, input=f"100644 blob {blob}\tother.txt\n".encode()).strip()
    commit = _run("commit-tree", tree, "-m", "junk", cwd=remote).strip()
    _run("update-ref", "refs/heads/claims", commit, cwd=remote)

    with pytest.raises(_mod.GitError, match="claims.json missing"):
        _mod.load(_mod.fetch())
