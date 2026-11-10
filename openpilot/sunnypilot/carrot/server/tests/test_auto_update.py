import asyncio
from contextlib import nullcontext
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from openpilot.sunnypilot.carrot.server.services import auto_update, git_state
from openpilot.sunnypilot.carrot.server.services.auto_update import (
  AUTO_REBOOT_DISENGAGED,
  AUTO_REBOOT_OFF,
  AUTO_REBOOT_PARK,
  AutoRebootCondition,
)


class TestAutoUpdate(unittest.TestCase):

  def setUp(self):
    self._patchers = []

  def patch(self, target, name, value):
    patcher = mock.patch.object(target, name, value)
    patcher.start()
    self.addCleanup(patcher.stop)

  def test_manager_must_be_live_after_any_length_build_and_restart(self):
    ready = auto_update.ManagerReady(delay=10)
    for now in range(600):
      self.assertFalse(ready.update(now, False))
    for now in range(600, 610):
      self.assertFalse(ready.update(now, True))
    self.assertTrue(ready.update(610, True))
    self.assertFalse(ready.update(611, False))
    self.assertFalse(ready.update(612, True))
    # A gap in observations cannot count as continuous healthy operation either.
    self.assertFalse(ready.update(630, True))

  def test_manager_monitor_retries_when_messaging_is_not_built_yet(self):
    built = False
    clock = 0.0

    def submaster(services):
      if not built:
        raise ImportError("native messaging not built")
      return types.SimpleNamespace(valid={"managerState": True}, alive={"managerState": True}, update=lambda _: None)

    cereal = types.ModuleType("openpilot.cereal")
    cereal.messaging = types.SimpleNamespace(SubMaster=submaster)
    with mock.patch.dict(sys.modules, {"openpilot.cereal": cereal}):
      self.patch(auto_update.time, "monotonic", lambda: clock)
      monitor = auto_update.ManagerMonitor()
      self.assertFalse(monitor.ready())
      built = True
      for tick in range(11):
        clock = float(tick)
        ready = monitor.ready()
      self.assertTrue(ready)

  def test_update_waits_for_manager_and_checkout_lock(self):
    for phase in ["building", "restarting", "busy", "ready"]:
      with self.subTest(phase=phase):
        from openpilot.common.repo_update import RepoBusyError
        readiness = iter([False] if phase == "building" else [True, False] if phase == "restarting" else [True] * 5)
        monitor = type("Monitor", (), {"ready": lambda self, readiness=readiness: next(readiness)})()
        calls = []

        async def status(calls=calls):
          calls.append("status")
          return {"available": True, "state": "ok", "behind": 1, "target_head": "new", "head": "old", "branch": "carrot-wip"}

        def lock(phase=phase):
          if phase == "busy":
            raise RepoBusyError("another operation")
          return nullcontext()

        async def prepare(repo, calls=calls):
          calls.append("prepare")

        async def git(args, timeout):
          return 0, "carrot-wip" if args[0] == "branch" else "old"

        async def pull(target, calls=calls):
          calls.append("pull")
          return True, True, target

        self.patch(auto_update, "get_git_status", status)
        self.patch(auto_update, "repo_lock", lock)
        self.patch(auto_update, "prepare_repo", prepare)
        self.patch(auto_update, "prepare_git_pull", lambda repo: (0, "verified", "new"))
        self.patch(auto_update, "_git", git)
        self.patch(auto_update, "_run_git_pull", pull)
        self.patch(auto_update, "_last_pull_at", float("-inf"))
        self.patch(auto_update, "read_auto_update_state", dict)
        self.patch(auto_update, "write_auto_update_event", lambda *args, **kwargs: {})
        result = asyncio.run(auto_update._attempt_update(monitor))
        self.assertEqual("pull" in calls, phase == "ready")
        self.assertEqual(result[1], phase == "ready")
        if phase == "building":
          self.assertFalse(calls)

  def test_manual_pull_clears_verified_lock_error_and_preserves_receipt(self):
    tmp = tempfile.mkdtemp(prefix="auto_update_test_")
    self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    tmp_path = Path(tmp)
    self.patch(git_state, "CARROT_STATE_DIR", str(tmp_path))
    self.patch(git_state, "CARROT_GIT_STATE_PATH", str(tmp_path / "git.json"))
    alerts = []
    self.patch(auto_update, "_set_auto_update_alert", lambda show: alerts.append(show))
    self.patch(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0))
    git_state.write_auto_update_event("error", error_code="reset_failed", error="index.lock: File exists", reboot_requested_head="receipt")
    auto_update.clear_recovered_git_ref_error()
    self.assertEqual(git_state.read_auto_update_state()["status"], "idle")
    self.assertEqual(git_state.read_auto_update_state()["reboot_requested_head"], "receipt")
    self.assertEqual(alerts, [False])

  def test_manual_pull_keeps_lock_alert_when_checkout_verification_fails(self):
    self.patch(auto_update, "read_auto_update_state", lambda: {
      "status": "error", "error_code": "reset_failed", "error": "index.lock: File exists",
    })
    self.patch(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 1))
    self.patch(auto_update, "write_auto_update_event", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must preserve alert")))
    auto_update.clear_recovered_git_ref_error()

  def test_park_reboot_requires_valid_disengaged_park_state(self):
    condition = AutoRebootCondition(AUTO_REBOOT_PARK)

    self.assertFalse(condition.update(now=0.0, selfdrive_valid=False, engaged=False, car_state_valid=True, gear_shifter="park"))
    self.assertFalse(condition.update(now=0.1, selfdrive_valid=True, engaged=True, car_state_valid=True, gear_shifter="park"))
    self.assertFalse(condition.update(now=0.2, selfdrive_valid=True, engaged=False, car_state_valid=True, gear_shifter="drive"))
    self.assertTrue(condition.update(now=0.3, selfdrive_valid=True, engaged=False, car_state_valid=True, gear_shifter="park"))

  def test_disengaged_reboot_requires_one_continuous_second(self):
    condition = AutoRebootCondition(AUTO_REBOOT_DISENGAGED)

    self.assertFalse(condition.update(now=10.0, selfdrive_valid=True, engaged=False))
    self.assertFalse(condition.update(now=10.9, selfdrive_valid=True, engaged=False))
    self.assertTrue(condition.update(now=11.0, selfdrive_valid=True, engaged=False))

  def test_disengaged_timer_resets_when_state_is_engaged_or_invalid(self):
    condition = AutoRebootCondition(AUTO_REBOOT_DISENGAGED)

    self.assertFalse(condition.update(now=1.0, selfdrive_valid=True, engaged=False))
    self.assertFalse(condition.update(now=1.8, selfdrive_valid=True, engaged=True))
    self.assertFalse(condition.update(now=2.0, selfdrive_valid=True, engaged=False))
    self.assertFalse(condition.update(now=2.8, selfdrive_valid=False, engaged=False))
    self.assertFalse(condition.update(now=3.0, selfdrive_valid=True, engaged=False))
    self.assertTrue(condition.update(now=4.0, selfdrive_valid=True, engaged=False))

  def test_offroad_reboot_requires_one_continuous_second_without_selfdrive_state(self):
    condition = AutoRebootCondition(AUTO_REBOOT_DISENGAGED)

    self.assertFalse(condition.update(
      now=20.0,
      selfdrive_valid=False,
      engaged=False,
      device_state_valid=True,
      device_started=False,
    ))
    self.assertFalse(condition.update(
      now=20.9,
      selfdrive_valid=False,
      engaged=False,
      device_state_valid=True,
      device_started=False,
    ))
    self.assertTrue(condition.update(
      now=21.0,
      selfdrive_valid=False,
      engaged=False,
      device_state_valid=True,
      device_started=False,
    ))

  def test_onroad_without_valid_selfdrive_state_does_not_reboot(self):
    condition = AutoRebootCondition(AUTO_REBOOT_DISENGAGED)

    self.assertFalse(condition.update(
      now=30.0,
      selfdrive_valid=False,
      engaged=False,
      device_state_valid=True,
      device_started=True,
    ))
    self.assertFalse(condition.update(
      now=32.0,
      selfdrive_valid=False,
      engaged=False,
      device_state_valid=True,
      device_started=True,
    ))

  def test_off_mode_never_requests_reboot(self):
    condition = AutoRebootCondition(AUTO_REBOOT_OFF)

    self.assertFalse(condition.update(now=100.0, selfdrive_valid=True, engaged=False, car_state_valid=True, gear_shifter="park"))

  def test_failed_fetch_never_uses_stale_behind_count(self):
    self.assertEqual(auto_update._verified_update_target({
      "available": False,
      "state": "fetch_error",
      "behind": 3,
      "target_head": "stale-head",
    }), (0, ""))
    self.assertEqual(auto_update._verified_update_target({
      "available": True,
      "state": "ok",
      "behind": 3,
      "target_head": "verified-head",
    }), (3, "verified-head"))

  def test_git_pull_reports_success_without_arming_reboot_when_nothing_changed(self):
    responses = iter([
      (0, "old-head"),
      (0, "HEAD is now at old-head"),
      (0, "Already up to date."),
      (0, "old-head"),
      (0, "old-head"),
    ])
    errors = []

    async def fake_git(args, timeout):
      del args, timeout
      return next(responses)

    self.patch(auto_update, "_git", fake_git)
    self.patch(auto_update, "read_auto_update_state", dict)
    self.patch(auto_update, "write_auto_update_event", lambda status, **fields: {"status": status, **fields})
    self.patch(auto_update, "_record_error", lambda code, detail, **fields: errors.append((code, detail, fields)))

    self.assertEqual(asyncio.run(auto_update._run_git_pull("old-head")), (True, False, "old-head"))
    self.assertEqual(errors[0][0], "head_unchanged")

  def test_git_pull_reports_actual_update_and_records_pull_time(self):
    responses = iter([
      (0, "old-head"),
      (0, "HEAD is now at old-head"),
      (0, "Updating old-head..new-head\nFast-forward\n 2 files changed"),
      (0, "new-head"),
      (0, "new-head"),
    ])
    recorded = []
    commands = []

    async def fake_git(args, timeout):
      commands.append(args)
      return next(responses)

    self.patch(auto_update, "_git", fake_git)
    self.patch(auto_update, "read_auto_update_state", dict)
    self.patch(auto_update, "write_auto_update_event", lambda status, **fields: {"status": status, **fields})
    self.patch(auto_update, "_set_auto_update_alert", lambda show, detail="": recorded.append(("alert", show)))
    self.patch(auto_update, "write_git_pull_time", lambda: recorded.append(("time", None)))

    self.assertEqual(asyncio.run(auto_update._run_git_pull("new-head")), (True, True, "new-head"))
    # The dead CWP phone-home was removed with upstream 4f4256c37b, so a pull no
    # longer records a notify step.
    self.assertEqual(recorded, [("alert", False), ("time", None)])
    self.assertIn(["merge", "--ff-only", "new-head"], commands)
    self.assertFalse(any(args[0] == "pull" for args in commands))

  def test_git_pull_failure_is_persisted_and_never_reports_update(self):
    responses = iter([
      (0, "old-head"),
      (0, "HEAD is now at old-head"),
      (1, "fatal: unable to access remote"),
    ])
    errors = []

    async def fake_git(args, timeout):
      del args, timeout
      return next(responses)

    self.patch(auto_update, "_git", fake_git)
    self.patch(auto_update, "read_auto_update_state", dict)
    self.patch(auto_update, "write_auto_update_event", lambda status, **fields: {"status": status, **fields})
    self.patch(auto_update, "_record_error", lambda code, detail, **fields: errors.append((code, detail, fields)))

    self.assertEqual(asyncio.run(auto_update._run_git_pull("new-head")), (False, False, ""))
    self.assertEqual(errors[0][0:2], ("pull_failed", "fatal: unable to access remote"))
    self.assertEqual(errors[0][2]["old_head"], "old-head")
    self.assertEqual(errors[0][2]["target_head"], "new-head")
    self.assertEqual(errors[0][2]["reset_rc"], 0)
    self.assertEqual(errors[0][2]["pull_rc"], 1)

  def test_git_pull_does_not_modify_repo_when_attempt_cannot_be_persisted(self):
    calls = []
    errors = []

    async def fake_git(args, timeout):
      del timeout
      calls.append(args)
      return 0, "old-head"

    self.patch(auto_update, "_git", fake_git)
    self.patch(auto_update, "read_auto_update_state", dict)
    self.patch(auto_update, "write_auto_update_event", lambda status, **fields: {})
    self.patch(auto_update, "_record_error", lambda code, detail, **fields: errors.append((code, detail, fields)))

    self.assertEqual(asyncio.run(auto_update._run_git_pull("new-head")), (False, False, ""))
    self.assertEqual(calls, [["rev-parse", "HEAD"]])
    self.assertEqual(errors[0][0], "state_write_failed")

  def test_same_target_that_already_requested_reboot_is_blocked_before_git_pull(self):
    errors = []

    async def fail_git(args, timeout):
      raise AssertionError(f"git should not run: {args} {timeout}")

    self.patch(auto_update, "_git", fail_git)
    self.patch(auto_update, "read_auto_update_state", lambda: {
      "status": "reboot_requested",
      "reboot_requested_head": "same-head",
    })
    self.patch(auto_update, "_record_error", lambda code, detail, **fields: errors.append((code, detail, fields)))

    self.assertEqual(asyncio.run(auto_update._run_git_pull("same-head")), (False, False, ""))
    self.assertEqual(errors[0][0], "duplicate_reboot_blocked")
    self.assertIs(errors[0][2]["blocked"], True)

  def test_git_pull_requires_new_head_to_match_upstream(self):
    responses = iter([
      (0, "old-head"),
      (0, "HEAD is now at old-head"),
      (0, "Updating old-head..unexpected-head\nFast-forward"),
      (0, "unexpected-head"),
      (0, "expected-head"),
    ])
    errors = []

    async def fake_git(args, timeout):
      del args, timeout
      return next(responses)

    self.patch(auto_update, "_git", fake_git)
    self.patch(auto_update, "read_auto_update_state", dict)
    self.patch(auto_update, "write_auto_update_event", lambda status, **fields: {"status": status, **fields})
    self.patch(auto_update, "_record_error", lambda code, detail, **fields: errors.append((code, detail, fields)))

    self.assertEqual(asyncio.run(auto_update._run_git_pull("expected-head")), (True, False, "unexpected-head"))
    self.assertEqual(errors[0][0], "head_mismatch")

  def test_auto_update_state_survives_as_bounded_history(self):
    tmp = tempfile.mkdtemp(prefix="auto_update_test_")
    self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
    tmp_path = Path(tmp)
    state_path = tmp_path / "git.json"
    self.patch(git_state, "CARROT_STATE_DIR", str(tmp_path))
    self.patch(git_state, "CARROT_GIT_STATE_PATH", str(state_path))

    requested = git_state.write_auto_update_event(
      "reboot_requested",
      target_head="target-head",
      reboot_requested_head="target-head",
    )
    self.assertEqual(requested["reboot_requested_head"], "target-head")

    for index in range(git_state.AUTO_UPDATE_HISTORY_LIMIT + 3):
      self.assertTrue(git_state.write_auto_update_event("error", error_code=f"error-{index}"))

    data = git_state.read_git_state()
    self.assertEqual(data["auto_update"]["reboot_requested_head"], "target-head")
    self.assertEqual(data["auto_update"]["error_code"], f"error-{git_state.AUTO_UPDATE_HISTORY_LIMIT + 2}")
    self.assertEqual(len(data["auto_update_history"]), git_state.AUTO_UPDATE_HISTORY_LIMIT)

  def test_manual_pull_recovery_clears_ref_error_but_preserves_reboot_receipt(self):
    for error in [
      "fatal: couldn't find remote ref refs/heads/release-tizi-staging",
      "fatal: Cannot fast-forward to multiple branches.",
    ]:
      with self.subTest(error=error):
        tmp = tempfile.mkdtemp(prefix="auto_update_test_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        tmp_path = Path(tmp)
        self.patch(git_state, "CARROT_STATE_DIR", str(tmp_path))
        self.patch(git_state, "CARROT_GIT_STATE_PATH", str(tmp_path / "git.json"))
        alerts = []
        self.patch(auto_update, "_set_auto_update_alert", lambda show, alerts=alerts: alerts.append(show))
        git_state.write_auto_update_event(
          "error", error_code="pull_failed", error=error,
          reboot_requested_head="already-requested",
        )

        auto_update.clear_recovered_git_ref_error()

        state = git_state.read_auto_update_state()
        self.assertEqual(state["status"], "idle")
        self.assertEqual(state["error"], "")
        self.assertEqual(state["reboot_requested_head"], "already-requested")
        self.assertEqual(alerts, [False])
        self.assertEqual(git_state.read_git_state()["auto_update_history"][0]["error_code"], "pull_failed")

  def test_manual_pull_does_not_clear_unrelated_or_reboot_errors(self):
    def unexpected(*args, **kwargs):
      raise AssertionError("unrelated failure must remain visible")

    self.patch(auto_update, "write_auto_update_event", unexpected)
    self.patch(auto_update, "_set_auto_update_alert", unexpected)
    for state in [
      {"status": "error", "error_code": "head_mismatch", "error": "incorrect HEAD"},
      {"status": "reboot_blocked", "error_code": "duplicate_reboot_blocked"},
      {"status": "error", "error_code": "pull_failed", "error": "connection failed"},
    ]:
      self.patch(auto_update, "read_auto_update_state", lambda state=state: state)
      auto_update.clear_recovered_git_ref_error()


if __name__ == "__main__":
  unittest.main()
