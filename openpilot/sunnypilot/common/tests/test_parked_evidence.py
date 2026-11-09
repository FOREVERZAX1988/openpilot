"""Tests for the dual-clock parked evidence (StarPilot parked_evidence.py
port): freshness math, resume-skew rejection, ignition gating, and the
collector's evidence assembly with injected clocks."""
import unittest

from openpilot.sunnypilot.common.parked_evidence import (
  DEVICE_TTL_NS,
  PANDA_TTL_NS,
  RESUME_SKEW_NS,
  ParkedEvidence,
  ParkedEvidenceCollector,
  fresh_offroad,
  fresh_parked,
)

MONO = 10_000_000_000_000  # ns
BOOT = 20_000_000_000_000
OFFSET = BOOT - MONO


def make_evidence(**overrides) -> ParkedEvidence:
  base = {
    "manager_offroad": True,
    "device_seen": True, "device_alive": True, "device_valid": True, "device_started": False,
    "device_stamp_mono_ns": MONO - 100_000_000,
    "device_recv_mono_ns": MONO - 100_000_000,
    "device_boot_minus_mono_at_recv_ns": OFFSET,
    "device_after_mono_ns": MONO - 10_000_000_000,
    "panda_seen": True, "panda_alive": True, "panda_valid": True,
    "panda_stamp_boot_ns": BOOT - 100_000_000,
    "panda_recv_mono_ns": MONO - 100_000_000,
    "panda_ignition": (False,),
  }
  base.update(overrides)
  return ParkedEvidence(**base)


