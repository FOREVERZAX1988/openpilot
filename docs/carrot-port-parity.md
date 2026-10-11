# Carrot 端口服务：cp ↔ sp 逐项对照与补齐计划

目标：把 CarrotPilot（`E:/cp`）提供的**全部端口服务**在本仓库补齐，且**统一由 sunnypilot
  
自己的控制链路承担**（`Params` 单一事实源 + cereal 取实时数据 + `CarrotServ` 单一入口 +
  
manager 托管进程），而不是在 fork 里再长出一套并行控制面。

数据来源：`E:/cp/openpilot/selfdrive/carrot` 静态扫描 + 设备实测（2026-09-27）。

## 1. 端口总表

| 端口       | 协议        | 用途                   | cp    | sp          | 备注                                 |
| -------- | --------- | -------------------- | ----- | ----------- | ---------------------------------- |
| 7705     | UDP 出     | 设备发现广播               | ✅     | ✅           | 已实测在发（carrot_man + carrot_navi 双源） |
| 7706     | UDP       | 导航数据上行 + 监听          | ✅     | ✅           |                                    |
| 7709     | TCP       | 路线点                  | ✅     | ✅           |                                    |
| 7710     | ZMQ       | 远程控制命令               | ✅     | ✅           | `carrot_man` `bind tcp://*:7710`   |
| 7711     | TCP       | xiaoge 车辆/模型数据       | ✅     | ✅           | `xiaoge_data`                      |
| 7713     | HTTP      | navi 侧信道 / sinf      | ✅     | ✅           |                                    |
| 7714     | TCP/WS    | v2 navi              | ✅     | ✅           |                                    |
| 12345    | UDP       | kisa 限速直写            | ✅     | ✅           | `carrot_man._kisa_port`            |
| **7000** | HTTP + WS | **API 服务器（App 主通道）** | ✅     | **阶段 1 完成** | 参数 REST 已可用；`/ws/*` 待补             |
| **6999** | WS + PTY  | recovery 支持终端        | ✅     | ❌           | `recovery/server.py` 2,563 行       |
| 8082     | HTTP      | xiaoge V-ASM 页面      | ✅(外部) | ✅(V-ASM)    | ⚠️ 端点不同：缺 `/store_toggle_values`   |
| 8088     | HTTP      | 本 fork 自有 nav 参数面板   | —     | ✅           | fork 独有，非 cp 端口                    |

## 2. 7000 的路由面（cp 135 条，33 个文件，约 30,379 行）

| 文件                                                                                                       | 路由  | 归属                                                                          |
| -------------------------------------------------------------------------------------------------------- | --- | --------------------------------------------------------------------------- |
| `features/dashcam/*`（routes/replay/catalog/upload/…）                                                     | 30+ | 行车记录仪（回放、预览、下载、上传）                                                          |
| `features/params.py`                                                                                     | 13  | **参数 REST（已移植核心）**                                                          |
| `features/system.py`                                                                                     | 10  | 设备信息、网络、心跳、标定状态                                                             |
| `features/support_terminal.py` + `services/support_terminal.py`                                          | 13  | 支持终端（与 6999 配合）                                                             |
| `features/tools/*`                                                                                       | 17  | 工具页（git 状态、任务、设备信息）                                                         |
| `features/youtube_live*.py`（5 个文件）                                                                       | 40+ | YouTube 直播（含 H264/FLV/RTMP/字幕）                                              |
| `features/terminal.py`                                                                                   | 6   | 终端命令桥                                                                       |
| `features/setting_*(profiles/popular_values/favorites/unit_index/web_settings)`                          | 17  | 设置档案与目录                                                                     |
| `features/ws.py`                                                                                         | 4   | **`/ws/raw`、`/ws/raw_multiplex`、`/ws/compact_state`、`/ws/camera/{camera}`** |
| `features/carrot_navi/*`                                                                                 | 5   | v2 navi 桥与诊断                                                                |
| `features/{mapbox_tokens,screenrecord,egpu_model,bluetooth,ssh_keys,vision_*,xiaoge,cars,static,stream}` | 20+ | 其余功能页                                                                       |

配套：`realtime/` 1,610 行（8 个 py，含 C++/Cython 的 compact state）、`recovery/` 2,563 行。

**App（navipilot）实际只用 4 个端点**：
  
`WS /ws/raw_multiplex?services=`、`WS /ws/camera/road`、`POST /api/param_set`、`GET /api/params_bulk`
  
（另有 `POST http://<ip>:8082/store_toggle_values` 下发设置）。

## 3. 阶段计划

| 阶段    | 内容                                                                                                                              | 状态                                                                                        |
| ----- | ------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| **1** | `server/` 骨架 + `/api/param_set` `/api/params_bulk` `/api/health` + 托管进程 `carrot_server`                                         | ✅ 完成（24 tests，设备端到端实测通过）                                                                  |
| 2     | `/ws/raw_multiplex`（cp `realtime/raw_protocol.py` 37 + `raw_services.py` 45 + `transports/raw_ws.py` 325 + `features/ws.py` 99） | ✅ 完成（`features/ws.py` + `services/raw_protocol.py` / `raw_services.py` / `raw_relay.py`）  |
| 3     | `/ws/camera/{camera}`（`realtime/transports/camera_ws.py` 471）                                                                   | ✅ 完成（`features/camera.py` + `services/camera_relay.py`）                                   |
| 4     | `/ws/compact_state` 及原生部分（652 + C++/Cython）                                                                                     | ❌ 有意不实现：cp 的紧凑二进制 HUD 协议无 cereal 对应，猜一个会给出解码成错误数字的流；由 `features/unsupported.py` 回 501     |
| 5     | `features/system.py` + `features/cars.py` + `features/settings.py` 等只读设备/设置接口                                                   | ✅ 完成（`features/system.py` 9 路由、`cars.py`、`settings.py`、`preferences.py`、`credentials.py`） |
| 6     | dashcam / terminal / tools / youtube_live / support_terminal / recovery(6999)                                                   | ⏸️ 有意不实现，见 `features/unsupported.py` 的逐项理由（媒体子系统/无鉴权远程 shell/云直播）                         |
| 7     | 8082 补 `POST /store_toggle_values`                                                                                              | ✅ 完成（`VASMService.store_toggle_values` + v_asm_server 路由）                                 |

> 2026-09-28 复核：设备实测 7000/7706/7709/7710/7711/7712/7713/7714/12345/8082 全部在监听，
>   
> 7705 广播正常发出。6999 与 8088 不在监听属预期（前者有意不实现，后者是 sp 自有面板未启用）。

## 3.1 明确不实现清单（有意为之，不是遗漏）

| 项                                                 | 理由                                           |
| ------------------------------------------------- | -------------------------------------------- |
| `/ws/compact_state`                               | Carrot Vision 的字节打包 HUD 协议在 sp 无对应 cereal 消息 |
| dashcam / screenrecord / replay                   | ~30 文件 ffmpeg 媒体子系统；sp 已有自己的路线存储与回放          |
| terminal / support_terminal                       | 7000 上的无鉴权远程 shell，同网段任何设备可执行车辆控制机上的命令       |
| youtube_live / vision_diag / vision_test          | 云直播与 Carrot Vision 上传/测试台                    |
| `/ws/carrot_navi/media`、`/stream`、`/ws/web_sound` | cp 自有 web HUD 的 fMP4/声音通道，sp 不跑该 HUD         |
| 6999 recovery 服务                                  | cp 的独立 PTY recovery 终端（2,563 行），同样是无鉴权 shell |

以上均由 `features/unsupported.py` 注册为 501（而不是留 404），让客户端能区分
  
「本 fork 较旧」与「URL 写错了」。

## 3.2 cereal 模式差异（已知，需谨慎）

