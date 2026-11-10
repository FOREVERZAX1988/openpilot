import asyncio
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

from openpilot.sunnypilot.carrot.server.services.git_config import prepare_git_pull, repair_git_config

SKIP_REASON = ("drives real git remotes, worktrees and index locks; it needs a full checkout on a "
               "device, and blocks on the network in a bare one")


def git(repo, *args, check=True):
  proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
  if check:
    assert proc.returncode == 0, proc.stdout + proc.stderr
  return proc.stdout.strip() if check else proc


def checkout(tmp_path, branch="carrot-wip"):
  seed, remote, device = (tmp_path / name for name in ("seed", "origin.git", "device"))
  seed.mkdir()
  git(seed, "init", "-b", branch)
  git(seed, "config", "user.name", "Git repair test")
  git(seed, "config", "user.email", "test@example.invalid")
  (seed / "version.txt").write_text("old\n")
  git(seed, "add", "version.txt")
  git(seed, "commit", "-qm", "initial")
  git(tmp_path, "clone", "--bare", str(seed), str(remote))
  git(tmp_path, "clone", "--depth=1", "--branch", branch, remote.as_uri(), str(device))
  (seed / "version.txt").write_text("new\n")
  git(seed, "commit", "-qam", "update")
  git(seed, "push", str(remote), branch)
  return seed, remote, device


def dispatch(dispatcher, api, action, **payload):
  if api == "job":
    job = {"id": "git-repair-test", "action": action, "payload": payload}
    asyncio.run(dispatcher.run_tool_job(job))
    return job["result"]
  response = asyncio.run(dispatcher.dispatch_sync(None, {"action": action, **payload}))
  return json.loads(response.text)


