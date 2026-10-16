"""The comma-side warp jetlink's large model runs, in the shape jetlink loads.

jetlink's frame loop runs openpilot's own warp, not one jetlink builds
(jetlink.openpilot.warp): a pickle holding {'run': a captured TinyJit,
'input_specs': {name: (shape, dtype, device)}} whose two inputs are both camera
frames as one (2, frame size) uint8 input_frame and their transforms as one
(2, 3, 3) float32 M_inv, out the (2, 6, model_h // 2, model_w // 2) frame the
link sends. Upstream openpilot builds that pickle with tinygrad's
examples/openpilot/compile_warp.py (--frames 2 --layout yuv420); this fork's
tinygrad predates that script and this fork's modeld runs no warp of its own,
so the artifact is built here, over the fork's own graph:
openpilot.selfdrive.modeld.compile_modeld.make_frame_prepare, the same
perspective warp, reached through the same nv12 layout a camera hands out.

The fork's build runs this once per camera it installs on
(sunnypilot/jetlink_adapter/SConscript), and nothing compiles a warp at
runtime: a device without one stays on the small model, and the offroad alert
says why (jetlink.openpilot.status.NO_WARP).

  python3 -m openpilot.sunnypilot.jetlink_adapter.warp_build \\
      --camera 1928x1208 --model 512x256 --output <path>

Two builds per camera, one build apart: the plain warp, which USB runs, and,
with --lossless, the same graph with the frame's MED errors as a second output,
which is what the Wi-Fi link loads and sends packed instead of the frame
(jetlink.openpilot.lossless, jetlink.lossless). jetlink's Warp reads the second
output as `errors`, and joining.py loads the lossless build over Wi-Fi alone.
"""
from __future__ import annotations

import argparse
import pickle
from pathlib import Path

import numpy as np

# how many camera frames one call warps, and the names it takes them under:
# jetlink.openpilot.warp.WARP_INPUT_NAMES, as TinyJit records a keyword call
# (sorted kwargs), which is what load() checks the pickle against
FRAMES = 2
INPUT_NAMES = ('M_inv', 'input_frame')


def parse_size(text: str) -> tuple[int, int]:
  """'WxH' as (w, h)."""
  w, sep, h = text.lower().partition('x')
  if not sep:
    raise argparse.ArgumentTypeError(f"expected WxH, not {text!r}")
  try:
    return int(w), int(h)
  except ValueError:
    raise argparse.ArgumentTypeError(f"expected WxH, not {text!r}") from None


def input_specs(frame_size: int, device: str) -> dict:
  """(shape, dtype, device) per input, as tinygrad's compile_warp.py writes
  them: what jetlink reads to size the frames it copies in, and the transforms.
  The frame the warp reads is modeld's frame_copy_size, not the camera's whole
  buffer (see nv12_copy_size)."""
  return {'input_frame': ((FRAMES, frame_size), np.dtype(np.uint8).str, device),
          'M_inv': ((FRAMES, 3, 3), np.dtype(np.float32).str, device)}


def with_errors(graph):
  """`graph` returning its frame's MED errors beside it (jetlink.lossless), in
  one graph.

  A second output, not a second graph: jetlink measured the errors at 0.5 ms of
  dispatch alone as their own graph, against 0.14 ms added to the warp's own
  (0.96 -> 1.10 ms p50, 2026-10-06). A lossless warp is what the Wi-Fi link runs
  (jetlink.openpilot.joining), where the frame travels packed at about half the
  bytes; the errors are what it packs, and the server reconstructs the frame
  from them bit for bit.
  """
  def run(input_frame, M_inv):
    from jetlink.openpilot.lossless import med
    warped = graph(input_frame, M_inv)
    return warped, med(warped)
  return run


