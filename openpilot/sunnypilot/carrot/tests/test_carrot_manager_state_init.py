'''Guard: every CarrotManager runtime attribute tick() touches must be seeded in
CarrotManager.__init__ itself.

Regression this pins (device boot loop, 2026-09-28) -- the *flattened* commit
91caae2181 shipped this shape::

    def __init__(self):
      ...
      self._curve_planner: Any = None
      # <-- __init__ ends here

    def _migrate_amap_enabled(self) -> None:
      "One-time migration ..."
      if self.params.get_bool("AmapEnabled"):
        ...
      self._enabled = False           # <-- runtime state smuggled into a helper
      self._port = 0
      self._sock = None
      self._lock = threading.Lock()

self._migrate_amap_enabled() was never called, so a fresh instance had no _lock
at all and the very first tick() died inside _ensure_socket()::

    carrot_man: tick() error: 'CarrotManager' object has no attribute '_lock'
      File ".../carrot_man.py", line 1583, in tick
        if not self._ensure_socket(self._port):
      File ".../carrot_man.py", line 732, in _ensure_socket
        with self._lock:

main_thread() catches every tick() exception and only logs it, so carrot_man kept
spinning on that error: the 7705 discovery beacon, carrotManSP and
navInstructionCarrotSP were never published and the UI fell into
"Restarting ui (exitcode 1)".  Lines 732/1583 in the traceback pin the running
code to 91caae2181, i.e. the state block really was missing from __init__.

Nothing here imports carrot_man (it needs Params + cereal); the source is
inspected with ast, exactly like test_carrot_man_port_ownership.py.
'''

import ast
import unittest
from pathlib import Path

CARROT_MAN = Path(__file__).resolve().parents[1] / "carrot_man.py"

# Attributes tick() / _ensure_socket() read before they can possibly write them.
# Keep in sync when the runtime-state block grows.
RUNTIME_STATE = {
  "_enabled", "_port", "_start_web",
  "_sock", "_lock", "_last_packet_mono", "_last_seq", "_remote_addr",
  "_broadcast_ip", "_broadcast_port", "_carrot_man_port", "_broadcast_thread",
  "_is_running", "_ip_address",
  "_route_thread", "_route_running", "_route_port",
  "_zmq_thread", "_zmq_running",
}

# Class-level defaults that keep a partially initialised instance from looping on
# AttributeError inside tick() instead of degrading.
BACKSTOP = {"_lock", "_sock", "_port", "_enabled", "_start_web"}


def _class(tree, name="CarrotManager"):
  for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == name:
      return node
  raise AssertionError(f"class {name} not found in {CARROT_MAN}")


def _methods(cls):
  return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}


def _assigned(fn):
  '''Attribute names assigned as self.<name> = ... anywhere inside fn.'''
  out = set()
  for node in ast.walk(fn):
    if isinstance(node, ast.Assign):
      targets = node.targets
    elif isinstance(node, ast.AnnAssign):
      targets = [node.target]
    else:
      continue
    for t in targets:
      if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
        out.add(t.attr)
  return out


def _assigned_names_in_class_body(cls):
  '''Plain (non-self) and self.<name> targets assigned at class level.'''
  out = set()
  for node in cls.body:
    if isinstance(node, ast.Assign):
      targets = node.targets
    elif isinstance(node, ast.AnnAssign):
      targets = [node.target]
    else:
      continue
    for t in targets:
      if isinstance(t, ast.Name):
        out.add(t.id)
      elif isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
        out.add(t.attr)
  return out


def _called_self_methods(fn):
  return {n.func.attr for n in ast.walk(fn)
          if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
          and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"}


class TestCarrotManagerStateInit(unittest.TestCase):
  def setUp(self):
    self.tree = ast.parse(CARROT_MAN.read_text())
    self.cls = _class(self.tree)
    self.methods = _methods(self.cls)

  def test_source_is_parseable(self):
    self.assertIn("__init__", self.methods)

  def test_runtime_state_is_seeded_in_init(self):
    missing = sorted(RUNTIME_STATE - _assigned(self.methods["__init__"]))
    self.assertFalse(
      missing,
      "CarrotManager.__init__ must seed these runtime attributes itself "
      f"(missing: {missing}); leaving them to a helper is what produced the "
      "'object has no attribute _lock' boot loop.")

  def test_migration_helper_does_not_own_runtime_state(self):
    leaked = sorted(RUNTIME_STATE & _assigned(self.methods["_migrate_amap_enabled"]))
    self.assertFalse(
      leaked,
      "runtime state must not live in _migrate_amap_enabled(): that helper is a "
      f"conditional one-shot param migration, not a safe owner (found: {leaked})")

  def test_init_calls_the_migration_helper(self):
    self.assertIn(
      "_migrate_amap_enabled", _called_self_methods(self.methods["__init__"]),
      "__init__ must call self._migrate_amap_enabled() or the legacy AmapEnabled "
      "migration never runs")

  def test_class_level_backstop_exists(self):
    missing = sorted(BACKSTOP - _assigned_names_in_class_body(self.cls))
    self.assertFalse(
      missing,
      f"class-level backstop(s) removed: {missing} - a partially initialised "
      "instance would loop on AttributeError in tick() again")


if __name__ == "__main__":
  unittest.main()
