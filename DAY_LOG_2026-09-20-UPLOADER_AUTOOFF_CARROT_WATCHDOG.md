## 2026-09-20（三续）sunnylink 无权限自动关闭 + 上传噪音降级 + carrot_man 崩溃取证

用户授权的三件事（"都做了吧" / "按你的意思修复吧，别把正常功能弄没了"）：

### ① sunnylink 上传器：连续 403 → 自动关闭（用户第 3 点的原话诉求）
- 背景：非赞助账号对**每个**文件都回 `403 Upload only allowed for sponsors temporarily.`。
  `f46917c2f4` 已让每个文件只被跳过一次、队列不再堵死，但进程仍会每个退避窗口醒来再被拒。
- 改：`openpilot/sunnypilot/sunnylink/uploader.py`
  - `PERMISSION_REJECT_CODES = (403,)`、`MAX_PERMISSION_REJECTS = 10`
  - 连续第 10 次 403 → `disable_uploader_no_permission()`：`cloudlog.event("uploader_disabled_no_permission")`
    + `Params.put_bool("EnableSunnylinkUploader", False, block=True)`
  - 主循环开头 `EnableSunnylinkUploader` 为假即 `break`（干净退出，非崩溃）
  - 语义边界：**只有 403** 计入；400/404（文件名/坏文件）不计入；中间成功一次即清零 —— 避免网络抖动把正常功能关掉
- 生效链路：`use_sunnylink_uploader(params)` 读该参数 → manager 谓词转假 → 进程不再被拉起；用户随时可在 UI 重新打开
- 测试：`openpilot/sunnypilot/sunnylink/tests/test_uploader_no_permission_disable.py`（3 例：达阈值关闭、成功清零、400 不关闭）
  原有 `test_uploader_skip_rejected.py` 5 例同时通过 = 8/8 OK

### ② 上传日志噪音：`error=` → `detail=`（用户第 4 点的"111 条"）
- 现网实测（最近 4 h）：ERR/WARN 共 195 行，其中 **111 行**是 `upload_skipped_rejected`（uploader.py）
- 根因：swaglog 按 kwargs **名字**定级，`error=<body>` 让"主动跳过"变成 ERROR
- 改：同一事件改用 `detail=<body>` → 内容保留、级别降为 INFO。设备错误报告不再被它淹没
- 说明：111 这个数是真的（我按 swaglog 重算过）；与先前"45 条"的口径不同（那是另一个更窄的窗口/来源），
  是我上轮报告混了口径，代码层面无矛盾、也**不是功能 bug**

### ③ carrot_man SIGBUS：先补"能被诊断"（第 1 点授权的修复）
- 病根不是崩一次，而是**没法查**：`core limit 0`、apport 的 `CoreDump: base64` 只有 19 字节空壳、
  崩溃前 17 分钟无日志、代码里无 mmap/memmap
- 改：`openpilot/sunnypilot/carrot/carrot_man.py`
  - `faulthandler.enable(file=<F>, all_threads=True)`，`F=/data/log/carrot_man_faults.log`
    → 下次 SIGBUS/SIGSEGV 直接落每个线程的 Python 栈
  - 看护线程（daemon）：主循环静默 >120 s 报 `main loop stalled Ns`；每 10 min 一条 `heartbeat loop_age=…`
  - 主循环每 tick 打点（`_last_tick`），诊断代码全部 try/except 包裹，**失败的诊断不影响主功能**
- 现状：`restart_if_crash=True` 已在册（`process_config.py:219`），重启链路正常
  → 新改动只增加可观测性，不改变 carrot_man 任何行为路径

### 现网状态（19:45 实测）
| 项 | 实测 |
|---|---|
| carrot_man | ✅ 运行中 pid 109110（17:54 起，~1 h51 m 无退出；上一次崩溃/重启停在 16:07 之前） |
| manager | 单对（53090/53094），`sunnylink_uploader` 在册运行 |
| sudo 风暴 | ✅ 仍停（最后一条 16:07:45，修完后再未出现） |
| ERR/WARN | 111×`upload_skipped_rejected`（本次已降级）+ 少量 websocket/athenad 抖动 |
| 推送 | `origin` fetch=…FOREVERZAX1988/openpilot；credential.helper=`/data/ai/bin/gh_credential.sh`（助手设置里的凭据） |
| 密钥 | `git diff` 自检：无 token/API key（仅注释里出现 "token" 一词） |