| 字段                                         | cp                        | sp                                       | 影响                                                                 |
| ------------------------------------------ | ------------------------- | ---------------------------------------- | ------------------------------------------------------------------ |
| `CarState.leftLatDist`                     | `@69`，hyundai carstate 写入 | **不存在**（sp 的 `@69` 是 `vehicleNaviSpeed`） | `xiaoge_data.collect_car_state` 用 `getattr(..., 0.0)` 兜底，不会崩；值恒为 0 |
| `ModelDataV2.MetaData.laneWidthLeft/Right` | 存在                        | **不存在**                                  | `xiaoge_vision.lane_width_meters` 已做容错；直接读会 AttributeError         |

补齐 `leftLatDist` 需要一个新的 ordinal（不能用 69），并同步 hyundai carstate 与
  
capnp 生成代码；属 schema 变更，需设备侧重新生成后再验证。

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
>   
> （`/data/openpilot:/usr/local/venv/lib/python3.12/site-packages:/data/.pydeps`），
>   
> 否则 aiohttp 不在路径里、6 项会被静默跳过。

---

## 6. 7000 的 web 面板（cp `web/`）：为什么现在是 8088，以及能否照搬

> 2026-10-11 补。回答「cp 的面板不是 7000 吗，为什么我们是 8088；现在 7000 只回 JSON，
>   
> 能不能直接照搬 cp 的 7000」。基准：cp = `E:/cp`（`carrot-wip`），sp = `E:/sp`（`test`）。

### 6.1 为什么 sp 是 8088 而不是 7000（根因）

三件事各归各位，不是端口写错：

| 事实                                      | 证据                                                                                                                                                                                                                                                                                   |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| cp 的面板就是 7000，**面板与 API 同一进程**          | cp `server/app.py::make_app()` 末尾 `app.router.add_static("/", str(WEB_DIR), show_index=True)`，`WEB_DIR` = `selfdrive/carrot/web`；cp `selfdrive/ui/carrot_web.py:10` `CARROT_WEB_PORT = 7000`（UI 用二维码指向它）                                                                             |
| sp 只移植了 7000 的 **API 层**，前端 `web/` 从未移植 | sp `server/app.py::create_app()` 里没有任何 `add_static`，`/` 由 `_index()` 回一份 JSON 路由清单。本文档第 3 节的阶段 1–7 **全部是 API**，没有一项是 web 前端                                                                                                                                                          |
| sp 另建 8088 作为自己的面板，并把 UI 二维码改指 8088     | sp `selfdrive/ui/carrot_web.py:10` `CARROT_WEB_PORT = 8088  # matches CarrotWebEnabled's documented port`；`sunnypilot/carrot/web_interface.py`（stdlib `ThreadingHTTPServer`）由 `carrot_man.py:1295` 启动，受 `CarrotWebEnabled` 门控（默认 `"0"`）；`carrot_tuning.py:163` 的文案写的是 "on port 8088" |

补充：sp 的完整 web UI 在 **5080**（`webui/` 子模块，`launch_chffrplus.sh:781`
  
`keep_alive webui webui/webuid.py 5080`，镜像大 UI 20 面板 + 18 子面板）。所以 sp 的分工是
  
**7000 = App 的 JSON API / 8088 = carrot 小面板 / 5080 = 大 UI 镜像**；cp 只有 7000 一个。

⚠️ `openpilot/sunnypilot/carrot/README.md` 目前把 7000 整条列在「Not present」表里，**已过期**：
  
`server/` 早已移植（sp 31 文件 / 5,399 行；cp 135 文件 / 27,499 行），且 `process_config.py:322`
  
已托管 `carrot_server` 进程。**只有 `web/` 确实没有。**

### 6.2 「直接照搬」的可行性：静态层可以，页面级不行

**静态层（`web/` 目录）—— 可搬，成本低**

- `web/` = 566 文件 / 9.2 MB。`web/js/`、`web/css/` 的**构建产物已入库**：`web/.gitignore` 明写
    
  *"Generated browser bundles are committed because the device serves this source tree directly
    
  and does not run Node at startup"* → **设备端不需要 Node**。
- `index.html` 的 87 个绝对引用只落在 `/js`、`/css`、`/assets` 三个前缀，全在 `web/` 树内 →
    
  `add_static("/", WEB_DIR)` 一条即可覆盖首屏。
- 落地所需：`server/config.py` 加 `WEB_DIR`（`SELFDRIVE_ASSETS_DIR` 对应的 `selfdrive/assets` sp 已有）、
    
  `create_app()` 末尾加 `add_static("/shared-assets/", …)` + `add_static("/", WEB_DIR)`。
- 可选增强（cp 的 `features/static.py` 321 行 + `services/static_assets.py` 252 行 +
    
  `services/asset_manifest.py` 210 行 + `services/web_capabilities.py`）：SHA-256 URL 指纹缓存、
    
  启动预压缩、`__CARROT_BOOTSTRAP__` 注入。**不搬也能跑**：前端只在 10 个文件里读
    
  `__CARROT_BOOTSTRAP__`，且 `index.html` 内联脚本对 `webSettings` 缺失有 try/catch 兜底 →
    
  退化成「无缓存指纹、无能力门控」，页面照常打开。

**页面级 —— 不能整站照搬。** cp 前端调 57 个 `/api` 端点，在 sp 的落点：

| 结果           | 数量     | 说明                                                                                                                                                                                                                  |
| ------------ | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 有真实处理器       | **41** | 参数 / 设置 / 档案 / 收藏 / 热门值 / 单位索引 / intro / cars / egpu / bluetooth / carrot_navi / mapbox / ssh_keys / system …                                                                                                       |
| 只有 501（有意拒绝） | **14** | dashcam 5（`read-state`、`upload/{start,cancel,summary,test}`）、support_terminal 3（`{start,status,stop}`）、tools 3（`POST /api/tools`、`POST /api/tools/start`、`POST /api/tools/jobs/notice`）、vision_diag 2、vision_test 1 |
| 未注册          | **2**  | `/api/carrot_navi/client_diagnostic`（**唯一真实缺口**）；`/api/live_runtime{x}` 是查询串归一化的误报，sp 有 `/api/live_runtime`                                                                                                         |

WS 侧另有 `/ws/terminal`、`/ws/terminal_pty`、`/ws/compact_state`、`/ws/web_sound`、
  
`/ws/carrot_navi/media`、`/stream` 全部 501。

按页面（依据 `web/js/generated/*.js` 的 API 依赖）折算：

| 页面                    | 依赖                                                                          | 照搬后                                                                                 |
| --------------------- | --------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `app.js`（壳）           | `/api/param_set`                                                            | ✅                                                                                   |
| `settings.js`         | favorites / popular_values / profiles / settings                            | ✅                                                                                   |
| `intro.js`            | intro / param_set / params_restore / web_settings                           | ✅                                                                                   |
| `drive.js`            | `/api/carrot_navi`、`/ws/carrot_navi`                                        | ⚠️ state 可用；media 通道 501                                                            |
| `tools.js`            | tools / dashcam / egpu / params_qr\_* / settings / bluetooth / web_settings | ⚠️ 只读部分可用；**`POST /api/tools` 与 `/api/tools/start` 是 501**，即「跑命令 / git reset」那半页不可用 |
| `logs.js`             | `/api/dashcam`、`/api/screenrecord`                                          | ❌ 全 501                                                                             |
| `terminal.js`         | `/ws/terminal`、`/ws/terminal_pty`                                           | ❌ 全 501                                                                             |
| `terminal-support.js` | `/api/support_terminal`                                                     | ❌ 全 501                                                                             |

### 6.3 为什么这 14+6 个不该为了「照搬面板」去补


`features/unsupported.py` 的模块 docstring 已逐项写明理由，其中两条是**安全底线**而非「还没做」：

- **terminal / support_terminal / tools 的写操作**：7000 上**没有任何鉴权**（cp 与 sp 的 server
    
  都没有 auth/token 校验）。它就是「同网段任何人都能在控制车辆的那台计算机上执行命令」的入口；
    
  cp 的 tools 页同理（`shell_cmd`、`git reset --hard`、`git sync`、`rebuild`）。
