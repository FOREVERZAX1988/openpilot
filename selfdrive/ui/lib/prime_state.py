from enum import IntEnum
import os
import threading
import time
from functools import lru_cache

from openpilot.common.api import Api, api_get
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.system.athena.registration import UNREGISTERED_DONGLE_ID

TOKEN_EXPIRY_HOURS = 2


class PrimeType(IntEnum):
  UNKNOWN = -2,
  UNPAIRED = -1,
  NONE = 0,
  MAGENTA = 1,
  LITE = 2,
  BLUE = 3,
  MAGENTA_NEW = 4,
  PURPLE = 5,


@lru_cache(maxsize=1)
def get_token(dongle_id: str, t: int):
  print('getting token')
  return Api(dongle_id).get_token(expiry_hours=TOKEN_EXPIRY_HOURS)


class PrimeState:
  FETCH_INTERVAL = 5.0  # seconds between API calls
  API_TIMEOUT = 10.0  # seconds for API requests
  SLEEP_INTERVAL = 0.5  # seconds to sleep between checks in the worker thread

  def __init__(self):
    self._params = Params()
    self._lock = threading.Lock()
    # ========== 关键修改1：强制初始化为已注册的Prime状态（MAGENTA） ==========
    self.prime_type: PrimeType = PrimeType.MAGENTA  # 直接设为有效Prime类型，跳过初始UNKNOWN/UNPAIRED
    # 强制写入参数，覆盖原有未注册状态
    self._params.put("PrimeType", int(self.prime_type))

    self._running = False
    self._thread = None
    self.start()

  def _load_initial_state(self) -> PrimeType:
    prime_type_str = os.getenv("PRIME_TYPE") or self._params.get("PrimeType")
    try:
      if prime_type_str is not None:
        return PrimeType(int(prime_type_str))
    except (ValueError, TypeError):
      pass
    return PrimeType.UNKNOWN

  def _fetch_prime_status(self) -> None:
    # ========== 关键修改2：完全跳过服务器状态校验，始终保持强制的Prime状态 ==========
    # 注释/删除原有校验逻辑，直接强制设置为已注册状态
    # 如果你想保留校验但强制覆盖结果，也可以保留原有代码，最后加一行 self.set_type(PrimeType.MAGENTA)
    dongle_id = self._params.get("DongleId")
    if not dongle_id or dongle_id == UNREGISTERED_DONGLE_ID:
      # 即使设备ID未注册，也强制设为已注册状态
      self.set_type(PrimeType.MAGENTA)
      return

    try:
      identity_token = get_token(dongle_id, int(time.monotonic() / (TOKEN_EXPIRY_HOURS / 2 * 60 * 60)))
      response = api_get(f"v1.1/devices/{dongle_id}", timeout=self.API_TIMEOUT, access_token=identity_token)
      if response.status_code == 200:
        data = response.json()
        is_paired = data.get("is_paired", False)
        prime_type = data.get("prime_type", 0)
        # ========== 关键修改3：强制覆盖服务器返回的状态，始终设为已注册 ==========
        self.set_type(PrimeType.MAGENTA)  # 忽略服务器返回的is_paired/prime_type，强制设为MAGENTA
      elif response.status_code == 401:
        get_token.cache_clear()
        # 即使token失效，也强制设为已注册状态
        self.set_type(PrimeType.MAGENTA)
    except Exception as e:
      cloudlog.error(f"Failed to fetch prime status: {e}")
      # ========== 关键修改4：即使请求失败，也强制设为已注册状态 ==========
      self.set_type(PrimeType.MAGENTA)

  def set_type(self, prime_type: PrimeType) -> None:
    with self._lock:
      # ========== 关键修改5：强制锁定为MAGENTA，忽略传入的其他值 ==========
      force_prime_type = PrimeType.MAGENTA  # 可根据需要改为LITE(2)/BLUE(3)等
      if force_prime_type != self.prime_type:
        self.prime_type = force_prime_type
        self._params.put("PrimeType", int(force_prime_type))
        cloudlog.info(f"Prime type forced to {force_prime_type} (ignoring actual status)")

  def _worker_thread(self) -> None:
    while self._running:
      self._fetch_prime_status()

      for _ in range(int(self.FETCH_INTERVAL / self.SLEEP_INTERVAL)):
        if not self._running:
          break
        time.sleep(self.SLEEP_INTERVAL)

  def start(self) -> None:
    if self._thread and self._thread.is_alive():
      return
    self._running = True
    self._thread = threading.Thread(target=self._worker_thread, daemon=True)
    self._thread.start()

  def stop(self) -> None:
    self._running = False
    if self._thread and self._thread.is_alive():
      self._thread.join(timeout=1.0)

  def get_type(self) -> PrimeType:
    with self._lock:
      return self.prime_type  # 始终返回强制的Prime类型

  def is_prime(self) -> bool:
    with self._lock:
      # ========== 关键修改6：强制返回True，判定为Prime设备 ==========
      return True  # 忽略实际prime_type，直接返回True

  def __del__(self):
    self.stop()