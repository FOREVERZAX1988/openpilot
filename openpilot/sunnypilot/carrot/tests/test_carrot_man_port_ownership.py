"""Guard: `CarrotManager._port` must only ever hold the port the UDP socket is
actually bound to.

Regression this pins: `tick()` used to assign the *desired* `CarrotManUdpPort`
param to `self._port`.  `_ensure_socket()` short-circuits when
`self._port == port`, so after that assignment it believed the socket was
already listening on the new port and never rebound: changing
`CarrotManUdpPort` had no effect until the process was restarted.  Worse, the
discovery broadcast (`make_send_message`) advertises `self._port`, so the phone
was told to talk to a port nobody was listening on -> "app cannot find device".

Only `_ensure_socket()` (binds) and `_close_socket()` (sets 0) may own
`self._port`; `__init__` seeds it.  `tick()` must pass the desired value as an
argument instead.
"""

import ast
import unittest
from pathlib import Path

CARROT_MAN = Path(__file__).resolve().parents[1] / "carrot_man.py"
OWNERS = {"__init__", "_ensure_socket", "_close_socket", "_migrate_amap_enabled"}


def _self_port_assigners(tree: ast.AST) -> set[str]:
  assigners: set[str] = set()
  for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
    for node in ast.walk(fn):
      if isinstance(node, ast.Assign):
        targets = node.targets
      elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
      else:
        continue
      for t in targets:
        if isinstance(t, ast.Attribute) and t.attr == "_port" \
           and isinstance(t.value, ast.Name) and t.value.id == "self":
          assigners.add(fn.name)
  return assigners


class TestCarrotManPortOwnership(unittest.TestCase):
  def test_source_is_parseable(self):
    ast.parse(CARROT_MAN.read_text())

  def test_tick_does_not_assign_bound_port(self):
    # NOTE: the state-init tail of CarrotManager.__init__ currently lives inside
    # _migrate_amap_enabled() (it is called from __init__), so that helper may
    # also seed self._port.  tick() must not.
    assigners = _self_port_assigners(ast.parse(CARROT_MAN.read_text()))
    self.assertNotIn(
      "tick", assigners,
      "tick() must not assign self._port: it is the port we are *bound* to, and overwriting it "
      "makes _ensure_socket() skip the rebind. Assigners: " + str(sorted(assigners)))

  def test_tick_rebinds_via_argument(self):
    src = CARROT_MAN.read_text()
    self.assertIn("_ensure_socket(want_port)", src,
                  "tick() must hand the desired port to _ensure_socket() so a param change rebinds")


if __name__ == "__main__":
  unittest.main()
