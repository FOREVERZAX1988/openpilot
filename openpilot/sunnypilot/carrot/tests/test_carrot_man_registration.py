"""Guard: carrot_man must be restartable by manager.

Regression (tizi): `PythonProcess("carrot_man", ...)` had no
`restart_if_crash=True`.  `PythonProcess.start()` returns immediately while
`self.proc is not None`, so once the daemon died it was never relaunched --
the 7706 UDP listener and the 7705 discovery beacon stayed down and the phone
app simply could not find the device.
"""

import ast
import unittest
from pathlib import Path

PROCESS_CONFIG = Path(__file__).resolve().parents[3] / "system" / "manager" / "process_config.py"
RESTARTABLE = {"carrot_man", "carrot_navi"}


def _python_processes(tree: ast.AST) -> dict[str, ast.Call]:
  out: dict[str, ast.Call] = {}
  for node in ast.walk(tree):
    if not isinstance(node, ast.Call):
      continue
    func = node.func
    if isinstance(func, ast.Name) and func.id == "PythonProcess" and node.args:
      first = node.args[0]
      if isinstance(first, ast.Constant) and isinstance(first.value, str):
        out[first.value] = node
  return out


class TestCarrotManRegistration(unittest.TestCase):
  def test_source_is_parseable(self):
    ast.parse(PROCESS_CONFIG.read_text())

  def test_carrot_man_exists(self):
    assert "carrot_man" in _python_processes(ast.parse(PROCESS_CONFIG.read_text()))

  def test_carrot_daemons_restart_if_crash(self):
    procs = _python_processes(ast.parse(PROCESS_CONFIG.read_text()))
    for name in RESTARTABLE:
      node = procs[name]
      flags = {kw.arg: kw.value for kw in node.keywords}
      assert "restart_if_crash" in flags, f"{name} must set restart_if_crash"
      value = flags["restart_if_crash"]
      assert isinstance(value, ast.Constant) and value.value is True, (
        f"{name}: restart_if_crash must be True (got {ast.dump(value)})")


if __name__ == "__main__":
  unittest.main()
