"""Smoke tests for the Tier-A FLM wiring batch (saved_source, GmFlmBinding,
selected_effects/torque_stages surface, full_surface_profile/store round trip,
event_evaluate, controller_selection, learning_preferences, runtime_identity).

Intent-ported from StarPilot upstream tests where self-contained; the heavier
per-module suites (full_surface_profile 375-line, manual_coordinates 306-line)
still follow in a later batch.
"""

import json
import os
import unittest

from openpilot.sunnypilot.saved_source import read_saved
from openpilot.sunnypilot.flm.runtime_identity import (
  canonical_physical_context, digest, physical_model_revision)
from openpilot.sunnypilot.flm.canonical_surface_adapter import (
  MANIFEST_SHA256, full_original_anchor, full_profile_sha256, original_anchor)
from openpilot.sunnypilot.flm.full_surface_profile import (
  POLICY as FULL_SURFACE_POLICY, FullSurfaceEnvelope, envelope_dict, envelope_from_dict,
  neutral_coordinates)
from openpilot.sunnypilot.flm.event_evaluate import POLICY as EVENT_POLICY
from openpilot.sunnypilot.flm.torque_surface import GmFlmBinding, GmSurface
from openpilot.sunnypilot.lateral.controller_selection import ControllerMode, parse_document
from openpilot.sunnypilot.lateral.torque_settings import (
  FieldChoice, PlatformProfile, serialize_document, parse_document as parse_surface_document)


POSIX_ONLY = unittest.skipUnless(os.name == 'posix', 'saved_source uses POSIX O_NONBLOCK/O_NOFLOOK flags')


def make_surface():
  return GmSurface.from_document({
    'profile': 'torque_universal',
    'knobs': {},
    'baseValues': [0.6, 0.8, 0.9, 1.0, 1.1],
  })


def make_binding(**kwargs):
  base = {
    'controller': 'starpilot',
    'policy': 'ordinary_cc',
    'basis': (12.0, 0.0, 0.9),
    'saved': (('k1', 'surface one', make_surface()),),
    'active': 'k1',
    'applied': True,
  }
  base.update(kwargs)
  return GmFlmBinding(**base)


def make_envelope(names=('ff_gain_left',), prior=None):
  rows = neutral_coordinates() if prior is None else prior.coordinates
  fp = full_profile_sha256('a' * 64, rows)
  return FullSurfaceEnvelope(
    1,
    MANIFEST_SHA256,
    full_original_anchor('a' * 64),
    original_anchor('a' * 64, names),
    'e' * 64,
    'c' * 64,
    'selected-controller-v2:' + ('d' * 64),
    'e' * 64,
    '0',
    'a' * 64,
    fp,
    fp,
    rows,
    rows,
    names,
    '9' * 64,
  ).validate()


class FakeParams:
  def __init__(self, root):
    self.root = root

  def get_param_path(self, key=""):
    return os.path.join(self.root, key)


class TestSavedSource(unittest.TestCase):

  @POSIX_ONLY
  def test_absent_is_distinct_from_unreadable(self):
    params = FakeParams(self._tmpdir())
    self.assertEqual(read_saved(params, 'SomeKey', 4096), (None, True))

  @POSIX_ONLY
  def test_complete_read_and_stability(self):
    root = self._tmpdir()
    with open(os.path.join(root, 'Key'), 'wb') as f:
      f.write(b'{"ok": true}')
    params = FakeParams(root)
    raw, readable = read_saved(params, 'Key', 4096)
    self.assertEqual(raw, b'{"ok": true}')
    self.assertTrue(readable)

  @POSIX_ONLY
  def test_oversize_is_unreadable_never_prefix(self):
    root = self._tmpdir()
    with open(os.path.join(root, 'Key'), 'wb') as f:
      f.write(b'x' * 33)
    self.assertEqual(read_saved(FakeParams(root), 'Key', 32), (b'', False))

  def _tmpdir(self):
    import tempfile
    root = tempfile.mkdtemp(prefix='flm_saved_')
    os.makedirs(root, exist_ok=True)
    self.addCleanup(lambda: None)  # temp dirs are disposable
    return root


