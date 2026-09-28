## 2026-09-19 时间/时区权威统一（macan-long-0919）

### 用户问题
1. 之前修好的「comma 设备时间自动按网络/定位更新」合并后是否还在？
2. 现在内存占多少？
3. CarrotNtpTimeSync 跟 NTP+AI 时区冲突吗？时区跟时钟是否直接关联？哪个方案好？

### 核查结论（合并后仍在）
- **AI 联网/GPS 自动时区 + OS 时钟统一：完好**。ai 子模块 954157e（merge upstream ai main 7e55944）保留了
  `infra/timezone.py`（detect_timezone_from_gps / detect_timezone_from_ip / apply_os_timezone / utc_offset_hours）、
  `server/runtime.py::gps_auto_timezone_loop`、`server/app_factory.py` 启动应用、`scheduler_actions.sync_timezone_wifi`。
  实测生效：`ai_timezone=Asia/Shanghai`、`/etc/timezone=Asia/Shanghai`、`/data/etc/localtime` 今日 14:23 更新、`date` = CST。
- **carrot 手机 epochTime/时区同步：代码在**（carrot_serv.py + CarrotNtpTimeSync 守卫），但默认 OFF，当前值 false → 实际未运行。
- **发现两处隐患**：
  1. 重复参数键：`CarrotTimeSyncEnabled`（已注册但全仓库零引用＝死键）与 `CarrotNtpTimeSync`（真正被 carrot_serv 用）语义重复，默认都是 0。
  2. carrot 路径写 `TimezoneName/TimezoneSource` 声称"防止 timed.py 覆盖"，但这两个 key 全仓库无读者 → 空操作，误导；
     且它用 `rm/ln -s /data/etc/localtime` 直接改时区，与 AI 的 `cp` 写同一文件 → 双写竞态。

### 设计：单一权威 + 分级兜底
| 层面 | 唯一权威 | 兜底 |
|---|---|---|
| 时刻 instant | 系统 NTP(AGNOS) + `timed.py`(GPS) | 手机 7706/7714 epochTime（仅在时钟无效时） |
| 时区 TZ | AI `gps_auto_timezone_loop`（GPS→联网IP，偏移守卫）→ `apply_os_timezone` | 无（不乱写） |

时区与时钟是**两个独立的旋钮**（时钟=RTC/NTP 绝对时刻；时区=/etc/localtime 呈现层），
但用户看到的"墙上时间"= 两者相乘，所以只需保证「每个旋钮各只有一个写者」。

### 实施（commit d103b0cf4b，纯 Python，不动 params_keys.h → 无 cereal 重编译风险）
- `carrot_serv.py::_maybe_sync_system_time`：
  - 新增 `system_time_valid()` 前置门 —— 时钟健康时直接返回，永不与 NTP/GPS 抢；
  - 时钟写入改 `sudo date -u -s @<epoch>`（明确 UTC 秒，消除本地时区二次偏移歧义）；
  - 移除全部时区副作用（rm/ln localtime、put TimezoneName/Source），时区交 AI 唯一权威；
  - `CarrotTimeSyncEnabled` 作为 `CarrotNtpTimeSync` 的别名读入 → 死键不再分叉。
- 测试：新增 2 用例（时钟有效时不干预、legacy 别名生效），去掉 TimezoneName/Source 断言，
  新增 `openpilot.common.time_helpers` leaf stub（该测试用 stub 包名的既有约定）。
  **结果：test_carrot_man 101 passed；test_param_registration 2 passed；test_carrot_controls 4 passed。**
- 参数保持默认 OFF：正常情况 NTP+AI 已足够，手机兜底仅在无网无星且时钟明显无效时才介入。

### 内存实测（3.5Gi 总）
used 1.8Gi / free 255Mi / buff-cache 1.6Gi / available 1.7Gi，无 swap。
Top RSS：ai.aid 330MB、openpilot.ui 231MB、mapd 129MB、webuid 90MB。

---

## 2026-09-19 推送收尾（origin: FOREVERZAX1988/openpilot, branch: macan-long-0919）

### 推送结果
- `143d10ae44..d103b0cf4b` —— 时间权威统一（carrot 时间同步降级为兜底）✅
- `d103b0cf4b..9871228fff` —— .gitmodules webui URL 修正 ✅
- 远端 HEAD == 本地 HEAD == 9871228fff ✅

### 子模块可达性全量核验（决定 fresh clone 是否完整）
| 子模块 | gitlink | 在 .gitmodules URL 上可达？ |
|---|---|---|
| ai | 954157e2 | ✅ (FOREVERZAX1988/ai macan-long-0919) |
| opendbc | 6903509f | ✅ (FOREVERZAX1988/opendbc macan-long-0919) |
| panda | 7d703710 | ✅ (FOREVERZAX1988/panda master-c3) |
| webui | a9c7d76c | ❌→**已修** |
| rednose | 8671c17c | ✅ (commaai/rednose master 之上游提交) |
| neural_network_data | b670f8f0 | ✅ (mouxangithub/neural-network-data master) |
| msgq / teleoprtc / tinygrad | e7396e76 / 1aa8fc43 / 66ee3cfb | ✅ (上游 ref) |

### webui 断点细节与修法
- `mouxangithub/webui` 只有 `main=a8211fe`，**不含** gitlink `a9c7d76`；该提交仅在
  `FOREVERZAX1988/webui` 的 `macan-long-0919` 上 → 按 SHA 拉取必失败，clone 不完整。
- mouxangithub 无推送权限（`git@github.com: Permission denied (publickey)`），故改为指向 fork。
- .gitmodules: `url=...FOREVERZAX1988/webui.git` + 补 `branch=macan-long-0919`
  （fork 默认分支 main=b620ca98 不含本分支修复，缺 branch 会让 `submodule update --remote` 回退丢修复）。
- 验证：对**新 URL 按目标 SHA fetch 成功**（等价 fresh clone 的 submodule update 路径）；
  `git submodule sync webui` 已同步本地 submodule URL。

### 备注（未动）
- 工作区仍有未跟踪文件：DAY_LOG_*.md、tools/macan/scan_*.py、scan_0079_*.txt、
  radar_handshake_report.txt、tool_results/、translations/*.po.bak。**未纳入提交**（保持仓库干净）。
