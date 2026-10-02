"""回归测试：Carrot 代码引用到的 param key 必须在 params_keys.h 里注册。

背景（2026-09-19 实机）：
  carrot_functions.py 读 ``AutoCurveSpeedAggressiveness``、carrot_serv.py 写
  ``TimezoneName``/``TimezoneSource``、athenad/carrot_man 写 ``NavDestination``，
  但这 4 个 key 从未在 ``common/params_keys.h`` 注册过（上游 master-c3 也没有）。
  运行期表现为：
    - 裸 Params().put() → UnknownKeyName 抛异常（被 try/except 吞掉 → 功能静默失效）
    - UnifiedParams.get_float() 吞掉 KeyError 后回落到默认 0.0
      → 城市道路曲率速度 * 0.0 → 永远算成 5 km/h
  两者都不会让设备崩溃，所以只能靠这条静态检查兜住。

覆盖范围：carrot 包内所有 .py + Carrot Tuning 设置页（param='Xxx' 那些控件）。
"""
import json
import os
import re
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
CARROT_DIR = os.path.join(REPO, "openpilot", "sunnypilot", "carrot")
CARROT_TUNING_UI = os.path.join(REPO, "openpilot", "selfdrive", "ui", "sunnypilot",
                                "layouts", "settings", "carrot_tuning.py")
PARAMS_KEYS_H = os.path.join(REPO, "openpilot", "common", "params_keys.h")

# Params / UnifiedParams 风格访问：xx.get_bool("Key") / self._params.put("Key") / unified.get_float("Key")
_CALL = re.compile(r'(?:\w*[Pp]aram\w*|unified|self\._unified)\s*\.\s*'
                   r'(?:get|put|get_bool|put_bool|get_int|put_int|get_float|put_float|get_str|put_str)'
                   r'\s*\(\s*["\']([A-Za-z0-9_]+)["\']')
# 设置页控件：option_item_sp(param='Key') / toggle_item_sp(param="Key")
_UI = re.compile(r'\bparam\s*=\s*["\']([A-Za-z0-9_]+)["\']')


def _registered_keys() -> set[str]:
  with open(PARAMS_KEYS_H, encoding="utf-8") as fh:
    return set(re.findall(r'\{\s*"([A-Za-z0-9_]+)"\s*,', fh.read()))


def _nav_defaults() -> dict[str, object]:
  with open(os.path.join(CARROT_DIR, "nav_params.json"), encoding="utf-8") as fh:
    return json.load(fh)


def _referenced_keys() -> dict[str, str]:
  files = [os.path.join(CARROT_DIR, f) for f in sorted(os.listdir(CARROT_DIR)) if f.endswith(".py")]
  files.append(CARROT_TUNING_UI)
  out: dict[str, str] = {}
  for path in files:
    with open(path, encoding="utf-8") as fh:
      text = fh.read()
    for m in list(_CALL.finditer(text)) + list(_UI.finditer(text)):
      key = m.group(1)
      if key[0].isupper():  # param key 约定首字母大写
        out.setdefault(key, os.path.relpath(path, REPO))
  return out


class TestCarrotParamRegistration(unittest.TestCase):
  def test_referenced_params_are_registered(self):
    registered = _registered_keys()
    self.assertGreater(len(registered), 500, "params_keys.h 解析异常")

    missing = {k: v for k, v in _referenced_keys().items() if k not in registered}
    if missing:
      detail = "\n".join(f"  {k:34s} <- {v}" for k, v in sorted(missing.items()))
      self.fail("以下 param key 被 Carrot 代码引用但未在 common/params_keys.h 注册"
                "（运行期会 UnknownKeyName / 静默回落默认值）:\n" + detail)

  def test_curve_speed_params_have_defaults(self):
    """曲率速度四件套必须成对存在（H=高速 / 无后缀=普通道路）。"""
    registered = _registered_keys()
    nav = _nav_defaults()
    for key, default in (("AutoCurveSpeedFactor", 100),
                         ("AutoCurveSpeedAggressiveness", 100),
                         ("AutoCurveSpeedFactorH", 100),
                         ("AutoCurveSpeedAggressivenessH", 100)):
      self.assertIn(key, registered, f"{key} 未在 params_keys.h 注册")
      self.assertEqual(nav.get(key), default, f"nav_params.json 中 {key} 默认值应为 {default}")


if __name__ == "__main__":
  unittest.main()
