"""Identity digest helpers extracted from StarPilot's runtime_adapter_registry.

The full 1,064-line multi-adapter orchestration registry is deliberately not
ported; these pure identity helpers are the only pieces the already-ported
flm modules need (manual_coordinates context binding, profile revisions).
Verbatim except for the module boundary.
"""

import hashlib
import json
import struct
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class SourceState:
  """Shared source-state contract (verbatim from runtime_adapter_registry)."""
  enabled: bool
  manual: bool
  reset: str
  source_epoch: str
  observed_ns: int
  expires_ns: int
  cp_sha256: str
  calibration: tuple[float, ...] = ()
  calibration_generation: str = ''
  persistent_source_epoch: str = ''
  # Optional-process-only selected configuration; never added to controls IPC.
  manual_baseline: tuple[float, ...] = field(default=(), compare=False, repr=False)


def digest(value):
  # Called at startup or by the separate learner, never JSON in Controls.tick.
  return hashlib.sha256(
    json.dumps(
      value,
      sort_keys=True,
      separators=(',', ':'),
      allow_nan=False,
      default=lambda item: {'data_hex': item.hex()} if isinstance(item, bytes) else (_ for _ in ()).throw(TypeError('unsupported identity value')),
    ).encode()
  ).hexdigest()


def car_params_digest(cp):
  """Bind all CP values, including legitimate infinity sentinels, without JSON NaN tokens."""
  def typed(value):
    kind = type(value)
    if kind is dict:
      if not all(type(key) is str for key in value):
        raise TypeError('non-string CarParams field')
      return ['dict', [[key, typed(value[key])] for key in sorted(value)]]
    if kind in (list, tuple):
      return [kind.__name__, [typed(item) for item in value]]
    if kind is float:
      return ['float64', struct.pack('>d', value).hex()]
    if kind is bytes:
      return ['bytes', value.hex()]
    if value is None or kind in (bool, int, str):
      return [kind.__name__, value]
    raise TypeError('unsupported CarParams identity value')

  return digest(typed(cp.to_dict()))


def canonical_physical_context(value):
  return digest(value)


def physical_model_revision(model):
  return digest(asdict(model))
