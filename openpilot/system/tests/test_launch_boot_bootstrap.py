"""Regression tests for the boot hang that depended on the network at power-on.

Symptom (reported from the device): booting while the car connects to a phone hotspot
leaves the screen on the comma logo for minutes, while booting on home Wi-Fi is fine.
And /tmp/webui.log contained

    ERROR: Could not find a version that satisfies the requirement aiohttp (from versions: none)
    ERROR: No matching distribution found for aiohttp

Root cause: launch_chffrplus.sh started the webui and the ai helper *before* ./manager.py
(i.e. before the UI can start), and both probed "is aiohttp importable?" with a PYTHONPATH
that could not see $DIR/.pydeps. aiohttp lives in the pip target dir on AGNOS (read-only
rootfs), so the probe was always false and the boot path ran a *network* `pip install`
on every single boot. pip's defaults are 15 s connect timeout with 5 retries, so a network
that is associated but half-working (a phone hotspot) stalls the boot for ~1.5 min+, and
the watchdog loop re-ran the same download every 45 s afterwards. The comma logo on screen
is the last frame before the UI starts, which is why the hang looks like "the comma icon
froze".

The two properties that fix it, and that these tests pin:
  1. the dependency probe sees .pydeps, so the network path is not taken on a normal boot;
  2. every remaining network fallback in the boot path is time-bounded, so even a broken
     network can delay the UI by seconds, not minutes.

Rename note (2026-10, tizi device): the script was refactored -- start_webui() and
start_op_assistant() are gone, replaced by start_service()/keep_alive() plus one shared
dependency path (setup_python_path -> ensure_pip_dep / ensure_pip_deps -> bootstrap_deps).
The guards below are written against that structure instead of against the old function
names, and BOOT_HELPERS is an explicit canary: if one of those helpers is renamed again,
test_boot_helpers_exist fails with a message telling you to re-verify the two properties,
rather than the other tests silently checking nothing.
"""
import importlib.util
import os
import pathlib
import re
import shutil
import subprocess
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
LAUNCH = REPO_ROOT / "launch_chffrplus.sh"
VENV_SITE = pathlib.Path("/usr/local/venv/lib/python3.12/site-packages")
PYDEPS = REPO_ROOT / ".pydeps"

# Shared helpers the guards below are expressed in terms of. See the rename note above.
BOOT_HELPERS = (
  "find_python",
  "setup_python_path",
  "ensure_pip_dep",
  "ensure_pip_deps",
  "bootstrap_deps",
  "start_service",
  "keep_alive",
)

# The two services that must exist before ./manager.py, and how the script starts them now.
KEEPALIVE_ENTRIES = {
  "webui": "keep_alive webui webui/webuid.py 5080",
  "aid": "keep_alive aid ai/aid.py 5090",
}

# Legacy (pre-refactor) shape: the installers patch a script that has these functions.
LEGACY_MARKERS = {
  "webui": ("start_webui() {", "webui-bootstrap-v2"),
  "aid": ("start_op_assistant() {", "aid-bootstrap-v2"),
}


def _bash_function(source: str, name: str) -> str:
  """Return the body of a top-level-or-nested bash function, whatever its indent."""
  match = re.search(r"^([ \t]*)" + re.escape(name) + r"\(\) \{.*?^\1\}", source, re.M | re.S)
  assert match is not None, f"{name}() not found in launch script"
  return match.group(0)


def _pythonpath_with_pydeps() -> str:
  parts = [str(REPO_ROOT)]
  if VENV_SITE.is_dir():
    parts.append(str(VENV_SITE))
  parts.append(str(PYDEPS))
  return ":".join(parts)


