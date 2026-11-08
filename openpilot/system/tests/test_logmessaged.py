import glob
import os
import time
import unittest
import uuid

from openpilot.common.test import OpenpilotTestCase
import openpilot.cereal.messaging as messaging
from openpilot.system.manager.process_config import managed_processes
from openpilot.common.hardware.hw import Paths
from openpilot.common.swaglog import SWAGLOG_MAX_SIZE, cloudlog, ipchandler
from openpilot.system.logmessaged import decode_record

TIMEOUT = 10.


class TestLogmessaged(OpenpilotTestCase):
  def setup_method(self):
    managed_processes['logmessaged'].start()
    while not os.path.exists(Paths.swaglog_ipc()):
      time.sleep(0.01)
    self.sock = messaging.sub_sock("logMessage", timeout=100, conflate=False)
    self.error_sock = messaging.sub_sock("logMessage", timeout=100, conflate=False)

    # ensure sockets are connected: probe until each socket has received one.
    # debug logs are published but not written to the log files.
    # logmessaged handles logs in order, so after the final drain no probes are in flight
    pending = {self.sock, self.error_sock}
    deadline = time.monotonic() + TIMEOUT
    while pending:
      assert time.monotonic() < deadline, "timed out connecting to logmessaged"
      cloudlog.debug("probe")
      time.sleep(0.01)
      pending = {s for s in pending if not messaging.drain_sock(s)}
    messaging.drain_sock(self.sock)
    messaging.drain_sock(self.error_sock)

  def teardown_method(self):
    del self.sock
    del self.error_sock
    managed_processes['logmessaged'].stop(block=True)

  def _get_log_files(self):
    return list(glob.glob(os.path.join(Paths.swaglog_root(), "swaglog.*")))

  def _recv_one(self):
    deadline = time.monotonic() + TIMEOUT
    while (m := messaging.recv_one(self.sock)) is None:
      assert time.monotonic() < deadline, "timed out waiting for logMessage"
    return m

  def _drain(self):
    # logmessaged handles logs in order, so everything logged before the sentinel is received before it
    sentinel = f"sentinel {uuid.uuid4()}"
    cloudlog.debug(sentinel)
    msgs = []
    while sentinel not in (m := self._recv_one()).logMessage:
      msgs.append(m)
    return msgs

  def test_simple_log(self):
    msgs = [f"abc {i}" for i in range(10)]
    for m in msgs:
      cloudlog.error(m)
    m = self._drain()
    assert len(m) == len(msgs)
    assert len(self._get_log_files()) >= 1

  def test_big_log(self):
    n = 10
    msg = "a"*SWAGLOG_MAX_SIZE
    # /data/log already holds hundreds of MB of swaglogs on a real device, so an
    # absolute-size assertion is environment-dependent (fails on COMMA_HARDWARE for
    # the wrong reason). Count only the bytes this test appends.
    before = {f: os.path.getsize(f) for f in self._get_log_files()}
    for _ in range(n):
      cloudlog.info(msg)
      # wait for each one, the non-blocking sender drops logs that don't fit in the socket buffer
      assert msg in self._recv_one().logMessage
    assert len(self._drain()) == 0

    logsize = sum(max(0, os.path.getsize(f) - before.get(f, 0)) for f in self._get_log_files())
    assert (n*len(msg)) < logsize < (n*(len(msg)+1024))


class TestDecodeRecord(unittest.TestCase):
  """Unit tests for the IPC payload decode.

  A single non-UTF-8 byte (0xff) used to raise UnicodeDecodeError out of main()'s
  loop and take logmessaged down; the manager restarted it, dropping every log
  message produced in the meantime.
  """

  def test_invalid_byte_is_replaced_not_raised(self):
    self.assertEqual(decode_record(b'\xff'), '\ufffd')

  def test_invalid_byte_does_not_eat_the_rest(self):
    self.assertEqual(decode_record(b'gps \xff ok'), 'gps \ufffd ok')

  def test_valid_utf8_untouched(self):
    payload = '温度 22°C'.encode()
    self.assertEqual(decode_record(payload), '温度 22°C')

  def test_empty_payload(self):
    self.assertEqual(decode_record(b''), '')

  def test_too_big_log(self):
    cloudlog.info("a"*SWAGLOG_MAX_SIZE)
    cloudlog.info("small")

    msgs = self._drain()
    assert len(msgs) == 1
