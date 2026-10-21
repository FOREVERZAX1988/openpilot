import os
import sys
import json
import shutil
import tempfile
import ctypes
import weakref
import builtins
import datetime
from pathlib import Path
from enum import IntEnum, IntFlag
from openpilot.common.swaglog import cloudlog

class ParamKeyFlag(IntFlag):
  PERSISTENT = 0x02
  CLEAR_ON_MANAGER_START = 0x04
  CLEAR_ON_ONROAD_TRANSITION = 0x08
  CLEAR_ON_OFFROAD_TRANSITION = 0x10
  DEVELOPMENT_ONLY = 0x40
  CLEAR_ON_IGNITION_ON = 0x80
  BACKUP = 0x100
  ALL = 0xFFFFFFFF

class ParamKeyType(IntEnum):
  STRING = 0
  BOOL = 1
  INT = 2
  FLOAT = 3
  TIME = 4
  JSON = 5
  BYTES = 6

_suffix = ".dylib" if sys.platform == "darwin" else ".so"


def _params_lib_path() -> Path:
  """Return a dlopen path that a rebuild of the source tree cannot corrupt.

  Loading libparams_c straight out of the checkout is unsafe on a device that also
  builds it: scons/SConscript rewrites libparams_c.so *in place*, and the kernel then
  serves the new bytes to every process that already mmapped the old ones. The
  symptom is a SIGSEGV inside libparams_c.so -- e.g. 2026-10-17 15:28, when
  manager.py and athenad died 6 seconds apart, taking the whole stack (and the
  assistant's websocket, mid-answer) down with them.
  """
  src = Path(__file__).with_name(f"libparams_c{_suffix}")
  try:
    st = src.stat()
    cache_root = Path("/data/.cache/params_lib") if Path("/data").is_dir() else Path(tempfile.gettempdir()) / "op_params_lib"
    dst = cache_root / f"libparams_c-{int(st.st_mtime)}-{st.st_size}{_suffix}"
    if not dst.is_file():
      cache_root.mkdir(parents=True, exist_ok=True)
      tmp = dst.with_name(f"{dst.name}.{os.getpid()}.tmp")
      shutil.copyfile(src, tmp)
      os.replace(tmp, dst)  # atomic: concurrent starts cannot see a partial copy
      for stale in sorted(cache_root.glob(f"libparams_c-*{_suffix}"))[:-3]:
        try:
          stale.unlink()
        except OSError:
          pass
    return dst
  except Exception:
    return src


lib = None
try:
  lib = ctypes.CDLL(_params_lib_path())
except OSError:
  cloudlog.warning("libparams_c.so missing, entering mock params mode, params stored in memory only!")
  lib = None

ParamsHandle = ctypes.c_void_p
class ParamsBuffer(ctypes.Structure):
  _fields_ = [("data", ctypes.c_void_p), ("size", ctypes.c_size_t)]

# ------------------- Bind C functions only if lib available -------------------
params_last_error = None
params_create = None
params_destroy = None
params_clear_all = None
params_check_key = None
params_get_key_type = None
params_get_default = None
params_get_stock = None
params_get_tuning_level = None
params_get_settings_tier = None
params_get = None
params_get_bool = None
params_put = None
params_put_bool = None
params_remove = None
params_get_path = None
params_keys_size = None
params_key_at = None
params_keys_by_flag = None

