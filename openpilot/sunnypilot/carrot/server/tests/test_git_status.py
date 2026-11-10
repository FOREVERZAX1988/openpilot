"""git_status must never write to the real checkout.

The launcher installs a downloaded overlay update at boot only when nothing
under /data/openpilot/.git is newer than .overlay_init. The periodic status
fetch used to run against the real repo, so .git was always newer and every
downloaded update was silently skipped at reboot. These tests pin the contract:
correct behind/ahead counts, and a byte-untouched real .git.
"""
import asyncio
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openpilot.sunnypilot.carrot.server.services import git_status
from openpilot.common import repo_update


def _git(*args: str, cwd=None) -> None:
  subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _snapshot(root: Path) -> dict:
  return {str(p.relative_to(root)): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}


def _advance_origin(origin: Path, seed: Path, content: str) -> str:
  (seed / "f.txt").write_text(content + "\n")
  _git("add", "-A", cwd=seed)
  _git("commit", "-m", content, cwd=seed)
  _git("push", str(origin), "master", cwd=seed)
  out = subprocess.run(["git", "rev-parse", "master"], cwd=origin, check=True, capture_output=True, text=True)
  return out.stdout.strip()


class TestGitStatus(unittest.TestCase):

  def setUp(self):
    tmp = tempfile.mkdtemp(prefix="git_status_test_")
    self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    self.tmp_path = Path(tmp)
    seed = self.tmp_path / "seed"
    seed.mkdir()
    _git("init", "-b", "master", cwd=seed)
    _git("config", "user.email", "test@test", cwd=seed)
    _git("config", "user.name", "test", cwd=seed)
    (seed / "f.txt").write_text("a\n")
    _git("add", "-A", cwd=seed)
    _git("commit", "-m", "a", cwd=seed)

    origin = self.tmp_path / "origin.git"
    _git("clone", "--bare", str(seed), str(origin))

    work = self.tmp_path / "work"
    _git("clone", str(origin), str(work))
    _git("config", "user.email", "test@test", cwd=work)
    _git("config", "user.name", "test", cwd=work)

    self.work, self.origin, self.seed = work, origin, seed
    for target, name, value in (
      (git_status, "REPO_DIR", str(work)),
      (git_status, "STATUS_GIT_DIR", str(self.tmp_path / "status_mirror")),
      (repo_update, "LOCK_PATH", str(self.tmp_path / "repo.lock")),
    ):
      patcher = mock.patch.object(target, name, value)
      patcher.start()
      self.addCleanup(patcher.stop)

  def test_behind_count_detected_without_touching_real_git(self):
    tip = _advance_origin(self.origin, self.seed, "b")

    before = _snapshot(self.work / ".git")
    status = asyncio.run(git_status.get_git_status(force=True))
    after = _snapshot(self.work / ".git")

    self.assertEqual(status["state"], "ok")
    self.assertEqual(status["behind"], 1)
    self.assertEqual(status["ahead"], 0)
    self.assertEqual(status["target_head"], tip)
    # The whole point: not one byte of the real .git may change, or the launcher
    # skips the overlay update install at the next boot.
    self.assertEqual(after, before)
    self.assertFalse((self.work / ".git" / "FETCH_HEAD").exists())

  def test_ahead_and_behind_counted_together(self):
    _advance_origin(self.origin, self.seed, "b")
    asyncio.run(git_status.get_git_status(force=True))

    (self.work / "local.txt").write_text("local\n")
    _git("add", "-A", cwd=self.work)
    _git("commit", "-m", "local", cwd=self.work)

    before = _snapshot(self.work / ".git")
    status = asyncio.run(git_status.get_git_status(force=True))

    self.assertEqual(status["state"], "ok")
    self.assertEqual(status["behind"], 1)
    self.assertEqual(status["ahead"], 1)
    self.assertEqual(_snapshot(self.work / ".git"), before)

  def test_up_to_date_after_pull(self):
    _advance_origin(self.origin, self.seed, "b")
    _git("pull", "--ff-only", cwd=self.work)

    status = asyncio.run(git_status.get_git_status(force=True))

    self.assertEqual(status["state"], "ok")
    self.assertEqual(status["behind"], 0)
    self.assertEqual(status["ahead"], 0)

  def test_mirror_self_heals_after_corruption(self):
    _advance_origin(self.origin, self.seed, "b")
    self.assertEqual(asyncio.run(git_status.get_git_status(force=True))["state"], "ok")

    mirror = Path(git_status.STATUS_GIT_DIR)
    (mirror / "HEAD").write_text("garbage")

    status = asyncio.run(git_status.get_git_status(force=True))
    self.assertEqual(status["state"], "ok")
    self.assertEqual(status["behind"], 1)

  def test_fetch_failure_reports_error_state(self):
    _advance_origin(self.origin, self.seed, "b")

    async def dead_fetch(url, refspec):
      return 128, "network down"

    patcher = mock.patch.object(git_status, "_fetch_status_mirror", dead_fetch)
    patcher.start()
    self.addCleanup(patcher.stop)
    status = asyncio.run(git_status.get_git_status(force=True))
    # A failed fetch must not report a usable upstream state.
    self.assertEqual(status["state"], "fetch_error")
    self.assertIs(status["available"], False)


if __name__ == "__main__":
  unittest.main()