- **compact_state**：Carrot Vision 的字节打包 HUD 协议在 sp 无对应 cereal 消息，猜一个会得到
    
  「解码成错误数字」的流。

所以照搬整站的净效果是：**新增 3 个完全不可用的页面 + 1 个半残页面，并制造「页面既然在，那把
  
后端也补上」的压力**——而补的正是上面这两条，与 sp 现有安全决策直接冲突。

### 6.4 三个可选方案（待决策）

| 方案                   | 做法                                                                                                                                       | 代价                                   | 风险                            |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ | ----------------------------- |
| **A. 不做**（维持现状）      | 7000 继续只做 App API；面板继续走 8088 / 5080                                                                                                      | 0                                    | 无                             |
| **B. 只搬「能用」的页面**（推荐） | 搬 `web/` 树 + `add_static`，但**摘掉** `logs` / `terminal` / `terminal-support` 三个页面的入口与 `tools` 页的命令区；补 `/api/carrot_navi/client_diagnostic` | 中（改 `index.html` 导航 + 3 个 bundle 入口） | 低（不引入无鉴权 shell）               |
| **C. 整站照搬**          | 原样搬 `web/` + 补齐 14 个 501 端点 + `/ws/terminal` 等                                                                                           | 大（cp `server/` 还有约 100 个文件未移植）       | **高**：引入无鉴权远程 shell / git 写操作 |

若选 B / C，必须同时处理：

1. **`/` 路由契约冲突**：`tests/test_carrot_server_completeness.py:296`
     
   `test_the_index_lists_the_routes` 断言 `GET /` 返回带 `routes` 键的 JSON。让 `/` 改服 SPA 会打破它
     
   → 需要把路由清单挪到 `/api/routes` 并同步改测试，且先确认伴生 App 不依赖 `GET /` 的 JSON。
2. **静态路由注册顺序**：`add_static("/")` 必须在所有显式路由（含 `unsupported.py` 的 `{tail:.*}`）之后注册，否则会遮蔽它们。
3. **`web/` 落点**：cp 在 `selfdrive/carrot/web`，sp 的 carrot 在 `sunnypilot/carrot/` → 建议
     
   `openpilot/sunnypilot/carrot/web/`，并同步 `WEB_DIR`。
4. **版权**：cp 是纯 MIT；`web/` 是 cp 的构建产物，建议在该目录放一份来源说明。
5. **不要连带 `cweb_push.py`**：它是每 5 s 把设备 IP POST 到第三方中继的 phone-home agent
     
   （URL 以 XOR 混淆内嵌），`carrot/README.md` 已把它标为「产品 / 隐私决策，不是移植任务」。

### 6.5 落地记录（2026-10-11）

先按 **B** 落地，随后用户改选 **C**：B 的「摘掉入口」全部回滚、501 端点全部补齐。下面是**最终状态**。

**7000 面板**

| 项 | 落地 |
|---|---|
| `web/` 树 | cp 的 `selfdrive/carrot/web` 逐字节复制到 `sunnypilot/carrot/web`（566 文件 / 9.2 MB）；构建产物已入库，设备不跑 Node |
| `config.py` | 新增 `BASE_DIR`/`ROOT_DIR`/`WEB_DIR`/`SELFDRIVE_ASSETS_DIR`/`TRAINING_ASSETS_DIR`/`OFFROAD_ASSETS_DIR`/`SOUND_ASSETS_DIR`/`DEFAULT_SETTINGS_PATH`，以及 dashcam / screenrecord / tmux / git-state 一组常量 |
| `app.py` | 按 cp 的 `features.register_all()` 顺序注册 **27 个 feature**，末尾 `add_static("/shared-assets/")` + `add_static("/", WEB_DIR)`；`GET /` 与 `/index.html` 由 `features/static.py::handle_index` 提供（注入 asset manifest / capabilities / web-settings）；原 `/` 的 JSON 路由清单在 `GET /api/routes` |
| `show_index` | **False**（cp 为 True）：面板不需要目录列表，开了会把 `web/src`、`web/tests` 暴露到局域网 |
| `unsupported.py` | 从 21 条拒绝缩到 **1 条**：只剩 `youtube_live`（cp 自己也不再提供） |

**`server/` 整树移植**

| 项 | 落地 |
|---|---|
| 规模 | cp 的 **99 个缺失文件**全部移植（`features/dashcam/` 25、`features/tools/` 5、`live_runtime/` 7、`terminal_commands/` 9、`services/` 23 等）；命名空间 `openpilot.selfdrive.carrot` → `openpilot.sunnypilot.carrot` |
| 基础模块 | `common/{async_process,repo_update,reboot}.py`、`selfdrive/car/openpilot_toggle.py`、`carrot/web_upload.py`、`carrot/realtime/`（`compact_state.py` 652 行 + `.pyx`/`.cc`/`.h`/`SConscript`，已接进 `sunnypilot/SConscript`） |
| **module/package 同名冲突** | `carrot_navi` / `tools` / `intro`：删 sp 的单文件、改用 cp 的包（cp 的 `carrot_navi/` 是超集，自带 `client_diagnostic`）；sp 独有的 `/api/regulatory` 移入 `system.py`，`/download/tmux.log` 由 cp 的 `terminal.py` 提供 |
| **同名不同 API 的 service** | `params.py` / `settings.py`：sp 版改名 `params_typed.py` / `settings_sp.py` 并重指 sp 的消费者，装 cp 版为规范；`device_info.py`：装 cp 版 + 追加 sp 的 `listening_ports` |
| 路径/API 重映射 | `openpilot.system.hardware` → `common.hardware`（**只改 cp 复制件**，sp 自有文件已回退以免改变其行为）；`openpilot.cereal.car` → `opendbc.car.structs.car`；`carrot.cruise_gap` → `sunnypilot.selfdrive.car.cruise_helpers` |
| `compact_state` | sp 的 `RawRelayHub` 增补 `is_compact_service` / `register_compact` / `_compact_frame`，复用 `compact_state.py` 编码；`compact_state_pyx` 可选（未编译时走纯 Python，线格式一致）；`/ws/compact_state` 由 `features/ws.py` 提供 |
| **未取（有意）** | `egpu_model.py`（sp 有自己的 `egpu.py`，读 chestnut/jetlink 而非 cp 的 `modeld/big_model` 管线）；两个 XOR 混淆 Discord webhook 与上传 relay **置空**；`carrot_settings.json`（189 KB，cp 前端设置页的元数据源）已复制 |
| 测试 | cp 的 `server/tests/` 移植 24 个（`test_egpu_model` 除外；`test_git_config` 整模块 skip——会真连远端）；sp 的契约测试按 cp 的实际行为更新（`web_language` 字段、intro 的 `shouldShow`、favorites 原样存、`known` 键等） |

**验证**

| 项 | 结果 |
|---|---|
| 路由 | **126 条**（原 96）；`GET /` 200 text/html；`/api/dashcam/*`、`/api/screenrecord/*`、`/api/vision_test/status`、`/api/terminal_pty/status`、`/api/support_terminal/status`、`/xiaoge` 全部 200；只有 `/api/youtube_live/*` 仍 501 |
| `ruff check openpilot` | **All checks passed**（cp 的 412 处自动修 + 36 条 per-file-ignores） |
| `compileall` | 干净 |
| carrot 测试 | **563 passed / 14 failed / 48 skipped**；那 14 项是桩件缺真 Params/cereal 的预存失败，已用 `git stash` 对比确认与本轮无关 |

> ⚠️ **安全提示（未变）**：7000 **依旧无鉴权**。C 方案把 cp 的终端、`/api/tools` 写操作、
> `support_terminal` 全部启用——同网段任何人都能在控车计算机上执行命令。若只要面板不要 shell，
> 回滚到 6.4 的 B 方案即可（改动集中在 `index.html` 与 3 个 JS 文件）。

---

## 端口与鉴权：与上游逐字一致（2026-10-11 定案：跟随上游）

