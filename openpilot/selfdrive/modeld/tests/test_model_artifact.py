"""The model artifacts modeld loads, and the tinygrad API it builds tensor views with.

Both of these broke the whole driving stack while looking like nothing: modeld died in
ModelState.__init__, so no modelV2 was published and the car showed no path, no lane lines
and no road edges. Neither failure is a crash of the model itself, so nothing in the driving
tests noticed -- these pin the two startup steps directly.

1. load_oob only knew the layout that openpilot's own dump_oob writes. What SConscript
   actually builds is tinygrad's examples/openpilot dump_pickle, which addresses out-of-band
   weights with BINPERSID instead of PEP 574 buffers.
2. Buffer.view in the pinned tinygrad is (nbytes, offset); modeld passed a dtype as the
   second argument.
"""
import io
import pickle
import struct
import tempfile

import numpy as np

from openpilot.common.test import OpenpilotTestCase
from openpilot.selfdrive.modeld.helpers import dump_oob, load_oob


class TestModelArtifact(OpenpilotTestCase):
  def test_openpilot_layout_round_trip(self):
    payload = {'metadata': {'a': 1}, 'weights': b'\x01\x02\x03' * 100}
    with tempfile.TemporaryFile(dir='/tmp') as f:
      dump_oob(payload, f)
      f.seek(0)
      self.assertEqual(load_oob(f), payload)

  def test_tinygrad_layout_persistent_id(self):
    from tinygrad import Device, Tensor
    from tinygrad.device import Buffer

    values = np.arange(16, dtype=np.float32)
    buf = Tensor(values).to(Device.DEFAULT).realize().uop.buffer

    class PersistentPickler(pickle.Pickler):
      def persistent_id(self, obj):
        return (obj.nbytes, 0) if isinstance(obj, Buffer) else None

    opcodes = io.BytesIO()
    PersistentPickler(opcodes).dump({'run': buf})
    raw = bytes(buf.as_memoryview())

    with tempfile.TemporaryFile(dir='/tmp') as f:
      f.write(struct.pack('<q', len(opcodes.getvalue())))
      f.write(opcodes.getvalue())
      f.write(raw)
      f.seek(0)
      out = load_oob(f)
    self.assertEqual(out['run'].nbytes, buf.nbytes)

  def test_input_view_offset_and_dtype(self):
    from tinygrad import Device, Tensor
    from openpilot.selfdrive.modeld.modeld import input_view

    packed = np.zeros(4 * 4 * 4 + 64, dtype=np.uint8)
    buffer = Tensor(packed, device=Device.DEFAULT)._buffer()

    first = input_view(buffer, (4, 4), __import__('tinygrad').dtypes.float32, 0)
    second = input_view(buffer, (4, 4), __import__('tinygrad').dtypes.float32, 64)
    self.assertEqual(first.shape, (4, 4))
    self.assertEqual(second.shape, (4, 4))
    self.assertEqual(first.dtype, __import__('tinygrad').dtypes.float32)

    first.assign(1.0).realize()
    second.assign(2.0).realize()
    out = buffer.as_memoryview()
    head = np.frombuffer(bytes(out), dtype=np.float32)
    self.assertTrue(np.all(head[:16] == 1.0))
    self.assertTrue(np.all(head[16:32] == 2.0))
