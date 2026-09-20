#!/usr/bin/env python3
"""A non-sponsor account gets 403 for every upload -> stop the uploader instead of queueing.

Repro (2026-09-20): sunnylink answers 403 {"detail":"Upload only allowed for sponsors
temporarily."} for *every* file of this account. Each file is now skipped once (see
test_uploader_skip_rejected), but the process kept waking up only to be refused again, so the
user asked for the feature to switch itself off after enough consecutive refusals instead of
re-queueing forever. After MAX_PERMISSION_REJECTS consecutive 403s the uploader writes
EnableSunnylinkUploader=False, which is the param the manager's process predicate reads.
"""

import os
import tempfile
import unittest
from unittest import mock

from openpilot.common.test import OpenpilotTestCase
from openpilot.sunnypilot.sunnylink import uploader as up

FORBIDDEN = b'{"type":"ForbiddenException","status":403,"detail":"Upload only allowed for sponsors temporarily."}'


class FakeResponse:
  def __init__(self, status_code: int, body: bytes = b""):
    self.status_code = status_code
    self.content = body
    self.request = mock.Mock(headers={"Content-Length": "16"})


class TestUploaderNoPermissionDisable(OpenpilotTestCase):
  def _rejects(self, uploader, n, status=403, body=FORBIDDEN):
    for i in range(n):
      fn = os.path.join(uploader.root, f"somefile{i}")
      with open(fn, "wb") as f:
        f.write(b"x" * 16)
      uploader.upload("boot", f"boot/0000{i}--0ac3964c96--149.zst", fn, 1, False)

  def _make(self, tmpdir):
    uploader = up.Uploader("dongle_id", tmpdir)
    uploader.params = mock.Mock()
    return uploader

  def test_consecutive_forbidden_rejects_disable_the_uploader(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      uploader = self._make(tmpdir)
      with mock.patch.object(uploader, "do_upload", return_value=FakeResponse(403, FORBIDDEN)), \
           mock.patch.object(up, "setxattr"), mock.patch.object(up, "cloudlog") as log:
        self._rejects(uploader, up.MAX_PERMISSION_REJECTS - 1)
        self.assertEqual(uploader.params.put_bool.call_count, 0,
                         "must not disable before the threshold is reached")
        self._rejects(uploader, 1)

    uploader.params.put_bool.assert_called_once_with("EnableSunnylinkUploader", False, block=True)
    events = [call.args[0] for call in log.event.call_args_list]
    self.assertEqual(events.count("uploader_disabled_no_permission"), 1,
                     "the user must see one clear line saying why the uploader switched off")

  def test_success_resets_the_consecutive_counter(self):
    with tempfile.TemporaryDirectory() as tmpdir:
      uploader = self._make(tmpdir)
      responses = [FakeResponse(403, FORBIDDEN)] * (up.MAX_PERMISSION_REJECTS - 1) + [FakeResponse(200)]
      with mock.patch.object(uploader, "do_upload", side_effect=responses), \
           mock.patch.object(up, "setxattr"), mock.patch.object(up, "cloudlog"):
        self._rejects(uploader, up.MAX_PERMISSION_REJECTS - 1)
        fn = os.path.join(tmpdir, "okfile")
        with open(fn, "wb") as f:
          f.write(b"x" * 16)
        self.assertTrue(uploader.upload("boot", "boot/ok.zst", fn, 1, False))
      with mock.patch.object(uploader, "do_upload", return_value=FakeResponse(403, FORBIDDEN)), \
           mock.patch.object(up, "setxattr"), mock.patch.object(up, "cloudlog"):
        self._rejects(uploader, 1)

    self.assertEqual(uploader.params.put_bool.call_count, 0,
                     "a working upload in between means the account is fine, so no disable")

  def test_bad_file_rejects_do_not_disable_the_uploader(self):
    # 400 (bad file extension) is a local file problem, not a missing entitlement.
    with tempfile.TemporaryDirectory() as tmpdir:
      uploader = self._make(tmpdir)
      with mock.patch.object(uploader, "do_upload", return_value=FakeResponse(400, b"bad ext")), \
           mock.patch.object(up, "setxattr"), mock.patch.object(up, "cloudlog"):
        self._rejects(uploader, up.MAX_PERMISSION_REJECTS + 5)

    uploader.params.put_bool.assert_not_called()


if __name__ == "__main__":
  unittest.main()
