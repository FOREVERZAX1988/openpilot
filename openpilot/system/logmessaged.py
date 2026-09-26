#!/usr/bin/env python3
import zmq
from typing import NoReturn

import openpilot.cereal.messaging as messaging
from openpilot.common.logging_extra import SwagLogFileFormatter
from openpilot.common.hardware.hw import Paths
from openpilot.common.swaglog import get_file_handler


def decode_record(payload: bytes) -> str:
  """Decode a swaglog payload sent over the IPC socket.

  Lossy on purpose: a single non-UTF-8 byte (came from a process logging raw
  binary/GPS data) used to raise UnicodeDecodeError straight out of main()'s
  loop, killing logmessaged -- the manager then restarted it and every log
  message produced in the meantime was dropped.
  """
  return payload.decode("utf-8", errors="replace")


def main() -> NoReturn:
  log_handler = get_file_handler()
  log_handler.setFormatter(SwagLogFileFormatter(None))
  log_level = 20  # logging.INFO

  ctx = zmq.Context.instance()
  sock = ctx.socket(zmq.PULL)
  sock.bind(Paths.swaglog_ipc())

  # and we publish them
  log_message_sock = messaging.pub_sock('logMessage')
  error_log_message_sock = messaging.pub_sock('errorLogMessage')

  try:
    while True:
      dat = b''.join(sock.recv_multipart())
      if not dat:
        continue  # empty frame: nothing to log, and dat[0] would IndexError
      level = dat[0]
      record = decode_record(dat[1:])
      if level >= log_level:
        log_handler.emit(record)

      if len(record) > 2*1024*1024:
        print("WARNING: log too big to publish", len(record))
        print(record[:100])
        continue

      # then we publish them
      msg = messaging.new_message(None, valid=True, logMessage=record)
      log_message_sock.send(msg.to_bytes())

      if level >= 40:  # logging.ERROR
        msg = messaging.new_message(None, valid=True, errorLogMessage=record)
        error_log_message_sock.send(msg.to_bytes())
  finally:
    sock.close()
    ctx.term()

    # can hit this if interrupted during a rollover
    try:
      log_handler.close()
    except ValueError:
      pass

if __name__ == "__main__":
  main()