用户问：「上游的终端 / `/api/tools` 写操作也一并启用，而 7000 依旧无鉴权——同网段任何人可在控车机上执行命令，**这个上游也是这样吗？**」

核验结论：**是，上游一模一样**；本仓这一处**没有做任何加严，也不打算自己加**。

| 核验项 | 命令 | 结果 |
|---|---|---|
| 7000 的 tools 面 | `git diff upstream/test HEAD -- openpilot/sunnypilot/carrot/server/features/tools/` | **空 diff** —— 含 `POST /api/tools`、`POST /api/tools/start` 等 7 条写路由，与上游同一份 |
| `support_terminal` | `git diff upstream/test HEAD -- openpilot/sunnypilot/carrot/server/services/support_terminal.py` | **空 diff** —— `PIN_FAILURE_LIMIT = 5` 那套 PIN 认证是**上游原有的**，不是我们加的 |
| 上游 7000 自身有无鉴权 | `git grep -i "auth" upstream/test -- 'openpilot/**/carrot/server/*'` | 只命中 `support_terminal` 的 PIN；**7000 上没有任何鉴权中间件** |
| 6999 门控 | `CarrotRecoveryEnabled` 默认 `"0"`（`openpilot/common/params_keys.h:445`）；`process_config.py:116` 据此决定起不起进程 | 与上游 `b161d88a44`「6999 behind an opt-in gate」一致（默认关） |

**决策（用户拍板：「没事 A 就行，这个跟随上游，等上游开发即可」）**：不自行给 7000 加鉴权，
跟随上游；上游哪天把鉴权/端口改了，我们再跟。
理由：自己加一套 guard，上游一改（端口号、中间件位置）就打架，等于白做还带维护债。

### 顺带：上游 2026-10-11 同日新提交的逐条对照

| 上游提交 | 内容 | 本仓状态 |
|---|---|---|
| `b161d88a44` | 6999 recovery 终端放到 opt-in 门后面 | 已随 `d7a8d87590` 移植（默认关） |
| `b57fdcc4d6` | CarrotPilot 整棵 server 树 + web 面板 | 已移植（见本文档上文） |
| `aae89bbea0` | 记录 7000 面板 / 6999 recovery / C 方案 | 由本文档承担 |
| `0bb80bd992` | 修 `shader_polygon` 的 `Optional[rl.Color]`（`2f5c41653` 的 lint sweep 把注解改成 `rl.Color | None`，而 `rl.Color` 是函数 → 定义期 `TypeError`，UI 进程 import 就崩、manager 反复重启） | **天然一致**：我们没跟那条 lint sweep（见 `DAY_LOG_2026-10-11-UPSTREAM_TEST_ALIGN.md` 第五节），`git diff upstream/test HEAD -- openpilot/system/ui/lib/shader_polygon.py` 为空 |

---

## 上游 `test` 追踪点（2026-10-11 17:40 复核）

| 项 | 值 |
|---|---|
| 上游 tip | `d4eeac955b` docs(carrot): record the device-tab sp sections and the three-service QR dialog —— 2026-10-11 16:12:08 +0800 |
| 本次复核 | `git fetch --no-tags --force https://github.com/mouxangithub/openpilot.git refs/heads/test:refs/remotes/upstream/test` → **无新提交**（仍是 `d4eeac955b`） |
| 本仓 | 分支 `sp-macanlong-test-f4aead756e`，HEAD `96ed4d547a`「跟随上游 `d4eeac955b`」 |
| 结论 | **内容级已对齐到上游 tip，港口无缺口**；唯一挂账见文末 |

### 13:37→16:12 这波 13 条的逐条处置

| 上游提交 | 内容 | 本仓 |
|---|---|---|
| `b161d88a44` | 6999 recovery 放 opt-in 门后 | 已移植 `d7a8d87590`（`CarrotRecoveryEnabled` 默认 `"0"`） |
| `b57fdcc4d6` | CarrotPilot 整棵 server 树 + web 面板 | 已移植 `d7a8d87590` |
| `aae89bbea0` | 记录 7000 面板 / 6999 recovery / C 方案 | 由本档承担 |
| `0bb80bd992` | 修 `shader_polygon` 的 `Optional[rl.Color]` | **天然一致**（未跟 lint sweep `2f5c41653e`） |
| `f6cf81de23` | 7000 单目录设置 catalog（按本 fork 重建） | 已移植 `2e73bea7c5` |
| `933d2230e3` | 7000 里显示 sunnypilot 自己的设置 | 随 `2e73bea7c5` 一并落地 |
| `2386709298` | 记录设备实测的设置融合结果 | 随 `2e73bea7c5` 一并落地 |
| `27a028bcf1` | 翻译并补全 7000 的 SP 设置分区 | 随 `2e73bea7c5` 一并落地 |
| `bf28d5c864` | 补 maps/imu/models 的 cgroup 翻译 | 已移植 `41d8a17abd` |
| `fd35a16c5b` | 记录 7000 中文标签与 maps/IMU 章节 | 已移植 `138705ac1e` |
| `ded58d5483` | 三服务二维码弹窗 + Device 页 SP 分区 | 已移植 `41d8a17abd` |
| `751b641330` | catalog 菜单按 menu id 查表 | 已移植 `ecb9f15fe5` |
| `d4eeac955b` | 记录 Device 页 SP 分区与三服务二维码 | 已移植 `96ed4d547a` |

复核命令（核到内容级，不只看 commit message）：

```bash
for c in b161d88a44 b57fdcc4d6 f6cf81de23 933d2230e3 2386709298 27a028bcf1 \
         bf28d5c864 fd35a16c5b ded58d5483 751b641330 d4eeac955b; do
  files=$(git show --name-only --format= $c)
  echo "$c files=$(echo "$files" | grep -c .) differs=$(git diff --name-only upstream/test HEAD -- $files | wc -l)"
done
```

实跑只有 4 处**本仓刻意差异**（非缺口）：`carrot_settings_sp.json`（按本 fork 重建）、
`web_settings.py`（fork 适配）、`pyproject.toml`（per-file-ignores）、`webui` 子模块指针（本仓在前），
以及 `params_keys.h` / `process_config.py` 的 6999 门控默认值（opt-in 默认关）。

### 唯一挂账

`2f5c41653e style(lint)` 的 ruff 清理（95 文件）—— 仍需独立一轮；上游其后用 `0bb80bd992`
修掉它引入的 UI import 崩溃（`rl.Color | None` 定义期 `TypeError` → `ui` 进程 import 即崩、
manager 反复 `Restarting ui`），**若要补这一条，必须连 `0bb80bd992` 一起取**。

---

## 上游 `test` 追踪点（2026-10-11 后续复核）

| 项 | 值 |
|---|---|
| 上游 tip | `15280cdbfd` feat(carrot): port the Carrot Vision road stream onto this fork —— 2026-10-11 16:42:42 +0800 |
| 本次复核 | `git ls-remote https://github.com/mouxangithub/openpilot.git refs/heads/test` → `15280cdbfd`（较上次复核 `d4eeac955b` **前进 1 条**） |
| 本仓 | HEAD 追加「跟随上游 `15280cdbfd`」提交 |

### 行车预览 /「Carrot Vision 不可用 · 等待启动」根因与修复

- **现象**：7000 面板 Drive 页点开 Carrot Vision（行车预览）后无画面，提示「Carrot Vision 不可用 / 等待启动」。
- **根因**（上游 commit message 原文）：Drive 页用 `CarrotVisionEnabled` 门控 Carrot Vision，而**本 fork 从未声明该 param** → 开始按钮永远无法点亮；并且它依赖的 `encoderd --carrot-vision-road` 与 `carrot_webrtcd` 两个进程在本 fork 根本不存在。
- **结论**：**是缺口（bug），不是"正常就这样"**。上游 `15280cdbfd` 已修复。

### 移植内容（`15280cdbfd` → 本仓）