def build(cam_w: int, cam_h: int, model_w: int, model_h: int, device: str | None = None,
          lossless: bool = False) -> dict:
  """The artifact: the graph captured, and the specs a loader sizes it with.

  The graph is the fork's: one frame_prepare per camera frame, both stacked, so
  one input_frame holds the pair and one M_inv their transforms, as modeld's
  own warp takes them. Inputs are allocated once on `device` and handed to
  TinyJit, which binds the JIT to those buffers: a frame replays the capture
  (jetlink.openpilot.warp.Warp).

  With `lossless` the capture returns (frame, med_errors) instead: jetlink's
  Warp exposes the errors as `errors`, model_state packs them, and the frame
  itself is not sent. Everything else about the artifact is the same.
  """
  from tinygrad import Device, Tensor, TinyJit

  from openpilot.selfdrive.modeld.compile_modeld import NV12Frame, make_frame_prepare
  from openpilot.selfdrive.modeld.compile_modeld import nv12_copy_size
  from openpilot.system.camerad.cameras.nv12_info import get_nv12_info

  device = device or Device.DEFAULT
  stride, y_height, uv_height, _ = get_nv12_info(cam_w, cam_h)
  frame_size = nv12_copy_size(stride, y_height, uv_height)
  nv12 = NV12Frame(cam_w, cam_h, stride, y_height, uv_height, frame_size)
  frame_prepare = make_frame_prepare(nv12, model_w, model_h)

  def run(input_frame, M_inv):
    return Tensor.stack(*(frame_prepare(input_frame[i], M_inv[i]) for i in range(FRAMES)))

  graph = with_errors(run) if lossless else run
  specs = input_specs(frame_size, device)
  tensors, views = {}, {}
  for name, (shape, dtype, dev) in specs.items():
    tensor = Tensor(np.zeros(shape, dtype=np.dtype(dtype)), device=dev).realize()
    tensors[name] = tensor
    views[name] = np.frombuffer(tensor.uop.base.buffer.as_memoryview(allow_zero_copy=True),
                                dtype=np.dtype(dtype)).reshape(shape)

  # random, so nothing constant-folds; the transforms as wide as compile_warp.py
  # draws them, which keeps the gather in range
  rng = np.random.default_rng(42)
  views['input_frame'][:] = rng.integers(0, 256, views['input_frame'].shape, dtype=np.uint8)
  views['M_inv'][:] = rng.standard_normal(views['M_inv'].shape) * 8

  # TinyJit captures on the second call, and a pickle taken before that
  # computes nothing, which load() refuses; three, as the build's old capture
  # did
  jit = TinyJit(graph, prune=True)
  try:
    for _ in range(3):
      # a lossless build returns both outputs, and both have to be realized
      made = jit(input_frame=tensors['input_frame'], M_inv=tensors['M_inv'])
      Tensor.realize(*(made if isinstance(made, (tuple, list)) else (made,)))
    Device[device].synchronize()
  except Exception:
    # the graph is held for the traceback: the first failure of a port is the
    # one worth reading, and a bare build log loses it
    import traceback
    traceback.print_exc()
    raise

  captured = list(getattr(jit.captured, 'expected_names', []))
  if captured != list(INPUT_NAMES):
    raise RuntimeError(f"the capture recorded {captured}, jetlink passes {list(INPUT_NAMES)}")
  return {'metadata': {}, 'run': jit, 'input_specs': specs}


def write(artifact: dict, output: Path) -> Path:
  """The artifact to `output` through a temporary: a compile killed mid-write
  leaves nothing under the name load() opens."""
  output = Path(output)
  output.parent.mkdir(parents=True, exist_ok=True)
  tmp = output.with_suffix(output.suffix + '.tmp')
  with open(tmp, 'wb') as f:
    pickle.dump(artifact, f)
  tmp.replace(output)
  return output


def main(argv: list[str] | None = None) -> None:
  """Build the warp for one camera, as the fork's build runs it."""
  p = argparse.ArgumentParser(prog='python -m openpilot.sunnypilot.jetlink_adapter.warp_build', description=main.__doc__)
  p.add_argument('--camera', type=parse_size, required=True, help='camera resolution, WxH')
  p.add_argument('--model', type=parse_size, required=True, help='model input, WxH')
  p.add_argument('--output', type=Path, required=True)
  p.add_argument('--device', help="what holds the warp's inputs; the default device unless a bench asks")
  p.add_argument('--lossless', action='store_true',
                 help='also output the frame\'s MED errors (the Wi-Fi link packs those instead)')
  args = p.parse_args(argv)

  (cam_w, cam_h), (model_w, model_h) = args.camera, args.model
  print(f"Compiling jetlink warp for {cam_w}x{cam_h} -> {model_w}x{model_h}...")
  out = write(build(cam_w, cam_h, model_w, model_h, args.device, lossless=args.lossless), args.output)
  print(f"  Saved to {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == '__main__':
  main()