class TestGmFlmBinding(unittest.TestCase):

  def test_selected_round_trip(self):
    binding = make_binding()
    self.assertIs(binding.selected(), binding.saved[0][2])
    doc = binding.document()
    doc['applied'] = False
    doc['active'] = None
    self.assertIsNone(GmFlmBinding.from_document(doc).selected())

  def test_document_round_trip_preserves_state(self):
    binding = make_binding(trial='a' * 32, baseline_active='k1', baseline_applied=True)
    doc = binding.document()
    self.assertEqual(set(doc), {'controller', 'policy', 'basis', 'saved', 'active', 'applied', 'trial',
                                'baselineActive', 'baselineApplied', 'manual', 'baselineManual',
                                'appliedManual', 'cleanupProgress'})
    restored = GmFlmBinding.from_document(doc)
    self.assertEqual(restored.controller, binding.controller)
    self.assertEqual(restored.basis, binding.basis)
    self.assertEqual(restored.trial, binding.trial)

  def test_unsupported_owner_rejected(self):
    with self.assertRaises(ValueError):
      make_binding(policy='not_a_policy')

  def test_bad_basis_rejected(self):
    with self.assertRaises(ValueError):
      make_binding(basis=(0.0, 0.0, 0.1))       # nonpositive factor
    with self.assertRaises(ValueError):
      make_binding(basis=(1.0, 0.0, -0.1))      # negative friction

  def test_unbound_activation_rejected(self):
    with self.assertRaises(ValueError):
      make_binding(active='missing')
    with self.assertRaises(ValueError):
      make_binding(active='k1', applied=False)


class TestFullSurfaceStore(unittest.TestCase):

  def test_policy_constant_alignment(self):
    self.assertEqual(FULL_SURFACE_POLICY, EVENT_POLICY)

  def test_neutral_envelope_round_trip(self):
    envelope = make_envelope()
    doc = envelope_dict(envelope)
    restored = envelope_from_dict(json.loads(json.dumps(doc)))
    self.assertEqual(envelope_dict(restored), doc)


class TestRuntimeIdentity(unittest.TestCase):

  def test_digest_is_stable_and_bytes_aware(self):
    self.assertEqual(digest(['x', 1, b'\x00']), digest(['x', 1, b'\x00']))
    self.assertNotEqual(digest(b'\x00'), digest(['data_hex', '00']))

  def test_physical_model_revision_changes_with_model(self):
    import dataclasses

    @dataclasses.dataclass
    class FakeModel:
      gain: float = 1.0

    self.assertNotEqual(
      physical_model_revision(dataclasses.replace(FakeModel(), gain=2.0)),
      physical_model_revision(FakeModel()))

  def test_canonical_context_stable(self):
    ctx = canonical_physical_context([1.0, 'torque', (0.1, 0.2)])
    self.assertEqual(len(ctx), 64)
    self.assertEqual(ctx, canonical_physical_context([1.0, 'torque', (0.1, 0.2)]))


class TestControllerSelection(unittest.TestCase):

  def test_mode_enum_values(self):
    self.assertEqual(ControllerMode('standard').value, 'standard')

  def test_parse_document_rejects_non_dict(self):
    with self.assertRaises((ValueError, TypeError)):
      parse_document(b'not json')


class TestTorqueSettings(unittest.TestCase):

  def test_serialize_parse_round_trip(self):
    profile = PlatformProfile(
      basis=(12.0, 0.0, 0.9),
      factor=FieldChoice(),
      friction=FieldChoice(),
      flm=make_binding(),
    )
    raw = serialize_document({'CHEVROLET_VOLT': profile})
    parsed = parse_surface_document(raw)
    self.assertIn('CHEVROLET_VOLT', parsed)
    restored = parsed['CHEVROLET_VOLT']
    self.assertEqual(restored.basis, profile.basis)
    self.assertEqual(restored.flm.basis, profile.flm.basis)
    self.assertEqual(restored.flm.controller, profile.flm.controller)


if __name__ == '__main__':
  unittest.main()