class TestFreshOffroad(unittest.TestCase):
  def test_fresh_evidence_passes(self):
    self.assertTrue(fresh_offroad(make_evidence(), now_mono_ns=MONO, now_boot_ns=BOOT))

  def test_stale_device_stamp_fails(self):
    self.assertFalse(fresh_offroad(
      make_evidence(device_stamp_mono_ns=MONO - DEVICE_TTL_NS - 1),
      now_mono_ns=MONO, now_boot_ns=BOOT))

  def test_stale_panda_fails(self):
    self.assertFalse(fresh_offroad(
      make_evidence(panda_stamp_boot_ns=BOOT - PANDA_TTL_NS - 1),
      now_mono_ns=MONO, now_boot_ns=BOOT))

  def test_resume_skew_fails(self):
    """A receipt-time (boot - mono) offset that puts the device stamp in the
    future of the current boot clock - beyond the RESUME_SKEW_NS sampling
    jitter window - voids the evidence."""
    # device_boot_age = BOOT - (stamp + offset_recv); stamp = MONO - 100ms,
    # so offset_recv must exceed OFFSET + 100ms + RESUME_SKEW_NS to go negative.
    self.assertFalse(fresh_offroad(
      make_evidence(device_boot_minus_mono_at_recv_ns=OFFSET + 100_000_000 + RESUME_SKEW_NS + 1),
      now_mono_ns=MONO, now_boot_ns=BOOT))
    # within the skew window it still passes
    self.assertTrue(fresh_offroad(
      make_evidence(device_boot_minus_mono_at_recv_ns=OFFSET + 100_000_000 + RESUME_SKEW_NS // 2),
      now_mono_ns=MONO, now_boot_ns=BOOT))

  def test_missing_boot_offset_fails(self):
    self.assertFalse(fresh_offroad(
      make_evidence(device_boot_minus_mono_at_recv_ns=None),
      now_mono_ns=MONO, now_boot_ns=BOOT))

  def test_started_or_missing_inputs_fail(self):
    for override in (
      {"manager_offroad": False},
      {"device_started": True},
      {"device_seen": False},
      {"device_alive": False},
      {"device_valid": False},
      {"panda_seen": False},
      {"panda_alive": False},
      {"panda_valid": False},
      {"panda_ignition": ()},
    ):
      with self.subTest(override=override):
        self.assertFalse(fresh_offroad(make_evidence(**override),
                                       now_mono_ns=MONO, now_boot_ns=BOOT))

  def test_zero_stamps_fail(self):
    self.assertFalse(fresh_offroad(
      make_evidence(device_stamp_mono_ns=0),
      now_mono_ns=MONO, now_boot_ns=BOOT))

  def test_stamp_not_after_barrier_fails(self):
    self.assertFalse(fresh_offroad(
      make_evidence(device_stamp_mono_ns=MONO - 10_000_000_000),
      now_mono_ns=MONO, now_boot_ns=BOOT))


class TestFreshParked(unittest.TestCase):
  def test_ignition_off_parks(self):
    self.assertTrue(fresh_parked(make_evidence(), now_mono_ns=MONO, now_boot_ns=BOOT))

  def test_any_ignition_on_fails(self):
    self.assertFalse(fresh_parked(make_evidence(panda_ignition=(False, True)),
                                  now_mono_ns=MONO, now_boot_ns=BOOT))

  def test_not_offroad_fails_even_ignition_off(self):
    self.assertFalse(fresh_parked(make_evidence(manager_offroad=False),
                                  now_mono_ns=MONO, now_boot_ns=BOOT))


class TestCollector(unittest.TestCase):
  class FakeSM:
    def __init__(self):
      self.updated = {"deviceState": True, "pandaStates": True}
      self.valid = {"deviceState": True, "pandaStates": True}
      self.logMonoTime = {"deviceState": MONO - 100_000_000}
      self.deviceState = type("DS", (), {"started": False})()
      self.pandaStates = type("PS", (), {"pandaStates": [
        type("P", (), {"pandaType": 6, "ignitionLine": False})()]})()

    def __getitem__(self, key):
      if key == "deviceState":
        return self.deviceState
      if key == "pandaStates":
        return self.pandaStates
      raise KeyError(key)

  def test_assembles_passing_evidence(self):
    sm = self.FakeSM()
    clocks = {"mono": MONO - 100_000_000, "boot": BOOT - 100_000_000}
    collector = ParkedEvidenceCollector(sm,
                                        mono_fn=lambda: clocks["mono"],
                                        boot_fn=lambda: clocks["boot"])
    collector.arm()
    # advance past the barrier; a deviceState frame published after it arrives
    clocks["mono"] += 10_000_000
    clocks["boot"] += 10_000_000
    sm.logMonoTime["deviceState"] = clocks["mono"] - 1_000_000
    evidence = collector.sample()
    self.assertIsNotNone(evidence)
    self.assertTrue(fresh_offroad(evidence, now_mono_ns=clocks["mono"], now_boot_ns=clocks["boot"]))
    self.assertTrue(fresh_parked(evidence, now_mono_ns=clocks["mono"], now_boot_ns=clocks["boot"]))

  def test_not_armed_returns_none(self):
    collector = ParkedEvidenceCollector(self.FakeSM(), mono_fn=lambda: MONO, boot_fn=lambda: BOOT)
    self.assertIsNone(collector.sample())

  def test_no_boot_clock_yields_none(self):
    """Non-POSIX hosts have no CLOCK_BOOTTIME; the safe direction is no evidence."""
    collector = ParkedEvidenceCollector(self.FakeSM(), mono_fn=lambda: MONO, boot_fn=lambda: None)
    collector.arm()
    self.assertIsNone(collector.sample())

  def test_stale_panda_receipt_breaks_evidence(self):
    sm = self.FakeSM()
    clocks = {"mono": MONO - 100_000_000, "boot": BOOT - 100_000_000}
    collector = ParkedEvidenceCollector(sm,
                                        mono_fn=lambda: clocks["mono"],
                                        boot_fn=lambda: clocks["boot"])
    collector.arm()
    clocks["mono"] += 10_000_000
    clocks["boot"] += 10_000_000
    collector.sample()
    # panda stops publishing; a later tick ages its receipt past the TTL
    clocks["mono"] += PANDA_TTL_NS + 1
    clocks["boot"] += PANDA_TTL_NS + 1
    sm.updated = {"deviceState": False, "pandaStates": False}
    evidence = collector.sample()
    self.assertFalse(fresh_parked(evidence, now_mono_ns=clocks["mono"], now_boot_ns=clocks["boot"]))


if __name__ == "__main__":
  unittest.main()
