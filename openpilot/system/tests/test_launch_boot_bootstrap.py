"""Regression tests for the boot hang that depended on the network at power-on.

Symptom (reported from the device): booting while the car connects to a phone hotspot
leaves the screen on the comma logo for minutes, while booting on home Wi-Fi is fine.
And /tmp/webui.log contained

    ERROR: Could not find a version that satisfies the requirement aiohttp (from versions: none)
    ERROR: No matching distribution found for aiohttp

Root cause: launch_chffrplus.sh used to start webui/aid *before* ./manager.py and both
probes ran without PYTHONPATH, so aiohttp (which lives in /data/.pydeps on the read-only
AGNOS rootfs) was never visible. The probe therefore always failed, every boot ran a
*network* `pip install aiohttp`, and pip's unbounded defaults (15 s connect timeout, 5
retries) turned a half-working network into a ~1.5 min+ stall before the UI could start.

The launcher has since been refactored into shared helpers (setup_python_path /
ensure_pip_dep(s) / bootstrap_deps_retry + keep_alive). These tests pin the properties
that keep the original bug fixed - they are written against the helper layer, not against
the removed start_webui()/start_op_assistant() functions:

  1. the probes see $PYDEPS_DIR, so the network path is not taken on a normal boot;
  2. PYTHONPATH is exported for manager's children (a daemon that cannot import aiohttp
     loses carrot_navi's 7714 receiver silently);
  3. every remaining network call in the boot path is time-bounded, so even a broken
     network can delay the UI by seconds, not minutes;
  4. a failed bootstrap defers to a background retry loop instead of blocking boot.
"""
import importlib.util
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
LAUNCH = REPO_ROOT / "launch_chffrplus.sh"
VENV_SITE = pathlib.Path("/usr/local/venv/lib/python3.12/site-packages")
PYDEPS = REPO_ROOT / ".pydeps"

WEBUI_INSTALLER = REPO_ROOT / "webui/install/integrate_openpilot.py"
AI_INSTALLER = REPO_ROOT / "ai/install/integrate_openpilot.py"

AIOHTTP_GROUP = "aiohttp jinja2 zmq zstandard numpy requests tqdm jeepney"


def _function_body(source: str, name: str) -> str:
  """Return the body of a shell function, whatever its indentation depth."""
  match = re.search(
    r"^(?P<ind>[ \t]*)" + re.escape(name) + r"\(\) \{.*?^(?P=ind)\}",
    source, re.M | re.S,
  )
  assert match is not None, f"{name}() not found in launch script"
  return match.group(0)


def _pythonpath_with_pydeps() -> str:
  parts = [str(REPO_ROOT)]
  if VENV_SITE.is_dir():
    parts.append(str(VENV_SITE))
  parts.append(str(PYDEPS))
  return ":".join(parts)


def _load_installer(path: pathlib.Path, module_name: str):
  spec = importlib.util.spec_from_file_location(module_name, path)
  assert spec is not None and spec.loader is not None, f"cannot load {path}"
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


LEGACY_WEBUI_FN = """  start_webui() {
    local root="$DIR"
    if [ ! -f "$root/webui/webuid.py" ]; then
      return 0
    fi
    local web_py=python3.12
    command -v "$web_py" >/dev/null 2>&1 || web_py=python3
    local venv_site="/usr/local/venv/lib/python3.12/site-packages"
    local pydeps="/data/.pydeps"
    local py_path="$root"
    [ -d "$venv_site" ] && py_path="$py_path:$venv_site"
    [ -d "$pydeps" ] && py_path="$py_path:$pydeps"
    if pgrep -f "[p]ython.* -m webui\\.webuid" >/dev/null 2>&1; then
      return 0
    fi
    (cd "$root" && PYTHONPATH="$py_path" WEBUI_TLS=1 "$web_py" -m webui.webuid >> /tmp/webui.log 2>&1 &)
  }"""

LEGACY_AI_FN = """  start_op_assistant() {
    local root="$DIR"
    if [ ! -f "$root/ai/aid.py" ]; then
      return 0
    fi
    local aid_py=python3.12
    command -v "$aid_py" >/dev/null 2>&1 || aid_py=python3
    local pydeps="$root/.pydeps"
    local py_path="$root"
    [ -d "$pydeps" ] && py_path="$py_path:$pydeps"
    if pgrep -f "[p]ython.* -m ai\\.aid" >/dev/null 2>&1; then
      return 0
    fi
    (cd "$root" && PYTHONPATH="$py_path" "$aid_py" -m ai.aid >> /tmp/aid.log 2>&1 &)
  }"""

LEGACY_TEMPLATE = """#!/usr/bin/env bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
launch() {
__WEBUI_FN__

__AI_FN__

  cd openpilot/system/manager
  ./manager.py
}
launch
"""


