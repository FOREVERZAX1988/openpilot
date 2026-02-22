#!/usr/bin/env python3
import time
import json
import jwt
from pathlib import Path
from datetime import datetime, timedelta, UTC
from openpilot.common.api import api_get
from openpilot.common.params import Params
from openpilot.common.spinner import Spinner
from openpilot.selfdrive.selfdrived.alertmanager import set_offroad_alert
from openpilot.system.hardware import HARDWARE, PC
from openpilot.system.hardware.hw import Paths
from openpilot.common.swaglog import cloudlog

UNREGISTERED_DONGLE_ID = "UnregisteredDevice"
# 新增：设置最大重试次数，避免无限循环
MAX_RETRY_TIMES = 3

def is_registered_device() -> bool:
  dongle = Params().get("DongleId")
  return dongle not in (None, UNREGISTERED_DONGLE_ID)

def register(show_spinner=False) -> str | None:
  params = Params()
  #return UNREGISTERED_DONGLE_ID
  dongle_id: str | None = params.get("DongleId")
  if dongle_id is None and Path(Paths.persist_root()+"/comma/dongle_id").is_file():
    # not all devices will have this; added early in comma 3X production (2/28/24)
    with open(Paths.persist_root()+"/comma/dongle_id") as f:
      dongle_id = f.read().strip()

  #pubkey = Path(Paths.persist_root()+"/comma/id_rsa.pub")
  #if not pubkey.is_file():
    #dongle_id = UNREGISTERED_DONGLE_ID
    #cloudlog.warning(f"missing public key: {pubkey}")

  if dongle_id in (None, UNREGISTERED_DONGLE_ID):
    if show_spinner:
      spinner = Spinner()
      spinner.update("registering device")

    # Create registration token, in the future, this key will make JWTs directly
    #with open(Paths.persist_root()+"/comma/id_rsa.pub") as f1, open(Paths.persist_root()+"/comma/id_rsa") as f2:
      #public_key = f1.read()
      #private_key = f2.read()

    # Block until we get the imei
    serial = HARDWARE.get_serial()
    start_time = time.monotonic()
    imei1='865420071781912'
    imei2='865420071781904'
    # 循环获取IMEI（最多等60秒）
    while imei1 is None and imei2 is None:
      try:
        imei1, imei2 = HARDWARE.get_imei(0), HARDWARE.get_imei(1)
      except Exception:
        cloudlog.exception("Error getting imei, trying again...")
        time.sleep(1)
      if time.monotonic() - start_time > 60 and show_spinner:
        spinner.update(f"registering device - serial: {serial}, IMEI: ({imei1}, {imei2})")
        break  # IMEI获取超时，直接终止
    # 核心修改：用重试次数替代无限循环
    backoff = 0
    retry_count = 0 # 初始化重试计数器
    start_time = time.monotonic()
    register_success = False  # 标记是否注册成功
    # 循环条件：未超过最大重试次数 + 未超时（可选60秒）
    while retry_count < MAX_RETRY_TIMES and time.monotonic() - start_time < 60:
      try:
        #register_token = jwt.encode({'register': True, 'exp': datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)}, private_key, algorithm='RS256')
        cloudlog.info(f"getting pilotauth (retry {retry_count + 1}/{MAX_RETRY_TIMES})")
        resp = api_get("v2/pilotauth/", method='POST', timeout=15,
                       imei=imei1, imei2=imei2, serial=serial)

        # 处理402/403错误（注册失败）
        if resp.status_code in (402, 403):
          cloudlog.info(f"Unable to register device, got {resp.status_code}, retry {retry_count + 1} failed")
          dongle_id = UNREGISTERED_DONGLE_ID
          if show_spinner:
            spinner.update(f"registering device - serial: {serial}, contact MR.ONE")
          retry_count += 1  # 重试次数+1
          time.sleep(2)
          continue  # 继续下一次重试

        # 注册成功
        dongleauth = json.loads(resp.text)
        dongle_id = dongleauth["dongle_id"]
        register_success = True
        break  # 成功后跳出循环

      except Exception:
        cloudlog.exception(f"failed to authenticate (retry {retry_count + 1})")
        retry_count += 1  # 异常也计入重试次数
        backoff = min(backoff + 1, 15)
        time.sleep(backoff)

      # 超时提示
      if time.monotonic() - start_time > 60 and show_spinner:
        spinner.update(f"registering device - serial: {serial}, IMEI: ({imei1}, {imei2})")
        break  # 注册超时，直接终止
        #return UNREGISTERED_DONGLE_ID # hotfix to prevent an infinite wait for registration

    # 重试次数耗尽/超时，直接标记为未注册
    if not register_success:
      cloudlog.warning(f"Register failed after {retry_count} retries, skip registration")
      dongle_id = UNREGISTERED_DONGLE_ID

    if show_spinner:
      spinner.close()

  if dongle_id:
    params.put("DongleId", dongle_id)

  # set_offroad_alert("Offroad_UnregisteredHardware", (dongle_id == UNREGISTERED_DONGLE_ID) and not PC)
  return dongle_id

if __name__ == "__main__":
  print(register())