def add_other_model(device):
  seed = device.parent / "seed"
  remote = device.parent / "origin.git"
  git(seed, "checkout", "-b", "carrot-other", "HEAD~1")
  (seed / "other-model.txt").write_text("other model only\n")
  git(seed, "add", "other-model.txt")
  git(seed, "commit", "-qm", "other model")
  git(seed, "push", str(remote), "carrot-other")
  git(device, "config", "--replace-all", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
  return git(seed, "rev-parse", "carrot-wip")


@unittest.skip(SKIP_REASON)
class TestGitConfig(unittest.TestCase):

  def setUp(self):
    tmp = tempfile.mkdtemp(prefix="git_config_test_")
    self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    self.tmp_path = Path(tmp)
    # isolated_git fixture
    patcher = mock.patch.dict(os.environ, {
      "GIT_CONFIG_GLOBAL": os.devnull,
      "GIT_CONFIG_NOSYSTEM": "1",
      "GIT_TERMINAL_PROMPT": "0",
    })
    patcher.start()
    self.addCleanup(patcher.stop)

  def patch(self, target, name, value):
    patcher = mock.patch.object(target, name, value)
    patcher.start()
    self.addCleanup(patcher.stop)

  def _web_dispatcher(self):
    """Load the real tool dispatcher without starting vehicle-only feature imports."""
    from openpilot.common import repo_update
    self.patch(repo_update, "LOCK_PATH", str(self.tmp_path / "repo.lock"))
    _, _, device = checkout(self.tmp_path)
    server_dir = Path(__file__).parents[1]
    base = "openpilot.sunnypilot.carrot.server.features"
    base_package = types.ModuleType(base)
    base_package.__path__ = [str(server_dir / "features")]
    tools_package = types.ModuleType(base + ".tools")
    tools_package.__path__ = [str(server_dir / "features" / "tools")]
    hardware = types.ModuleType("openpilot.system.hardware")
    hardware.HARDWARE = types.SimpleNamespace(get_device_type=lambda: "tici")
    patcher = mock.patch.dict(sys.modules, {
      base: base_package,
      base + ".tools": tools_package,
      hardware.__name__: hardware,
    })
    patcher.start()
    self.addCleanup(patcher.stop)
    loaded = {}
    for name in ("jobs", "actions", "dispatcher"):
      module_name = f"{base}.tools.{name}"
      spec = importlib.util.spec_from_file_location(module_name, server_dir / f"features/tools/{name}.py")
      module = importlib.util.module_from_spec(spec)
      sys.modules[module_name] = module
      spec.loader.exec_module(module)
      loaded[name] = module
    dispatcher = loaded["dispatcher"]
    self.patch(dispatcher.jobs, "persist_changed", lambda: None)
    self.patch(dispatcher, "write_git_pull_time", lambda: None)
    self.patch(dispatcher, "clear_recovered_git_ref_error", lambda: None)
    real_run = subprocess.run
    commands = []

    def run(argv, **kwargs):
      if kwargs.get("cwd") == "/data/openpilot":
        kwargs["cwd"] = str(device)
        commands.append(argv)
      return real_run(argv, **kwargs)

    async def capture(argv, *, cwd, **kwargs):
      result = run(argv, cwd=cwd, timeout=kwargs["timeout"], capture_output=True, text=True)
      return result.returncode, result.stdout + result.stderr

    async def stream(job, argv, *, cwd, **kwargs):
      rc, out = await capture(argv, cwd=cwd, **kwargs)
      dispatcher.jobs.append(job, out)
      return rc

    self.patch(subprocess, "run", run)
    self.patch(dispatcher.jobs, "capture_exec", capture)
    self.patch(dispatcher.jobs, "stream_exec", stream)
    return dispatcher, device, commands

  def test_migrated_fetch_and_upstream_repaired_without_switching_model(self):
    for branch in ["carrot-wip", "carrot-cinque-terre", "carrot-bmr_v6"]:
      with self.subTest(branch=branch):
        tmp = tempfile.mkdtemp(prefix="git_config_test_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        _, remote, device = checkout(Path(tmp), branch)
        old_spec = "+refs/heads/release-tizi-staging:refs/remotes/origin/release-tizi-staging"
        git(device, "config", "--replace-all", "remote.origin.fetch", old_spec)
        git(device, "config", f"branch.{branch}.merge", "refs/heads/release-tizi-staging")
        before = git(device, "rev-parse", "HEAD")
        failed = git(device, "pull", "--ff-only", check=False)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("couldn't find remote ref refs/heads/release-tizi-staging", failed.stderr)

        rc, output = repair_git_config(str(device))

        self.assertEqual(rc, 0, output)
        self.assertIn("Removed obsolete fetch ref", output)
        self.assertIn(f"Upstream repaired: {branch} -> origin/{branch}", output)
        self.assertEqual(git(device, "branch", "--show-current"), branch)
        self.assertEqual(git(device, "rev-parse", "HEAD"), before)
        self.assertEqual(git(device, "remote", "get-url", "origin"), remote.as_uri())
        git(device, "pull", "--ff-only")
        self.assertEqual(git(device, "rev-parse", "HEAD"), git(remote, "rev-parse", f"refs/heads/{branch}"))

  def test_removes_duplicate_stale_refs_but_preserves_custom_mappings_and_changes(self):
    _, _, device = checkout(self.tmp_path)
    old_spec = "+refs/heads/deleted:refs/remotes/origin/deleted"
    for spec in [old_spec, old_spec, "+refs/tags/*:refs/tags/*", "^refs/heads/private/*"]:
      git(device, "config", "--add", "remote.origin.fetch", spec)
    (device / "version.txt").write_text("local staged change\n")
    git(device, "add", "version.txt")
    (device / "untracked.txt").write_text("keep me\n")
    status = git(device, "status", "--porcelain")
    index = git(device, "write-tree")
    head = git(device, "rev-parse", "HEAD")

    rc, output = repair_git_config(str(device))

    self.assertEqual(rc, 0, output)
    specs = git(device, "config", "--get-all", "remote.origin.fetch").splitlines()
    self.assertNotIn(old_spec, specs)
    self.assertIn("+refs/tags/*:refs/tags/*", specs)
    self.assertIn("^refs/heads/private/*", specs)
    self.assertEqual(git(device, "status", "--porcelain"), status)
    self.assertEqual(git(device, "write-tree"), index)
    self.assertEqual(git(device, "rev-parse", "HEAD"), head)

  def test_valid_differently_named_upstream_and_non_origin_remote_are_preserved(self):
    _, _, device = checkout(self.tmp_path)
    git(device, "remote", "rename", "origin", "my-fork")
    git(device, "branch", "-m", "my-local-branch")
    rc, output = repair_git_config(str(device))
    self.assertEqual(rc, 0, output)
    self.assertEqual(git(device, "rev-parse", "--abbrev-ref", "@{upstream}"), "my-fork/carrot-wip")
    self.assertEqual(git(device, "branch", "--show-current"), "my-local-branch")
    before = (device / ".git/config").read_bytes()
    rc, output = repair_git_config(str(device))
    self.assertEqual(rc, 0, output)
    self.assertEqual((device / ".git/config").read_bytes(), before)

  def test_missing_upstream_reconnected_by_exact_current_branch_name(self):
    _, _, device = checkout(self.tmp_path)
    git(device, "branch", "--unset-upstream")
    rc, output = repair_git_config(str(device))
    self.assertEqual(rc, 0, output)
    self.assertEqual(git(device, "rev-parse", "--abbrev-ref", "@{upstream}"), "origin/carrot-wip")

  def test_missing_remote_branch_does_not_guess_a_model_or_modify_config(self):
    _, _, device = checkout(self.tmp_path)
    git(device, "branch", "-m", "carrot-missing-model")
    git(device, "config", "branch.carrot-missing-model.merge", "refs/heads/deleted")
    before = (device / ".git/config").read_bytes()
    rc, output = repair_git_config(str(device))
    self.assertNotEqual(rc, 0)
    self.assertIn("No valid upstream or matching remote branch", output)
    self.assertEqual((device / ".git/config").read_bytes(), before)
    self.assertEqual(git(device, "branch", "--show-current"), "carrot-missing-model")

  def test_unreachable_remote_preserves_config_and_worktree(self):
    _, _, device = checkout(self.tmp_path)
    git(device, "remote", "set-url", "origin", str(self.tmp_path / "missing.git"))
    before = (device / ".git/config").read_bytes()
    (device / "version.txt").write_text("keep local change\n")
    rc, output = repair_git_config(str(device))
    self.assertNotEqual(rc, 0)
    self.assertIn("Git configuration repair failed", output)
    self.assertEqual((device / ".git/config").read_bytes(), before)
    self.assertEqual((device / "version.txt").read_text(), "keep local change\n")

  def test_remote_change_can_repair_fetch_before_user_selects_a_new_branch(self):
    _, _, device = checkout(self.tmp_path)
    git(device, "branch", "-m", "release-tizi-staging")
    git(device, "config", "--replace-all", "remote.origin.fetch",
        "+refs/heads/release-tizi-staging:refs/remotes/origin/release-tizi-staging")
    rc, output = repair_git_config(str(device), remote="origin", repair_upstream=False)
    self.assertEqual(rc, 0, output)
    self.assertEqual(git(device, "branch", "--show-current"), "release-tizi-staging")
    git(device, "fetch", "origin")
    self.assertTrue(git(device, "rev-parse", "--verify", "refs/remotes/origin/carrot-wip"))

  def test_detached_head_remains_detached(self):
    _, _, device = checkout(self.tmp_path)
    git(device, "checkout", "--detach")
    head = git(device, "rev-parse", "HEAD")
    rc, output = repair_git_config(str(device))
    self.assertEqual(rc, 0, output)
    self.assertEqual(git(device, "branch", "--show-current"), "")
    self.assertEqual(git(device, "rev-parse", "HEAD"), head)

  def test_fetch_failure_does_not_reconnect_upstream(self):
    _, _, device = checkout(self.tmp_path)
    git(device, "config", "branch.carrot-wip.merge", "refs/heads/deleted")
    real_run = subprocess.run

    def fail_fetch(argv, **kwargs):
      if argv[:2] == ["git", "fetch"]:
        return subprocess.CompletedProcess(argv, 1, "", "fetch failed")
      return real_run(argv, **kwargs)

    self.patch(subprocess, "run", fail_fetch)
    rc, output = repair_git_config(str(device))
    self.assertNotEqual(rc, 0)
    self.assertIn("fetch failed", output)
    self.assertEqual(git(device, "config", "branch.carrot-wip.merge"), "refs/heads/deleted")

  def test_web_reboots_use_chime_helper(self):
    for api in ['job', 'sync']:
      for action in ['reboot', 'reset_calib', 'rebuild_all']:
        with self.subTest(api=api, action=action):
          dispatcher, _, _ = self._web_dispatcher()
          calls = []
          real_popen = subprocess.Popen

          def popen(argv, calls=calls, real_popen=real_popen, **kwargs):
            if argv[0] == 'bash':
              calls.append(('command', argv))
              return None
            return real_popen(argv, **kwargs)

          self.patch(dispatcher, 'spawn_reboot', lambda calls=calls, **kw: calls.append(('reboot', kw)))
          self.patch(dispatcher.subprocess, 'Popen', popen)
          self.patch(dispatcher.os, 'remove', lambda path: None)

          async def no_sleep(delay):
            pass

          self.patch(dispatcher.asyncio, 'sleep', no_sleep)
          result = dispatch(dispatcher, api, action)
          self.assertTrue(result['ok'])
          if action == 'rebuild_all':
            self.assertEqual(calls, [('command', ['bash', '-lc',
                                         'cd /data/openpilot && scons -c && rm -rf prebuilt && python3 -m openpilot.common.reboot'])])
          else:
            delay = {'delay': 1.0} if action == 'reset_calib' and api == 'sync' else {}
            self.assertEqual(calls, [('reboot', delay)])

  def test_manual_pull_recovers_orphaned_index_lock(self):
    from openpilot.common import repo_update
    for api in ["job", "sync"]:
      with self.subTest(api=api):
        dispatcher, device, _ = self._web_dispatcher()
        lock = device / ".git/index.lock"
        lock.write_bytes(b"interrupted Git operation")
        self.patch(repo_update, "STALE_INDEX_SECONDS", -1)
        self.patch(repo_update, "git_process_running", lambda: False)
        result = dispatch(dispatcher, api, "git_pull")
        self.assertTrue(result["ok"], result)
        self.assertFalse(lock.exists())

  def test_manual_git_waits_while_build_owns_checkout(self):
    from openpilot.common.repo_update import repo_lock
    for api in ["job", "sync"]:
      with self.subTest(api=api):
        dispatcher, _, commands = self._web_dispatcher()
        with repo_lock():
          result = dispatch(dispatcher, api, "git_pull")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "GIT_BUSY")
        self.assertEqual(commands, [])

  def test_web_reset_repairs_migration_before_requested_reset(self):
    for api in ["job", "sync"]:
      for mode in ["hard", "mixed", "soft"]:
        with self.subTest(api=api, mode=mode):
          dispatcher, device, commands = self._web_dispatcher()
          git(device, "config", "--replace-all", "remote.origin.fetch",
              "+refs/heads/release-tizi-staging:refs/remotes/origin/release-tizi-staging")
          git(device, "config", "branch.carrot-wip.merge", "refs/heads/release-tizi-staging")
          (device / "version.txt").write_text("user change\n")

          result = dispatch(dispatcher, api, "git_reset", mode=mode, target="HEAD")

          self.assertTrue(result["ok"], result)
          self.assertEqual(git(device, "rev-parse", "--abbrev-ref", "@{upstream}"), "origin/carrot-wip")
          fetch = ["git", "fetch", "--prune", "--no-recurse-submodules", "origin", "+refs/heads/carrot-wip:refs/remotes/origin/carrot-wip"]
          self.assertLess(commands.index(fetch), commands.index(["git", "reset", f"--{mode}", "HEAD"]))
          self.assertEqual((device / "version.txt").read_text(), ("old\n" if mode == "hard" else "user change\n"))

  def test_web_pull_repairs_config_and_updates_current_branch(self):
    for api in ["job", "sync"]:
      with self.subTest(api=api):
        dispatcher, device, _ = self._web_dispatcher()
        git(device, "config", "--replace-all", "remote.origin.fetch",
            "+refs/heads/release-tizi-staging:refs/remotes/origin/release-tizi-staging")
        result = dispatch(dispatcher, api, "git_pull")
        self.assertTrue(result["ok"], result)
        self.assertEqual((device / "version.txt").read_text(), "new\n")
        self.assertEqual(git(device, "branch", "--show-current"), "carrot-wip")

  def test_web_repair_failure_does_not_reset_or_pull(self):
    for api in ["job", "sync"]:
      for action in ["git_reset", "git_pull"]:
        with self.subTest(api=api, action=action):
          dispatcher, device, commands = self._web_dispatcher()
          git(device, "remote", "set-url", "origin", str(device / "missing.git"))
          (device / "version.txt").write_text("keep my changes\n")
          result = dispatch(dispatcher, api, action, mode="hard", target="HEAD")
          self.assertFalse(result["ok"], result)
          self.assertFalse(any(cmd[:2] in (["git", "reset"], ["git", "pull"]) for cmd in commands))
          self.assertEqual((device / "version.txt").read_text(), "keep my changes\n")

  def test_web_remote_change_removes_inherited_fetch_ref(self):
    for api in ["job", "sync"]:
      for action in ["git_remote_set", "git_remote_add"]:
        with self.subTest(api=api, action=action):
          dispatcher, device, _ = self._web_dispatcher()
          url = git(device, "remote", "get-url", "origin")
          git(device, "config", "--replace-all", "remote.origin.fetch",
              "+refs/heads/release-tizi-staging:refs/remotes/origin/release-tizi-staging")
          result = dispatch(dispatcher, api, action, name="origin", url=url)
          self.assertTrue(result["ok"], result)
          git(device, "fetch", "origin")

  def test_pull_applies_only_selected_model_despite_multiple_fetch_heads(self):
    for api in ["job", "sync"]:
      for duplicate_tracking in [False, True]:
        with self.subTest(api=api, duplicate_tracking=duplicate_tracking):
          dispatcher, device, commands = self._web_dispatcher()
          expected = add_other_model(device)
          if duplicate_tracking:
            git(device, "config", "--add", "branch.carrot-wip.merge", "refs/heads/carrot-other")
            failed = git(device, "pull", "--ff-only", check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("Cannot fast-forward to multiple branches", failed.stderr)

          def prepare(repo, device=device):
            result = prepare_git_pull(repo)
            # Reproduce an unrelated fetch changing FETCH_HEAD after target selection.
            git(device, "fetch", "origin", "carrot-wip", "carrot-other")
            self.assertEqual(len((device / ".git/FETCH_HEAD").read_text().splitlines()), 2)
            return result

          self.patch(dispatcher, "prepare_git_pull", prepare)
          result = dispatch(dispatcher, api, "git_pull")
          self.assertTrue(result["ok"], result)
          self.assertEqual(git(device, "rev-parse", "HEAD"), expected)
          self.assertEqual(git(device, "branch", "--show-current"), "carrot-wip")
          self.assertEqual(git(device, "config", "--get-all", "branch.carrot-wip.merge"), "refs/heads/carrot-wip")
          self.assertFalse((device / "other-model.txt").exists())
          self.assertIn(["git", "merge", "--ff-only", expected], commands)

  def test_ambiguous_tracking_without_exact_branch_does_not_guess_model(self):
    _, _, device = checkout(self.tmp_path)
    add_other_model(device)
    git(device, "branch", "-m", "unknown-model")
    git(device, "config", "--add", "branch.unknown-model.merge", "refs/heads/carrot-other")
    config = (device / ".git/config").read_bytes()
    before = git(device, "rev-parse", "HEAD")
    rc, output, target = prepare_git_pull(str(device))
    self.assertNotEqual(rc, 0)
    self.assertFalse(target, output)
    self.assertEqual((device / ".git/config").read_bytes(), config)
    self.assertEqual(git(device, "rev-parse", "HEAD"), before)

  def test_auto_update_repairs_tracking_and_ignores_unrelated_fetch(self):
    from openpilot.sunnypilot.carrot.server.services import auto_update, git_status

    _, device, commands = self._web_dispatcher()
    expected = add_other_model(device)
    git(device, "config", "--add", "branch.carrot-wip.merge", "refs/heads/carrot-other")
    events = []

    async def run_git(args, timeout=10):  # noqa: ASYNC109 -- matches the production Git adapter
      proc = await asyncio.to_thread(subprocess.run, ["git", *args], cwd="/data/openpilot", capture_output=True, text=True, timeout=timeout)
      return proc.returncode, (proc.stdout + proc.stderr).strip()

    async def notify(head):
      pass

    def prepare(repo):
      result = prepare_git_pull(repo)
      git(device, "fetch", "origin", "carrot-wip", "carrot-other")
      return result

    self.patch(git_status, "_git", run_git)
    self.patch(auto_update, "_git", run_git)
    self.patch(auto_update, "get_git_status", git_status._read_status)
    self.patch(auto_update, "prepare_git_pull", prepare)
    self.patch(auto_update, "read_auto_update_state", dict)
    self.patch(auto_update, "write_auto_update_event", lambda status, **fields: events.append(status) or {"status": status})
    self.patch(auto_update, "_set_auto_update_alert", lambda *args: None)
    self.patch(auto_update, "write_git_pull_time", lambda: None)
    self.patch(auto_update, "_notify_cwp", notify)
    self.patch(auto_update, "_last_pull_at", float("-inf"))
    self.assertEqual(asyncio.run(auto_update._attempt_update(types.SimpleNamespace(ready=lambda: True))), (True, True, expected))
    self.assertEqual(events, ["pulling", "updated"])
    self.assertEqual(git(device, "rev-parse", "HEAD"), expected)
    self.assertFalse((device / "other-model.txt").exists())
    self.assertIn(["git", "merge", "--ff-only", expected], commands)

  def test_recovery_pull_uses_same_selected_branch_repair(self):
    from openpilot.sunnypilot.carrot.server.services import git_config
    _, _, device = checkout(self.tmp_path)
    expected = add_other_model(device)
    git(device, "config", "--add", "branch.carrot-wip.merge", "refs/heads/carrot-other")
    self.addCleanup(os.chdir, os.getcwd())
    os.chdir(device)
    self.assertEqual(git_config.main(), 0)
    self.assertEqual(git(device, "rev-parse", "HEAD"), expected)
    self.assertFalse((device / "other-model.txt").exists())

  def test_duplicate_tracking_preserves_valid_renamed_branch_and_remote(self):
    _, _, device = checkout(self.tmp_path)
    git(device, "branch", "-m", "my-local-branch")
    git(device, "remote", "rename", "origin", "my-fork")
    git(device, "config", "--add", "branch.my-local-branch.merge", "refs/heads/carrot-wip")
    rc, output, target = prepare_git_pull(str(device))
    self.assertEqual(rc, 0, output)
    self.assertEqual(target, git(device, "rev-parse", "refs/remotes/my-fork/carrot-wip"))
    self.assertEqual(git(device, "config", "--get-all", "branch.my-local-branch.merge"), "refs/heads/carrot-wip")
    self.assertEqual(git(device, "branch", "--show-current"), "my-local-branch")

  def test_duplicate_tracking_is_not_repaired_before_successful_fetch(self):
    _, _, device = checkout(self.tmp_path)
    add_other_model(device)
    git(device, "config", "--add", "branch.carrot-wip.merge", "refs/heads/carrot-other")
    before = (device / ".git/config").read_bytes()
    original = subprocess.run

    def fail_fetch(args, **kwargs):
      if args[:2] == ["git", "fetch"]:
        return subprocess.CompletedProcess(args, 1, "", "offline")
      return original(args, **kwargs)

    self.patch(subprocess, "run", fail_fetch)
    rc, output, target = prepare_git_pull(str(device))
    self.assertNotEqual(rc, 0)
    self.assertFalse(target, output)
    self.assertEqual((device / ".git/config").read_bytes(), before)

  def test_pull_refuses_divergence_without_merging_other_history(self):
    for api in ["job", "sync"]:
      with self.subTest(api=api):
        dispatcher, device, _ = self._web_dispatcher()
        git(device, "config", "user.name", "Local change")
        git(device, "config", "user.email", "test@example.invalid")
        (device / "local.txt").write_text("local commit\n")
        git(device, "add", "local.txt")
        git(device, "commit", "-qm", "local commit")
        before = git(device, "rev-parse", "HEAD")
        result = dispatch(dispatcher, api, "git_pull")
        self.assertFalse(result["ok"], result)
        self.assertEqual(git(device, "rev-parse", "HEAD"), before)


if __name__ == "__main__":
  unittest.main()