| 上游改动 | 本仓落地 |
|---|---|
| `params_keys.h` 增 `CarrotVisionEnabled` / `CarrotVisionActive` | 原样 |
| `system/webrtc/carrot/`（session/state/video/webrtcd）+ `system/webrtc/carrot_webrtcd.py` | 原样（self-contained 变体，不动通用 `webrtcd` 的生命周期） |
| `process_config.py` 增 `carrot_webrtcd` / `carrot_vision_encoderd`（门控 `and_(iscar, enable_webrtc)`，`enable_webrtc` 读 `CarrotVisionEnabled`） | 与本地 `logmessaged restart_if_crash` 补丁合并保留 |
| `encoderd.cc` `--carrot-vision-road` + on-demand（`encode_on_demand`，仅 `CarrotVisionActive` 时真编码） | 原样 |
| `encoder.h` / `v4l_encoder.{h,cc}` `set_idle()` 空闲静默 | 原样 |
| `loggerd.h` `carrot_vision_road_camera_info`（只取 narrow-road 轨，省 C3 两路硬件编码） | 原样 |
| `carrot_settings_sp.json` 目录项 + `VEH_DM` 菜单挂载 | 已并入；`_generated` 元数据按本 fork 重算（`kept 178`，`CarrotVisionEnabled` 不再列于 `dropped_undeclared`） |

与上游刻意差异（非缺口）：stream 目标仍映射本 fork 的 `livestreamNarrowRoadEncodeData`；state 桥接指向 sunnypilot 的
`openpilot/sunnypilot/carrot/realtime/compact_state`（`CARROT_STATE_SERVICES` / `encode_carrot_state_frame`）。

### 设备侧生效步骤（2026-10-11 实操）

移植只改源码，C3 上必须重建两处，否则现象照旧：

```bash
# 1) encoderd: --carrot-vision-road 只在新二进制里（旧二进制会 LOGE "Argument ... is not supported" 后退出）
cd /data/openpilot
scons --ccflags="-O0" -j2 openpilot/system/loggerd/encoderd

# 2) libparams_c.so: 新 key 必须在 .so 里，否则参数读/写报 UnknownKeyName
#    -O0 + 单线程是硬要求：params.cc 在 C3 上 -O2 会被 OOM SIGKILL（见 launch_chffrplus.sh）
scons --ccflags="-O0" -j1 openpilot/common/libparams_c.so
```

随后**重启 manager**才能让新 `.so` 生效（面板与 manager 都是启动时加载）：

```bash
# 手动杀 + start；注意 manager_control(action="restart") 的 pkill 模式是 "manager/manager.py"，
# 实际 cmdline 是 "python3 ./manager.py"（cwd=openpilot/system/manager）→ 匹配不到，会起第二个 manager！
pkill -9 -f '^python3? \./manager\.py$'          # 连同 openpilot.* 残留一起收掉，别动 aid/webui
# 再 manager_control(action="start")
```

**已知坑：manager 关机挂死。** `kill -TERM/-INT ./manager.py` 会打印 `got CTRL-C, exiting` 后卡在
shutdown（`do_wait`），只停掉一部分子进程就永久停住（实测残留 `manage_athenad` / `manage_sunnylinkd` /
`sunnylink.backups.manager` / `carrot.xiaoge_data` 等 5 个），期间 7000/8088 随之下线（面板消失）；
同时 manager 本身还留着 1:34 起未回收的 `<defunct>` 僵尸。遇到"卡 UI / 面板没了"时先看这个。
恢复：`kill -9` 掉所有 `./manager.py` 与 `openpilot.*` 残留 → `manager_control(action="start")`。
手动起的 manager 是 detached（`start_new_session`），不再受 `launch_chffrplus.sh` 监管，方便时重启设备回到正常受管状态。

验证（offroad 即可）：`curl -s http://127.0.0.1:7000/api/params_bulk?names=CarrotVisionEnabled` 返回 `{"CarrotVisionEnabled":true}`
（预览页的门就是它）。`carrot_webrtcd` / `carrot_vision_encoderd` 的门是 `and_(iscar, enable_webrtc)`，
offroad 且无车（`CarParams` 空 ⇒ `notCar`）**不会**启动，上车点火后才起 —— 属预期，不是缺口。

### 追踪点更新（2026-10-11 18:20）

| 项 | 值 |
|---|---|
| 上游 tip | `0667496636` fix(carrot): carrot vision encoder skips unclaimed streams and uses this fork's Params API |
| 本次拉取 | `15280cdbfd` → `0667496636`（+2 条），`git fetch https://github.com/mouxangithub/openpilot.git test:refs/remotes/upstream/test` |
| 本仓 | `1a4d454b2e` + `0667496636` 已内容级移植（HEAD 之后那条 fix commit） |

两条都是 Carrot Vision 自己的 bug，且都会让预览「有画面但永远不出图」，必须跟：

| 上游 commit | 症状 | 本仓落地 |
|---|---|---|
| `1a4d454b2e` | 车外摄像头检查 runner 第一次写 `IsTakingSnapshot` 直接抛原始 key 名错误（本 fork 从未声明，但 `vision_test.py` / `vision_diag.py` / `offroad_alerts.py` 早就在用） | `params_keys.h` 补 `IsTakingSnapshot` / `Offroad_IsTakingSnapshot` |
| `0667496636` | ① `encoderd_thread` 的 `assert(it != end(cameras))`：Carrot Vision 只要 narrow-road 一路而 camerad 给三路 → 一开就 assert 死；② `put_bool_nonblocking` 本 fork 无此别名 → `CarrotVisionActive` 写不进去、编码器永远 idle | `encoderd.cc` 改 skip/`continue`；`webrtcd.py` 改 `put_nonblocking`（**刻意差异**：上游传 `"1"/"0"` 字符串，本 fork 的 Params 会类型校验报 `proposed_type=str expected_type=BOOL`，改传 `bool`） |

### 本 fork 特有：carrot 视频轨的两个硬缺口（`carrot/video.py`）

上游 `carrot/video.py` 直接 `import av`（PyAV）并用 `av.Packet`，还依赖基类里的 `self._dt`。
本 fork 两者都不成立：

| 缺口 | 证据 | 处理 |
|---|---|---|
| 无 PyAV | `import av` 在 `/usr/bin/python3`、`/usr/bin/python3.12`、`/usr/local/venv/bin/python3` 全部 `ModuleNotFoundError`；`third_party/wheels` 也没有 av wheel | 上游 comma 早已在 webrtc 里去掉 av（`3f93b00120 webrtc: remove av (#38369)`），本 fork 的 `system/webrtc/device/video.py` 就是那套替代实现 → carrot 轨改用同一 `EncodedVideoFrame`（`bytes(packet)` + `packet.pts` 正是 teleoprtc `_send_track_loop` 的全部要求） |
| 基类不存 `dt` | 本 fork `teleoprtc/tracks.py: TiciVideoStreamTrack.__init__` 收 `dt` 却不 `self._dt = dt`（只有 `TiciTrackWrapper` 用 `getattr(track, "_dt", 0.05)` 兜底）；而 carrot 轨 `recv()` 每帧都算 `frame_id * self._dt * self._clock_rate` | carrot 轨自己存 `self._dt = dt` |

不加这两处，`--carrot-vision-road` 起来后 `webrtcd.py:181` 的惰性 import 会直接 `ModuleNotFoundError`（会话建不起来），
即便装了 PyAV，`recv()` 也会每帧 `AttributeError` 被 except 吞掉 → 永远发不出帧。**上游同样有这个缺口，值得回报。**

### 追踪点再更新（2026-10-11 18:35）

上游 tip → `a46e35f7e2`（docs：记档本轮 Carrot Vision 对齐 + 导航结论）。新增两条里只有 `f6512bf146` 是代码：

| 上游 commit | 症状 | 本仓落地 |
|---|---|---|
| `f6512bf146` | `stream.py` / `ssh_keys` / 热门值 / xiaoge 代理都读 `request.app["http"]`，但 plan-C 移植后**从没有人创建它** → 每次 `/stream` 代理在到达 webrtcd 之前就 `KeyError('http')` 死掉（面板预览必 500） | `app.py` 按 cp 原样补 `_http_session_ctx` cleanup context（startup 建 `ClientSession`，cleanup 关闭） |