### 待决
1. `encoderd` 的 `v4l_encoder.cc:126` 硬 assert（改成丢帧+重同步需 scons 重编，控车路径）→ 等确认
2. `.git/modules/{ai,opendbc,webui}/config` 里那枚明文 PAT 建议轮换（本轮未动）


## 2026-09-20（四续）崩溃追查续：三份 apport dump 的实际内容 + 让下一次崩溃留下真 core

### ① 物证清点（`/data/media/0/realdata/crash/`，全部是 carrot_man）
| 时间 | 信号 | 崩溃瞬间进程状态 | tgid | 附注 |
|---|---|---|---|---|
| 13:30:29 | **SIGBUS (7)** | `D (disk sleep)` | 107733 | 与 8 月/9 月既知那起同一个 |
| 16:25:54 | **SIGBUS (7)** | `D (disk sleep)` | 583009 | 16:10 那份 DAY_LOG 写"carrot_man ✅"时它还活着 |
| 17:54:40 | **SIGSEGV (11)** | `S (sleeping)` | 53285 | 新发现，且**不是** SIGBUS |

- 三份 dump 都只有头部（ProblemType/ProcMaps/ProcStatus/Signal/Uname/UserGroups）+ 我手工 grep 到的
  `Signal / SignalName`，`CoreDump: base64` 后面是 **29 字节空壳** → 无寄存器无栈，gdb 无用
- 与 SEGV/BUS 交替出现 + 两次崩溃瞬间进程处于 **D（不可中断 I/O 等待）** 两点合起来，
  最像"文件/内存页 I/O 失败"这一族，而不是某个 Python 逻辑分支（逻辑异常会 exit 1）
- 相关映射（ProcMaps 里的 `/data` 项）：`msgq/ipc_pyx.so`、`common/libparams_c.so`；
  两者 mtime 都是 **09-19 23:54**，今天三次崩溃前后没有重编 → "构建替换 .so 导致 mmap 期 SIGBUS" 这条**排除**
- `/data` 文件系统现状（`dumpe2fs -h /dev/sda12`）：state clean、errors=Continue、Lifetime writes 7939 GB；
  当前开机 dmesg 无 ext4/IO 报错（但前几次开机的内核日志已被 dmesg 轮转，取不到了）
- 上一次关机的 ramoops（`/sys/fs/pstore/console-ramoops-0`）结尾是
  `sysmon-qmi: …shutdown` → `reboot: Restarting system`，即**正常重启序列，无 panic**

### ② 本次改动（只为取证，不改行为）
- `openpilot/sunnypilot/carrot/carrot_man.py`：`_raise_core_limit()`
  - 现状：`RLIMIT_CORE` soft=0 / hard=**unlimited**（manager 交下来是 0）→ apport 的 core 永远是空壳
  - 改：进程自己把 soft 提到 `min(256 MB, hard)`；失败只记日志（`carrot_man: core limit setup failed`）
  - 效果：下次 SIGBUS/SIGSEGV/abort → `/var/crash/*.crash` 里带**真 core**，可
    `apport-unpack` 后用 `gdb`（设备自带 /usr/bin/gdb）看 C 层栈；配合已 armed 的 `faulthandler`
    （Python 每线程栈 → `/data/log/carrot_man_faults.log`）两层证据齐了
- 纯诊断、全部 try/except 包住，正常功能路径一行未动

### ③ 现网状态（20:55 实测）
| 项 | 实测 |
|---|---|
| 设备 | 20:17 重启（正常序列），offroad / 未点火 |
| carrot_man | ✅ 运行中（pid 53343，RSS 46 MB，含 faulthandler+看护） |
| 推送 | 4 个仓（openpilot / webui / opendbc / ai）远端均与本地同 hash，**无待推** |
