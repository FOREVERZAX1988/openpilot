import os
import subprocess
import tempfile
import unittest

from openpilot.common.test import OpenpilotTestCase
from openpilot.system.updated.updated import carry_build_artifacts

# The firmware paths the packager strips from the staged tree (they stay
# tracked in the panda fork for pandad's DFU rescue), and the .gitignore
# entries the stripped tree carries so device rebuilds resolve as ignored.
PACKAGED_FIRMWARE = [
  "panda/board/obj/bootstub.panda.bin",
  "panda/board/obj/bootstub.panda_h7.bin",
  "panda/board/obj/panda.bin.signed",
  "panda/board/obj/panda_h7.bin.signed",
]
GITIGNORE = """\
panda/board/obj/*.bin
panda/board/obj/*.bin.signed
.params_registry_ok
"""


def _git(repo: str, *args: str) -> str:
  return subprocess.check_output(["git", *args], cwd=repo, stderr=subprocess.STDOUT, encoding="utf8")


def _init_repo(path: str) -> str:
  os.makedirs(path, exist_ok=True)
  _git(path, "init", "-q")
  _git(path, "config", "user.email", "test@example.com")
  _git(path, "config", "user.name", "test")
  with open(os.path.join(path, ".gitignore"), "w") as f:
    f.write(GITIGNORE)
  _git(path, "add", ".gitignore")
  _git(path, "commit", "-q", "-m", "init")
  return path


def _tracked(repo: str) -> set[str]:
  return set(_git(repo, "ls-files").splitlines())


def _status(repo: str) -> str:
  return _git(repo, "status", "--porcelain").strip()


class TestFirmwareCarryLifecycle(OpenpilotTestCase):

  def test_device_rebuild_carried_and_tree_stays_clean(self):
    """The post-strip world: the staged tree ships no firmware, the device
    rebuilds it (ignored), and every later finalize carries the device build
    into the finalized tree without ever dirtying git status."""
    with tempfile.TemporaryDirectory() as tmp:
      basedir = _init_repo(os.path.join(tmp, "basedir"))
      finalized = _init_repo(os.path.join(tmp, "finalized"))
      staging_root = os.path.join(tmp, "staging")
      os.makedirs(staging_root, exist_ok=True)

      # finalized: staged tree - no firmware tracked at all (packager strips it)
      self.assertEqual("", _tracked(finalized) & set(PACKAGED_FIRMWARE))

      # basedir: device rebuild, ignored
      for rel in PACKAGED_FIRMWARE:
        fw = os.path.join(basedir, rel)
        os.makedirs(os.path.dirname(fw), exist_ok=True)
        with open(fw, "w") as f:
          f.write("device-build")
      self.assertEqual("", _status(basedir))

      carry_build_artifacts(basedir, finalized, staging_root)

      for rel in PACKAGED_FIRMWARE:
        # device build present in the finalized tree for pandad's DFU rescue
        self.assertTrue(os.path.isfile(os.path.join(finalized, rel)))
        self.assertNotIn(rel, _tracked(finalized))
        with open(os.path.join(finalized, rel)) as f:
          self.assertEqual("device-build", f.read())
      self.assertEqual("", _status(finalized))

  def test_tracked_firmware_is_not_carried_or_whitewashed(self):
    """A tree still tracking the firmware (pre-strip) must keep its packaged
    copy intact through a carry: tracked files are neither carried nor
    cleaned, so the packager strip is what fixes the status - the carry must
    not silently mangle it."""
    with tempfile.TemporaryDirectory() as tmp:
      basedir = _init_repo(os.path.join(tmp, "basedir"))
      finalized = _init_repo(os.path.join(tmp, "finalized"))
      staging_root = os.path.join(tmp, "staging")
      os.makedirs(staging_root, exist_ok=True)

      rel = PACKAGED_FIRMWARE[0]
      # finalized: packaged CI build, tracked (as the pre-strip tree ships it)
      fw = os.path.join(finalized, rel)
      os.makedirs(os.path.dirname(fw), exist_ok=True)
      with open(fw, "w") as f:
        f.write("ci-build")
      _git(finalized, "add", "-f", rel)
      _git(finalized, "commit", "-q", "-m", "ship firmware")
      # basedir: device rebuild of the same path, but tracked -> not ignored
      fw = os.path.join(basedir, rel)
      os.makedirs(os.path.dirname(fw), exist_ok=True)
      with open(fw, "w") as f:
        f.write("device-build")
      _git(basedir, "add", "-f", rel)
      _git(basedir, "commit", "-q", "-m", "device rebuild tracked")

      carry_build_artifacts(basedir, finalized, staging_root)

      with open(os.path.join(finalized, rel)) as f:
        self.assertEqual("ci-build", f.read())

  def test_carry_leaves_non_firmware_untouched(self):
    with tempfile.TemporaryDirectory() as tmp:
      basedir = _init_repo(os.path.join(tmp, "basedir"))
      finalized = _init_repo(os.path.join(tmp, "finalized"))
      staging_root = os.path.join(tmp, "staging")
      os.makedirs(staging_root, exist_ok=True)

      with open(os.path.join(basedir, ".params_registry_ok"), "w") as f:
        f.write("abc123")
      os.makedirs(os.path.join(basedir, "prebuilt"))
      with open(os.path.join(basedir, "prebuilt", "libfoo.so"), "w") as f:
        f.write("elf")

      carry_build_artifacts(basedir, finalized, staging_root)

      with open(os.path.join(finalized, ".params_registry_ok")) as f:
        self.assertEqual("abc123", f.read())
      self.assertTrue(os.path.isfile(os.path.join(finalized, "prebuilt", "libfoo.so")))


if __name__ == "__main__":
  unittest.main()