设备侧验证（不依赖真车）：起一个假 webrtcd 监听 127.0.0.1:5001，再起临时 `create_app()`（7099），
POST `/stream` → `200` 且原样透传假 webrtcd 的响应体；修复前这里是 `KeyError('http')`。

上游 docs 记档里提到"本 fork Params 无 `put_bool_nonblocking` → 用 `put_nonblocking(key, "1"/"0")`"：
**mouxan 那份 fork 的 Params 接受字符串，我们这份不接受**（`TypeError: proposed_type=str expected_type=BOOL`）
→ 我们传 `bool`，功能等价。


### 追踪点再更新（2026-10-11 18:53，本次会话）

| 项 | 值 |
|---|---|
| 取上游手法 | `git fetch https://github.com/mouxangithub/openpilot.git test:refs/remotes/upstream/test --force`（`git fetch upstream` 走 SSH 不通；`upstream` 的 fetch refspec 只覆盖 master-c3）|
| 上游 tip | `15d03795bc` `feat(carrot): model manager and sunnypilot vehicle selection on 7000` |
| 上一个 tip | `a46e35f7e2`（纯 docs）随本次一并落地 |

| 上游 commit | 内容 | 本仓落地 |
|---|---|---|
| `a46e35f7e2` | docs：记档本轮 Carrot Vision 对齐 + Carrot 导航结论（`docs/carrot-7000-settings-fusion.md` 新增第 10 节）| `git apply` 原样 |
| `15d03795bc` | 7000 面板新增 `/api/opui/*` 代理 → 5080 webui daemon；Device 页挂「模型管理」「sunnypilot 车型选择」；`car.js` 车型选择 | 12 文件 `git apply` 全清；`server/config.py` 增 `WEBUI_PROXY_TARGET`（默认 `http://127.0.0.1:5080`，env 可覆盖）|

**设备侧兼容性已实测（本机，不依赖真车）：**

- `create_app()` 冒烟：221 条路由，`/api/opui/{tail}` 已注册；
- 新面板 JS 只调 5 个 opui 端点 —— `models`、`models/favorite`、`models/select`、`vehicle/platforms`、`vehicle/select`，
  **本 fork 的 webui（5080，`6d0320e`）这五个全都有** → 无需升级 webui 子模块；
- 真机 `curl http://127.0.0.1:5080/api/opui/models` → 200 JSON（`active_source: qcom` …），代理目标可用；
- daemon 不在时 `proxy_opui` 返 502，面板退回通用渲染；`app["http"]` 复用 `f6512bf146` 建好的共享 ClientSession。

**顺手清的坑**：本仓曾有一条误建 ref `refs/heads/refs/remotes/upstream/test`（`a6156bb030`），
让 `git log refs/remotes/upstream/test` 报 `refname 'refs/remotes/upstream/test' is ambiguous`。已删（本地 ref，不影响远端）。

### 当前设备状态（2026-10-11 18:53，停车）

```
curl 127.0.0.1:7000/                     -> 200
curl 127.0.0.1:7000/api/camera/status    -> {"ok":true,"mode":"direct-encode-relay","cameras":{},"idle":true}
curl 127.0.0.1:7000/api/params_bulk?...  -> {"CarrotVisionEnabled":true,"CarrotVisionActive":null,"IsLiveStreaming":null}
params: CarrotVisionEnabled=1 / CarrotVisionActive 未设 / IsLiveStreaming 未设 / CarrotNaviV2Enabled=1
pgrep: 无 encoderd / carrot_webrtcd / carrot_vision_encoderd（停车，未点火）
```

即：**面板侧的「Carrot Vision 不可用 / 等待启动」在停车时本来就该出现**（无编码器在发布帧 + `CarrotVisionActive` 未置位），
真正要看的是**点火接管后** `carrot_vision_encoderd` + `carrot_webrtcd` 是否被 manager 拉起、`/api/camera/status` 是否有 `cameras.road` 帧龄。
这一步仍未做（需要真车）。


### 追踪点复核（2026-10-11 19:23）——上游 tip 未变

| 项 | 值 |
|---|---|
| 取上游手法 | `git fetch --no-tags --force https://github.com/mouxangithub/openpilot.git test:refs/remotes/upstream/test` |
| 复核手法 | `git ls-remote --heads https://github.com/mouxangithub/openpilot.git test`（直接问远端，不依赖本地 ref）|
| 上游 tip | `e6e42a548b` **未变**（= 上次同步点 `docs(carrot): record the /api/opui channel…`）|
| 结论 | **无新提交可拉**；本仓与上游 tip 已对齐（对 `e6e42a548b` 唯一改动的 `docs/carrot-7000-settings-fusion.md`，`git diff HEAD:<f> e6e42a548b:<f>` 为空）|

上游其余分支（参考，非本仓追踪线，且**无 `main`**）：`master 3323aafb`、`master-c3 dcde0f2d`、
`master-c3-prebuild 87059db5`、`dp dc5e1b9e`、`tn 20d17229`、`tn-c3 dcde0f2d`、`tn-c3-prebuild 8b40ee93`。

**「行车预览点开摄像头无画面 + sunnypilot不可用/等待开始」= 停车时预期行为，非 bug**
（详见 `docs/navipilot-integration-gap.md` §5.1）：`camera_relay.py` 是纯中继、不起编码器，
停车且 `IsLiveStreaming` 未置位时无发布方 → `/api/camera/status` 报 `{"cameras":{},"idle":true}`；
`carrot_webrtcd` / `carrot_vision_encoderd` 门控 `and_(iscar, enable_webrtc)`，offroad 不启动。
**唯一待办（需真车）**：点火接管后确认两进程被 manager 拉起、`cameras.road` 有帧龄。

### 追踪点复核（2026-10-11 19:30）—— 换手法复核，上游 tip 仍未变

| 项 | 值 |
|---|---|
| 手法 | `git fetch --no-tags https://github.com/mouxangithub/openpilot.git test`（HTTPS 直连，成功；SSH `git@github.com:` 依旧 `Permission denied (publickey)`）|
| 结果 | `FETCH_HEAD = e6e42a548b`，与 `refs/remotes/upstream/test` 一致；`git log e6e42a548b..FETCH_HEAD` **为空** |
| 结论 | **仍无新提交可拉**（用户第二次问「上游好像又多了一个 commit」，这是第二次复核；`sha` 也从 GitHub 侧复核过）|

附：本次同时处理了 App 侧（sp搭子）出包链路，见 `docs/navipilot-integration-gap.md` §6.1。

### 追踪点推进（2026-10-11）—— 上游 +2 提交：`e6e42a548b` → `4a6d3d8fa1`

