#!/usr/bin/env python3
"""Fresh offroad/parked evidence with dual-clock cross-validation.

StarPilot parked_evidence.py port. Pure decision logic first, a collector
second: anything that must only act while the car is genuinely parked
(Safe Mode restore, dangerous remote writes) asks this module, instead of
trusting a single flag that can survive a suspend/resume.

Python deviceState stamps MONOTONIC (via the message's logMonoTime); the
device's CLOCK_BOOTTIME runs through suspends while CLOCK_MONOTONIC does
not, so a resume in between stamps and now shows up as a skew between the
two clocks - that is what the resume barrier and RESUME_SKEW_NS catch.
"""
import time
from dataclasses import dataclass, field

DEVICE_TTL_NS = 1_500_000_000  # deviceState publisher, allowing one missed frame
PANDA_TTL_NS = 300_000_000     # pandaStates publisher, allowing one missed frame
RESUME_SKEW_NS = 5_000_000


@dataclass(frozen=True)
class ParkedEvidence:
  manager_offroad: bool
  device_seen: bool
  device_alive: bool
  device_valid: bool
  device_started: bool
  device_stamp_mono_ns: int
  device_recv_mono_ns: int
  device_boot_minus_mono_at_recv_ns: int | None
  device_after_mono_ns: int  # collector must set a startup/resume barrier before receiving evidence
  panda_seen: bool
  panda_alive: bool
  panda_valid: bool
  panda_stamp_boot_ns: int
  panda_recv_mono_ns: int
  panda_ignition: tuple[bool, ...] = field(default=())


def fresh_offroad(evidence: ParkedEvidence, *, now_mono_ns: int, now_boot_ns: int) -> bool:
  """Confirm effective offroad mode, including Force Offroad with ignition on."""
  e = evidence
  if (not e.manager_offroad or not all((e.device_seen, e.device_alive, e.device_valid,
                                        e.panda_seen, e.panda_alive, e.panda_valid)) or
      e.device_started or e.device_boot_minus_mono_at_recv_ns is None or
      not e.panda_ignition or
      min(e.device_stamp_mono_ns, e.panda_stamp_boot_ns, e.device_recv_mono_ns, e.panda_recv_mono_ns) <= 0 or
      e.device_stamp_mono_ns <= e.device_after_mono_ns):
    return False
  device_mono_age = now_mono_ns - e.device_stamp_mono_ns
  device_boot_age = now_boot_ns - (e.device_stamp_mono_ns + e.device_boot_minus_mono_at_recv_ns)
  panda_boot_age = now_boot_ns - e.panda_stamp_boot_ns
  device_receipt_age = now_mono_ns - e.device_recv_mono_ns
  panda_receipt_age = now_mono_ns - e.panda_recv_mono_ns
  return (0 <= device_mono_age <= DEVICE_TTL_NS and
          -RESUME_SKEW_NS <= device_boot_age <= DEVICE_TTL_NS and
          0 <= panda_boot_age <= PANDA_TTL_NS and
          0 <= device_receipt_age <= DEVICE_TTL_NS and
          0 <= panda_receipt_age <= PANDA_TTL_NS)


def fresh_parked(evidence: ParkedEvidence, *, now_mono_ns: int, now_boot_ns: int) -> bool:
  """Confirm fresh offroad mode with ignition off for operations that require it."""
  return not any(evidence.panda_ignition) and fresh_offroad(evidence, now_mono_ns=now_mono_ns, now_boot_ns=now_boot_ns)


