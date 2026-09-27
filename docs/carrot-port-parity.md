# Carrot 端口服务：cp ↔ sp 逐项对照与补齐计划

目标：把 CarrotPilot（`E:/cp`）提供的**全部端口服务**在本仓库补齐，且**统一由 sunnypilot
自己的控制链路承担**（`Params` 单一事实源 + cereal 取实时数据 + `CarrotServ` 单一入口 +
manager 托管进程），而不是在 fork 里再长出一套并行控制面。

数据来源：`E:/cp/openpilot/selfdrive/carrot` 静态扫描 + 设备实测（2026-09-27）。

## 1. 端口总表

| 端口 | 协议 | 用途 | cp | sp | 备注 |
|---|---|---|---|---|---|
| 7705 | UDP 出 | 设备发现广播 | ✅ | ✅ | 已实测在发（carrot_man + carrot_navi 双源） |
| 7706 | UDP | 导航数据上行 + 监听 | ✅ | ✅ | |
| 7709 | TCP | 路线点 | ✅ | ✅ | |
| 7710 | ZMQ | 远程控制命令 | ✅ | ✅ | `carrot_man` `bind tcp://*:7710` |
| 7711 | TCP | xiaoge 车辆/模型数据 | ✅ | ✅ | `xiaoge_data` |
| 7713 | HTTP | navi 侧信道 / sinf | ✅ | ✅ | |
| 7714 | TCP/WS | v2 navi | ✅ | ✅ | |
| 12345 | UDP | kisa 限速直写 | ✅ | ✅ | `carrot_man._kisa_port` |
| **7000** | HTTP + WS | **API 服务器（App 主通道）** | ✅ | **阶段 1 完成** | 参数 REST 已可用；`/ws/*` 待补 |
| **6999** | WS + PTY | recovery 支持终端 | ✅ | ❌ | `recovery/server.py` 2,563 行 |
| 8082 | HTTP | xiaoge V-ASM 页面 | ✅(外部) | ✅(V-ASM) | ⚠️ 端点不同：缺 `/store_toggle_values` |
| 8088 | HTTP | 本 fork 自有 nav 参数面板 | — | ✅ | fork 独有，非 cp 端口 |

## 2. 7000 的路由面（cp 135 条，33 个文件，约 30,379 行）

| 文件 | 路由 | 归属 |
|---|---|---|
| `features/dashcam/*`（routes/replay/catalog/upload/…） | 30+ | 行车记录仪（回放、预览、下载、上传） |
| `features/params.py` | 13 | **参数 REST（已移植核心）** |
| `features/system.py` | 10 | 设备信息、网络、心跳、标定状态 |
| `features/support_terminal.py` + `services/support_terminal.py` | 13 | 支持终端（与 6999 配合） |
| `features/tools/*` | 17 | 工具页（git 状态、任务、设备信息） |
| `features/youtube_live*.py`（5 个文件） | 40+ | YouTube 直播（含 H264/FLV/RTMP/字幕） |
| `features/terminal.py` | 6 | 终端命令桥 |
| `features/setting_*(profiles/popular_values/favorites/unit_index/web_settings)` | 17 | 设置档案与目录 |
| `features/ws.py` | 4 | **`/ws/raw`、`/ws/raw_multiplex`、`/ws/compact_state`、`/ws/camera/{camera}`** |
| `features/carrot_navi/*` | 5 | v2 navi 桥与诊断 |
| `features/{mapbox_tokens,screenrecord,egpu_model,bluetooth,ssh_keys,vision_*,xiaoge,cars,static,stream}` | 20+ | 其余功能页 |

配套：`realtime/` 1,610 行（8 个 py，含 C++/Cython 的 compact state）、`recovery/` 2,563 行。

**App（navipilot）实际只用 4 个端点**：
`WS /ws/raw_multiplex?services=`、`WS /ws/camera/road`、`POST /api/param_set`、`GET /api/params_bulk`
（另有 `POST http://<ip>:8082/store_toggle_values` 下发设置）。

## 3. 阶段计划

| 阶段 | 内容 | 状态 |
|---|---|---|
| **1** | `server/` 骨架 + `/api/param_set` `/api/params_bulk` `/api/health` + 托管进程 `carrot_server` | ✅ 完成（24 tests，设备端到端实测通过） |
| 2 | `/ws/raw_multiplex`（cp `realtime/raw_protocol.py` 37 + `raw_services.py` 45 + `transports/raw_ws.py` 325 + `features/ws.py` 99） | 待做 |
| 3 | `/ws/camera/{camera}`（`realtime/transports/camera_ws.py` 471） | 待做 |
| 4 | `/ws/compact_state` 及原生部分（652 + C++/Cython） | 待做 |
| 5 | `features/system.py` + `features/cars.py` + `features/settings.py` 等只读设备/设置接口 | 待做 |
| 6 | dashcam / terminal / tools / youtube_live / support_terminal / recovery(6999) | 待评估（体量大、与 App 主链无关） |
| 7 | 8082 补 `POST /store_toggle_values` | 待做（小） |

## 4. 统一控制原则（所有阶段共同遵守）

1. **状态只经 `Params`**：写参数一律用 `Params.put`，并在写前用 `Params.get_type()` 把
   值强制成声明类型——`put` 对类型不符是**抛 TypeError**，不是隐式转换（`OnroadUploads`
   那次就是这样踩到的）。写错类型返回 400 并带可读原因，绝不放成 500。
2. **实时数据只读 cereal**：WebSocket 流以 `SubMaster` 订阅现有服务，不新造数据面。
3. **不新增控制入口**：任何要改车行为的动作，最终都落到 `CarrotServ.update_raw` /
   `card.py` 单点写入，保持 `carState` 单写入者。
4. **进程由 manager 托管**：`carrot_server` 注册为 `always_run`（`enabled=not
   CARROT_WEB_EXTERNAL`），崩溃可见、可回滚，不自己 daemon 化。
5. **核心可离线测试**：`services/params.py` 不导入原生 params（按类型名分派、`UnknownKeyName`
   有兜底），因此纯函数部分在任何机器都能跑；HTTP 层用 aiohttp test_utils 端到端跑。

## 5. 阶段 1 的实测证据（设备 192.168.2.246）

```
LISTEN 0 128 0.0.0.0:7000
GET  /api/health        -> {"ok": true, "status": "ok"}
GET  /api/params_bulk?names=IsMetric,CarrotEnabled,DefinitelyNotAKey
                        -> {"ok": true, "values": {"IsMetric": true, "CarrotEnabled": true, "DefinitelyNotAKey": null}}
POST /api/param_set {"name":"IsMetric","value":"oops"}
                        -> 400 {"ok": false, "error": "cannot read 'oops' as a boolean"}
POST /api/param_set {"name":"OnroadUploads","value":0}
                        -> {"ok": true, "name": "OnroadUploads", "value": false}
POST /api/param_set {"name":"CarParams","value":"x"}
                        -> 400 {"ok": false, "error": "CarParams is written by the device and is read-only over the API"}
POST /api/param_set {"name":"NopeKey","value":1}
                        -> 400 {"ok": false, "error": "unknown parameter NopeKey"}
```

单测：本地 18 通过 / 6 跳过（缺 aiohttp 与原生 params）；设备上 **24/24 通过**（含 6 项真实
aiohttp + 真实 Params 的端到端）。

> 注意：设备上跑这些测试要用 launcher 的真实 `PYTHONPATH`
> （`/data/openpilot:/usr/local/venv/lib/python3.12/site-packages:/data/.pydeps`），
> 否则 aiohttp 不在路径里、6 项会被静默跳过。
