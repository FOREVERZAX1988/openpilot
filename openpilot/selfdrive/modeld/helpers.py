import io
import pickle
import shutil
import struct
import tempfile
from pathlib import Path

from openpilot.common.file_chunker import get_manifest_path
from openpilot.common.hardware.usb import CHESTNUT_USB_PRODUCT, USB_DEVICES_PATH, is_chestnut_usb_id

MODELS_DIR = Path(__file__).resolve().parent / 'models'

# Re-added for compile_modeld.py (this fork's compile-time pickling path, kept
# because jetlink_adapter/tests/test_queues.py imports it). The tn upstream
# removed both from here and moved dump_oob to modeld_v2/helpers.py; keeping the
# stock-modeld compile script alive needs them on this module.
def dump_oob(obj, f):
  with tempfile.TemporaryFile(dir=".") as tmp:
    def buffer_callback(pb: pickle.PickleBuffer):
      m = pb.raw()
      tmp.write(struct.pack('<q', m.nbytes))
      tmp.write(m)
      pb.release()  # keep peak ram at ~1 buffer
    stream = io.BytesIO()
    pickle.Pickler(stream, protocol=5, buffer_callback=buffer_callback).dump(obj)
    opcodes = stream.getvalue()
    f.write(struct.pack('<q', len(opcodes)))
    f.write(opcodes)
    tmp.seek(0)
    shutil.copyfileobj(tmp, f)


def modeld_pkl_path(chestnut: bool):
  prefix = 'big_' if chestnut else ''
  return MODELS_DIR / f'{prefix}driving_tinygrad.pkl'

def load_oob(f):
  """Unpickle a model artifact: 8-byte opcode length, opcode stream, then weight buffers.

  Two layouts are in circulation and both have to load, because the two compilers in this
  tree disagree on how out-of-band buffers are addressed:

  A) openpilot's own dump_oob (compile_modeld.py, selfdrive/modeld): PEP 574 buffers, each
     prefixed with its length, referenced by NEXT_BUFFER -- pickle.load(buffers=...) below.
  B) tinygrad's examples/openpilot dump_pickle, which is what SConscript's compile_model()
     actually runs (compile_onnx.py --out-of-band, for both Darwin and comma_arm64): one raw
     device-buffer blob covering the rest of the file, referenced by BINPERSID with
     (nbytes, offset) and resolved via Unpickler.persistent_load.

  Reading a B-layout pkl with the A path raised "A load persistent id instruction was
  encountered, but no persistent_load function was specified": modeld died in
  ModelState.__init__ before the first frame, so the car drew no path, no lane lines and no
  road edges at all. The 2026-10-24 restore to "upstream's form" only accounted for A --
  upstream builds its pkls with compile_modeld.py, this fork's SConscript does not.

  Callers pass an open file object (open_file_chunked covers the big model's chunked
  manifest).
  """
  opcodes = f.read(struct.unpack('<q', f.read(8))[0])
  rest = f.read()

  def buffers():
    r = io.BytesIO(rest)
    while (h := r.read(8)):
      pb = pickle.PickleBuffer(bytearray(struct.unpack('<q', h)[0]))
      if r.readinto(pb) != pb.raw().nbytes:
        raise EOFError("incomplete model buffer")
      yield pb

  try:
    return pickle.load(io.BytesIO(opcodes), buffers=buffers())
  except pickle.UnpicklingError as e:
    if 'persistent' not in str(e):
      raise

  # B layout: the remaining bytes are the weight blob; a persistent id is (nbytes, offset) into it.
  import numpy as np
  from tinygrad import Device, Tensor
  blob = Tensor(np.frombuffer(rest, dtype=np.uint8)).to(Device.DEFAULT).realize().uop.buffer
  u = pickle.Unpickler(io.BytesIO(opcodes))
  u.persistent_load = lambda pid: blob.view(*pid)
  return u.load()

# the top level of the pkl compile_modeld.py writes. checked at both ends: a pkl from another
# compile_modeld.py unpickles fine and only fails on the first key it lacks, as a bare KeyError
MODELD_PKL_KEYS = ('metadata', 'input_devices', 'run_model')

def check_modeld_pkl(jits: dict, path) -> None:
  missing = [k for k in MODELD_PKL_KEYS if k not in jits]
  if missing:
    raise RuntimeError(f"{path} is missing {missing}: it was compiled by a different compile_modeld.py than this modeld, rebuild it")

# every warp jit is compiled for one driver camera resolution and keyed by it, so a prebuilt cut
# on a device with a different camera carries none for this one. Without this the mismatch
# surfaces as a bare FileNotFoundError or KeyError inside ModelState.__init__ and the process
# just stops. See PREBUILT_ALL_CAMERAS in modeld/SConscript
def _camera_mismatch(cam_w: int, cam_h: int, compiled: str, path) -> RuntimeError:
  have = f"{path} has only [{compiled or 'none'}]"
  return RuntimeError(f"no jit for this device's {cam_w}x{cam_h} driver camera: {have}. This build was compiled for another device")

def dm_warp_path(cam_w: int, cam_h: int):
  path = MODELS_DIR / f'dm_warp_{cam_w}x{cam_h}_tinygrad.pkl'
  if not path.is_file():
    compiled = ', '.join(sorted(p.name.split('_')[2] for p in MODELS_DIR.glob('dm_warp_*_tinygrad.pkl')))
    raise _camera_mismatch(cam_w, cam_h, compiled, MODELS_DIR)
  return path

def check_camera_jit(jits: dict, cam_w: int, cam_h: int, path) -> None:
  if (cam_w, cam_h) not in jits:
    compiled = ', '.join(f'{w}x{h}' for w, h in sorted(k for k in jits if isinstance(k, tuple)))
    raise _camera_mismatch(cam_w, cam_h, compiled, path)


def chestnut_present() -> bool:
  for d in USB_DEVICES_PATH.glob("*"):
    try:
      usb_id = (int((d / "idVendor").read_text(), 16), int((d / "idProduct").read_text(), 16))
      product = (d / "product").read_text().strip()
      if is_chestnut_usb_id(*usb_id) and product == CHESTNUT_USB_PRODUCT:
        return True
    except Exception:
      pass
  return False

def chestnut_compiled() -> bool:
  path = modeld_pkl_path(chestnut=True)
  return (path.is_file() or Path(get_manifest_path(path)).is_file()) and all(
    (MODELS_DIR / f'big_driving_warp_{size}_tinygrad.pkl').is_file() for size in ('1344x760', '1928x1208'))
