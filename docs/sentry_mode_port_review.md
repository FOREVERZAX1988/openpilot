# StarPilot `sentry_mode` 移植评审（架构与接口治理）

> 评审人：openpilot-architecture-engineer
> 评审对象：`E:\StarPilot\openpilot\starpilot\sentry_mode\` → `E:\sp`（openpilot/sunnypilot fork，丰田纵深 + carrot 导航）
> 评审时间：2026-11-09
> 本次评审**未修改任何文件**（仅新增本文档作为评审产出）。

---

## 1. 结论（一句话）

**Conditional-Go，但必须大幅收窄语义**：StarPilot 的 `sentry_mode` 核心层（policy/storage/status/preferences/runtime，904 行）在我方**技术上可移植**，但其语义前提（停车时设备持续供电 + IMU 加速度 + 双摄像头 + 手机推送生态）在我方 C3 上**仅部分成立**；建议**只移植「停车状态监测 + 事件记录」层**，明确放弃「运动检测告警」语义，**整体 no-go** 原样移植。

---

## 2. 问题定义

| 维度 | 值 | 证据 |
|---|---|---|
| 源 fork | StarPilot，`openpilot/starpilot/sentry_mode/`，1593 行（实测 `wc -l *.py`） | 见 §3.1 |
| 目标 fork | `E:\sp`，分支 `master`，HEAD `a147321237` | `git branch --show-current` / `git log --oneline -5` |
| 硬件 | comma C3（AGNOS，`COMMA_HARDWARE`），设备 `192.168.7.246`（SSH 只读） | `openpilot/system/hardware/__init__.py:11` `TICI = os.path.isfile('/TICI')` |
| 车型 | 丰田纵深（Toyota），控制权归属主理人 | 任务背景 |
| 环境 | Windows 开发机 + C3 设备 | 任务背景 |

---

## 3. 证据来源

### 3.1 StarPilot 源侧（实际读取，非推测）

```
$ wc -l E:/StarPilot/openpilot/starpilot/sentry_mode/*.py
    1 __init__.py
   14 actions.py
  589 notifications.py
  163 policy.py
   82 preferences.py
  214 runtime.py
  113 status.py
  332 storage.py
   85 web_push.py
 1593 total
```

- `E:\StarPilot\openpilot\starpilot\sentry_mode\README.md:1-9`：明确写 *"Motion detection has not yet been qualified on a physical device or vehicle."*，且 *"Sentry never starts another sensor, camera or power service."*
- `policy.py:12-17`：`ARM_DELAY_SECONDS = 90.0`、`LOOP_INTERVAL_SECONDS = 0.1`、`ALARM_TRIGGER_COUNT = 25`、`ALARM_TIME_SECONDS = 30.0`、`RESET_TIME_SECONDS = 60.0`
- `policy.py:60-72`：`Inputs` 字段 = `enabled / offroad / voltage_ok / device_fresh / ignition_off / sample`
- `policy.py:127-141`：判据是 **加速度模长变化的 delta**（`abs(magnitude - previous) <= sensitivity` → 不计触发）
- `runtime.py:110-131`（`_authority`）：依赖 `deviceState` / `pandaStates` / `peripheralState` + `IsOffroad` / `DoShutdown` 参数 + `p.ignitionLine or p.ignitionCan`
- `runtime.py:133-155`（`_sample`）：依赖 `accelerometer` 消息，`event.timestamp` + `sm.logMonoTime["accelerometer"]` 双时钟校验
- `runtime.py:198-208`（`main`）：`SubMaster(["accelerometer", "deviceState", "pandaStates", "peripheralState"])`，10 Hz tick
- `runtime.py:210-217`：`CameraSnapshot()` 抓 `("wide", "cabin")` 两路图 → **依赖 Galaxy 双摄**
- `storage.py:19-25`：`MAX_EVENTS = 512`，事件字段 `{version, eventId, sessionId, kind, monoTimeNs, wallTimeNs}`，`kind ∈ ("warning","alarm","selfie")`
- `storage.py:174-186`：`images` 校验要求 JPEG 头 `\xff\xd8` / 尾 `\xff\xd9`
- `preferences.py:14`：`KEY = "SentryMotionPreferences"`，`MAX_BYTES = 512`
- `notifications.py:28`：`APP_IDS = ('com.starpilot.galaxy', 'link.firestar.companion', 'link.galaxy.bluetooth.natehubby76')` → **强绑 Galaxy 手机生态**
- `notifications.py:37`：`CHANNELS = ('webPush', 'discord', 'webhook', 'ntfy', 'appPush')`
- `web_push.py:1`：自实现 RFC8291/8292 VAPID（`cryptography` 依赖）
- StarPilot 进程注册：`E:\StarPilot\openpilot\system\manager\process_config.py:127-128`（`sentry_motion`）、`:136-138`（`sensord_run` = `started or sentry_motion`）、`:173-174`（`sensord` + `sentry_motion` 两条）
  - **关键**：StarPilot 为 sentry 专门把 `sensord` 从 `only_onroad` 改成 `sensord_run`，让 IMU 在停车时继续跑。

### 3.2 我方 fork 现状（实际读取）

**消息契约**
- `openpilot/cereal/custom.capnp` 共 1501 行，33 个顶层 struct（`grep -n "^struct" openpilot/cereal/custom.capnp`）
- `openpilot/cereal/log.capnp:6` `using Custom = import "custom.capnp";`
- `openpilot/cereal/log.capnp:2734-2736`：
  ```
  customReserved17 @143 :Custom.CustomReserved17;
  customReserved18 @144 :Custom.CustomReserved18;
  customReserved19 @145 :Custom.CustomReserved19;
  ```
- `openpilot/cereal/custom.capnp:1242-1247`：`CustomReserved17 @0xa30662f84033036c {}` 与 `CustomReserved18 @0xc86a3d38d13eb3ef {}` **均为空 struct**
- **全仓无任何使用者**（可复算）：
  ```
  $ grep -rn "customReserved17\|customReserved18\|CustomReserved17\|CustomReserved18" --include=*.py --include=*.cc --include=*.h .
  （无输出）
  $ grep -n "customReserved17\|customReserved18\|customReserved19" openpilot/cereal/services.py
  128:  "customReserved19": (True, 4., 1),  # liveTorqueParametersSP, published by torqued_ext
  ```
  → **customReserved17 / customReserved18 两个槽位完全空闲**，可直接占用（不必追加新 ordinal）。
- `openpilot/cereal/AGENTS.md:36-46` 明确写了「THE RESERVED-SLOT PATTERN」：认领 `CustomReservedN` 的方式是**重命名 struct + 重命名 union member，ordinal 与 `@0x` id 都不动**，禁止新增 struct。
- Event union ordinal 占用实测（脚本解析 `struct Event` 花括号配对）：
  ```
  used ordinals: 0..154 连续无空洞
  gaps: []
  ```
  → **Event union 已无空缺 ordinal**，新消息必须走 reserved-slot 重命名路线，不能追加。
- `openpilot/cereal/messaging/tests/validate_sp_cereal_upstream.py:104-121`：CI 兼容门禁只检查「union variant 上游是否存在」；**non-union struct 内部加字段是安全的**（capnp 向前兼容）。
- `openpilot/cereal/SConscript:6`：`schema_files = ['log.capnp', 'deprecated.capnp', 'custom.capnp']`，新增 capnp 文件需改这里。

**Params**
- `openpilot/common/params_keys.h:41` `{"DoShutdown", {CLEAR_ON_MANAGER_START, BOOL}}`
- `openpilot/common/params_keys.h:80` `{"IsOffroad", {CLEAR_ON_MANAGER_START, BOOL}}`
- `openpilot/common/params_keys.h:290` `{"SunnylinkDongleId", {PERSISTENT, STRING}}`
- `openpilot/common/params_keys.h:293` `{"SunnylinkEnabled", {PERSISTENT, BOOL, "1"}}`
- `openpilot/common/params_keys.h:586` `{"CarrotEnabled", {PERSISTENT | BACKUP, BOOL, "0", std::nullopt, 1, SETTINGS_SIMPLE}}`
- **无任何 `Sentry*` 键**：`$ grep -rn "sentry\|Sentry" --include=*.py --include=*.capnp --include=*.h --include=*.json .` 仅命中 `sentry.io` / `sentry_sdk` 的无关残留。
- `openpilot/sunnypilot/common/param_read.py:47-107` 已提供 `read_bool / read_float / read_str`（未注册键安全降级），**必须用它读新键**。

**进程**
- `openpilot/system/manager/process_config.py:338`：
  ```
  PythonProcess("sensord", "openpilot.system.sensord.sensord", only_onroad, enabled=not PC),
  ```
  → **我方 sensord 只在 onroad 运行**（与 StarPilot 的 `sensord_run` 不同）。
- `openpilot/system/manager/process_config.py:321` `camerad` 门控 = `or_(driverview, livestream, onroad_preview)` → **停车时 camerad 不跑**
- `openpilot/system/manager/process_config.py:75-76` `qcomgps` = `started and not ublox_available()` → **停车时 GPS 不跑**
- `openpilot/system/manager/process_config.py:87-88` `only_onroad(started) = started`
- `openpilot/system/manager/process_config.py:398` `modeld_tinygrad` / `:329` `modeld` → **停车时模型不跑**
- `openpilot/system/manager/process_config.py:441` `hardwared` = `always_run` → **停车时 hardwared 常驻**（发 `deviceState` 2 Hz、`peripheralState` 来自 pandad）
- `openpilot/selfdrive/pandad/pandad.cc:311-332` `send_peripheral_state()` → `pm->send("peripheralState", msg)`
- `openpilot/selfdrive/pandad/pandad.cc:456` `PubMaster pm({"can", "pandaStates", "peripheralState"})`
- `openpilot/system/hardware/hardwared.py:205` `pm = messaging.PubMaster(['deviceState'])`，`hardwared` = `always_run`
- `openpilot/system/hardware/hardwared.py:206` `sm = messaging.SubMaster([... "pandaStates" ...], poll="pandaStates")`
- `openpilot/system/hardware/hardwared.py:124-152` `touch_thread` 常驻线程，读 `/dev/input/by-path/platform-894000.i2c-event` → **`touch` 消息停车时也在发**
- `openpilot/system/hardware/hardwared.py:20` `from openpilot.selfdrive.selfdrived.alertmanager import set_offroad_alert`
- `openpilot/system/manager/manager.py:192` `params.put_bool("IsOffroad", True, block=True)`；`:221` 随 started 变化更新
- `openpilot/system/hardware/power_monitoring.py:16` `MAX_TIME_OFFROAD_S = 30*3600`（30 小时后强制断电）
- `openpilot/system/hardware/power_monitoring.py:122-131` 低压 / 超时 → `should_shutdown`
- `openpilot/selfdrive/pandad/pandad.cc:266-268` `power_save_desired = !ignition_local` → **熄火后 panda 进省电**

**相机 / 传感器**
- `openpilot/system/camerad/cameras/hw.h:60-66`：
  ```
  const CameraConfig CABIN_CAMERA_CONFIG = {
    .camera_num = 2,
    .stream_type = VISION_STREAM_CABIN,
    .publish_name = "cabinCameraState",
    .enabled = !getenv("DISABLE_DRIVER"),
  ```
- `openpilot/system/camerad/cameras/spectra.cc:284-286` 注释：*"A camera that is disabled by configuration (e.g. DISABLE_DRIVER on comma 3, **which has no cabin camera**)"*
  → **comma 3 无座舱摄像头**（只有 TICI 才有 driver camera）。这是本次评审最关键的一条硬件结论。
- `openpilot/system/sensord/sensord.py:113` `(LSM6DS3_Accel(I2C_BUS_IMU), "accelerometer", True)` → 我方 sensord 是 **Python 版**（非 StarPilot 的 C++ `sensors_qcom2.cc`）
- `openpilot/system/sensord/sensord.py:38` 注释：*"the gyro and accelerometer share an IRQ due to the comma three routing only one GPIO"*
- `openpilot/cereal/log.capnp:2620` `accelerometer @98 :SensorEventData;`，`:292-307` `SensorEventData` 含 `acceleration @4 :SensorVec`
- `openpilot/cereal/log.capnp:544-549` `PandaState` 含 `ignitionLine @2 :Bool` / `ignitionCan @13 :Bool`
- `openpilot/cereal/log.capnp:702-707` `PeripheralState` 含 `voltage @1 :UInt32`
- `openpilot/cereal/log.capnp:455` `carBatteryCapacityUwh @25 :UInt32`
- `openpilot/cereal/log.capnp:444` `started @11 :Bool`
- `openpilot/cereal/services.py:25` `"accelerometer": (True, 104., 104)`

**通知 / UI**
- `openpilot/sunnypilot/carrot/server/features/push.py:1-6` 注释：*"Web Push + PWA endpoints (Galaxy-inspired, StarPilot MIT). The phone installs the panel as a PWA and subscribes to push"* → **我方已有 Galaxy 生态的替代品：carrot PWA Web Push**
- `openpilot/sunnypilot/carrot/server/features/push.py:103` `send_push(sub, payload, vapid_keys, session)`
- `openpilot/sunnypilot/carrot/server/services/web_push.py:103-121` `async def send_push(subscription, payload, vapid_keys, session)` → **已经是 async，签名与 StarPilot 的 `web_push.py` 语义兼容**
- `openpilot/sunnypilot/carrot/server/features/push.py:28-40` `WebPushSubscriptions` 存 Params
- **但**：`$ grep -rn "send_push" --include=*.py openpilot/` 只有 `features/push.py:100`（handle_test）与 `services/web_push.py:103`（定义）→ **生产代码里没有任何地方真正调用 send_push**，只有测试按钮会推。
- `openpilot/selfdrive/selfdrived/alertmanager.py:17-22` `set_offroad_alert(alert, show_alert, extra_text)` → `Params().put(alert, a, block=True)`；`:13-14` 读 `alerts_offroad.json`
- `openpilot/selfdrive/selfdrived/alerts_offroad.json` — 现有 offroad 告警清单（`Offroad_TemperatureTooHigh` / `Offroad_ConnectivityNeeded` / …），**无 sentry 条目**
- `openpilot/selfdrive/ui/widgets/offroad_alerts.py:20-58` `OFFROAD_ALERT_TEMPLATES` 需同步登记文案（走 `tr_noop`）
- `openpilot/sunnypilot/sunnylink/settings_ui.json` — 9 个 panel，widget 类型统计：`toggle × 80, option × 23, multiple_button × 18, info × 1` → **有 toggle 载体**
- `openpilot/sunnypilot/carrot/tests/audit_ui_reach.py:1-45` — 已有 UI 入口审计机制；`:34-38` 定义 control path 范围（`openpilot/selfdrive/controls` + `openpilot/sunnypilot/selfdrive/controls` 里的 `"Carrot*"` 字面量 + `params_keys.h` 注册）
- `openpilot/selfdrive/ui/mici/layouts/offroad_alerts.py` — C3 的 mici UI 有 offroad 告警页
- `openpilot/common/hardware/comma/hardware.py:420-435` `has_builtin_display()`（受 `WebuiHeadlessMode` 影响）→ C3 有内置屏
- `openpilot/selfdrive/ui/ui.py:12-16` `MiciMainLayout` / `MiciMainLayoutSP` → **C3 走 mici 布局**
- `openpilot/selfdrive/ui/ui_state.py:27` `BACKLIGHT_OFFROAD = 65 if HARDWARE.get_device_type() == "mici" else 50` → **C3 停车时背光降到 65%，屏是亮的**（重要：本地屏提示可行）

**其它**
- `openpilot/sunnypilot/common/parked_evidence.py` — **我方已有 StarPilot `parked_evidence.py` 的移植**（含 `fresh_offroad` / `fresh_parked` / `ParkedEvidenceCollector`），可直接复用
- `openpilot/sunnypilot/selfdrive/selfdrived/conditional_experimental_mode.py`（373 行）— 「纯状态机 + 参数门控 + 不直接改控制律」先例，**结构上最接近本次要移植的 policy 层**
- `openpilot/selfdrive/selfdrived/selfdrived.py:714-740` — 已有的 accelerometer IMU impulse 消费（impact dashcam），证明 accelerometer 在 onroad 可用
- **无 `saved_source.py` / `saved_document.py` / `stored_artifacts.py`**：`$ find . -name "saved_source.py" -o -name "saved_document.py" -o -name "stored_artifacts.py"` → 无输出 → StarPilot 的「精确字节源」基建缺失
- **无 `starpilot/storage.py`** → `starpilot_storage_root()` 不存在
- **无 galaxy 目录**：`$ find . -type d -name "galaxy*"` → 无输出

---

## 4. 已验证 / 推断 / 待确认

### 4.1 已验证（静态代码阅读，可复算）

| # | 结论 | 复算命令 |
|---|---|---|
| V1 | StarPilot sentry_mode 共 1593 行，核心可移植层 904 行（policy 163 + storage 332 + status 113 + preferences 82 + runtime 214） | `wc -l E:/StarPilot/openpilot/starpilot/sentry_mode/*.py` |
| V2 | StarPilot 自己在 README 承认运动检测**未在实车/实机验证** | `cat E:/StarPilot/openpilot/starpilot/sentry_mode/README.md` |
| V3 | StarPilot 需在停车时保持 sensord 运行 | `E:/StarPilot/openpilot/system/manager/process_config.py:136-138,173-174` |
| V4 | 我方 sensord 是 `only_onroad`，停车时不跑 → **无 accelerometer** | `grep -n "sensord" openpilot/system/manager/process_config.py` → `:338` |
| V5 | **comma 3 无座舱摄像头**（`DISABLE_DRIVER`） | `openpilot/system/camerad/cameras/spectra.cc:284-286` + `hw.h:66` |
| V6 | 我方 camerad 停车时不跑 | `openpilot/system/manager/process_config.py:321` |
| V7 | 我方 GPS 停车时不跑 | `openpilot/system/manager/process_config.py:75-76` |
| V8 | Event union ordinal 0..154 **连续无空洞**，无空缺槽 | 见 §3.2 脚本 |
| V9 | `customReserved17 @143` / `customReserved18 @144` 两槽**空 struct 且全仓无人使用** | `grep -rn "customReserved17\|customReserved18" --include=*.py --include=*.cc --include=*.h .` → 无输出 |
| V10 | 我方已有 `parked_evidence.py` 移植（`fresh_parked` 等） | `openpilot/sunnypilot/common/parked_evidence.py` |
| V11 | 我方已有 carrot PWA Web Push 实现（async `send_push`），但**生产代码无调用点** | `grep -rn "send_push" --include=*.py openpilot/` → 仅 2 处 |
| V12 | C3 停车时背光 65%（屏未熄），mici 有 offroad 告警页 | `openpilot/selfdrive/ui/ui_state.py:27` + `openpilot/selfdrive/ui/mici/layouts/offroad_alerts.py` |
| V13 | `params_keys.h` 无任何 Sentry 键；`saved_source.py`/`saved_document.py`/`stored_artifacts.py`/`starpilot/storage.py` 在我方**不存在** | 上述 grep/find 全部无输出 |
| V14 | StarPilot sentry 强绑 Galaxy App（3 个 APP_IDS）+ 5 个推送通道 | `notifications.py:28,37` |
| V15 | 我方 UI 设置面支持 `toggle` widget（80 个） | `settings_ui.json` widget 统计 |

### 4.2 推断（基于代码的合理推断，需设备/实车确认）

| # | 推断 | 依据 |
|---|---|---|
| I1 | C3 停车时 IMU 若需常驻，会与 pandad 省电策略冲突（熄火即 `power_save`），可能唤醒 I2C 总线导致电量上升 | `pandad.cc:266-268` + `power_monitoring.py:122-131` |
| I2 | 若把 sensord 门控改成 `started or sentry_enabled`，与 `camerad`/`modeld`/`qcomgpsd` 的 onroad-only 策略不一致，会形成「半开」配置（只有 IMU 醒着） | process_config 门控族对比 |
| I3 | C3 无 cabin camera 意味着「车内有人」这一判据在**不新增硬件**前提下无法直接实现；唯一可行的近似是 cabin camera 缺失时的替代物 —— 但 C3 没有 cabin camera，所以连近似都没有 | V5 |
| I4 | `touch` 消息（hardwared 常驻线程）可作为「有人触碰设备」的弱信号，但只在触摸屏被物理触碰时触发，无法覆盖「车内有人但没碰屏」 | `hardwared.py:124-152` |
| I5 | StarPilot 的 `storage.py` 大量使用 `fcntl` / `os.O_NOFOLLOW` / `dir_fd` 等 POSIX 语义，在 Windows 开发机上不可运行，但**设备端是 Linux**，移植无平台障碍 | storage.py 全文 |
| I6 | 我方 30 小时 offroad 强制断电（`MAX_TIME_OFFROAD_S = 30*3600`）会成为哨兵时长的硬上限 | `power_monitoring.py:16` |

### 4.3 待确认（需设备/实车验证）

| # | 待确认项 | 验证方法 |
|---|---|---|
| U1 | C3 实机是否**确实**没有 cabin camera（代码注释说没有，但需硬件确认） | SSH `192.168.7.246`：`ls /dev/video*`、`dmesg \| grep -i os04`，或查 `cabinCameraState` 是否有帧 |
| U2 | 熄火后 panda 省电状态下 I2C 上的 LSM6DS3 是否还能读出有效加速度 | 设备上实测读 `i2c-get`/启用 sensord 观察 `accelerometer` 消息 |
| U3 | C3 停车时 `peripheralState.voltage` 的实际值与跌落曲线 | 记录 12 小时 offroad 的 voltage |
| U4 | 手机端 carrot PWA Web Push 在 C3 无网络（4G 弱）时的可达性 | 实车/实机推送测试 |
| U5 | `carrot_server`（7000）在 offroad 时是否可用（应是，always_run） | `curl -s --noproxy '*' http://127.0.0.1:7000/api/params` |

---

## 5. 逐题回答

### 5.1 通知通道选型

**推荐组合（三层分层，各司其职）：**

| 层 | 通道 | 承载内容 | 理由 | 证据等级 |
|---|---|---|---|---|
| **L1 本地屏** | raylib mici UI（`Offroad_` 告警机制）+ 可选蜂鸣 | 「哨兵已武装 / 检测到活动 / 异常」 | C3 有内置屏且停车时背光 65% 未熄；已有成熟的 `set_offroad_alert` → Params → mici offroad 页链路；**不依赖任何手机生态** | 静态代码已验证 |
| **L2 设备事件流** | **cereal 消息**（reserved slot `customReserved17`） | 哨兵状态机迁移（arming/armed/warning/alarm/disarmed） | 事件是「机器对机器」的事实通道，是唯一能让 UI / web / 云 / 日志都消费同一事实的载体；我方已有 `carrotManSP` / `carrotNaviSP` 等先例 | 静态代码已验证 |
| **L3 远程推送** | **carrot PWA Web Push**（复用 `openpilot/sunnypilot/carrot/server/services/web_push.py`） | 仅 `warning` / `alarm` 两级，终态事件 | 我方已有完整 VAPID + `send_push` 实现（async 签名与 StarPilot 兼容）；手机装 PWA 即可，**不需要 App** | 静态代码已验证（生产调用点待补） |
| **L4 Web UI** | 7000 carrot 面板新页 | 事件列表 / 历史 / 开关 | 7000 是 CarrotPilot 生态的主通道（`always_run`），与 phone app 同一产品面 | 静态代码已验证 |

**明确不推荐：**
- ❌ **sunnylink 推送**：`SunnylinkEnabled` 默认 `"1"`（`params_keys.h:293`），但 sunnylink 是 **sunnypilot 官方 App 的云服务**（`SUNNYLINK_API_HOST = https://stg.api.sunnypilot.ai`，`api.py:20`），且我方 fork 的实际用户群在 carrot 生态（7000/7705/phone app），不是 sunnypilot App。往 sunnylink 塞哨兵事件会：
  1. 绑定到与用户实际使用的 App 不同的通道；
  2. 引入对 `stg.api.sunnypilot.ai` 的隐私外发（事件元数据 + 位置），需单独合规评估；
  3. `sunnylink` 的 settings 面在 `settings_ui.json` 里是**远端可配置**的 schema，改它会影响 App 端渲染 —— 成本远高于收益。

  → **若将来要接 sunnylink，作为 L3 的一个并行通道，而不是替代 L3。**

- ❌ **StarPilot `notifications.py`（589 行）直接移植**：绑定 `APP_IDS`（Galaxy 专用）、Discord/ntfy/webhook 需要用户自备账号与外部服务、白名单 IP 与 TLS 策略与 AGNOS 设备环境不匹配。**整层丢弃。**

- ❌ **只做 Web UI 不做本地屏**：车机屏是唯一「人不在车里也能立刻看到」的通道（车内有人时人就在屏前）。7000 Web UI 在停车时通常无人打开。

**结论**：**L1 本地屏（主）+ L2 cereal 事件（事实源）+ L3 carrot PWA Web Push（远程）** 三层，**L4 Web UI 作为历史查看**。sunnylink 不进第一批。

---

### 5.2 cereal 消息契约设计

#### 5.2.1 放 `custom.capnp` 还是新文件？

**放 `custom.capnp`，通过认领 reserved slot 重命名实现。** 理由：

1. `openpilot/cereal/AGENTS.md:36-46` 明确写死了这条路：*"In custom.capnp, rename the lowest free struct ... keeping the line's `@0x...` verbatim"*，并把「新增 struct/field 给 fork 特性」列为 ANTI-PATTERN（*"otherwise the next upstream rebase collides"*）。
2. Event union ordinal **0..154 无空洞**（V8），追加新 ordinal 只能从 155 起 —— 这会与上游未来新增冲突，且触犯 AGENTS.md。
3. `customReserved17 @143` / `customReserved18 @144` **结构体是空的且全仓无人使用**（V9）→ 零冲突成本。
4. 新建 `sentry.capnp` 需要改 `openpilot/cereal/SConscript:6` 的 `schema_files` + 新增 union member，而 union member 仍需 ordinal → 一样要碰 `log.capnp`。**没有省事，且违反本仓约定。**

#### 5.2.2 ID 分配规则

- **不改 `@0x` id**：`customReserved17 @0xa30662f84033036c` 保持原样，只改 struct 名。
- **不改 ordinal**：`customReserved17 @143` 保持 `@143`，只改 union member 名。
- **字段 ordinal 只追加**，从 `@0` 起，不复用、不重排。

#### 5.2.3 capnp 草案

**Step 1 — `openpilot/cereal/custom.capnp`：**

把
```capnp
struct CustomReserved17 @0xa30662f84033036c {
}
```
改为
```capnp
# Sentry: parked-state monitoring events (openpilot/sunnypilot/sentry/).
# Claimed from the empty customReserved17 slot: the @0x id and the union
# ordinal @143 stay untouched, so upstream compatibility is unaffected.
struct SentryStateSP @0xa30662f84033036c {
  version @0 :Int32;            # schema version of this message (1)
  state @1 :SentryState;       # the state machine's current state
  eventId @2 :Text;             # unique id of the event that caused this state, "" if none
  sessionId @3 :Text;           # one id per daemon lifetime; binds a state to its run
  monoTimeNs @4 :Int64;         # CLOCK_MONOTONIC ns at the transition
  wallTimeNs @5 :Int64;         # CLOCK_REALTIME ns; NOT proof of an accurate wall clock
  # Why the state machine is in this state (the disarmed reason, the blocking
  # authority check, ...). Empty string when there is nothing to explain.
  reason @6 :Text;

  enum SentryState {
    disabled @0;          # the feature switch is off
    disarmed @1;          # parked, but one of the authority checks failed
    arming @2;            # counting down to the arming delay
    armed @3;             # watching
    warning @4;           # a motion/activity event crossed the warning threshold
    alarm @5;             # the event crossed the alarm threshold
    error @6;             # the daemon cannot observe (sensor/state unavailable)
  }
}
```

**Step 2 — `openpilot/cereal/log.capnp`（union member 重命名，ordinal 不动）：**
```capnp
    customReserved17 @143 :Custom.CustomReserved17;   →    sentryStateSP @143 :Custom.SentryStateSP;
```

**Step 3 — `openpilot/cereal/services.py`：**
```python
  # Sentry: parked-state monitoring events (openpilot/sunnypilot/sentry/).
  # Frequency 2 Hz matches the state machine's slowest meaningful change rate;
  # the daemon only publishes on transitions, so decimation 1 keeps every event.
  "sentryStateSP": (True, 2., 1),
```

**Step 4 — 构建**：`scons` 重新生成 `gen/` 与 `services.h`（**禁止手改或提交生成物**，`cereal/AGENTS.md` ANTI-PATTERNS 明列）。

#### 5.2.4 契约要点与兼容性论证

| 事项 | 结论 | 依据 |
|---|---|---|
| 上游可解析性 | **安全**：`Event` union 新增了一个上游不认识的 variant → 但 `validate_sp_cereal_upstream.py:104-121` 只在「**同一个 typeId 的 struct 且含 union**」时报违规；`SentryStateSP` 是**新 typeId**（虽然 `@0x` 沿用旧空 struct 的 id —— 见下） | ⚠️ 见下方风险 |
| ⚠️ `@0x` id 复用风险 | `customReserved17` 的 id `0xa30662f84033036c` 在上游**也是一个已知 typeId**（空 struct）。把它改造成带字段的 struct，上游读到时字段是未知的 → capnp 对「未知字段」是**向前兼容忽略**，安全；但上游对该 typeId 的 `hasUnion` 判断会变化 —— `SentryStateSP` 内含 `enum` 字段但**不含 union**（enum 是普通字段不是 union），所以 `hasUnion=False` → **不触发 CI 门禁** | `validate_sp_cereal_upstream.py:104-107` 只看 `hasUnion` |
| 字段 ordinal 只追加 | 安全。capnp 允许 struct 内追加字段，旧 log 读到新 schema 时新字段为默认值 | `cereal/AGENTS.md` "Appending is safe" |
| `version` 字段 | 保留。StarPilot 的 `storage.py` 每条事件都带 `version: 1`，语义一致 |
| 量纲 | `monoTimeNs` / `wallTimeNs` 是 **ns 整数**，与 StarPilot `storage.py:22` 的 `monoTimeNs` / `wallTimeNs` 一致；`reason` 是文本（不是枚举）→ 允许扩展原因而不动 ordinal |
| 无位置数据 | **刻意**：不写 lat/lon。StarPilot 自己也强调 *"There are no image paths, location data or network requests"*（README） | 隐私 |
| 无图像路径 | **刻意**：C3 无 cabin camera（V5），且不该在 cereal 里传图 | — |

**一个必须显式记录的取舍**：把 `customReserved17`（一个上游已知的空 typeId）改造成带字段的 struct，虽然 capnp 向前兼容规则下安全，但**破坏了「保留槽永远为空」的上游不变量**。本仓的 `customReserved19` 已经这么干过（`custom.capnp:1250-1268` 已被 zoompilot 填满），所以这是**本仓既有先例**，可接受。但必须在 PR 里写明。

**备选方案（更保守）**：若评审组认为复用上游 typeId 不可接受，则**放弃 cereal 承载状态机**，改为：状态机状态经由 **Params（JSON）** 暴露给 UI / Web（`Params` 已有 JSON 类型，`params_keys.h:16` 等大量先例），cereal 只在**最终批（见 §5.5）**才引入。
→ **我的建议：走 §5.2.3 的 reserved-slot 方案，因为它是本仓 AGENTS.md 明确指定的唯一路径，且 customReserved19 已有先例。**

---

### 5.3 进程归属

**推荐：独立进程 `openpilot/sunnypilot/sentry/sentryd.py`，注册进 `process_config.py`。**

理由（对照四个候选）：

| 候选 | 评估 |
|---|---|
| **复用 `selfdrived`** | ❌ **强烈反对**。`selfdrived` 是 `only_onroad`（`process_config.py:354`），停车时不跑 —— 哨兵的核心价值就是停车时工作。而且 selfdrived 是控制链路的一部分，其崩溃会留下控车输出空档（`process_config.py:16-17` 注释明确说控制链**永不**被 watchdog 拉起）。把哨兵塞进去 = 把一个非控车功能挂到控车进程上。 |
| **复用 `hardwared`** | ❌ hardwared 是 `always_run`（`process_config.py:441`），停车时确实在跑 —— 但它是**电源/热管理守护**，塞入哨兵状态机会污染它的关闭判定语义，且 hardwared 已有 `DoShutdown`/低压断电职责，哨兵的"延长停车时长"诉求会与它直接冲突（这是 StarPilot 明确不做的事：README *"Sentry neither extends parked runtime nor clears shutdown requests"*）。 |
| **复用 `carrot_man` / `carrot_server`** | ❌ carrot 进程是**导航/手机投影**域，`always_run` 但业务无关；哨兵塞进去会让 carrot_man 的 crash 影响面扩大到安全域。 |
| **独立 `sunnypilot/sentry/` 进程** | ✅ **推荐**。① 生命周期与哨兵语义一致（offroad-only 或 always_run+自门控）；② 崩溃不影响控车链；③ 与 StarPilot 的 `sentry_motion` 进程一一对应，移植映射清晰（StarPilot `process_config.py:174`）；④ 后续加 push / storage 不会污染别的进程。 |

#### 3.1 进程门控设计

```python
# openpilot/system/manager/process_config.py
def sentry_enabled(started: bool, params: Params, CP: car.CarParams) -> bool:
  """Sentry parked-state monitoring: offroad only, and only when the user
  turned it on. Never runs onroad: the car is moving, there is nothing to watch.
  """
  return not started and params.get_bool("SentryEnabled")
```
```python
procs += [
  # Sentry: parked-state monitoring. Offroad-only + opt-in; it publishes
  # sentryStateSP and records events, it never touches the control path.
  PythonProcess("sentryd", "openpilot.sunnypilot.sentry.sentryd", sentry_enabled,
                enabled=not PC, restart_if_crash=True),
]
```

**门控三态**（必须写清楚，避免"以为开了"）：

| 状态 | 行为 |
|---|---|
| `SentryEnabled=0`（默认） | 进程**根本不启动** → 零资源开销、零电量影响 |
| `SentryEnabled=1` + onroad | 进程**不启动**（`not started`）→ 行驶中无哨兵开销 |
| `SentryEnabled=1` + offroad | 进程启动 |

> 这比 StarPilot 的 `sentry_motion` 更严格：StarPilot 的 `sentry_motion` 门控是 `not started and sentry_enabled(params)`（`process_config.py:127-128`），语义一致。**但 StarPilot 额外改了 `sensord` 门控让 IMU 停车常驻（`sensord_run`），我方不做这个改动**（见 §5.4）。

#### 3.2 最小组件清单

| 组件 | 需要 | 说明 |
|---|---|---|
| **Params** | ✅ 必须 | `SentryEnabled`（BOOL）、`SentryEventLog`（JSON，事件列表）、可能 `SentryPreferences`（JSON）。**新键必须进 `params_keys.h` 并重编 `libparams_c.so`**（`params/param_read.py:1-27` 说明未注册键会抛 `UnknownKeyName`）。读取一律用 `openpilot/sunnypilot/common/param_read.py` 的 `read_bool`/`read_str`。 |
| **cereal sub** | ✅ 必须 | `deviceState`（2 Hz，hardwared 发）、`pandaStates`（10 Hz，pandad 发）、`peripheralState`（2 Hz，pandad 发）、`touch`（可选，hardwared 触摸线程发）。**不订阅 `accelerometer`**（见 §5.4）。 |
| **cereal pub** | ✅ 必须 | `sentryStateSP`（2 Hz 上限，仅在状态迁移时发）。 |
| **相机** | ❌ 不需要 | C3 无 cabin camera；不启 camerad。 |
| **IMU** | ❌ 不需要（第一批） | 我方 sensord 是 `only_onroad`；为哨兵改 sensord 门控属于**新增硬件唤醒路径**，越界（见 §5.4）。 |
| **网络** | ❌ 进程本身不需要 | 推送由 7000 侧（carrot_server）消费 `sentryStateSP` 后触发，不让 sentryd 直接出网 —— 遵循 StarPilot 的 *"no network requests"* 原则。 |
| **文件存储** | ✅ 需要（可选） | 事件持久化用 Params JSON 或 `/data/media/0/...` 下的私有目录；**不建议**照搬 StarPilot 的 `storage.py`（332 行、纯 POSIX `dir_fd`/`flock`/`O_NOFOLLOW`），理由见 §5.5。 |

---

### 5.4 触发条件的传感器来源 —— **核心结论**

#### 5.4.1 我方在「不新增硬件」前提下能拿到的信号

| 信号 | 消息 | 停车时是否可用 | 证据 |
|---|---|---|---|
| 车辆静止 / offroad | `deviceState.started` + Params `IsOffroad` | ✅ 可用 | `manager.py:192,221`；`hardwared.py:205` always_run |
| 点火关闭 | `pandaStates[].ignitionLine` / `ignitionCan` | ✅ 可用 | `log.capnp:545,549`；`pandad.cc:456` always_run |
| 电压 / 电量 | `peripheralState.voltage` + `deviceState.carBatteryCapacityUwh` | ✅ 可用 | `log.capnp:704,455`；`pandad.cc:311-332` |
| 设备存活 | `deviceState` 新鲜度 | ✅ 可用 | `parked_evidence.py` |
| **加速度（车内活动）** | `accelerometer` | ❌ **停车时不可用** | `process_config.py:338` sensord = `only_onroad` |
| **车内图像** | `cabinCameraState` | ❌ **C3 无此相机** | `spectra.cc:284-286` *"comma 3 ... has no cabin camera"* |
| GPS 位置/速度 | `gpsLocation` / `gpsLocationExternal` | ⚠️ 我方 GPS 进程 `only_onroad`（`process_config.py:75-76`），但**手机端 carrot 可提供 `carrotManSP.xPosSpeed` / `xPosLat`** | `custom.capnp:919-921`；`carrot_man.py:1095,1098` |
| 触摸事件 | `touch` | ✅ 弱信号可用 | `hardwared.py:124-152` 常驻线程 |
| 驾驶员监控 | `driverMonitoringState` | ❌ 停车时不跑（`dmonitoringd` = `dm_process`） | `process_config.py:357` |

#### 5.4.2 判定

> **当前传感器条件下，"哨兵"（parked intrusion detection）语义不成立。**

论证：

1. **无车内存在性传感器**。哨兵的核心语义是「车停了 + 车里有人/有动静 → 告警」。我方 **C3 无座舱摄像头**（V5，代码级注释，非推测），**IMU 停车时不供电**（V4）。这两个恰是 StarPilot 用来判定的两个输入（`policy.py:60-72` 的 `sample` 来自 `accelerometer`；`runtime.py:210-217` 的 `CameraSnapshot` 抓 `wide`+`cabin`）。
2. **残余信号只能测到"物理扰动"，测不到"有人"**。即使强行让 sensord 停车常驻：
   - IMU 在停车时贴在挡风玻璃上，测到的是**车辆本身的微振动**（风、施工、路人经过车旁、行人撞击），不是"车内有人"；
   - StarPilot 自己也承认 *"Motion detection has not yet been qualified on a physical device or vehicle"*（README），且其判据是**加速度模长 delta**（`policy.py:139-141`）—— 这在真实车辆上的误报率没有任何证据支撑。
   - 更糟：StarPilot 为此专门把 `sensord` 从 `only_onroad` 改成 `sensord_run`（`process_config.py:136-138`），即**为哨兵唤醒 IMU 电源路径**。我方 `pandad.cc:266-268` 在熄火后置 panda 省电，强行唤醒 IMU 是与电源管理正面对抗，会侵蚀 offroad 续航（`MAX_TIME_OFFROAD_S = 30*3600`，`power_monitoring.py:16`）。
3. **可用信号的真实上限**：我方能可靠测到的是「车是否停着、点火是否关、电量是否够、是否被触碰/扰动」。这支撑的是 **parked-state monitoring（停车状态监测）**，**不是 intrusion detection（入侵检测）**。

#### 5.4.3 建议的可落地最小范围

**明确收缩语义：`Sentry` → `ParkedWatch`（停车看护）**，只做下列三件事，**明确不做**「检测到人/入侵」：

| 能力 | 判据 | 可用信号 | 状态 |
|---|---|---|---|
| **A. 停车状态守卫** | 车辆静止 + 点火关闭 + 电量充足 + 证据新鲜 → `armed`；任一条件失效 → `disarmed` 并给出 `reason` | `deviceState` / `pandaStates` / `peripheralState` + `parked_evidence.fresh_parked` | ✅ **可落地，语义诚实** |
| **B. 事件记录** | 状态迁移全部落盘（Params JSON / 私有目录），带 `eventId` / `sessionId` / `monoTimeNs` / `wallTimeNs` / `reason` | 无外部依赖 | ✅ **可落地** |
| **C. 冲击/扰动事件**（可选，第二批） | 检测到**车辆外部冲击**（不是车内有人）—— 这一项需要 accelerometer 停车可用 | ❌ 需改 sensord 门控 | ⚠️ **条件成立才做** |
| ~~D. 车内有人 / 入侵~~ | — | 无传感器 | ❌ **不做** |
| ~~E. 停车抓拍~~ | — | C3 无 cabin camera | ❌ **不做** |

**关于 C 的判定条件**：只有当**实机证明**熄火后 LSM6DS3 仍能输出有效数据（U2），且实测误报率可接受（连续 24h 停车、周边有车流/行人的场景），才允许做 C。**在此之前 C 明确缓行。**检测语义若最终要落地，**交给云端/手机端**（手机 App 有 GPS、相机、麦克风）—— 即「设备只上报停车状态与车机侧事件，真正的活动检测在手机端做」。

**这与主理人原始设想的"仅停车状态监测 + 事件记录，检测交给云端"一致，本评审予以支持并给出边界：设备端不做任何"有人"推断。**

---

### 5.5 移植分批建议

把 904 行核心层拆成 **4 批**，每批独立可验证、可独立回滚。

| 批次 | 内容 | 源行数 | 验收标准 | 状态 |
|---|---|---|---|---|
| **P0 契约预备**（非移植） | `params_keys.h` 加 `SentryEnabled`；`custom.capnp` 认领 `customReserved17` → `SentryStateSP`；`log.capnp` union member 重命名；`services.py` 注册 `sentryStateSP`；`scons` 重建 | 0（新增约 60 行 schema/param） | ① `scons` 通过；② `python openpilot/cereal/messaging/tests/validate_sp_cereal_upstream.py` 通过；③ 设备 `cat /data/params/d/SentryEnabled` 可读；④ `git diff openpilot/cereal/gen` 为空（生成物未提交） | **可立即做** |
| **P1 纯策略层**（无硬件、无进程） | `policy.py`（163 行）→ `openpilot/sunnypilot/sentry/policy.py`，**只保留状态机**，`Settings` 换成本地 Params 语义（`enabled` / `sensitivity` / `warningTimeSeconds` → 我方只保留 `enabled`，因为 motion 判据不做） | ~120（删掉 motion 判据后） | ① 单元测试覆盖：arming 90s 计数、任一 authority 失效即 disarm、resume 后 disarm、单调时钟回退 → `unavailable`；② **零 cereal 依赖、零 IO**（纯函数）；③ `PYTHONPATH=E:/sp python -m unittest openpilot/sunnypilot/sentry.tests.test_policy` 全绿 | **可立即做**（纯逻辑，无风险） |
| **P2 停车看护进程** | `runtime.py`（214 行）→ `openpilot/sunnypilot/sentry/sentryd.py`，**去掉 `_sample`（accelerometer）与 camera**，改为「只做 authority 判定 + 状态迁移 + 发 `sentryStateSP`」；复用我方 `parked_evidence.py` | ~150 | ① `process_config.py` 注册，**默认 `SentryEnabled=0` 时进程不启动**（用 `pgrep -af sentryd` 验证）；② 打开开关后停车 → `sentryStateSP` 从 `disarmed` → `arming` → `armed`；③ **任一 authority 失效 → 1s 内转 `disarmed` 并带 `reason`**；④ 熄火拔电/上车 → 进程存活且状态正确；⑤ **offroad 时进程 CPU < 1%**（`top`/`proclogd`） | **可做**（P1 完成后） |
| **P3 事件记录 + UI + 推送** | 事件持久化（**不复用 StarPilot `storage.py` 全部 332 行**，只借鉴其字段集与"满则停写不删旧"的语义）+ `alerts_offroad.json` 新增 `Offroad_Sentry*` + `offroad_alerts.py` 模板登记 + 7000 面板页 + carrot Web Push 接入 | ~250（含我方新写） | ① 事件记录含 `eventId`/`sessionId`/双时钟/`reason`；② **存储满 → 停止写新事件，不删旧事件**（与 StarPilot `storage.py:150-160` 语义一致）；③ 车机屏能看到 `Offroad_Sentry*` 告警；④ 7000 页面能列事件；⑤ Web Push 能收到 `warning`/`alarm`（需手机订阅 PWA）；⑥ 事件元数据**不含位置、不含图像** | **条件放行**（P2 完成后） |
| **P4 扰动检测（可选）** | `accelerometer` 停车采样 + delta 判据 | ~80 | **前置门槛**：① U2 实机确认熄火后 IMU 有效；② 24h 停车误报率实测 ≤ 1 次/天；③ 停车 12h 电量衰减 ≤ X%（需定义）；④ **三者全过才开工** | **缓行 / 默认不做** |
| **丢弃** | `notifications.py`（589）+ `web_push.py`（85） | 674 | — | **不移植**。我方已有 carrot PWA Web Push（`services/web_push.py:103-121`），签名兼容且更完整。 |
| **不移植** | `status.py`（113）、`actions.py`（14）、`preferences.py`（82） | 209 | — | **重新设计**。`status.py` 依赖 `starpilot_storage_root()`（我方不存在）；`actions.py` 依赖 `saved_document.commit_exact`（我方不存在）；`preferences.py` 依赖 `saved_source.read_saved`（我方不存在）。见下节。 |

#### 为什么 `preferences.py` / `actions.py` / `status.py` 要重写而不是直译

这三者共 209 行，全部依赖 StarPilot 的**「精确字节源」基建**，我方**不存在**：

```
$ find . -name "saved_source.py" -o -name "saved_document.py" -o -name "stored_artifacts.py"
（无输出）
$ find . -type d -name "galaxy*"
（无输出）
```

- `preferences.py:57` `read_preferences` → `read_saved(params, KEY, MAX_BYTES)`（`saved_source.py:23-49`，用 `os.open` + `O_NOFOLLOW` + inode/mtime 前后比对做"逐字节精确读"）
- `actions.py:8` → `commit_exact(params, key, max_bytes, raw, expected, authorized, temp_prefix)`（`saved_document.py`）
- `status.py:9-12` → `from openpilot.starpilot.storage import starpilot_storage_root`

而 `saved_source`/`saved_document` 存在的**唯一理由**是 StarPilot 的 Galaxy Web 面板要「一个字节一个字节精确地替换用户保存的 JSON 文档」，防止半写。我方**没有 Galaxy 面板**（有 carrot 面板 + sunnylink settings，但两者都是走 Params 的类型化读写）。

→ **我方应直接用 Params 的 JSON 类型**（`params_keys.h` 已有大量 JSON 键，如 `:16 ApiCache_FirehoseStats`、`:48 FLMActiveOverrides`）+ `openpilot/sunnypilot/common/param_read.py:read_str` 读取。这比引入 3 个 StarPilot 专属基建文件（`saved_source` 82 行 + `saved_document` + `stored_artifacts`）**更简单、更符合本仓惯例**。

#### 必须缓行的清单（明确写死）

1. **`accelerometer` 停车采样（P4）** —— 需改 `sensord` 门控 = 新增硬件唤醒路径，与 `pandad.cc:266-268` 的熄火省电正面冲突；且 StarPilot 自己都没在实车验证过。
2. **`storage.py` 的 POSIX 强化版（`O_NOFOLLOW`/`dir_fd`/`flock`/`os.link` 无覆盖发布）** —— 332 行，价值密度低。我方只需"有界 + 满则停写 + 不删旧"的**语义**，不需要全套对抗性文件系统加固。
3. **任何形式的停车抓拍** —— C3 无 cabin camera。
4. **`sunnylink` 推送接入** —— 涉及向 `stg.api.sunnypilot.ai` 外发事件元数据，需独立隐私评估 + 与用户实际 App 生态对齐的决策。
5. **`sentry` 命名本身** —— 建议改名为 `ParkedWatch`（见 §5.4.3），避免用户误解为具备入侵检测能力。

---

### 5.6 风险清单（Top 5）

| # | 风险 | 严重度 | 具体形态 | 缓解措施 |
|---|---|---|---|---|
| **R1** | **隐私 / 位置泄露** | 高 | 哨兵事件若携带 GPS 坐标或时间序列，可反推用户作息与常驻地点。StarPilot 特意做了防护：*"There are no image paths, location data or network requests"*（README）、`storage.py:22` 字段集里**没有** lat/lon。**若我方在 `SentryStateSP` 里加了 `xPosLat`，就打破了这个不变量** | ① `SentryStateSP` **禁止** lat/lon/图像字段；② `reason` 只写枚举化原因码的**文本描述**，不含坐标；③ 事件只落本地 Params/私有目录，**不出网**（推送只推 `{title, body}` 文本，不推坐标）；④ PR 评审时把"schema 字段清单"作为显式检查项；⑤ 补一个测试：序列化 `sentryStateSP` 后断言不含 lat/lon/image 字节 |
| **R2** | **电量 / 停车续航** | 高 | 为哨兵让 IMU 常驻（StarPilot 的 `sensord_run`）会在熄火后唤醒 I2C 总线，与 `pandad.cc:266-268` 的省电策略对抗；`power_monitoring.py:122-131` 的低压/超时断电会**直接杀掉哨兵**，导致"该告警时设备已断电" | ① **第一批不做 IMU**（§5.4.3 C 缓行）；② `SentryEnabled=0` 时进程**不启动**（`process_config.py` 门控），零开销；③ 状态机引入 `voltage_ok` 门控（沿用 `policy.py:127-131`），低压即 disarm；④ **绝不延长 offroad 时长**、绝不碰 `DoShutdown`（StarPilot README 明确 *"Sentry neither extends parked runtime nor clears shutdown requests"*）；⑤ 后续若做 P4，必须实测 12h/24h 停车电量曲线后再放行 |
| **R3** | **误触发 / 误报** | 中高 | 车辆外部扰动（风、施工、行人撞车、过大风导致车身晃动）会被 IMU delta 判据触发；`policy.py:139-141` 的 `abs(magnitude - previous) <= sensitivity` 判据对**安装刚度、路面、温度漂移**极度敏感。StarPilot 自己的 README 承认未在实车验证 | ① 第一批**不做 motion 判据**（§5.4.3）；② 即便做 P4，也必须**先有实机基线**（同地静止 24h 的 delta 分布），阈值取基线的 P99 再放大；③ `sensitivity` 必须走 Params 可调，**不得硬编码**；④ 保留 StarPilot 的双阈值结构（`warning` 与 `alarm` 分级，`policy.py:143-147`），并保留 `ALARM_TRIGGER_COUNT=25` + `ALARM_TIME_SECONDS=30` 的**持续性**要求（不是单次触发）；⑤ 记录所有触发事件供离线复盘（这也是 R1 里"只存元数据"仍要保留的原因） |
| **R4** | **资源占用 / 进程膨胀** | 中 | 新增一个常驻进程（即使 offroad-only）在 30 小时停车期（`MAX_TIME_OFFROAD_S`）内持续占用内存与一次调度；10 Hz tick（StarPilot `runtime.py:198-208`）在 C3 的四核上虽轻，但**不该在无事件时满速跑** | ① 默认 `SentryEnabled=0` → 进程不存在；② tick 降到 **1 Hz**（状态机的时间分辨率需求 ≤ 1s，远小于 90s arming 延迟与 30s alarm 窗口）；③ **状态迁移才发消息**（`sentryStateSP` 只在变时 pub），不做 2 Hz 满速推；④ 状态机的输入全部来自已有消息（`deviceState` 2 Hz / `pandaStates` 10 Hz），**不新增传感器订阅**；⑤ 用 `proclogd` 观察 offroad 24h 的 RSS 曲线 |
| **R5** | **权限 / 远程写入面** | 中 | StarPilot 的 `actions.py` 提供**从 Web 面板精确替换用户保存文档**的能力，且 `status.py` 有 `authorized` 回调保护。我方若照搬 `actions.py` 而不做 `authorized` 门控，就等于给 7000 面板开了一条「改哨兵配置」的写入面。`carrot_recovery` 已经因为"未认证远程 shell"被标为默认关闭（`process_config.py:216-220` 的注释是本仓的先例警示） | ① 哨兵开关**只允许本地改**（车机屏 / 7000 面板），且只写 `SentryEnabled` 一个 BOOL，**不提供任意 JSON 文档替换**；② 若将来要远程改，必须走 `authorized` 回调（重新检查停车证据）+ 只写类型化字段；③ `SentryEventLog` 只允许**进程自身追加**，任何 HTTP 面**只读**；④ 复用 `openpilot/sunnypilot/common/param_read.py` 的容错读取，未注册键安全降级；⑤ 在 `audit_ui_reach.py` 的规则下，若哨兵开关无 UI 入口，必须登记进 `docs/carrot_no_ui_switches.md` 并给出 7000 `POST /api/param_set` 的手动路径 |

**额外风险（不进 Top5 但必须记录）**

| # | 风险 | 缓解 |
|---|---|---|
| R6 | **Params 键未注册**：新键不进 `params_keys.h` 或 `libparams_c.so` 未重编 → `UnknownKeyName` 抛异常 | 读取一律走 `param_read.py` 的 `read_bool`/`read_str`；设备端用 `cat /data/params/d/SentryEnabled` 复核；重编必须 `rm -f openpilot/common/params_c.os openpilot/common/libparams_c.so` + `scons cache_dir=/tmp/nocache` |
| R7 | **capnp 生成物被提交 / ordinal 冲突** | `cereal/AGENTS.md` 明列"禁止提交 `gen/` 与 `services.h`"；`customReserved17` 是全仓唯一空闲槽（V9），认领前重跑 `grep -rn "customReserved17" .` 确认仍空闲；跑 `validate_sp_cereal_upstream.py` |
| R8 | **命名误导**：叫 `sentry` 但只做停车监测，用户以为有入侵检测 | 建议模块名 `parked_watch`，UI 文案明确"停车状态监测（不含车内入侵检测）" |
| R9 | **fork-port-audit 的静默容错地雷**：若 P4 引入 `getattr(msg, 'xxx', 0)` 掩盖"某车型/某硬件没有该字段"，会得到"移植成功但不工作" | 严格遵守 `fork-port-audit` 硬规则：写入方矩阵先行；禁止用 `getattr(..., 0)` 掩盖覆盖缺口；验收命令必须可复算 |

---

## 6. 兼容性结论汇总

| 契约面 | 结论 | 影响范围 |
|---|---|---|
| **cereal schema** | ✅ 兼容（走 reserved-slot 认领路线，ordinal 与 `@0x` 均不动；字段只追加） | 全仓 `Event` union；所有 rlog/replay 工具 |
| **Params** | ⚠️ 需重编 | `params_keys.h` + `libparams_c.so`；设备端需 `cat /data/params/d/<Key>` 复核 |
| **进程** | ⚠️ 新增 1 条 `process_config.py` 条目；**不改任何既有门控**（尤其不改 `sensord` 的 `only_onroad`） | `manager.py` 的 `ensure_running` 循环；`managerState.processes` 列表多一项 |
| **端口** | ✅ 无新增端口。7000 复用既有 carrot_server；**不引入新端口**（避免踩 `port-matrix-and-service-map` 的归属混淆） | — |
| **控车链路** | ✅ 零影响。sentryd **不订阅** `carState`/`carControl`/`controlsState`，不写任何控制参数，不在 `controlsd`/`plannerd`/`selfdrived` 里加钩子 | 控车安全域 |
| **消息频率** | ✅ 新服务 `sentryStateSP` 声明 2 Hz，实际只在状态迁移时发；`SubMaster` 的 `alive`/`freq_ok` 语义需注意 —— **零频服务会被当作"always alive"**（`messaging/__init__.py:202` `on_demand = {s: SERVICE_LIST[s].frequency <= 1e-5}`），所以 `2.` 是安全值（>0.99 才会进入频率检查） | `messaging/__init__.py:241-243` |

---

## 7. 验证矩阵

| # | 验证项 | 方法 | 门槛 |
|---|---|---|---|
| V-1 | cereal 兼容 | `python openpilot/cereal/messaging/tests/validate_sp_cereal_upstream.py --generate -f schema.json --cereal-dir openpilot/cereal` 后与上游 dump 比对 | 无 violation |
| V-2 | schema 构建 | `scons -j4` | 通过；`git status` 中 `openpilot/cereal/gen` 与 `services.h` 无改动 |
| V-3 | Params 注册 | 设备 `cat /data/params/d/SentryEnabled`；`cat /data/params/d/SentryEventLog` | 键存在、类型正确、可写可读 |
| V-4 | 进程门控 | 设备 `pgrep -af sentryd`（开关关闭时应无输出） | 关闭=无进程；打开=有进程 |
| V-5 | 状态机单测 | `PYTHONPATH=E:/sp python -m unittest openpilot.sunnypilot.sentry.tests.test_policy` | 全绿 |
| V-6 | 状态迁移 | 设备上 `cereal` 订阅或日志查看 `sentryStateSP` | offroad → `disarmed`→`arming`→`armed`；上车 → `disarmed` |
| V-7 | 权威失效 | 拔掉 GPS/断开车辆状态 | 1 s 内 `disarmed` 且 `reason` 非空 |
| V-8 | 本地屏告警 | 车机屏（mici offroad 页） | 显示 `Offroad_Sentry*` 告警 |
| V-9 | 7000 面板 | `curl -s --noproxy '*' http://127.0.0.1:7000/api/sentry/events` | 返回事件列表（仅元数据） |
| V-10 | Web Push | 手机订阅 PWA 后触发 `warning` | 手机收到通知 |
| V-11 | 资源占用 | offroad 24h，`proclogd` / `top` | RSS 与 CPU 无异常增长 |
| V-12 | UI 入口审计 | `python openpilot/sunnypilot/carrot/tests/audit_ui_reach.py --write` | 生成的 `docs/carrot_no_ui_switches.md` 与代码一致（`test_carrot_ui_reach.py` 通过） |
| V-13 | 隐私断言 | 单测：序列化 `sentryStateSP` 后断言不含 lat/lon/图像 | 通过 |
| V-14 | 事件存储上限 | 灌满事件 | 停写新事件，**旧事件不删** |

---

## 8. 回滚方案

| 层级 | 回滚动作 |
|---|---|
| **运行期** | `SentryEnabled=0` → 进程门控（`not started and get_bool("SentryEnabled")`）使其立即退出，无需重启 manager（`manager.py:232` 每秒重评估 `ensure_running`） |
| **代码期** | 删除 `process_config.py` 中 `sentryd` 一行 → manager 下个周期停进程；`sentryStateSP` 订阅方若存在需同步移除 |
| **schema 期** | `git revert` cereal 三处改动 + 重新 `scons`。**注意**：`customReserved17` 一旦被别的分支认领，需协调（这是 reserved-slot 模式的固有代价） |
| **Params 期** | `params.remove("SentryEnabled")`（键注册保留即可，不影响其它功能） |

**回滚安全性**：所有改动均为**新增**，不改任何既有进程门控、不改任何控制律、不改 `sensord` 门控 → **回滚不影响控车链路**。

---

## 9. 后续行动

| # | 行动 | 负责人 | 阻塞项 | 门槛 |
|---|---|---|---|---|
| A1 | 确认 C3 实机**确无** cabin camera（U1） | 设备验证 | — | SSH 查 `/dev/video*` + `dmesg \| grep -i os04` |
| A2 | 确认熄火后 IMU 可读性（U2） | 设备验证 | — | 实机读数 |
| A3 | **P0 契约预备**（schema + params + services） | 架构 | A1（确认无冲突后再改） | V-1 / V-2 / V-3 |
| A4 | **P1 纯策略层**（policy.py，无 IO） | 实现 | — | V-5 |
| A5 | **P2 停车看护进程**（sentryd） | 实现 | A4 | V-4 / V-6 / V-7 / V-11 |
| A6 | **P3 事件 + UI + 推送** | 实现 | A5 | V-8 / V-9 / V-10 / V-13 / V-14 |
| A7 | 命名决策：`sentry` → `parked_watch`？ | 架构 + 主理人 | — | — |
| A8 | 500 行的 `storage.py` 替代方案设计（Params JSON vs 私有目录） | 架构 | — | 与 P3 同步 |
| A9 | P4（扰动检测）立项或永久否决 | 主理人 | A2 + 实机误报率基线 | 三门槛全过 |

---

## 10. 判定汇总

| 范围 | 判定 |
|---|---|
| StarPilot `sentry_mode` **原样整体**移植 | 🔴 **NO-GO** |
| `notifications.py` + `web_push.py`（674 行）移植 | 🔴 **NO-GO**（Galaxy 生态强绑；我方已有等价实现） |
| `status.py` / `actions.py` / `preferences.py`（209 行）直译 | 🔴 **NO-GO**（依赖我方不存在的 `saved_source`/`saved_document`/`starpilot_storage`） |
| `storage.py`（332 行）直译 | 🟡 **CONDITIONAL**（只借鉴语义，重写实现） |
| `runtime.py` 含 accelerometer + camera（214 行） | 🟡 **CONDITIONAL**（第一批去掉 motion 与 camera；P4 缓行） |
| `policy.py`（163 行）移植为纯状态机 | 🟢 **GO** |
| 停车状态监测 + 事件记录（自定义精简实现） | 🟢 **GO** |
| 车内入侵检测 / 停车抓拍 | 🔴 **NO-GO**（C3 无硬件支撑） |
| sunnylink 推送接入 | 🟡 **CONDITIONAL**（需独立隐私评估 + 生态决策；不进第一批） |

**总体：CONDITIONAL-GO**，范围收窄为「停车状态看护 + 事件记录 + 本地屏/7000/carrot PWA 三层通知」，**不含任何入侵检测语义**。

---

## 11. 证据等级标注

| 等级 | 含义 | 本报告中的使用 |
|---|---|---|
| **L1 静态代码阅读** | 直接读文件确认，含行号与可复算命令 | 全部 §3 事实、V1-V15 |
| **L2 需设备验证** | 需 SSH 到 192.168.7.246 实测 | U1-U5、I1-I6、V-3 ~ V-14 |
| **L3 需实车验证** | 需在真实车辆上验证 | R2 电量曲线、R3 误报率基线、§5.6 的所有"缓解措施有效性" |
| **L4 推断** | 基于代码的合理推断，标注为「推断」 | §4.2 全部 |
