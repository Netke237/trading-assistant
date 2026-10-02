# backend/tests/test_claim_script.py
"""Tests for scripts/claim.py's ledger round trip on the `claims` branch.

The defect pinned here: git() ran subprocess in text mode, and on Windows
text-mode stdin rewrites "\\n" as "\\r\\n". `git mktree` therefore got
"...\\tclaims.json\\r\\n" and named the ledger file "claims.json\\r". load()
asked for "claims.json", found nothing and returned an empty ledger, so
`list` and `renew` reported no claims, and the next write from any session
dropped every claim. Eight such commits reached origin/claims by 2026-10-01
(0346cdc5 .. 028fae17, 4aaebf0d, 08f2e50b); 9e4470de then erased
CONTRACT-LIQUIDITY-DTE, and 08f2e50b / 8cff5f72 three more live claims.

The tests drive a REAL temporary bare remote rather than mocking subprocess,
because the bug was in the bytes that reached git. scripts/ is not a package,
so the module is loaded via importlib, matching test_state_audit_bookkeeping.py.
"""
from __future__ import annotations

import importlib.util
import argparse
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
    # Keep the script's git calls inside the temp repos, whatever the caller's env.
    for var in ("GIT_DIR", "GIT_WORK_TREE", "CLAIMS_REMOTE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(_mod, "REMOTE", "origin")
    # CI runners have no user.name/user.email; commit-tree needs an identity.
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "test")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "test@localhost")
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


def test_write_survives_windows_text_mode_newline_translation(repo, monkeypatch):
    """Linux CI does no newline translation, so emulate Windows: any str stdin
    handed to subprocess in text mode gets "\\n" -> "\\r\\n". The unfixed git()
    (text=True) then produced "claims.json\\r"; bytes stdin is untouched."""
    real_run = subprocess.run

    def windows_run(*args, **kwargs):
        if isinstance(kwargs.get("input"), str):  # str stdin == text mode
            kwargs["input"] = kwargs["input"].replace("\n", "\r\n")
        return real_run(*args, **kwargs)

    monkeypatch.setattr(_mod.subprocess, "run", windows_run)
    assert _mod.write(None, {"claims": [_claim("TASK-A", "feat-a")]}, "a")
    monkeypatch.setattr(_mod.subprocess, "run", real_run)

    assert _tree_names(repo) == ["claims.json"]
    assert [c["task"] for c in _mod.load(_mod.fetch())["claims"]] == ["TASK-A"]


def _push_tree(repo: Path, name: str, body: bytes) -> None:
    remote = repo / "remote.git"
    blob = _run("hash-object", "-w", "--stdin", cwd=remote, input=body).strip()
    tree = _run("mktree", cwd=remote, input=f"100644 blob {blob}\t{name}\n".encode()).strip()
    commit = _run("commit-tree", tree, "-m", "x", cwd=remote).strip()
    _run("update-ref", "refs/heads/claims", commit, cwd=remote)


def test_load_raises_giterror_on_invalid_json(repo):
    _push_tree(repo, "claims.json", b'{"claims": [')
    with pytest.raises(_mod.GitError, match="not a valid ledger"):
        _mod.load(_mod.fetch())


def test_load_refuses_a_directory_named_like_the_ledger(repo):
    remote = repo / "remote.git"
    blob = _run("hash-object", "-w", "--stdin", cwd=remote, input=b"{}\n").strip()
    sub = _run("mktree", cwd=remote, input=f"100644 blob {blob}\tx\n".encode()).strip()
    tree = _run("mktree", cwd=remote, input=f"040000 tree {sub}\tclaims.json\n".encode()).strip()
    commit = _run("commit-tree", tree, "-m", "x", cwd=remote).strip()
    _run("update-ref", "refs/heads/claims", commit, cwd=remote)
    with pytest.raises(_mod.GitError, match="claims.json missing"):
        _mod.load(_mod.fetch())


@pytest.mark.parametrize("body", [b"{}", b"null", b"[]", b'{"claims": {}}',
                                  b'{"claims": [{"task": "x"}]}',
                                  b'{"claims": [{"task": "x", "branch": "b", '
                                  b'"claimed_at": "yesterday", "expires_at": "2099-01-01T00:00:00Z"}]}'])
def test_load_refuses_a_ledger_of_the_wrong_shape(repo, body):
    """{} used to read as "no claims", so the next take erased the ledger."""
    _push_tree(repo, "claims.json", body)
    with pytest.raises(_mod.GitError, match="not a valid ledger"):
        _mod.load(_mod.fetch())


def test_write_refuses_a_tree_not_named_exactly_claims_json(repo, monkeypatch):
    """Whatever mangles mktree's stdin next, write() must not push the result."""
    real_run = subprocess.run

    def crlf_mktree(cmd, *args, **kwargs):
        if cmd[:2] == ["git", "mktree"]:
            kwargs["input"] = kwargs["input"].replace(b"\n", b"\r\n")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(_mod.subprocess, "run", crlf_mktree)
    with pytest.raises(_mod.GitError, match="refusing to push"):
        _mod.write(None, {"claims": []}, "x")
    assert _run("ls-remote", "../remote.git", cwd=repo / "work") == ""


def test_load_ignores_names_that_only_look_like_the_ledger(repo):
    _push_tree(repo, " claims.json", b'{"claims": []}\n')
    with pytest.raises(_mod.GitError, match="claims.json missing"):
        _mod.load(_mod.fetch())


@pytest.mark.parametrize("quiet,code", [(True, 0), (False, 1)])
def test_list_reports_an_unreadable_ledger_instead_of_crashing(repo, capsys, quiet, code):
    _push_tree(repo, "claims.json", b"not json")
    assert _mod.cmd_list(argparse.Namespace(quiet=quiet)) == code
    assert "ledger unreadable" in capsys.readouterr().out
