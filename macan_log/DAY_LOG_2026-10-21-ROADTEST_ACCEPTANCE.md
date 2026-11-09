# 路试验收一页纸（2026-10-21）

本轮搬进来的上游功能**全部默认关**（三个 BOOL 默认 `"0"`，`CustomKp` 默认 1.0）：
不开号等于没数据，开了也要有判据才叫验收。这一页是「下次路试一次跑完」的清单，
配套可执行判据 `scripts/roadtest_verify.py`（+ 20 条单测）。

## 0. 前置：键必须在已编译的 .so 里

写进 Params 但库不认识 = 静默回落默认值（车安全，但功能等于没开）。

```
/usr/local/venv/bin/python3 scripts/roadtest_verify.py preflight
```

本轮实测（2026-10-21 07:56 重建后，`libparams_c.so` 2872216 bytes）：

| 键 | 默认 | 在 .so | 当前值 |
|---|---|---|---|
| `CustomKp` | 1.0 | yes | 1.0 |
| `VehicleTunesEnabled` | 0 | yes | False |
| `LeadFollowPolicyEnabled` | 0 | yes | False |
| `LeadStopDepartPolicyEnabled` | 0 | yes | False |
| `WebPushVapid` | (JSON) | yes | 公钥已设（私钥已脱敏，不回显） |
| `WebPushSubscriptions` | (JSON) | yes | 2 条订阅 |

`preflight` 退出码非 0 就**别上路**——先重建 `libparams_c.so`（单目标、`-j1`，
`SConstruct` 已把 `params.cc` 钉在低优化级别，避免整机 scons 的内存尖峰）。

## 1. 先只开 stop/depart，跑一段 stop-and-go

```
scripts/roadtest_verify.py set LeadStopDepartPolicyEnabled 1     # 只在 offroad 生效
```

判据（对照仿真基线，改前先重跑一次确认基线没漂）：

```
PYTHONPATH=/data/openpilot /usr/local/venv/bin/python3 scripts/simulate_lead_stop_depart.py
# 期望 5/5 PASS；基线 depart ≈ 3.70 s、最小间距 ≈ 4.50 m
```

车上要看的四件事：起步时刻不早于前车真的动、停稳距离不变短、松刹车到动不再有迟滞、
低速蠕行不点头。任一条不对 → `set ... 0` 回滚，不要带着凑。

## 2. 稳了再叠加跟车策略

```
scripts/roadtest_verify.py set LeadFollowPolicyEnabled 1
```

判据：跟车间距不抖（无明显 push-pull）、有车切入不点头、松油更线性但不变肉。
两条一起开若出问题，先关这条分辨归属，不要同时回滚两条。

## 3. 同一次路试顺带验车道宽门控 + latency 反压（`bde651b930`）

```
scripts/roadtest_verify.py status          # 拉 http://127.0.0.1:8082/api/status
scripts/roadtest_verify.py status --json   # 贴进路试记录
```

六条判定 + 两条 `info`（`info` 不参与判定）：

| 判据 | 通过条件 |
|---|---|
| `lane.intervalSeconds >= 0.6` | c2df04b193 的 600 ms 下限生效 |
| `lane.cameraAvailable` | camerad 供图（false 说明根本没起） |
| `lane.inference.latencyMs > 0` | 车道推理在跑 |
| `interval >= latency*1.15` | 反压地板：间隔随延迟抬，不是写死 0.6 |
| `gate.laneWidth > 0` | **`bde651b930` 的 meta 车道宽已填** |
| `gate.reason != waiting` | 不再卡在 `waiting for carState and modelV2` |
| info: `laneWidth >= 3.0` / `resultFresh` | 只记录，不判定（无车道时合法） |

offroad 基线是 `laneWidth=0.0` / `reason=waiting...` / `cameraAvailable=false`，
所以**offroad 现在跑 `status` 就是 FAIL**（本轮实测 rc=1，cameraError 明写
`road camera is unavailable; start openpilot/camerad first`） —— 那是判据有区分力，不是坏了。

## 4. `CustomKp` 只在需要时抬

默认 1.0 = 零影响；UI 在 Developer 页 `Steering Kp Scale`（50..200 → 0.50..2.00）。
只在「横摆偏软/偏硬」被明确记录时才动，动一次记一次值，不要和上面两步同轮改。

## 5. PWA Web Push 手机侧

`http://<lan-ip>:7000/push` 只验页面可达（非安全上下文浏览器不注册 SW，页面会黄字提示）；
真收推送要 https（cloudflared 隧道域名）→ 开启通知 → 发送测试通知。
两个键已从 `/data/carrot/state/web_push.json` 搬回 Params，现在进 Params 备份。

## 回滚

```
scripts/roadtest_verify.py set LeadFollowPolicyEnabled 0
scripts/roadtest_verify.py set LeadStopDepartPolicyEnabled 0
scripts/roadtest_verify.py set VehicleTunesEnabled 0
scripts/roadtest_verify.py set CustomKp 1.0
```

三个 BOOL 关闭时 planner 整段空操作（`test_longitudinal_policy_hooks` 有顺序断言），
`CustomKp=1.0` 时 Kp 缩放是恒等；回滚后无需重建任何库。

## 本轮不验收

- **A 批 `latcontrol_torque.py` 钩子**（`VehicleTunesEnabled`）：本车
  `resolve_vehicle_tune(PORSCHE_MACAN) -> None`，接了也是死代码，且与
  `44a32ec77c` / `2d9c586376` 同文件冲突。
- 登记表剩 3 条全为 eval：`982fb613f5`（FLM 分析器）/ `d81eec5899`（视觉限速，
  ~22 MB onnx）/ `077456330f`（纯登记键，随前两条走）。

## 离车已验（今天重跑，全绿）

| 项 | 结果 |
|---|---|
| `scripts.test_roadtest_verify` | 20 passed |
| `test_longitudinal_policy_hooks` + `test_latcontrol_custom_kp` | 8 passed |
| `test_lead_stop_depart_policy` + `test_lead_follow_policy` + `test_vehicle_tune_dispatch` | 41 passed |
| `system.tests.test_launch_boot_bootstrap` | 8 passed, 1 skipped（aiohttp 探针不可复现，预期） |

已知偏差：`selfdrive/controls/tests/test_leads.py` 是 process replay，离车 60 s 跑不完，
与本轮改动无关。