def _load_installer(rel: str):
  path = REPO_ROOT / rel
  spec = importlib.util.spec_from_file_location(path.parent.parent.name + "_installer", path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


class BootNetworkDependencyTest(unittest.TestCase):
  """Nothing in the pre-manager boot path may wait on the network."""

  @classmethod
  def setUpClass(cls):
    cls.script = LAUNCH.read_text(encoding="utf-8")

  def test_boot_helpers_exist(self):
    """Canary: these guards are expressed in terms of these helpers.

    If this fails after a refactor, do NOT just update the names -- re-verify that
    (a) the dependency probe still runs with $PYDEPS_DIR on PYTHONPATH and
    (b) every network fallback before ./manager.py is still time-bounded.
    """
    for name in BOOT_HELPERS:
      with self.subTest(helper=name):
        self.assertIn(f"{name}() {{", self.script,
                      f"{name}() is gone: the boot guards in this file no longer apply, "
                      f"re-verify probe-visibility + network bounds before renaming BOOT_HELPERS")

  def test_webui_and_aid_start_through_keep_alive_before_manager(self):
    """If this changes, the whole hazard moves and these guards must be revisited."""
    manager_at = self.script.index("  ./manager.py")
    for service, entry in KEEPALIVE_ENTRIES.items():
      with self.subTest(service=service):
        self.assertIn(entry, self.script)
        self.assertLess(self.script.index(entry), manager_at,
                        f"{service} must start before ./manager.py (that ordering is the bug)")

  def test_probes_see_pydeps(self):
    """The probes must put $PYDEPS_DIR on PYTHONPATH, otherwise pip runs every boot."""
    setup = _bash_function(self.script, "setup_python_path")
    self.assertIn('[ -d "$PYDEPS_DIR" ] && py_path="$py_path:$PYDEPS_DIR"', setup)

    # start_service() hands the same PY_PATH to the service it spawns.
    service = _bash_function(self.script, "start_service")
    self.assertIn('local py_path="$PY_PATH"', service)
    self.assertIn('PYTHONPATH="$py_path"', service)

    # Both dependency bootstrap paths probe with that path. The only probe allowed to run
    # bare is the "is pip itself available" check, which does not need $pydeps.
    for fn in ("ensure_pip_dep", "ensure_pip_deps"):
      with self.subTest(func=fn):
        body = _bash_function(self.script, fn)
        self.assertIn('PYTHONPATH="$py_path" "$py" -c "import', body)
        for line in body.splitlines():
          if '"$py" -c "import' not in line or line.lstrip().startswith("#"):
            continue
          if 'PYTHONPATH="$py_path"' in line:
            continue
          probed = line.split('"$py" -c "import', 1)[1].split('"', 1)[0].strip()
          self.assertEqual("pip", probed,
                           f'{fn} probes {probed!r} without PYTHONPATH="$py_path" (line: {line.strip()})')

  def test_every_network_call_in_the_boot_path_is_bounded(self):
    """A new curl/wget/pip in the boot path must not be able to hang the UI start."""
    for lineno, line in enumerate(self.script.splitlines(), start=1):
      if line.lstrip().startswith("#"):
        continue
      with self.subTest(line=lineno):
        if re.search(r"\bcurl\b", line):
          self.assertIn("--max-time", line, f"curl without --max-time at line {lineno}")
        if "pip install" in line and "--no-index" not in line:
          self.assertIn("--timeout", line, f"network pip install without --timeout at line {lineno}")
          self.assertIn("--retries 0", line, f"network pip install without --retries 0 at line {lineno}")
        if re.search(r"\bwget\b", line):
          self.assertIn("--timeout", line, f"wget without --timeout at line {lineno}")

  def test_probe_succeeds_where_the_old_one_failed(self):
    """Functional check: .pydeps really is what makes the probe pass."""
    if not (PYDEPS / "aiohttp").is_dir():
      self.skipTest("no .pydeps/aiohttp on this machine")
    python = None
    for candidate in ("python3.12", "python3", sys.executable):
      if shutil.which(candidate) or os.path.exists(candidate):
        python = candidate
        break
    self.assertIsNotNone(python)

    with_pydeps = subprocess.run([python, "-c", "import aiohttp"], capture_output=True,
                                 env={**os.environ, "PYTHONPATH": _pythonpath_with_pydeps()})
    self.assertEqual(0, with_pydeps.returncode, with_pydeps.stderr.decode())

    bare = subprocess.run([python, "-c", "import aiohttp"], capture_output=True,
                          env={**os.environ, "PYTHONPATH": str(REPO_ROOT)})
    if bare.returncode == 0:
      self.skipTest("aiohttp is also importable without .pydeps here; probe bug not reproducible")
    self.assertNotEqual(0, bare.returncode, "old probe should have failed (that was the bug)")


class InstallerTemplateTest(unittest.TestCase):
  """The installers must never re-insert the unbounded legacy form.

  Two shapes exist on real devices:
    * new-style (this device): start_service()/keep_alive(), no per-service function ->
      the installer has to recognise it and leave the script alone;
    * legacy: start_webui()/start_op_assistant() still present -> the installer patches it,
      and the version marker is what makes an already-patched device re-patchable.
  """

  def test_installers_skip_the_new_style_script(self):
    for rel in ("webui/install/integrate_openpilot.py", "ai/install/integrate_openpilot.py"):
      with self.subTest(installer=rel):
        result = _load_installer(rel).patch_launch_script(LAUNCH, dry_run=True)
        self.assertTrue(result.get("ok"), result)
        self.assertFalse(result.get("changed"), f"{rel} would rewrite the refactored script: {result}")
        self.assertIn("keep_alive", result.get("note", ""))

  def test_legacy_installers_keep_their_idempotence_guards(self):
    """The upgrade guards key off a version marker, so already-installed devices get patched."""
    webui = (REPO_ROOT / "webui/install/integrate_openpilot.py").read_text(encoding="utf-8")
    ai = (REPO_ROOT / "ai/install/integrate_openpilot.py").read_text(encoding="utf-8")
    self.assertIn('BOOTSTRAP_MARKER = "webui-bootstrap-v2"', webui)
    self.assertIn("if BOOTSTRAP_MARKER in content:", webui)
    self.assertIn('AID_BOOTSTRAP_MARKER = "aid-bootstrap-v2"', ai)
    self.assertIn("if AID_BOOTSTRAP_MARKER in content:", ai)

  def test_legacy_shaped_script_carries_the_marker(self):
    """Shape-driven: a script that still has the old functions must be marker-tagged,
    so the installer recognises it as already-patched instead of patching it twice."""
    script = LAUNCH.read_text(encoding="utf-8")
    for service, (func, marker) in LEGACY_MARKERS.items():
      with self.subTest(service=service):
        if func in script:
          self.assertIn(marker, script, f"legacy shape without {marker}; installer would re-patch")


if __name__ == "__main__":
  unittest.main()
