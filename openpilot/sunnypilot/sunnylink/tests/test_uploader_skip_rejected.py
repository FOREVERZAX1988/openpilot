#!/usr/bin/env python3
"""A file the sunnylink cloud refuses (403/404) must not be retried forever.

Repro that motivated this: sunnylink answers every upload from a non-sponsor account with
403 {"detail":"Upload only allowed for sponsors temporarily."}. The uploader kept picking
the same boot/*.zst, logged an ERROR and backed off one hour, on repeat -- the rest of the
queue never drained. 403/404 are now treated as handled (file is tagged uploaded so it is
skipped) and reported once as `upload_skipped_rejected` instead of `upload_failed`.
"""

import os
import tempfile
import unittest
from unittest import mock

from openpilot.common.test import OpenpilotTestCase
from openpilot.sunnypilot.sunnylink import uploader as up


class FakeResponse:
  def __init__(self, status_code: int, body: bytes = b"", content_length: str = "16"):
    self.status_code = status_code
    self.content = body
    self.request = mock.Mock(headers={"Content-Length": content_length})


class TestUploaderSkipRejected(OpenpilotTestCase):
  def _upload(self, tmpdir, response, key="boot/00000004--0ac3964c96--149.zst"):
    fn = os.path.join(tmpdir, "somefile")
    with open(fn, "wb") as f:
      f.write(b"x" * 16)
    uploader = up.Uploader("dongle_id", tmpdir)
    with mock.patch.object(uploader, "do_upload", return_value=response), \
         mock.patch.object(up, "setxattr") as set_xattr, \
         mock.patch.object(up, "cloudlog") as log:
      result = uploader.upload("boot", key, fn, 1, False)
    return result, set_xattr, log, uploader

  def test_forbidden_is_handled_and_tagged_not_retried(self):
    body = b'{"type":"ForbiddenException","status":403,"detail":"Upload only allowed for sponsors temporarily."}'
    with tempfile.TemporaryDirectory() as tmpdir:
      result, set_xattr, log, uploader = self._upload(tmpdir, FakeResponse(403, body))

    self.assertTrue(result, "403 must count as handled, otherwise the same file is retried forever")
    set_xattr.assert_called_once()
    self.assertEqual(uploader.last_status_code, 403)
    events = [call.args[0] for call in log.event.call_args_list]
    self.assertIn("upload_skipped_rejected", events)
    self.assertNotIn("upload_failed with content", events)

  def test_gone_is_handled_too(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      result, _, _, _ = self._upload(tmpdir, FakeResponse(404, b"not found"))
    self.assertTrue(result)

  def test_bad_request_is_handled_too(self):
    # Live repro (tizi, 2026-09-20): the uploader sat on one crash dump for hours --
    # 400 {"detail":"Invalid file extension: crash/2026-09-19--17-50-30_..._loggerd_encoder"}.
    # That file sits in immediate_folders, so it was picked first on every pass and blocked
    # every other upload. It must be tagged as handled, not retried.
    body = b'{"type":"BadRequestException","status":400,"detail":"Invalid file extension: crash/2026-09-19--17-50-30_473338fe_openpilot_system_loggerd_encoder"}'
    with tempfile.TemporaryDirectory() as tmpdir:
      result, set_xattr, log, uploader = self._upload(
        tmpdir, FakeResponse(400, body),
        key="crash/2026-09-19--17-50-30_473338fe_openpilot_system_loggerd_encoder")

    self.assertTrue(result, "400 must count as handled, otherwise the queue head never drains")
    set_xattr.assert_called_once()
    self.assertEqual(uploader.last_status_code, 400)
    events = [call.args[0] for call in log.event.call_args_list]
    self.assertIn("upload_skipped_rejected", events)
    self.assertNotIn("upload_failed with content", events)

  def test_auth_failure_is_still_reported_and_retried(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      result, set_xattr, log, uploader = self._upload(tmpdir, FakeResponse(401, b"bad token"))

    self.assertFalse(result, "401 is recoverable (re-login), so keep retrying it")
    set_xattr.assert_not_called()
    self.assertEqual(uploader.last_status_code, 401)
    events = [call.args[0] for call in log.event.call_args_list]
    self.assertIn("upload_failed with content", events)

  def test_success_path_unchanged(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      result, set_xattr, log, _ = self._upload(tmpdir, FakeResponse(200, b""))
    self.assertTrue(result)
    set_xattr.assert_called_once()
    events = [call.args[0] for call in log.event.call_args_list]
    self.assertIn("upload_success", events)


if __name__ == "__main__":
  unittest.main()
