#!/usr/bin/env python3
"""Default-off 上游移植项的「上路前 / 上路后」验收助手。

本轮搬进来的功能全部默认关（`VehicleTunesEnabled` / `LeadFollowPolicyEnabled` /
`LeadStopDepartPolicyEnabled` 默认 "0"，`CustomKp` 默认 1.0），不开号等于没数据。
这个脚本把「该开哪个键、开到哪、看什么数、算不算通过」固化成命令，不再靠回忆：

  preflight  键表（params_keys.h）→ 已编译 .so → 当前值，三处对齐检查
  plan       打印验收顺序与判据（一页清单的机读版）
  status     拉 vasm /api/status，跑判据（车道宽门控 + latency 反压）
  set        在 offroad 下写一个开关（onroad 直接拒绝，避免行进中改行为）

退出码：0 全部通过 / 1 有判据失败或键缺失 / 2 用法或前置条件不满足。

判据阈值一律是常量，`--json` 输出便于贴进路试记录。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OP_ROOT = REPO_ROOT / "openpilot"
PARAMS_KEYS = OP_ROOT / "common" / "params_keys.h"
PARAMS_SO = OP_ROOT / "common" / "libparams_c.so"
DEFAULT_STATUS_URL = "http://127.0.0.1:8082/api/status"

# 本树 sunnypilot/carrot/xiaoge/v_asm_server.py
INFERENCE_BACKPRESSURE_FACTOR = 1.15
# c2df04b193 的 600ms 车道推理下限
LANE_INTERVAL_FLOOR_S = 0.6
# 车道宽门控的最小宽度（v_asm_server.VASM_MIN_LANE_WIDTH_METERS）
LANE_WIDTH_MIN_M = 3.0
# bde651b930 之前 offroad 的固定取值，用来判「门控是否还卡在等信号」
WAITING_REASON = "waiting for carState and modelV2"

# 开关 → (默认值, 归属, 一句话说明)
SWITCHES = {
  "CustomKp": ("1.0", "controls/latcontrol_torque.py", "横向 Kp 用户缩放，1.0 = 零影响"),
  "VehicleTunesEnabled": ("0", "controls/vehicle_tune_dispatch.py", "车辆横向调参表；本车 Macan 无表，开与不开等价"),
  "LeadFollowPolicyEnabled": ("0", "controls/longitudinal_planner.py", "非紧急跟车策略"),
  "LeadStopDepartPolicyEnabled": ("0", "controls/longitudinal_planner.py", "stop/depart：视觉接近帽 + 静止起步"),
  "WebPushVapid": (None, "system/athena (PWA)", "Web Push VAPID 键，已回 Params（进备份）"),
  "WebPushSubscriptions": (None, "system/athena (PWA)", "Web Push 订阅表，已回 Params（进备份）"),
}
BOOL_SWITCHES = ("VehicleTunesEnabled", "LeadFollowPolicyEnabled", "LeadStopDepartPolicyEnabled")
FLOAT_SWITCHES = ("CustomKp",)
CUSTOM_KP_RANGE = (0.5, 2.0)

KEY_RE = re.compile(r'\{"(?P<key>\w+)",\s*\{(?P<body>[^}]*)\}\}')
QUOTED_RE = re.compile(r'"(.*)"')


SECRET_KEYS = ("WebPushVapid", "WebPushSubscriptions")


def redact(key: str, value):
  """VAPID 私钥和推送 endpoint 不进日志：只回形状，不回内容。"""
  if key == "WebPushVapid":
    return {"public_key": "<set>", "private_key": "<redacted>"} if isinstance(value, dict) else "<redacted>"
  if key == "WebPushSubscriptions":
    return f"<{len(value)} subscription(s)>" if isinstance(value, list) else "<redacted>"
  return value


def parse_key_defaults(header_text: str) -> dict[str, str | None]:
  """params_keys.h → {键名: 默认值}（无默认值的类型如 JSON 记为 None）。"""
  out: dict[str, str | None] = {}
  for m in KEY_RE.finditer(header_text):
    default = None
    for part in (p.strip() for p in m.group("body").split(",")[1:]):
      dm = QUOTED_RE.fullmatch(part)
      if dm:
        default = dm.group(1)
        break
    out[m.group("key")] = default
  return out


def keys_missing_from_so(so_bytes: bytes, keys) -> list[str]:
  """已编译的 .so 里查不到的键 —— 说明键表没编进库，写进去也读不到（回落默认）。"""
  missing = []
  for key in keys:
    needle = key.encode()
    if needle not in so_bytes:
      missing.append(key)
  return missing


def check_writable(is_offroad: bool) -> tuple[bool, str]:
  if not is_offroad:
    return False, "当前 onroad（IsOffroad=false）：开关只在停車/熄火时改，改完要重启对应进程"
  return True, "offroad，可以写"


def _lane(status: dict) -> dict:
  return status.get("lane") or {}


def _gate(status: dict) -> dict:
  return status.get("gate") or {}


def evaluate_status(status: dict, backpressure: float = INFERENCE_BACKPRESSURE_FACTOR) -> list[dict]:
  """对 /api/status 跑判据。返回 [{check, ok, detail, info}]，info 项不参与判定。"""
  lane, gate = _lane(status), _gate(status)
  latency = (lane.get("inference") or {}).get("latencyMs")
  interval = lane.get("intervalSeconds")
  checks: list[dict] = []

  def add(name: str, ok, detail: str, info: bool = False) -> None:
    checks.append({"check": name, "ok": ok, "detail": detail, "info": info})

  num_interval = isinstance(interval, (int, float))
  add("lane.intervalSeconds >= 0.6", num_interval and interval >= LANE_INTERVAL_FLOOR_S - 1e-9,
      f"intervalSeconds={interval}")
  add("lane.cameraAvailable", lane.get("cameraAvailable") is True,
      f"cameraAvailable={lane.get('cameraAvailable')} cameraError={lane.get('cameraError')!r}")
  add("lane.inference.latencyMs > 0", isinstance(latency, (int, float)) and latency > 0,
      f"latencyMs={latency}")
  if isinstance(latency, (int, float)) and latency > 0 and num_interval:
    floor = round(latency * backpressure / 1000.0, 3)
    add(f"interval >= latency*{backpressure}", interval >= floor - 5e-3,
        f"intervalSeconds={interval} floor={floor}s")
  width = gate.get("laneWidth")
  add("gate.laneWidth > 0", isinstance(width, (int, float)) and width > 0,
      f"laneWidth={width} reason={gate.get('reason')!r}")
  add("gate.reason != waiting", gate.get("reason") != WAITING_REASON,
      f"reason={gate.get('reason')!r}")
  add("gate.laneWidth >= 3.0 m (info)", isinstance(width, (int, float)) and width >= LANE_WIDTH_MIN_M,
      f"laneWidth={width} threshold={LANE_WIDTH_MIN_M}", info=True)
  add("lane.resultFresh (info)", lane.get("resultFresh"),
      f"resultFresh={lane.get('resultFresh')} lastFrameAgeSeconds={lane.get('lastFrameAgeSeconds')}", info=True)
  return checks


def verdict(checks: list[dict]) -> bool:
  return all(c["ok"] for c in checks if not c["info"])


def fetch_status(url: str = DEFAULT_STATUS_URL, timeout: float = 3.0) -> dict:
  with urllib.request.urlopen(url, timeout=timeout) as resp:
    return json.loads(resp.read().decode("utf-8"))


def _params():
  if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
  from openpilot.common.params import Params  # 延迟导入，测试不需要它
  return Params()


def read_param(params, key: str):
  try:
    return params.get(key)
  except Exception as exc:  # 旧 .so 不认识这个键时会抛 UnknownKeyName
    return f"<{type(exc).__name__}: {exc}>"


def normalize_value(key: str, raw: str) -> str:
  if key in BOOL_SWITCHES:
    low = raw.strip().lower()
    if low in ("1", "true", "on", "yes"):
      return "1"
    if low in ("0", "false", "off", "no"):
      return "0"
    raise ValueError(f"{key} 只接受 0/1/true/false，收到 {raw!r}")
  if key in FLOAT_SWITCHES:
    val = float(raw)
    lo, hi = CUSTOM_KP_RANGE
    if not lo <= val <= hi:
      raise ValueError(f"{key} 只接受 {lo}..{hi}（车安全，越界无意义），收到 {val}")
    return f"{val:.2f}"
  return raw


def plan_lines() -> list[str]:
  return [
    "第 0 步  preflight：三个新键必须在 libparams_c.so 里，否则写了也读不到",
    "第 1 步  LeadStopDepartPolicyEnabled=1 跑一段 stop-and-go；判据见 simulate_lead_stop_depart.py 基线",
    "         （depart 3.70s / 最小间距 4.50m 五场景），上车看：起步时刻、停稳距离、无油门迟滞",
    "第 2 步  稳住后叠加 LeadFollowPolicyEnabled=1；判据：跟车间距不抖、切入不点头、松油更线性",
    "第 3 步  同一次路试顺带验 bde651b930 车道宽门控：roadtest_verify.py status 六条判定全绿",
    "第 4 步  CustomKp 只在需要时抬（1.0 是零影响）；Developer 页 Steering Kp Scale 50..200",
    "第 5 步  Web Push 手机侧要 https（cloudflared 域名）才注册 SW，http 只验页面可达",
    "不在本轮：A 批 latcontrol_torque 钩子（Macan 无调参表，死代码）；FLM/视觉限速两条 eval",
  ]


def cmd_preflight(args) -> int:
  header = PARAMS_KEYS.read_text(encoding="utf-8") if PARAMS_KEYS.exists() else ""
  defaults = parse_key_defaults(header)
  so_bytes = PARAMS_SO.read_bytes() if PARAMS_SO.exists() else b""
  missing_in_header = [k for k in SWITCHES if k not in defaults]
  missing_in_so = keys_missing_from_so(so_bytes, [k for k in SWITCHES if k in defaults])
  params = _params()
  current = {k: redact(k, read_param(params, k)) for k in SWITCHES}

  print(f"params_keys.h : {PARAMS_KEYS} ({'ok' if header else 'MISSING'})")
  print(f"libparams_c.so: {PARAMS_SO} ({len(so_bytes)} bytes)")
  print(f"{'key':28} {'default':10} {'in .so':7} current")
  for key, (_default, _owner, _why) in SWITCHES.items():
    built = "no" if key in missing_in_so else "yes"
    print(f"{key:28} {str(defaults.get(key)):10} {built:7} {current[key]!r}")
  if missing_in_header:
    print(f"\n[FAIL] params_keys.h 里没有：{', '.join(missing_in_header)}")
  if missing_in_so:
    print(f"\n[FAIL] 已编译 .so 里没有：{', '.join(missing_in_so)} → 需要重建 libparams_c.so")
  if missing_in_header or missing_in_so:
    return 1
  print("\n[OK] 六个键在键表和 .so 里都在，写进去读得到")
  return 0


def cmd_plan(args) -> int:
  for line in plan_lines():
    print(line)
  return 0


def cmd_status(args) -> int:
  try:
    status = fetch_status(args.url, args.timeout)
  except (urllib.error.URLError, TimeoutError, OSError) as exc:
    print(f"[FAIL] 拉不到 {args.url}：{exc}（车机 offroad 时 vasm 可能没起）", file=sys.stderr)
    return 1
  checks = evaluate_status(status)
  if args.json:
    print(json.dumps({"ok": verdict(checks), "checks": checks}, ensure_ascii=False, indent=2))
  else:
    for c in checks:
      tag = "info" if c["info"] else ("PASS" if c["ok"] else "FAIL")
      print(f"[{tag:4}] {c['check']:34} {c['detail']}")
    print(f"\n{'PASS' if verdict(checks) else 'FAIL'} 车道宽门控 + latency 反压")
  return 0 if verdict(checks) else 1


def cmd_set(args) -> int:
  if args.key not in SWITCHES:
    print(f"未知键 {args.key}；可选：{', '.join(SWITCHES)}", file=sys.stderr)
    return 2
  try:
    value = normalize_value(args.key, args.value)
  except ValueError as exc:
    print(str(exc), file=sys.stderr)
    return 2
  params = _params()
  ok, why = check_writable(bool(params.get_bool("IsOffroad")))
  print(f"{args.key} -> {value}  ({why})")
  if not ok:
    return 2
  params.put(args.key, value)
  print(f"读回：{redact(args.key, read_param(params, args.key))!r}；重启对应进程/整机后生效")
  return 0


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  sub = parser.add_subparsers(dest="cmd", required=True)
  sub.add_parser("preflight", help="键表 × .so × 当前值 三处对齐").set_defaults(func=cmd_preflight)
  sub.add_parser("plan", help="打印验收顺序与判据").set_defaults(func=cmd_plan)
  p_status = sub.add_parser("status", help="拉 vasm /api/status 跑判据")
  p_status.add_argument("--url", default=DEFAULT_STATUS_URL)
  p_status.add_argument("--timeout", type=float, default=3.0)
  p_status.add_argument("--json", action="store_true")
  p_status.set_defaults(func=cmd_status)
  p_set = sub.add_parser("set", help="offroad 下写开关")
  p_set.add_argument("key")
  p_set.add_argument("value")
  p_set.set_defaults(func=cmd_set)
  return parser


def main(argv=None) -> int:
  args = build_parser().parse_args(argv)
  return args.func(args)


if __name__ == "__main__":
  sys.exit(main())