| 项 | 值 |
|---|---|
| 取上游手法 | `git fetch --no-tags https://github.com/mouxangithub/openpilot.git '+refs/heads/test:refs/remotes/upstream/test'`（HTTPS + `/data/ai/bin/gh_credential.sh`；SSH `git@github.com:` 仍 `Permission denied (publickey)`）|
| 复核手法 | `git ls-remote https://github.com/mouxangithub/openpilot.git refs/heads/test` → `4a6d3d8fa1`（直接问远端）|
| 上游 tip | `e6e42a548b` → **`4a6d3d8fa1`（+2 提交）** |
| 新提交 1 | `834393b6fb` Device 页把内联列表换成 picker（`setting_device_actions.js` 352 行改动 + 新增 `device_tab.css` 样式 + 三语）|
| 新提交 2 | `4a6d3d8fa1` 模型面板精确对齐 5080（**两槽位 + 树形弹窗**，`setting_device_actions.js` 412 行）|
| 落地手法 | `git cherry-pick 834393b6fb 4a6d3d8fa1` —— **全清，零冲突**（共 7 文件 / +646 −257）|
| 逐文件核对 | 7 个受动文件 `git rev-parse HEAD:<f>` == `git rev-parse upstream/test:<f>` → 与上游 tip **零差异** |
| 为何能干净落地 | 这 7 个文件在本仓 HEAD 与 `e6e42a548b` **逐字节相同**（无本地改动），所以等价于直接前移 |
| 生效方式 | 纯 JS/CSS/翻译，7000 面板按目录静态服务 → **不需要重编**，刷新页面即生效 |
  
  ### 更正（2026-10-11 21:40）—— 「行车预览：打开摄像头无画面 + sunnypilot 不可用/等待开始」= **真 bug，已修**
  
  此前记的"停车时预期、非 bug"（见上文 19:23 一节）**针对的是 App 侧的 `/ws/camera/road`**，
  和用户在设备上看到的现象不是一回事。设备端这两行字是**大 UI 的路视告警框**：
  
  | 证据 | 值 |
  |---|---|
  | 文案来源 | `selfdrive/ui/translations/app_zh-CHS.po`：`"sunnypilot Unavailable"→"sunnypilot 不可用"`、`"Waiting to start"→"等待开始"`（`ALERT_STARTUP_PENDING`，mid 尺寸）|
  | 绘制者 | `selfdrive/ui/onroad/augmented_road_view.py:80` → `AlertRendererSP`（全大 UI 只有这一个 AlertRenderer 实例，`selfdrive/ui/onroad/onroad/*` 无第二处）|
  | 为什么离路会画 | selfdrived 离路不跑 → `get_alert()` 合成 startup-pending；`IsOnroadPreview` 只让 `ui_state.started` 为真，没拦告警 |
  | 为什么无画面 | 预览走的是 `CameraView("camerad", VISION_STREAM_NARROW_ROAD)`，而 `camerad` 的启动条件是 `or_(driverview, livestream)` —— **预览不在其中** → 只有底色占位 |
  
  修法（3 处，commit `d0d6f0c6ae`）：
  
  1. `onroad/alert_renderer.py` + `mici/onroad/alert_renderer.py`：`IsOnroadPreview` 时 `get_alert()` 返回 `None`；
  2. `sunnypilot/onroad/alert_renderer.py`：mid/small 告警按**实际绘制行**测量字形高度再居中
     （原来用硬编码 `"A"` 探针：CJK 回退字体 ×1.25 缩放 → 块高被低估 → 两行整体偏下、动态框高偏小）；
  3. `system/manager/process_config.py`：`camerad` 条件加 `onroad_preview`。
  
  **踩坑**：`or_`/`and_` 是 `operator.or_/and_` 的薄封装，**只接受 2 个函数**——
  `or_(driverview, livestream, onroad_preview)` 让 manager 起来就崩
  （`TypeError: or_ expected 2 arguments, got 3`，见 `/data/community/crashes/`）；已改为嵌套。commit `458116254d`。
  
  **为什么"上次说修好了但没变化"**：改完没重启进程。`manager.py`(20:29:45) 与 `ui`(20:29:45) 都早于 21:14 的补丁，
  运行中的进程永远拿不到新代码——`process_config.py` 必须**重启 manager** 才生效，UI 的绘制代码必须**重启 ui 进程**才生效。
  
  **已做的部署与实测（21:37–21:38）**：`manager_control restart` → `manager 181079/181085` + `ui 181118` + `camerad 181944`；
  `/dev/shm/msgq_visionipc_camerad_{0,1,2}` 时间戳持续刷新（三路相机在发布帧）；`write_params IsOnroadPreview=true`
  即触发 manager 拉起 camerad（就是预览按按钮时发生的事），swaglog 21:37:20 后 **0 条 ERROR/exception**。
  

### 追踪点推进（本次）—— 上游 `4a6d3d8fa1` → `f2fe2c822f`（+11 提交，全清）

| 项 | 值 |
|---|---|
| 取上游手法 | `git fetch --no-tags https://github.com/mouxangithub/openpilot.git test:refs/remotes/mouxan/test`（HTTPS；SSH `git@github.com:` 仍 `Permission denied (publickey)`）|
| 复核手法 | `git ls-remote https://github.com/mouxangithub/openpilot.git refs/heads/test` → `f2fe2c822f`（直接问远端）|
| 上游 tip | `4a6d3d8fa1` → **`f2fe2c822f`（+11 提交，线性）** |
| 新提交（老→新）| `e1605b8e20` 刷新 web asset manifest hash；`5d6fcf271b` cp↔sp 能力差距 + 7000/5080 路线图文档；`95c0f12c5e` Device 页 OSM/蓝牙/行程/IMU 分区；`11d7809f44` **CarrotPilot radar stack（EnableRadarTracks 门控，~11.6k 行，含 Cython）**；`dd1e3e8ea8` car capnp 类型改从 opendbc 取；`a1e6d06982` **红绿灯观察 trial（`signalcolord` + signal_assist + tools/signal_analysis）**；`b3140559d2`/`8ffd6932d3` signal 测试落到本 fork 布局；`c948c5443f`/`74a79b3857` 文档；`f2fe2c822f` 面板修复（picker 死按钮 / 蓝牙空白 / AR 开关锁死）|
| 落地手法 | 逐个 `git cherry-pick`（非 merge），**11 个全清 + 2 处冲突手工并集** |
| 冲突 1 | `openpilot/common/params_keys.h`：并入上游新增 `RadarTrackFlip` / `EnableRadarTracksResult`；把 `EnableCornerRadar`、`EnableSpeedTF` 从本 fork 的 `BOOL` 改成上游的 `INT`（carrot 侧本就是 `get_int()` 读、滑块按 `-3..1` 写 → 原 `BOOL` 声明与消费者不一致）；保留本地的 `HDPuse` / `HardwareC3xLite` |
| 冲突 2 | `openpilot/system/manager/process_config.py`：`modeld` 采纳上游 `and_(or_(only_onroad, onroad_preview), is_stock_model)`（预览要拉起 modeld，与本次预览修复同向），新增 `signalcolord`；`dmonitoringmodeld` **保留本 fork 的 `driverview`**（上游的 `dm_process` 在本 fork 已被移除，且本 fork 无 `is_dm_disabled`）|
| 子模块（关键）| 上游 opendbc pin 由 `a378bf0aa` **force-update** 到 `ffd662d88`（tn-c3 +62 提交，主体是 zoompilot Mazda 模块与 Toyota brake onset）→ 在 opendbc 仓做一次合并 `bbdaeae6c`：33 处冲突，mazda/生成物（`docs/CARS.md`、`routes.py`、`car_list.json`）/`safety/tests/common.py` 取上游，`gm`/`hyundai` 四文件保留本 fork（`params_access` 约定 + navi 端口防御门控），`test_models.py`/`test_speed_dep_config.py` 手工并集 |
| capnp 合并残留 | 自动合并在 `opendbc/car/car.capnp` 把 `pcmCruiseGap @62`/`softHoldActive`/`activateCruise`/stock-navigation 段**插了两遍**，capnp 直接报 `'pcmCruiseGap' is already defined` → 去重；新 pin 唯一非 Mazda 增量 = `RadarData.radarTrackFlipped @4`（radar stack 依赖）|
| pin 误记更正 | 第一次 merge 提交（`8fc4eb74c`）漏 `git add opendbc/car/car.capnp`（去重发生在暂存之后）→ 已 `--amend` 为 `bbdaeae6c`，超级工程 pin 随后补记 |
| 校验 | `log.capnp`+`car.capnp` capnp 编译通过；本次新增/改动 39 个 `*.py` 全 `py_compile` 通过；`mazda`/`volkswagen`/`hyundai`/`sunnypilot.car.interfaces` 导入 OK；Macan `PORSCHE_MACAN_MK1` 与 Mazda CX-5 2022 的 `CarParams` 构建 OK |
| 未做 / 风险 | 设备 venv **无 pytest** → 测试套件未跑；radar stack 含 Cython（`radar_motion/_motion_native.pyx`）+ `SConscript` → **必须重编**才生效；上游那 62 个 opendbc 提交里 Mazda/Toyota 部分本车（Macan）不用，但仍是未上车的代码，建议先在设备上只跑 Macan 回归 |
| 生效方式 | 重编（scons/make）+ **重启 manager**（新增进程 `signalcolord`、`radarcan`、`radard_dpath`）；纯 JS/CSS/翻译部分刷新页面即生效 |

