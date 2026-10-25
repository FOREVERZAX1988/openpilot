## 2026-09-20（再续）崩溃追查 + 三处修复 + 一次自造的管理器事故

### 一、用户 4 件事的现状
| # | 事项 | 结论 |
|---|------|------|
| 1 | macan 融合按钮恒 true + 备份推送 `sp-macan-long-dev` | ✅ **早已完成**：远端 `sp-macan-long-dev` = `macan-long-0919` = `f46917c2f4`，其中含融合锁 `3e2be75204`。仅本地分支引用陈旧（还指着 `5081e60f9c`） |
| 2 | navipilot 最新版能否编出 APK | ❌ **编不出**。最新两次 run 都 failure（`r260901` 09-09 / `Amapauto`），都卡在 `Build signed Release APK (multi-ABI)`；最新可用 APK 仍是 **`r260726`**（09-08，`app-debug.apk`） |
| 3 | 机子还有哪些报错/bug | 见四、五（本轮修了 3 处，另有 2 处待决） |
| 4 | 方案B / 查那个崩溃 | 见二、三 |

### 二、两个崩溃的追查

#### A. `encoderd` SIGABRT（就是留下坏 crash 文件、堵死上传队列的那个）
- 物证：`/data/media/0/realdata/crash/2026-09-19--17-50-30_473338fe_openpilot_system_loggerd_encoder`
  与 `--17-50-44_…`（各 373 KB，**无扩展名**，会被服务器 400 拒收）
- dump 头：`ExecutablePath …/system/loggerd/encoderd`、`ProcCmdline ./encoderd`、**`Signal: 6 / SIGABRT`**，两次相隔 12 秒
- 同期 swaglog 已被轮转删除（现存最早 09-19 18:21）→ abort 前日志不可得
- 代码定位：`system/loggerd/encoder/v4l_encoder.cc` 稳态路径只有三处断言，最可疑是
  **`line 126: assert(extra.timestamp_eof/1000 == ts); // stay in sync`**（VisionIPC 帧时间戳 ↔ V4L2 编码器输出时间戳失步），
  另两处 `line 41 data_offset`、`line 342 extras.empty()` 分别在取帧/停流路径
- 影响：encoderd 一死 → **三路相机流全断、当前 segment 报废**（loggerd 会重启它）
- 该文件为本仓相对上游**未改**的代码（`git log` 只有上游提交）
- 建议（未动，等确认）：把 `line 126` 的硬 `assert` 换成"记日志 + 丢帧/重同步"，单帧失步不再整进程 abort。需 `scons` 重编 `encoderd`，属控车路径，风险中等

#### B. `carrot_man` SIGBUS（今天 13:30 新崩的，此前未发现）
- `apport.log`：`13:30:17 called for global pid 107733, signal 7`
- dump 头：`ExecutablePath /usr/bin/python3.12`、**`ProcCmdline openpilot.sunnypilot.carrot.carrot_man`**、`Signal 7 / SIGBUS`
- manager：`13:30:25 Restarting carrot_man (exitcode -7)` → 新 pid 156937
- **拿不到 core**：`core limit 0`，apport 的 `CoreDump: base64` 只有 19 字节空壳（gdb 无用）→ 只能靠日志+代码推断
- 崩溃前 17 分钟完全静默（13:12:41 起完线程后无输出）；代码里**无 mmap/memmap 用法** → SIGBUS 根因暂不可定位
- 15 小时内 carrot_man 共死 5 次：`exit 1`×2（09-19 22:49、09-20 00:12）、`exit 0`×2（关 CarrotEnabled 等正常退出）、**SIGBUS×1**
- 建议：加"无日志静默/异常退出"看护，或复现后再深挖

### 三、"机器上还有什么报错"——本轮实际修掉的三处

#### ① sunnylink 上传队列堵死（400）——**修好的代码没生效**
- 现象：`crash/2026-09-19--17-50-30_…_loggerd_encoder` 每 ~2 分钟一条
  `upload_failed … <Response [400]> Invalid file extension …`，队列后面永远排不上；本次开机（12:39）后累计 **93 条 ERROR**
- 根因：400 修复（`f46917c2f4`，**13:24 才提交**）晚于 uploader 进程启动（**12:40**）→ 跑的还是旧代码
- 处理：回收该进程后新代码生效，实测两个坏文件都被打标跳过（`upload_skipped_rejected`），
  队列开始正常排空（2 分钟内推进了 24 个文件）

