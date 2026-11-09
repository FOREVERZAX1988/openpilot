## 2026-09-15 GPS 自动时区 + 纯OP主动发送显示备注 (macan-long-0915)

### 待办确认的2项（用户已批准）均已实现

#### 1. GPS 自动时区（实现）
- 系统时间此前恒为 UTC（ai_timezone=Asia/Shanghai 只存于 AI config store，未应用到 OS/显示）。
- **实现**：
  - `ai/infra/timezone.py`：新增 `detect_timezone_from_gps(lat,lng)`——用 timezonefinder 由 WGS84 坐标反查 IANA 时区；对 `Etc/GMT+..` 生成的怪异名规范化到下拉框已知项。
  - `ai/server/runtime.py`：新增 `gps_auto_timezone_loop`——读实时 GPS fix，检测时区，与当前 `ai_timezone` 不同才写入（保守，10 分钟冷却）。
  - `ai/server/app_factory.py`：启动/清理 `gps_tz_task`。
- 验证：Shanghai/Berlin/Tokyo/LA/London/NYC 坐标命中正确；runtime/app_factory 导入干净。
- 注：GPS fix 需车辆通电/卫星锁定才有；无 fix 时保持现状不覆盖。

#### 2. 纯OP 主动发送显示设计（备注形式，未启用）
- 在 opendbc `carcontroller.py` 纯OP HUD 分支插入完整注释设计块：
  - 展示 OP 实际发送的 ACC_05.Status/FM/Mom/Verz/Loes、ACC_02.Status_Anzeige/Wunschgeschw/Abstandsindex/PrimAnz、ACC_04.Texte_Zusatz/ZielV。
  - 三种启用方式（前端 state reader / 后端 log/param / 保持注释）。
  - 标注超驰时 FM=0/Mom=0 撤力矩语义，避免误显示为激活。
- 默认关闭，不改运行行为；opendbc test_macan_mlb 33 passed + volkswagen 37 passed。

### 推送
- ai → 2cbd45c（GPS 自动时区 + 0915夜 route-scan docs）
- opendbc → 9c91671（主动发送显示备注）
- 主仓 → a6ef204d（bump 两子模块）
- 三仓均推送到远程 macan-long-0915，ls-remote 核实一致。

## 追加（macan-long-0915 续）

### 3. MacanRadarFusion 纯OP模式雷达融合修正（openpilot radard.py）
- **用户要求**：macan_radar_fusion 开关在融合模式和纯OP模式都应有意义——开=雷达参与辅助视觉（也驱动仪表盘）；关=仅视觉判定。
- **原缺陷**：radard.py `_macan_fusion_enabled()` 加了 `MacanFusionMode=1` 门控，导致纯OP模式(融合关)下雷达视觉融合被强制禁用。
- **路由实测验证（本人扫描）**：routes `00000004`、`00000049`（原厂ACC控制，bus2==bus0）在 `ACC_Status_ACC=0`(off) / `ACC_Status_Anzeige=0` 时，bus2 雷达仍持续发送真实 `ACC_Abstandsindex`(512→703)、`ACC_Gesetzte_Zeitluecke`(0→6)、`ACC_Geschw_Zielfahrzeug`(3.2–81.6 km/h)——**证实用户判断正确**：雷达即使 st=0/2(关闭/待命) 基础 idx/时距/前车速度信号仍照发。
- **修复**：移除 `MacanFusionMode` 门控，仅保留 `openpilotLongitudinalControl + MacanRadarFusion`。融合/纯OP模式均可启用雷达视觉融合。
- 测试：test_macan_mlb 33 passed, test_volkswagen 4 passed + 96 subtests。

### 4. GPS 自动时区 + OS 系统时钟统一（ai 子模块）
- **用户要求2**：一是联网自动校准，二是 OS 系统时钟也一并统一时区。
- **新增 `apply_os_timezone(tz)`**（infra/timezone.py）：把 IANA 时区写入 `/data/etc/localtime`（NA 的 /etc/localtime symlink 指向它）+ `/etc/timezone`。用 sudo cp/tee（comma 用户有 sudo，/data 为 rw ext4）。
- **接线**：
  - `server/runtime.py` GPS loop：检测到新时区后同步调用 `apply_os_timezone`。
  - `server/app_factory.py` 启动时：读保存的 `ai_timezone` 应用一次（开机即生效，不等 GPS 变化）。
  - `server/handlers/config_handlers.py`：用户手动改时区时同步应用。
- **验证**：`date` 从 UTC 变为 CST（Asia/Shanghai）；/data/etc/localtime 561 字节、/etc/timezone=Asia/Shanghai。

### 推送分支
- 主仓/子模块均走 macan-long-0915（子模块同名）。

## 追加2（macan-long-0916 目标）: 联网自动校准时区 + OS 时钟统一补强

### 5. "一联网就自动校准时区" 实现
- **新 `detect_timezone_from_ip()`**（infra/timezone.py）：用设备出口 IP 调 ip-api.com（无需 key，直接返回 timezone）。
  ```python
  detect_timezone_from_ip(timeout) -> str | None  # e.g. Asia/Hong_Kong, Asia/Shanghai
  ```
- **新 `utc_offset_hours(name)`**（infra/timezone.py）：返回 IANA 时区的 UTC 偏移（小时），用于防同偏移名称churn。
- **gps_auto_timezone_loop 升级**（server/runtime.py）：
  - 优先级：GPS fix 最准 → 无 GPS 时回退到网络出口 IP（无需点火/卫星锁定）。
  - 新增 **偏移守卫**：仅当 UTC 偏移真正改变（Shanghai+8→Tokyo+9）才覆写 ai_timezone；
    同偏移名称flip（IP 探测 Shanghai→Hong_Kong 均 +8）不 churn 用户保留的时区。
  - 检测到变化后同步 apply_os_timezone（OS 系统时钟 /etc/localtime + /etc/timezone 统一）。
- **on_wifi 触发器**（tools/domains/platform/scheduler.py + scheduler_actions.py）：
  - 新增 action `sync_timezone_wifi` —— 设备**一加入 WiFi 即触发**一次时区校准（无需等 GPS/点火）。
  - 注册为默认定时任务 `WiFi 自动校准时区`（on_wifi, 60min）。
- **启动即应用**（server/app_factory.py）：aid 启动时把保存的 ai_timezone 同步到 OS 系统时钟。
- **手动设置同步**（server/handlers/config_handlers.py）：WebUI 手动改时区立即应用 OS 时钟。

### 测试
- detect_timezone_from_ip 实测返回 Asia/Hong_Kong（当前 egress）；GPS Shanghai=Asia/Shanghai；偏移守卫正确（+8/+9/+/时区）。
- execute_scheduler_action("sync_timezone_wifi") 返回 "tz unchanged"（当前+8与IP同偏移，正确保留保存时区）。
- test_scheduler_nl_pure 2 passed；runtime/app_factory/radard 语法+导入 OK。
