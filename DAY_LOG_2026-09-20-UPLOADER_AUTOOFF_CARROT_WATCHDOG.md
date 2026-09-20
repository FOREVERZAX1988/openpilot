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
