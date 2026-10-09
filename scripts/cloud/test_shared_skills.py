"""Persistence and discovery contract checks; no user installation or network."""
import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from install_shared_skills import checkout_skills, link_shared_root
from verify_shared_skills import check


class SharedSkillsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "checkout/skills"
        self.example = self.source / "example"
        self.example.mkdir(parents=True)
        (self.example / "SKILL.md").write_text("---\nname: example\ndescription: Test skill\n---\n")
        self.dest = self.root / "codex/skills"
        self.dest.mkdir(parents=True)

    def link(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return link_shared_root(self.source, [self.dest])

    def test_links_are_reused_and_follow_source_updates(self):
        self.assertEqual(self.link(), [])
        target = self.dest / "claude-dotfiles"
        self.assertTrue(target.is_symlink())
        self.assertEqual(target.resolve(), self.source.resolve())
        (self.source / "support.txt").write_text("new source file")
        self.assertEqual((target / "support.txt").read_text(), "new source file")
        new_skill = self.source / "new-skill"
        new_skill.mkdir()
        (new_skill / "SKILL.md").write_text("new skill added after installation")
        self.assertTrue((target / "new-skill/SKILL.md").is_file())
        self.assertEqual(self.link(), [])

    def test_existing_file_preserved(self):
        target = self.dest / "claude-dotfiles"
        target.write_bytes(b"keep existing file")
        self.assertEqual(self.link(), [str(target)])
        self.assertEqual(target.read_bytes(), b"keep existing file")

    def test_existing_directory_preserved(self):
        target = self.dest / "claude-dotfiles"
        target.mkdir()
        (target / "sentinel").write_bytes(b"keep existing skill")
        self.assertEqual(self.link(), [str(target)])
        self.assertFalse(target.is_symlink())
        self.assertEqual((target / "sentinel").read_bytes(), b"keep existing skill")

    def test_broken_link_preserved(self):
        target = self.dest / "claude-dotfiles"
        missing = self.root / "missing"
        target.symlink_to(missing, target_is_directory=True)
        self.assertEqual(self.link(), [str(target)])
        self.assertEqual(target.readlink(), missing)

    def test_wrong_source_link_preserved(self):
        other = self.root / "other"
        other.mkdir()
        target = self.dest / "claude-dotfiles"
        target.symlink_to(other, target_is_directory=True)
        self.assertEqual(self.link(), [str(target)])
        self.assertEqual(target.resolve(), other.resolve())

    def test_discovery_requires_actual_enabled_user_source(self):
        manifest = self.example / "SKILL.md"
        unrelated = self.root / "repo/skills/example/SKILL.md"
        for path, scope, enabled, missing in [
            (unrelated, "user", True, True),
            (manifest, "repo", True, True),
            (manifest, "user", False, True),
            (manifest, "user", True, False),
        ]:
            with self.subTest(path=path, scope=scope, enabled=enabled):
                result = {"data": [{"skills": [{"name": "example", "path": str(path),
                           "scope": scope, "enabled": enabled}], "errors": []}]}
                with contextlib.redirect_stdout(io.StringIO()):
                    summary = check(result, self.root / "checkout")
                self.assertEqual(bool(summary["missing_or_disabled"]), missing)

    def test_update_cannot_overwrite_ignored_local_file(self):
        upstream = self.root / "checkout"

        def git(*args):
            return subprocess.run(["git", "-C", str(upstream), *args], check=True,
                                  capture_output=True, text=True)

        git("init", "-b", "main")
        git("config", "user.name", "Setup test fixture")
        git("config", "user.email", "fixture@example.invalid")
        (upstream / ".gitignore").write_text("ignored.txt\n")
        git("add", ".")
        git("commit", "-m", "Initial fixture")
        installed = self.root / "installed"
        with patch("install_shared_skills.REPOSITORY", str(upstream)):
            with contextlib.redirect_stdout(io.StringIO()):
                checkout_skills(installed, update=False)
            sentinel = installed / "ignored.txt"
            sentinel.write_bytes(b"existing local data")
            initial_head = subprocess.check_output(["git", "-C", str(installed),
                                                   "rev-parse", "HEAD"])
            (upstream / "ignored.txt").write_text("incoming tracked data")
            git("add", "-f", "ignored.txt")
            git("commit", "-m", "Introduce conflicting tracked path")
            with self.assertRaises(subprocess.CalledProcessError):
                checkout_skills(installed, update=True)
            self.assertEqual(sentinel.read_bytes(), b"existing local data")
            self.assertEqual(subprocess.check_output(["git", "-C", str(installed),
                                                      "rev-parse", "HEAD"]), initial_head)


if __name__ == "__main__":
    unittest.main()