### 追踪点推进（本次）—— 上游 `f2fe2c822f` → `6a077d7866`（+2 提交，全清）

| 项 | 值 |
|---|---|
| 取上游手法 | `git fetch https://github.com/mouxangithub/openpilot.git test:refs/remotes/mouxan/test`（HTTPS；SSH `git@github.com:` 仍 `Connection closed`，不可用）|
| 复核手法 | `git ls-remote https://github.com/mouxangithub/openpilot.git refs/heads/test` → `6a077d7866`（直接问远端，不信本地 ref）|
| 上游 tip | `f2fe2c822f` → **`6a077d7866`（+2 提交，线性）** |
| 新提交 1 | `b2ae03287d` Device 页只留真设置：`device_info.py` 按目录描述自身的状态标记过滤掉只读行（Updater* / MapdVersion / OsmLocationName / ImuCalibrationStatus / LocalDriveStats …），再扣掉几个由专属 manager 块负责的动作 → OSM 12→3、Models 11→8、Trips 3→1、Imu 4→1；同时给 web-lab 补上 Experimental 分组（此前只能敲终端命令翻这个 capability，**AR 开关看着永远是死的**）|
| 新提交 2 | `6a077d7866` 每个 param 只落一个 section：`OsmLocal` / `OsmMapDataEnabled` / `TeslaMadsScreenButton` 同时挂在两个目录节点下 → 渲染成重复行；group builder 改为归给**第一个** section |
| 落地手法 | `git cherry-pick b2ae03287d 6a077d7866` —— **全清，零冲突**（7 文件 +50 −4；1 文件 +15 −2）|
| patch-id 核对 | 两个 cherry-pick 与上游 **patch-id 完全一致**（`9c626bc67a` / `df7e729139`），即平移而非改写 |
| 逐文件核对 | 7 个受动文件 `git rev-parse HEAD:<f>` == `git rev-parse mouxan/test:<f>` → 与上游 tip **零差异** |
| 校验 | `py_compile openpilot/sunnypilot/carrot/server/services/device_info.py` 通过；纯 JS/CSS/翻译无编译步骤 |
| 生效方式 | `web/js/generated/*`、`web/css/generated/*`、`web/src/features/tools/*`、三语翻译 → 7000 面板静态服务，**刷新页面即生效**；`server/services/device_info.py` 在 `carrot_server` 进程里已 import → **必须重启 manager** 才生效 |


### 本仓主动偏离（2026-10-11 23:40）—— Device 页「一个 param 只落一个分区」补完到基础分组

**不是上游移植**：收尾上游 `b2ae03287d` / `6a077d7866` 那条规则时发现它没走完，属本仓有意偏离。

| 项 | 结论 |
|---|---|
| 上游那两笔的射程 | `_sp_device_setting_groups()` 的 `assigned` 只对**目录驱动的 SP 分区**去重；`Device / Software / Toggles / Developer` 四个**手写基础分组**不在其中 → 合并后的整张表仍有两个 param 出现两次 |
| 改前实测（live `/api/settings/snapshot`）| `IsMetric` ∈ {Toggles, Trips}；`AlphaLongitudinalEnabled` ∈ {Developer, Vehicle}；重复数 = 2 |
| 改法 | `assigned` 初值 `set()` → `set(DEVICE_SETTING_DEFAULTS)`：基础分组算「第一个分区」，SP 分区不得复述 |
| 必须一起改的连带 | `Trips` 唯一目录 param 就是 `IsMetric`，去重后该分区**一条行都没有**；而客户端 `getVisibleDeviceGroups()` 用「有行」判可见 → 侧栏条目会消失。故把 `Trips` 加进 `SP_CAPABILITY_GROUP_IDS`（它本来就只画 trips 管理器块，数据靠 `loadDeviceTripsManager` 填）|
| 改后实测 | 重复数 2 → 0；`Vehicle` −`AlphaLongitudinalEnabled`；`Trips` 退出 `device_groups`（客户端保留条目）；其余分区零变化 |
| 测试 | `test_device_setting_groups.py`：改掉「基础 param 可被 SP 分区复述」那句注释，新增 `test_no_parameter_appears_in_two_device_groups` / `test_a_section_never_restates_a_base_param` —— 12/12 通过（设备无 pytest，用等价 harness 直接驱动测试模块）|
| 生效方式 | 服务端改动要重启 `carrot_server`；`setting_device_config.js` 是静态服务的，刷新页面即生效 |
| 与上游差异（重要）| 上游 `device_info.py` / `setting_device_config.js` **保持原样**。若上游日后把基础分组也并入去重，内容级对齐时这里会冲突（我们多一句 seed）|

#### 更正：`Software` 分区的 `Updater*` 不是「多余的设置行」，不能删

上一次把它列为遗留缺陷，**该判断是错的**：

| 项 | 值 |
|---|---|
| `DEVICE_SETTING_DEFAULTS` 是什么 | **它就是取值清单**：`get_device_setting_values()` 按它读 param 并塞进 snapshot 的 `device_values` |
| `Software` 分区怎么画 | `js/pages/setting_device.js:572` 是**专用渲染**（Current Version / Download / Install / Target Branch / Uninstall），值取 `data.UpdaterCurrentDescription`、`data.UpdaterState`、`data.UpdaterNewDescription`、`data.UpdaterTargetBranch`、`data.GitBranch` |
| 所以 | 把名字从分组删掉 = 同时从 `DEVICE_SETTING_DEFAULTS` 删掉 = **snapshot 不再带这些值** → 那几行全变 `-`，更新 UI 坏掉。这不是「去掉重复行」，是把功能删了 |
| 而且那个现象不存在 | `Software` 分区不逐行渲染分组名单（专用渲染器不吃它），「状态行占着真设置的位置」在 Device 页不成立 |
| 上游同款 | 我们的 `device_info.py` 与上游 tip **逐字节相同**，基础分组也一样 → 上游自己也没动。上游 commit message 拿 `Updater*` 举例不准确：真正被 `(read-only)` 标记过滤掉的是 22 个**目录项**（`MapdVersion` / `OsmLocationName` / `ImuCalibrationStatus` / `LocalDriveStats` …）|

#### 附带发现（本次未处理）：`carrot_settings_sp.json` 不同步，少了上游的 Toggles 分组

| 项 | 值 |
|---|---|
| 现象 | 本仓 `carrot_settings_sp.json` 373 个 param，上游 tip 338 个；**双向差异**：本仓独有 39（fork 参数），**上游独有 4**（`ExperimentalMode` / `ExperimentalModeConfirmed` / `ExperimentalModeLeadGap` / `ExperimentalModeSetSpeed`）+ 2 个菜单节点（`CARROT_SP_UI_TOGGLES` / `CARROT_SP_UI_ALPHA_LONGITUDINAL_TOGGLES`）|
| 根因 | 该文件由 `carrot/tools/build_settings_catalog.py` 生成，`ui_page_params()` 扫 `openpilot/selfdrive/ui/sunnypilot/layouts/settings/`。上游的 `toggles.py` 与 `alpha_longitudinal_toggles.py` 是 `a6156bb030`（"适配c3"）加的，**该提交不是本仓 HEAD 的祖先**（merge base `20be508f66` 里也没有这两个文件）→ 本仓那份目录没有 toggles 页 → 扫不出 `toggles` 页 → 目录里就没这两个节点 |
| 影响 | CarrotPilot 设置页少一个 Toggles / Alpha Longitudinal 分组（Device 页的 Toggles 是手写基础分组，不受影响）|
| 未处理原因 | 属另一条线：要移植 `a6156bb030` 的 UI 文件并重新生成目录 |