class BootNetworkDependencyTest(unittest.TestCase):
  """Nothing in the pre-manager boot path may wait on the network."""

  @classmethod
  def setUpClass(cls):
    cls.script = LAUNCH.read_text(encoding="utf-8")
    # The real invocation, not the "./manager.py" mentions in the comments above it.
    match = re.search(r"^[ \t]*\./manager\.py[ \t]*$", cls.script, re.M)
    assert match is not None, "launch script no longer starts ./manager.py"
    cls.manager_idx = match.start()

  def test_pydeps_is_on_the_python_path_for_every_probe(self):
    """The probes must see .pydeps, otherwise the network path is taken on every boot."""
    self.assertIn('PYDEPS_DIR="/data/.pydeps"', self.script)
    setup = _function_body(self.script, "setup_python_path")
    self.assertIn('[ -d "$PYDEPS_DIR" ] && py_path="$py_path:$PYDEPS_DIR"', setup)

    # Both dependency helpers build their PYTHONPATH through setup_python_path().
    for name in ("ensure_pip_dep", "ensure_pip_deps", "python_package_ok"):
      with self.subTest(func=name):
        body = _function_body(self.script, name)
        self.assertIn('setup_python_path "$DIR"', body)
        self.assertIn('PYTHONPATH="$py_path"', body)

  def test_aiohttp_group_is_bootstrapped_before_manager(self):
    """The webui/aid dependency group must be installed (and inherited) before manager."""
    group_idx = self.script.index(f"ensure_pip_deps {AIOHTTP_GROUP}")
    self.assertLess(group_idx, self.manager_idx)

    # manager.py launches every daemon through Popen() without env=, so daemons only get
    # $PYDEPS_DIR if the launcher exports it (this is what killed carrot_navi's 7714).
    export_idx = self.script.index('export PYTHONPATH="$PY_PATH"')
    self.assertLess(export_idx, self.manager_idx)
    self.assertIn('PY_PATH=$(setup_python_path "$DIR")', self.script)

  def test_every_network_call_in_the_script_is_bounded(self):
    """A new curl/wget/pip in the boot path must not be able to hang the UI start."""
    for lineno, line in enumerate(self.script.splitlines(), start=1):
      if line.lstrip().startswith("#"):
        continue
      with self.subTest(line=lineno):
        if re.search(r"\bcurl\b", line):
          self.assertIn("--max-time", line, f"curl without --max-time at line {lineno}")
          self.assertIn("--connect-timeout", line, f"curl without --connect-timeout at line {lineno}")
        if "pip install" in line:
          self.assertIn("--timeout", line, f"pip install without --timeout at line {lineno}")
          self.assertIn("--retries 0", line, f"pip install without --retries 0 at line {lineno}")
        if re.search(r"\bwget\b", line):
          self.assertIn("--timeout", line, f"wget without --timeout at line {lineno}")

  def test_failed_bootstrap_defers_to_a_background_retry(self):
    """A missing dependency must never block the UI: retry in the background instead."""
    self.assertIn('bootstrap_deps_retry >> /tmp/bootstrap.log 2>&1 &', self.script)
    boot = self.script.index("if bootstrap_deps; then")
    self.assertLess(boot, self.manager_idx)
    retry = _function_body(self.script, "bootstrap_deps_retry")
    self.assertIn("sleep", retry)

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


class InstallerIntegrationTest(unittest.TestCase):
  """Installers must leave the new-style launcher alone, but repair legacy scripts."""

  # (installer, module name, marker attribute, marker value, function, probe interpreter)
  INSTALLERS = (
    (WEBUI_INSTALLER, "webui_integrate", "WEBUI_BOOTSTRAP_MARKER", "webui-bootstrap-v2",
     "start_webui", '"$web_py"'),
    (AI_INSTALLER, "ai_integrate", "AID_BOOTSTRAP_MARKER", "aid-bootstrap-v2",
     "start_op_assistant", '"$aid_py"'),
  )

  def setUp(self):
    self.tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="launch-bootstrap-"))
    self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

  def _write_script(self, content: str) -> pathlib.Path:
    path = self.tmpdir / "launch_chffrplus.sh"
    path.write_text(content, encoding="utf-8")
    return path

  def test_installers_do_not_rewrite_the_new_style_launcher(self):
    """keep_alive already starts webui/aid; patching again would double-start them."""
    original = LAUNCH.read_text(encoding="utf-8")
    for rel, mod_name, _marker_attr, _marker, _fn, _interp in self.INSTALLERS:
      with self.subTest(installer=rel.parent.name):
        module = _load_installer(rel, mod_name)
        path = self._write_script(original)
        result = module.patch_launch_script(path)
        self.assertTrue(result.get("ok"), result)
        self.assertFalse(result.get("changed"), result)
        self.assertIn("keep_alive", result.get("note", ""))
        self.assertEqual(original, path.read_text(encoding="utf-8"))

  def test_installers_upgrade_legacy_scripts_to_a_bounded_bootstrap(self):
    """Old installs carry .pydeps/WEBUI_TLS but not the marker, so they must be re-patched."""
    legacy = LEGACY_TEMPLATE.replace("__WEBUI_FN__", LEGACY_WEBUI_FN).replace("__AI_FN__", LEGACY_AI_FN)
    for rel, mod_name, marker_attr, marker, fn_name, interp in self.INSTALLERS:
      with self.subTest(installer=rel.parent.name):
        module = _load_installer(rel, mod_name)
        self.assertEqual(marker, getattr(module, marker_attr),
                         f"{rel} must keep {marker_attr} so old installs are re-patched")

        path = self._write_script(legacy)
        dry_run = module.patch_launch_script(path, dry_run=True)
        self.assertTrue(dry_run.get("changed"), dry_run)
        self.assertEqual(legacy, path.read_text(encoding="utf-8"), "dry run must not write")

        result = module.patch_launch_script(path)
        self.assertTrue(result.get("changed"), result)
        patched = path.read_text(encoding="utf-8")
        self.assertIn(marker, patched)
        self.assertNotIn(legacy, patched)

        body = _function_body(patched, fn_name)
        self.assertIn(f'PYTHONPATH="$py_path" {interp} -c "import aiohttp"', body)
        for line in body.splitlines():
          if re.search(r"\bcurl\b", line):
            self.assertIn("--max-time", line, f"unbounded curl in {rel}: {line.strip()}")
          if "pip install" in line:
            self.assertIn("--timeout", line, f"unbounded pip in {rel}: {line.strip()}")
            self.assertIn("--retries 0", line, f"pip retries in {rel}: {line.strip()}")


if __name__ == "__main__":
  unittest.main()
