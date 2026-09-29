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
import ast
import json
import os
import re
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
CARROT_DIR = os.path.join(REPO, "openpilot", "sunnypilot", "carrot")
CARROT_TUNING_UI = os.path.join(REPO, "openpilot", "selfdrive", "ui", "sunnypilot",
                                "layouts", "settings", "carrot_tuning.py")
PARAMS_KEYS_H = os.path.join(REPO, "openpilot", "common", "params_keys.h")

# 上游删除、fork 仍需做一次性迁移/清理的遗留 key。允许被引用，但每一次引用都必须包在
# try/except UnknownKeyName 里（见下面的 test_retired_keys_are_only_touched_inside_guards）：
# 这些 key 已不在 params_keys.h，新版 libparams 的 check_key() 会直接抛 UnknownKeyName，
# 裸读会让 CarrotManager.__init__ 抛异常 → manager 无限重启 carrot_man。
# AmapEnabled / AmapMapDataEnabled 随上游 "Amap Web hard removal" (d5de54392c) 一起删除，
# carrot_man._migrate_amap_enabled() 是唯一还认它们的迁移垫片，迁移完成后会 remove() 掉。
LEGACY_RETIRED_KEYS: frozenset[str] = frozenset({"AmapEnabled", "AmapMapDataEnabled"})

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

    missing = {k: v for k, v in _referenced_keys().items()
               if k not in registered and k not in LEGACY_RETIRED_KEYS}
    if missing:
      detail = "\n".join(f"  {k:34s} <- {v}" for k, v in sorted(missing.items()))
      self.fail("以下 param key 被 Carrot 代码引用但未在 common/params_keys.h 注册"
                "（运行期会 UnknownKeyName / 静默回落默认值）:\n" + detail)

  def test_retired_keys_are_only_touched_inside_guards(self):
    """LEGACY_RETIRED_KEYS 的豁免不是白名单：每次访问都必须在 try/except UnknownKeyName 内。

    否则豁免会把上面那条检查架空——一个裸 ``params.get_bool("AmapEnabled")`` 在新版
    libparams 上就是 CarrotManager.__init__ 抛异常 + manager 无限重启 carrot_man。
    两种安全写法都认：
      1. 直接把遗留 key 字面量传给 Params 方法，且整句在 try/except UnknownKeyName 内；
      2. ``for key in ("AmapEnabled", ...)`` 这种循环，循环体里有 try/except UnknownKeyName
         （carrot_man._migrate_amap_enabled 的写法：一个 key 缺失不能拖累另一个 key）。
    """
    param_methods = {"get", "put", "get_bool", "put_bool", "get_int", "put_int", "get_float",
                     "put_float", "get_str", "put_str", "remove", "check_key", "get_type"}
    offenders: list[str] = []

    for path in [os.path.join(CARROT_DIR, f) for f in sorted(os.listdir(CARROT_DIR)) if f.endswith(".py")]:
      with open(path, encoding="utf-8") as fh:
        text = fh.read()
      if not any(k in text for k in LEGACY_RETIRED_KEYS):
        continue
      tree = ast.parse(text)
      rel = os.path.relpath(path, REPO)

      # Nodes sitting inside a Try that catches UnknownKeyName are considered guarded.
      guarded: set[int] = set()
      for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(isinstance(h.type, ast.Name) and h.type.id == "UnknownKeyName"
                                             for h in node.handlers):
          for sub in ast.walk(node):
            guarded.add(id(sub))

      def _is_retired_str(node: ast.AST) -> bool:
        return isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in LEGACY_RETIRED_KEYS

      # (1) bare literal handed to a Params-style call
      for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
          continue
        if call.func.attr not in param_methods:
          continue
        args = list(call.args) + [kw.value for kw in call.keywords]
        if any(_is_retired_str(a) for a in args) and id(call) not in guarded:
          offenders.append(f"  {rel}:{call.lineno} bare params.{call.func.attr}(...) on a retired key")

      # (2) retired literal in a loop iterable whose body has no UnknownKeyName guard
      for node in ast.walk(tree):
        if not isinstance(node, ast.For):
          continue
        iters = node.iter.elts if isinstance(node.iter, (ast.Tuple, ast.List, ast.Set)) else [node.iter]
        if not any(_is_retired_str(i) for i in iters):
          continue
        body_guarded = any(isinstance(sub, ast.Try) and any(
          isinstance(h.type, ast.Name) and h.type.id == "UnknownKeyName" for h in sub.handlers)
          for sub in ast.walk(node))
        if not body_guarded:
          offenders.append(f"  {rel}:{node.lineno} loops over a retired key without an UnknownKeyName guard")

    if offenders:
      self.fail("以下遗留 key 的访问没有 try/except UnknownKeyName 保护"
                "（新版 libparams 会抛 UnknownKeyName，裸访问会让 carrot_man 反复重启）:\n"
                + "\n".join(offenders))

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