#### ② `hardware.booted()` 引发的 sudo 风暴（37 MB auth.log）
- 现象：`/var/log/auth.log` 涨到 **37.9 MB**，其中 **4525 次**
  `sudo cat /sys/kernel/debug/msm_vidc/core0/info`（+4829 次 pam session），**约 3 次/秒**
- 根因：`webui/server/bridge/startup_blockers.py` 与 `hardwared.py` 每次都调
  `HardwareComma.booted()`，而它无条件 `sudo_read` 编码器 debug 节点
- 修：`booted()` 在 `monotonic() >= 120s` 后直接返回 True（语义等价，原判据已不可能返回 False）
- 验证：重启 webuid（旧 52262 → 新 584689）后，**最后一次 sudo 落在 16:07:45，之后再无**（此前稳定 3/s）

#### ③ `sunnylink_uploader` 退出后永不复活
- `PythonProcess` 默认 `restart_if_crash=False`，而该进程没显式打开 → 一旦退出（崩溃/被 kill）就不会再被拉起，
  只有重启 manager/设备才回来，上传静默停摆
- 修：`process_config.py` 该条目补 `restart_if_crash=True`（与 logmessaged 同类问题同类修法）

#### ④ `ai` 的 `manager_control` 用错 cwd（本轮自造事故的根因）
- `system_control_tools.py` 以 `cwd=/data/openpilot` 启动 manager，而正常启动路径
  （`launch_chffrplus.sh`）是 `cd openpilot/system/manager`
- ⇒ `process_config.py` 里所有相对路径判据（`os.path.exists("../../sunnypilot/sunnylink/uploader.py")` 等）失效，
  **静默丢掉 `sunnylink_uploader`**（managerState 里根本没有这个条目）
- 修：`cwd=str(manager_py.parent)`；已 bump gitlink
- 事故复盘：用工具重启 manager 时旧新两代管理器重叠了约 1 秒，引发一簇
  `Messaging failure : Address already in use` 与 `logmessaged/timed/mapd_manager/backup_manager` 崩溃
  （`/data/community/crashes/2026-09-20--16-04-1x.log`）。随后我用正确 cwd 手工重启并 -9 清掉旧对，
  现已收敛为单对 manager（582868/582892），四路进程齐活

### 四、当前状态（16:10 实测）
| 项 | 实测 |
|---|---|
| manager | 单对 `582868/582892`，cwd 正确（`…/system/manager`） |
| `sunnylink_uploader` | ✅ 重新在册并运行（pid 583013），`upload_skipped_rejected` 正常打标、排队推进 |
| `carrot_man` | ✅ 运行（583009） |
| sudo 风暴 | ✅ 停（最后一条 16:07:45） |
| 遗留 ERROR | 仅 `upload_skipped_rejected` 仍走 ERROR 级（`error=` kwarg 所致，**计数已从"每退避窗口一次"降为"每文件一次"**）；`athenad ws_recv/ws_send` 属网络抖动 |
| 温度/空间 | 62.8 ℃ / 剩余 18.8% |
| 残留进程 | 清掉两个挂了 2.8 小时的 `git-remote-https`（无 token 的 push 卡死） |

### 五、关于"sunnylink 是不是传不上去"——是的
- 服务器对**所有**文件回 **403**：`Upload only allowed for sponsors temporarily`
  → 现在**确实一个都传不上去**，不是本地 bug；坏文件堵队列那条已修好，现在每个文件只被礼貌跳过一次，队列不再卡死
- 想真正上传，需要服务器侧放开（赞助者）或换上传目标

### 六、待决 / 风险
1. **凭据**：本机无可用 push 凭据——`~/.ssh` 空、无 credential helper；`origin.pushurl` 只有用户名（裸 `git push` 会挂死）；
   `.git/modules/{ai,opendbc,webui}/config` 里还躺着**同一枚明文 PAT**（今天更早那轮曾把它打进输出 ⇒ **应立即轮换**）。
   本轮 4 个提交都在本地，未推送。
2. `encoderd` assert 改造（需重编、控车路径）→ 等确认。
3. `carrot_man` SIGBUS 无 core，根因未明 → 建议加看护复现。
4. `upload_skipped_rejected` 想彻底不报 ERROR，把 `error=` 换成 `detail=` 即可（一行，未动）。
5. 本地 `sp-macan-long-dev` 分支引用陈旧（远端其实已是最新），只是本地指针问题。