if lib is not None:
  def _bind_raw(name, args, result=None):
    function = getattr(lib, name)
    function.argtypes = args
    function.restype = result
    return function

  params_last_error = _bind_raw("params_last_error", [], ctypes.c_char_p)
  def _bind(name, args, result=None):
    function = _bind_raw(name, args, result)
    def checked(*call_args):
      value = function(*call_args)
      if error := params_last_error():
        raise RuntimeError(error.decode())
      return value
    return checked

  def _bind_optional(name, args, result=None):
    """Bind a symbol the device's library may predate.

    `params_keys.h` and the bindings are compiled into libparams_c.so, so a device that
    has not rebuilt the library since the parameter metadata landed has no such symbol.
    Letting _bind raise would take down every daemon that imports Params; the callers of
    the metadata are written to read a missing answer as "leave this parameter alone".
    """
    try:
      return _bind(name, args, result)
    except AttributeError:
      cloudlog.warning(f"params: {name} missing from the params library (stale libparams_c.so?)")
      return None

  params_create = _bind("params_create", [ctypes.c_char_p, ctypes.c_size_t], ParamsHandle)
  params_destroy = _bind("params_destroy", [ParamsHandle])
  params_clear_all = _bind("params_clear_all", [ParamsHandle, ctypes.c_uint])
  params_check_key = _bind("params_check_key", [ParamsHandle, ctypes.c_char_p], ctypes.c_bool)
  params_get_key_type = _bind("params_get_key_type", [ParamsHandle, ctypes.c_char_p], ctypes.c_int)
  params_get_default = _bind("params_get_default", [ParamsHandle, ctypes.c_char_p], ParamsBuffer)
  params_get_stock = _bind_optional("params_get_stock", [ParamsHandle, ctypes.c_char_p], ParamsBuffer)
  params_get_tuning_level = _bind_optional("params_get_tuning_level", [ParamsHandle, ctypes.c_char_p], ctypes.c_int)
  params_get_settings_tier = _bind_optional("params_get_settings_tier", [ParamsHandle, ctypes.c_char_p], ctypes.c_int)
  params_get = _bind("params_get", [ParamsHandle, ctypes.c_char_p, ctypes.c_bool], ParamsBuffer)
  params_get_bool = _bind("params_get_bool", [ParamsHandle, ctypes.c_char_p, ctypes.c_bool], ctypes.c_bool)
  params_put = _bind("params_put", [ParamsHandle, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_bool], ctypes.c_int)
  params_put_bool = _bind("params_put_bool", [ParamsHandle, ctypes.c_char_p, ctypes.c_bool, ctypes.c_bool], ctypes.c_int)
  params_remove = _bind("params_remove", [ParamsHandle, ctypes.c_char_p], ctypes.c_int)
  params_get_path = _bind("params_get_path", [ParamsHandle, ctypes.c_char_p, ctypes.c_size_t], ParamsBuffer)
  params_keys_size = _bind("params_keys_size", [ParamsHandle], ctypes.c_size_t)
  params_key_at = _bind("params_key_at", [ParamsHandle, ctypes.c_size_t], ParamsBuffer)
  params_keys_by_flag = _bind("params_keys_by_flag", [ParamsHandle, ctypes.c_uint, ctypes.POINTER(ParamsBuffer), ctypes.c_size_t], ctypes.c_size_t)

PYTHON_2_CPP = {
  (str, ParamKeyType.STRING): lambda v: v,
  (builtins.bool, ParamKeyType.BOOL): lambda v: "1" if v else "0",
  (int, ParamKeyType.INT): str,
  (float, ParamKeyType.FLOAT): str,
  (datetime.datetime, ParamKeyType.TIME): lambda v: v.isoformat(),
  (dict, ParamKeyType.JSON): json.dumps,
  (list, ParamKeyType.JSON): json.dumps,
  (bytes, ParamKeyType.BYTES): lambda v: v,
}
CPP_2_PYTHON = {
  ParamKeyType.STRING: lambda v: v.decode("utf-8"),
  ParamKeyType.BOOL: lambda v: v == b"1",
  ParamKeyType.INT: int,
  ParamKeyType.FLOAT: float,
  ParamKeyType.TIME: lambda v: datetime.datetime.fromisoformat(v.decode("utf-8")),
  ParamKeyType.JSON: json.loads,
  ParamKeyType.BYTES: lambda v: v,
}

