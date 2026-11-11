"""spawn=True launches a fresh interpreter that does not inherit manager state.

Ported from carrotpilot 2fe2caf60; sp selects spawn for services whose crash
restarts must not inherit the manager's IPC state: qcomgpsd and carrot_man.
"""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import unittest
from openpilot.common.test import OpenpilotTestCase
from openpilot.common.parameterized import parameterized

MANAGER_DIR = Path(__file__).resolve().parents[1]


def factories():
  path = MANAGER_DIR / 'process.py'
  tree = ast.parse(path.read_text(encoding='utf-8'))
  definition = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PythonProcess')
  default, spawned = Mock(), Mock()
  namespace = {'ManagerProcess': type('Base', (), {'proc': None, 'shutting_down': False}),
               'Process': default, 'get_context': Mock(return_value=SimpleNamespace(Process=spawned)),
               'launcher': Mock(), 'cloudlog': Mock()}
  exec(compile(ast.Module(body=[definition], type_ignores=[]), str(path), 'exec'), namespace)
  return namespace, default, spawned



class TestPythonProcessSpawnTests(OpenpilotTestCase):

  @parameterized.expand([False, True], names=('spawn',))
  def test_start_uses_selected_context_and_does_not_duplicate_child(self, factories, spawn):
    ns, default, spawned = factories
    process = ns['PythonProcess']('worker', 'worker.module', lambda *_: True, spawn=spawn)
    process.start()
    process.start()
    selected, unused = (spawned, default) if spawn else (default, spawned)
    selected.assert_called_once_with(name='worker', target=ns['launcher'], args=('worker.module', 'worker'))
    selected.return_value.start.assert_called_once_with()
    unused.assert_not_called()
    if spawn:
      ns['get_context'].assert_called_once_with('spawn')
    else:
      ns['get_context'].assert_not_called()


  def test_deferred_and_restart_sensitive_services_select_spawn(self):
    path = MANAGER_DIR / 'process_config.py'
    calls = [n for n in ast.walk(ast.parse(path.read_text(encoding='utf-8')))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'PythonProcess']
    selected = [n.args[0].value for n in calls if any(k.arg == 'spawn' and ast.literal_eval(k.value) for k in n.keywords)]
    # Order follows process_config.py: qcomgpsd before carrot_man.
    assert selected == ['qcomgpsd', 'carrot_man']


  @parameterized.expand([(False, 'carrot_man'), (True, 'carrot_man'), (False, 'qcomgpsd'), (True, 'qcomgpsd')], names=('legacy_fork', 'service'))
  def test_real_crash_restart_and_supervisor_responsiveness(self, tmp_path, legacy_fork, service):
    if legacy_fork and not hasattr(os, 'fork'):
      raise unittest.SkipTest('fork comparison requires POSIX')
    probe = Path(__file__).with_name('process_lifecycle_probe.py')
    result = subprocess.run([sys.executable, str(probe), str(tmp_path), str(int(legacy_fork)), service],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data['pids'][0] != data['pids'][1]
    assert data['crash_exitcode'] != 0
    assert data['max_supervision_s'] < 2.0
    assert data['fork_callbacks'] == (2 if legacy_fork else 0)
    # With legacy fork the child inherits the probe's globals (PARENT_ONLY=True);
    # a spawned child starts fresh and must report False.
    assert data['inherited_parent_state'] == [legacy_fork, legacy_fork]
    assert data['stopped']
