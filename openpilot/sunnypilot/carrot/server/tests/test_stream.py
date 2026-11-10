import asyncio
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock, MagicMock


def load_stream_module():
  # Load only this HTTP feature; unrelated Bluetooth/device routes require Linux.
  name = "openpilot.sunnypilot.carrot.server.features.stream"
  diagnostics = ModuleType("openpilot.sunnypilot.carrot.server.services.vision_diag")
  diagnostics.record_stream_proxy_event = lambda event: None
  patcher = mock.patch.dict(sys.modules, {diagnostics.__name__: diagnostics})
  patcher.start()
  try:
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / "features/stream.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
  finally:
    patcher.stop()
  return module


class TestStream(unittest.TestCase):

  def test_stream_with_hud_preserves_upstream_response(self):
    for cluster_hud in [0, 1]:
      for status in [200, 409]:
        with self.subTest(cluster_hud=cluster_hud, status=status):
          stream = load_stream_module()
          body = b'{"cameras":["road"],"client_id":"browser"}'
          answer = json.dumps({"sdp": "answer"} if status == 200 else {"code": "carrot_vision_busy"}).encode()
          response = SimpleNamespace(status=status, headers={"Content-Type": "application/json"}, read=AsyncMock(return_value=answer))
          session = MagicMock()
          session.post.return_value.__aenter__ = AsyncMock(return_value=response)
          session.post.return_value.__aexit__ = AsyncMock(return_value=False)
          params = MagicMock()
          params.get_int.return_value = cluster_hud
          request = SimpleNamespace(
            app={"params": params, "http": session}, remote="127.0.0.1",
            headers={"Content-Type": "application/json"}, read=AsyncMock(return_value=body),
          )
          events = []
          patcher = mock.patch.object(stream, "record_stream_proxy_event", events.append)
          patcher.start()
          self.addCleanup(patcher.stop)

          result = asyncio.run(stream.proxy_stream(request))

          self.assertEqual(result.status, status)
          self.assertEqual(result.body, answer)
          self.assertEqual(result.headers["Content-Type"], "application/json")
          self.assertEqual(session.post.call_args.args, (stream.WEBRTCD_URL,))
          self.assertEqual(session.post.call_args.kwargs["data"], body)
          self.assertEqual(events[-1]["ok"], status == 200)


if __name__ == "__main__":
  unittest.main()