def ensure_bytes(v):
  return v.encode() if isinstance(v, str) else v

def _copy_string(value):
  if value.data is None:
    return None
  return ctypes.string_at(value.data, value.size)

class UnknownKeyName(Exception):
  pass

class Params:
  # mock 全局内存存储
  _mock_store = {}
  def __init__(self, d=""):
    self.d = d
    if lib is not None:
      path = ensure_bytes(d)
      self.p = params_create(path, len(path))
      self._finalizer = weakref.finalize(self, params_destroy, self.p)
      self._finalizer.atexit = False
    else:
      # mock mode, no native handle
      self.p = None

  def __reduce__(self):
    return (type(self), (self.d,))

  def clear_all(self, tx_flag=ParamKeyFlag.ALL):
    if lib is not None:
      params_clear_all(self.p, int(tx_flag))
    else:
      self._mock_store.clear()

  def check_key(self, key):
    key = ensure_bytes(key)
    if b"\0" in key:
      raise UnknownKeyName(key)
    if lib is not None and not params_check_key(self.p, key):
      raise UnknownKeyName(key)
    return key

  def python2cpp(self, proposed_type, expected_type, value, key):
    cast = PYTHON_2_CPP.get((proposed_type, expected_type))
    if cast:
      return cast(value)
    raise TypeError(f"Type mismatch while writing param {key}: {proposed_type=} {expected_type=} {value=}")

  def _cpp2python(self, t, value, default, key):
    if value is None:
      return None
    try:
      return CPP_2_PYTHON[t](value)
    except (KeyError, TypeError, ValueError):
      cloudlog.warning(f"Failed to cast param {key} with {value=} from type {t=}")
      return self._cpp2python(t, default, None, key)

  def _default(self, key):
    if lib is not None:
      return _copy_string(params_get_default(self.p, key))
    return None

  def get(self, key, block=False, return_default=False):
    k = self.check_key(key)
    if lib is not None:
      t = self.get_type(k)
      default = self._default(k) if return_default else None
      value = _copy_string(params_get(self.p, k, block))
      if value == b"":
        if block:
          raise KeyboardInterrupt
        return self._cpp2python(t, default, None, key)
      return self._cpp2python(t, value, default, key)
    else:
      # mock read
      return self._mock_store.get(k.decode(), None)

  def get_bool(self, key, block=False):
    if lib is not None:
      return bool(params_get_bool(self.p, self.check_key(key), block))
    else:
      k = self.check_key(key).decode()
      return bool(self._mock_store.get(k, False))

  def _get_typed(self, key, default, cast, block=False):
    """Coerce a param to `cast`, falling back to `default` for unset/bogus values.

    carrot code ported from cp calls the canonical typed getters
    (`get_int` / `get_float` / `get_str`); this fork's Params only had `get_bool`.
    """
    value = self.get(key, block=block)
    if value is None:
      return cast(default)
    try:
      if isinstance(value, bytes):
        value = value.decode()
      return cast(value)
    except (TypeError, ValueError, AttributeError):
      return cast(default)

  def get_int(self, key, default=0, block=False):
    return self._get_typed(key, default, int, block)

  def get_float(self, key, default=0.0, block=False):
    return self._get_typed(key, default, float, block)

  def get_str(self, key, default="", block=False):
    return self._get_typed(key, default, str, block)

  # 上游 ef4153c74c 在此处新增 get_int/get_float/get_str；本 fork 早在 ab65c63d49 就为
  # 同一缺口落地了上面的 mock 感知版本（多一个可选 block 形参，且先解 bytes 再转 int/float），
  # 语义为上游版的超集 —— 故不再重复定义，避免同名遮蔽（后定义会盖掉 mock 分支）。

  def _put_cast(self, key, dat):
    return ensure_bytes(self.python2cpp(type(dat), self.get_type(key), dat, key))

  def put(self, key, dat, block=False):
    k = self.check_key(key)
    if lib is not None:
      value = self._put_cast(k, dat)
      params_put(self.p, k, value, len(value), block)
    else:
      # mock write
      self._mock_store[k.decode()] = dat

  def put_nonblocking(self, key, dat):
    return self.put(key, dat, block=False)

  def put_bool(self, key, val, block=False):
    if lib is not None:
      params_put_bool(self.p, self.check_key(key), val, block)
    else:
      k = self.check_key(key).decode()
      self._mock_store[k] = bool(val)

  def put_int(self, key, val, block=False):
    self.put(key, int(val), block=block)

  def put_float(self, key, val, block=False):
    self.put(key, float(val), block=block)

  def put_str(self, key, val, block=False):
    self.put(key, str(val), block=block)

  def put_bool_nonblocking(self, key, val):
    self.put_bool(key, val, block=False)

  def put_int_nonblocking(self, key, val):
    self.put_int(key, val, block=False)

  def put_float_nonblocking(self, key, val):
    self.put_float(key, val, block=False)

  def remove(self, key):
    k = self.check_key(key)
    if lib is not None:
      params_remove(self.p, k)
    else:
      k_dec = k.decode()
      if k_dec in self._mock_store:
        del self._mock_store[k_dec]

  def get_param_path(self, key=""):
    key = ensure_bytes(key)
    if lib is not None:
      return _copy_string(params_get_path(self.p, key, len(key))).decode()
    return "/mock/params"

  def get_type(self, key):
    if lib is not None:
      return ParamKeyType(params_get_key_type(self.p, self.check_key(key)))
    # mock default to string
    return ParamKeyType.STRING

  # 上游 5ee2c9f618 的三项参数元数据。stock_value 与 get(key, return_default=True)
  # 的区别：它是键自身的属性，不取决于这个参数是否被写过。返回原始字节（与
  # _copy_string 一致，上游同形），调用方自行按类型解码 —— safe_mode_runtime._stock 就是。
  def get_stock_value(self, key):
    """The value the car shipped with, or the registered default."""
    if lib is not None and params_get_stock is not None:
      return _copy_string(params_get_stock(self.p, self.check_key(key)))
    return None

  def get_tuning_level(self, key):
    """Which tuning level the key belongs to; 0 means it is not a knob."""
    if lib is not None and params_get_tuning_level is not None:
      return params_get_tuning_level(self.p, self.check_key(key))
    return 0

  def get_settings_tier(self, key):
    """Where the key belongs in the settings page (0 simple, 1 advanced)."""
    if lib is not None and params_get_settings_tier is not None:
      return params_get_settings_tier(self.p, self.check_key(key))
    return 1

  def all_keys(self, flag=ParamKeyFlag.ALL):
    if lib is not None:
      if flag == ParamKeyFlag.ALL:
        keys = []
        for i in range(params_keys_size(self.p)):
          keys.append(_copy_string(params_key_at(self.p, i)))
        return keys
      max_keys = 1024
      buf = (ParamsBuffer * max_keys)()
      count = params_keys_by_flag(self.p, int(flag), buf, max_keys)
      return [_copy_string(buf[i]) for i in range(min(count, max_keys))]
    else:
      return [k.encode() for k in self._mock_store.keys()]

  def get_default_value(self, key):
    k = self.check_key(key)
    if lib is not None:
      return self._cpp2python(self.get_type(k), self._default(k), None, key)
    return None

  def cpp2python(self, key, value):
    return self._cpp2python(self.get_type(key), value, None, key)

if __name__ == "__main__":
  import sys
  params = Params()
  key = sys.argv[1]
  params.check_key(key)
  if len(sys.argv) == 3:
    val = sys.argv[2]
    print(f"SET: {key} = {val}")
    params.put(key, val, block=True)
  elif len(sys.argv) == 2:
    print(f"GET: {key} = {params.get(key)}")
