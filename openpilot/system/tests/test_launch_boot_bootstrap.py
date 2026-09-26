"""Regression tests for the boot hang that depended on the network at power-on.

Symptom (reported from the device): booting while the car connects to a phone hotspot
leaves the screen on the comma logo for minutes, while booting on home Wi-Fi is fine.
And /tmp/webui.log contained

    ERROR: Could not find a version that satisfies the requirement aiohttp (from versions: none)
    ERROR: No matching distribution found for aiohttp

Root cause: launch_chffrplus.sh runs start_webui() and start_op_assistant() *before*
./manager.py (i.e. before the UI can start), and both probe "is aiohttp importable?".

  start_webui:   if ! "$web_py" -c "import aiohttp"            <- no PYTHONPATH
  start_op_assistant: if ! PYTHONPATH="$py_path" "$aid_py" -c "import aiohttp"

aiohttp lives in $DIR/.pydeps on AGNOS (read-only rootfs), so the webui probe could never
see it: the guard was always true and the script tried a *network* `pip install aiohttp`
on every single boot. pip's defaults are 15 s connect timeout with 5 retries, so a network
that is associated but half-working (a phone hotspot) stalls the boot for ~1.5 min+, and
the watchdog loop re-ran the same download every 45 s afterwards. The comma logo on screen
is the last frame before the UI starts, which is why the hang looks like "the comma icon
froze".

These tests pin the two properties that fix it:
  1. the probe sees .pydeps, so the network path is not taken at all on a normal boot;
  2. every remaining network fallback in the boot path is time-bounded, so even a broken
     network can delay the UI by seconds, not minutes.
"""
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

BOOTSTRAP_MARKER = "webui-bootstrap-v2"
AID_BOOTSTRAP_MARKER = "aid-bootstrap-v2"


def _function_body(source: str, name: str) -> str:
  match = re.search(r"  " + re.escape(name) + r"\(\) \{.*?^\  \}", source, re.M | re.S)
  assert match is not None, f"{name}() not found in launch script"
  return match.group(0)


def _pythonpath_with_pydeps() -> str:
  parts = [str(REPO_ROOT)]
  if VENV_SITE.is_dir():
    parts.append(str(VENV_SITE))
  parts.append(str(PYDEPS))
  return ":".join(parts)


class BootNetworkDependencyTest(unittest.TestCase):
  """Nothing in the pre-manager boot path may wait on the network."""

  @classmethod
  def setUpClass(cls):
    cls.script = LAUNCH.read_text(encoding="utf-8")
    cls.webui = _function_body(cls.script, "start_webui")
    cls.aid = _function_body(cls.script, "start_op_assistant")

  def test_both_helpers_run_before_manager(self):
    """If this changes, the whole hazard moves and these guards must be revisited."""
    self.assertIn("  start_webui\n", self.script)
    self.assertIn("  start_op_assistant\n", self.script)
    self.assertLess(self.script.index("  start_webui\n"), self.script.index("  ./manager.py"))
    self.assertLess(self.script.index("  start_op_assistant\n"), self.script.index("  ./manager.py"))

  def test_aiohttp_probe_sees_pydeps(self):
    """Both probes must put $pydeps on PYTHONPATH, otherwise pip runs every boot."""
    for name, body, py in (("start_webui", self.webui, "web_py"), ("start_op_assistant", self.aid, "aid_py")):
      with self.subTest(func=name):
        self.assertIn(f'PYTHONPATH="$py_path" "${py}" -c "import aiohttp"', body)
        # ...and the unbounded form must be gone.
        self.assertNotIn(f'! "${py}" -c "import aiohttp"', body)

  def test_pip_install_is_bounded_and_behind_the_probe(self):
    for name, body, py in (("start_webui", self.webui, "web_py"), ("start_op_assistant", self.aid, "aid_py")):
      with self.subTest(func=name):
        probe_marker = f'PYTHONPATH="$py_path" "${py}" -c "import aiohttp"'
        self.assertIn(probe_marker, body, "probe must see .pydeps, else pip runs every boot")
        probe = body.index(probe_marker)
        pip_line_idx = body.index(f' "${py}" -m pip install')
        self.assertLess(probe, pip_line_idx, "pip must only run when the probe failed")
        pip_line = body[body.rindex("\n", 0, pip_line_idx) + 1:body.index("\n", pip_line_idx)]
        self.assertIn("--timeout", pip_line)
        self.assertIn("--retries 0", pip_line)

  def test_every_network_call_in_the_script_is_bounded(self):
    """A new curl/wget/pip in the boot path must not be able to hang the UI start."""
    for lineno, line in enumerate(self.script.splitlines(), start=1):
      if line.lstrip().startswith("#"):
        continue
      with self.subTest(line=lineno):
        if re.search(r"\bcurl\b", line):
          self.assertIn("--max-time", line, f"curl without --max-time at line {lineno}")
        if "pip install" in line:
          self.assertIn("--timeout", line, f"pip install without --timeout at line {lineno}")
          self.assertIn("--retries 0", line, f"pip install without --retries 0 at line {lineno}")
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
  """A fresh install / re-patch must not put the unbounded form back."""

  def _template(self, rel: str, var: str) -> str:
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    match = re.search(r"^" + var + r" = r'''(.*?)^'''", text, re.M | re.S)
    assert match is not None, f"{var} not found in {rel}"
    return match.group(1).rstrip("\n")

  def test_webui_template_matches_installed_script(self):
    template = self._template("webui/install/integrate_openpilot.py", "START_WEBUI_FN")
    self.assertEqual(template, _function_body(LAUNCH.read_text(encoding="utf-8"), "start_webui"))

  def test_ai_template_matches_installed_script(self):
    template = self._template("ai/install/integrate_openpilot.py", "START_OP_ASSISTANT_FN")
    self.assertEqual(template, _function_body(LAUNCH.read_text(encoding="utf-8"), "start_op_assistant"))

  def test_installers_can_repair_an_old_script(self):
    """The upgrade guards key off a version marker, so already-installed devices get patched."""
    webui = (REPO_ROOT / "webui/install/integrate_openpilot.py").read_text(encoding="utf-8")
    ai = (REPO_ROOT / "ai/install/integrate_openpilot.py").read_text(encoding="utf-8")
    self.assertIn(f'BOOTSTRAP_MARKER = "{BOOTSTRAP_MARKER}"', webui)
    self.assertIn("if BOOTSTRAP_MARKER in content:", webui)
    self.assertIn(f'AID_BOOTSTRAP_MARKER = "{AID_BOOTSTRAP_MARKER}"', ai)
    self.assertIn("if AID_BOOTSTRAP_MARKER in content:", ai)
    self.assertIn(BOOTSTRAP_MARKER, LAUNCH.read_text(encoding="utf-8"))
    self.assertIn(AID_BOOTSTRAP_MARKER, LAUNCH.read_text(encoding="utf-8"))


if __name__ == "__main__":
  unittest.main()
