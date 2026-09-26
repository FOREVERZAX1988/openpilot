import glob
import os
import time
import unittest

from openpilot.common.test import OpenpilotTestCase
import openpilot.cereal.messaging as messaging
from openpilot.system.manager.process_config import managed_processes
from openpilot.common.hardware.hw import Paths
from openpilot.common.swaglog import cloudlog, ipchandler
from openpilot.system.logmessaged import decode_record


class TestLogmessaged(OpenpilotTestCase):
  def setup_method(self):
    # clear the IPC buffer in case some other tests used cloudlog and filled it
    ipchandler.close()
    ipchandler.connect()

    managed_processes['logmessaged'].start()
    self.sock = messaging.sub_sock("logMessage", timeout=1000, conflate=False)
    self.error_sock = messaging.sub_sock("logMessage", timeout=1000, conflate=False)

    # ensure sockets are connected
    time.sleep(0.5)
    messaging.drain_sock(self.sock)
    messaging.drain_sock(self.error_sock)

  def teardown_method(self):
    del self.sock
    del self.error_sock
    managed_processes['logmessaged'].stop(block=True)

  def _get_log_files(self):
    return list(glob.glob(os.path.join(Paths.swaglog_root(), "swaglog.*")))

  def test_simple_log(self):
    msgs = [f"abc {i}" for i in range(10)]
    for m in msgs:
      cloudlog.error(m)
    time.sleep(0.5)
    m = messaging.drain_sock(self.sock)
    assert len(m) == len(msgs)
    assert len(self._get_log_files()) >= 1

  def test_big_log(self):
    n = 10
    msg = "a"*3*1024*1024
    for _ in range(n):
      cloudlog.info(msg)
    time.sleep(0.5)

    msgs = messaging.drain_sock(self.sock)
    assert len(msgs) == 0

    logsize = sum([os.path.getsize(f) for f in self._get_log_files()])
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
