"""Guards for the opt-in neural signal observer (upstream 30d93e8093).

The interesting failure mode is not the inference chain -- that needs two
pinned ONNX files which are deliberately absent -- but the *selection* code
around it: ``automatic_backend`` reads four Params keys, and one of them
(``DriverMonitoringSessionDisabled``) does not exist in this fork's
``params_keys.h``. ``Params.get_bool`` raises ``UnknownKeyName`` for such a
key, so the upstream spelling would kill the auto worker on its first loop.
The tests below pin the fault-tolerant read, the display mapping that keeps
mixed red/arrow labels red, and the "nothing runs unless a flag asks" rule.
"""
import re
from pathlib import Path

import pytest

from openpilot.selfdrive.modeld import signal_neural_shadow as shadow
from openpilot.sunnypilot.carrot.tests.audit_param_consistency import parse_params_keys

MODULE = Path(shadow.__file__)
BACKEND_KEYS = {'DriverMonitoringEnabled', 'DriverMonitoringSessionDisabled',
                'IsDriverViewEnabled', 'UsbGpuActive'}


class UnknownKeyName(Exception):
  """Same class *name* as Params' real error: param_read matches on that."""


class FakeParams:
  """A Params stand-in that fails exactly like the device for unknown keys."""

  def __init__(self, values):
    self.values = dict(values)

  def _read(self, key):
    if key not in self.values:
      raise UnknownKeyName(key)
    return self.values[key]

  def get_bool(self, key):
    return bool(self._read(key))

  def get_int(self, key):
    return int(self._read(key))


def test_selection_is_off_by_default_and_rejects_a_bad_backend(tmp_path):
  assert not shadow.neural_requested(tmp_path)
  assert shadow.backend_requested(tmp_path) == 'cpu'
  (tmp_path / 'neural_enabled').write_text('1\n')
  assert shadow.neural_requested(tmp_path)
  (tmp_path / 'neural_backend').write_text('auto')
  assert shadow.backend_requested(tmp_path) == 'auto'
  (tmp_path / 'neural_backend').write_text('gpu')
  with pytest.raises(ValueError, match='invalid neural backend'):
    shadow.backend_requested(tmp_path)


def test_automatic_backend_survives_keys_this_fork_never_registered():
  # DM enabled: the GPU belongs to the DM model, so neural work stays on CPU.
  assert shadow.automatic_backend(FakeParams({'DriverMonitoringEnabled': 1})) == 'tracking_cpu'
  # DM off and the USB GPU present: QCOM is allowed.
  assert shadow.automatic_backend(FakeParams({'DriverMonitoringEnabled': 0, 'UsbGpuActive': 1})) == 'qcom'
  # A driver-facing camera needs the GPU too, even with DM off.
  assert shadow.automatic_backend(
    FakeParams({'DriverMonitoringEnabled': 0, 'UsbGpuActive': 1, 'IsDriverViewEnabled': 1})) == 'tracking_cpu'
  # Preparation mode (2) demands the measured-housing CPU evidence contract.
  assert shadow.automatic_backend(FakeParams({'SignalAssistMode': 2, 'UsbGpuActive': 1})) == 'tracking_cpu'
  # No keys at all: the whole selection still answers instead of raising.
  assert shadow.automatic_backend(FakeParams({})) == 'tracking_cpu'


def test_no_backend_key_is_read_raw_and_only_one_may_be_unregistered():
  """Every key goes through param_read; an unregistered key must be intentional.

  A raw ``params.get_bool('...')`` on a missing key is a crash, not a default,
  so the module is not allowed to contain one.
  """
  source = MODULE.read_text()
  assert not re.findall(r"params\.get_(?:bool|int|float|str)\(", source)
  used = set(re.findall(r"read_bool\(params, '([^']+)'", source))
  assert used == BACKEND_KEYS, used
  registered = set(parse_params_keys())
  assert registered, 'params_keys.h did not parse'
  assert used - registered == {'DriverMonitoringSessionDisabled'}, (
    f'only the DM-session key may be unregistered here; {sorted(used - registered)}')


def test_display_tracks_keeps_red_in_mixed_labels_and_yellow_stays_unknown():
  tracks = [{'id': 1, 'box': [0, 0, 1, 1], 'label': 'red,right', 'score': .9, 'source': 'detected', 'neural_age': .1},
            {'id': 2, 'box': [0, 0, 1, 1], 'label': 'green', 'score': .9, 'source': 'tracked', 'neural_age': .2},
            {'id': 3, 'box': [0, 0, 1, 1], 'label': 'yellow', 'score': .9, 'source': 'detected', 'neural_age': .1},
            {'id': 4, 'box': [0, 0, 1, 1], 'label': 'red', 'score': .4, 'source': 'detected', 'neural_age': .1}]
  out = shadow.display_tracks(tracks)
  assert [o['evidence']['raw'] for o in out] == ['red', 'green', 'unknown', 'unknown']
  assert [o['state'] for o in out] == ['unknown'] * 4
  assert [o['label'] for o in out] == ['red,right', 'green', 'yellow', 'red']
  assert all('control_permission' not in o for o in out)


def test_qcom_selection_refuses_without_locally_validated_caches(tmp_path):
  with pytest.raises(RuntimeError, match='QCOM caches'):
    shadow.run_selected(tmp_path, 'qcom')


def test_nothing_runs_unless_a_flag_asks_for_it(tmp_path):
  assert shadow.run(tmp_path) is None
  assert shadow.run_selected(tmp_path, 'tracking_cpu') is None