class ParkedEvidenceCollector:
  """Collects ParkedEvidence from deviceState + pandaStates SubMasters.

  Our publishers do not stamp CLOCK_BOOTTIME (that would be a cereal
  schema change), so the collector derives the boot-domain stamps itself:
  for each received frame it samples (boot - mono) at receipt and treats
  the receipt time as the frame's boot stamp, while the deviceState mono
  stamp still comes from the publisher-side logMonoTime. Resume skew
  therefore surfaces as the boot-domain device age disagreeing with its
  mono-domain age - the RESUME_SKEW_NS check catches it.

  clock helpers are injectable for hosts and tests. On hosts without
  CLOCK_BOOTTIME the collector yields evidence that always fails
  fresh_offroad (boot stamps unknown), which is the safe direction.

  Usage: arm() at startup (and again after any resume), then sample()
  every loop tick after sm.update(0).
  """

  def __init__(self, sm, mono_fn=time.monotonic_ns, boot_fn=None):
    self.sm = sm
    self._mono_fn = mono_fn
    self._boot_fn = boot_fn if boot_fn is not None else self._default_boot_fn
    self._after_mono_ns = 0

  @staticmethod
  def _default_boot_fn():
    try:
      return time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    except (AttributeError, OSError):
      return None  # non-POSIX host: boot stamps unknown, evidence stays invalid

  def arm(self) -> None:
    """(Re)arm the startup/resume barrier; call again after any resume."""
    self._after_mono_ns = self._mono_fn()

  def sample(self) -> ParkedEvidence | None:
    """Collect one evidence snapshot from the latest messages, or None before armed."""
    if self._after_mono_ns == 0:
      return None
    now_mono_ns = self._mono_fn()
    now_boot_ns = self._boot_fn()
    if now_boot_ns is None:
      return None
    boot_minus_mono = now_boot_ns - now_mono_ns

    # deviceState: publisher-side mono stamp via logMonoTime, receipt age tracked here
    device_seen = bool(self.sm.updated['deviceState'])
    if device_seen:
      self._device_recv_mono_ns = now_mono_ns
      self._device_stamp_mono_ns = int(self.sm.logMonoTime['deviceState'])
      self._device_started = bool(self.sm['deviceState'].started)
      self._device_valid = bool(self.sm.valid['deviceState'])
    device_recv_mono_ns = getattr(self, '_device_recv_mono_ns', 0)
    device_stamp_mono_ns = getattr(self, '_device_stamp_mono_ns', 0)

    # pandaStates: receipt boot stamp (see docstring); ignition per panda
    panda_seen = bool(self.sm.updated['pandaStates'])
    if panda_seen:
      self._panda_recv_mono_ns = now_mono_ns
      self._panda_stamp_boot_ns = now_boot_ns
      states = list(self.sm['pandaStates'].pandaStates)
      # log.PandaState.PandaType.unknown is 0; a literal keeps this module import-light
      self._panda_valid = bool(self.sm.valid['pandaStates']) and any(ps.pandaType != 0 for ps in states)
      self._panda_ignition = tuple(bool(ps.ignitionLine) for ps in states)
    panda_recv_mono_ns = getattr(self, '_panda_recv_mono_ns', 0)
    panda_stamp_boot_ns = getattr(self, '_panda_stamp_boot_ns', 0)

    # "alive" = received within its own TTL (the receipt-age check in
    # fresh_offroad enforces this; mirror it here so the flag is honest).
    # age == 0 counts: the frame arrived in this very tick. A never-received
    # topic has recv == 0, whose age dwarfs any TTL and stays not-alive.
    device_alive = 0 <= now_mono_ns - device_recv_mono_ns <= DEVICE_TTL_NS
    panda_alive = 0 <= now_mono_ns - panda_recv_mono_ns <= PANDA_TTL_NS

    return ParkedEvidence(
      manager_offroad=not bool(getattr(self, '_device_started', True)),
      device_seen=device_seen,
      device_alive=device_alive,
      device_valid=bool(getattr(self, '_device_valid', False)),
      device_started=bool(getattr(self, '_device_started', True)),
      device_stamp_mono_ns=device_stamp_mono_ns,
      device_recv_mono_ns=device_recv_mono_ns,
      device_boot_minus_mono_at_recv_ns=boot_minus_mono,
      device_after_mono_ns=self._after_mono_ns,
      panda_seen=panda_seen,
      panda_alive=panda_alive,
      panda_valid=bool(getattr(self, '_panda_valid', False)),
      panda_stamp_boot_ns=panda_stamp_boot_ns,
      panda_recv_mono_ns=panda_recv_mono_ns,
      panda_ignition=tuple(getattr(self, '_panda_ignition', ())),
    )
