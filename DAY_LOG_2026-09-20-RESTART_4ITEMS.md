## 2026-09-20（续）重启后核验 + 4 件事落地

### 用户诉求
「我手动重启了，你看下可以了没？4件事按你推荐的方案执行吧」
（4 件事 = 上一轮 DAY_LOG「五、遗留/待确认」那 4 条）

### 一、重启后核验：✅ 通过
| 项 | 实测 |
|---|---|
| logmessaged 归属 | pid **53319**，父进程 manager(53206)，开机 08:54 由 manager 拉起；`ss -xlp` 显示 `/tmp/logmessage` 有监听 |
| 坏字节 E2E（新托管关系下重测） | zmq 发 `\x14{"msg":"AI-AUDIT-BAD-\xff-END"}` → **pid 不变**；紧接着 `AI-AUDIT-AFTER-OK` 正常落盘，坏字节那条落为 `AI-AUDIT-BAD-\ufffd-END` |
| 近 30 分钟 ERROR 统计 | **只有 1 条**：sunnylink_uploader 403（见五）。日志静默、解码崩溃均未复现 |
| 运行代码 | `a865437662`，「dirty: false」——本机就是推送后的那份 |

### 二、① 写回被吞的两个设置 → 已写回
`UnifiedParams.put()`（走修复后的真实写入路径，非直接改文件）：
```
before: {'MacanStartStopDistance': 0, 'Brightness': 0}
after : params/d/MacanStartStopDistance=3, params/d/Brightness=5
nav_params.json md5 c2a5028a… 前后不变，git 里干净（不再污染仓库）
```
- 顺带查清一个**不是 bug 的假象**：`Params.put()` 默认 `block=False` 是**异步入队**的，
  写完立刻读可能读到旧值——`put(..., block=True)` 实测同步生效（7→文件 7）。
  之前怀疑的「同进程读回旧值」是这条异步 flush，不是新 bug。
- 注意：**长驻进程要下次重启后才会看到新值**（当前 UI 进程内缓存的是旧值）。

### 三、② logmessaged 托管 → 已完成（见一）
不再需要手工拉起；`restart_if_crash=True` 生效后由 manager 托管。

### 四、③ 实机别再跑 test_manager → 已加护栏
```
system/manager/test/test_manager.py
+ @unittest.skipIf(COMMA_HARDWARE, "starts/stops the real manager stack: PC/CI only")
```
**顺带修正上一轮的一个误判**：原写「`params.clear_all()` 会清掉本机 123 个调参」——**不成立**。
`OpenpilotTestCase.run()` 会进 `OpenpilotPrefix`，params 落在 `/data/params/<prefix>`（实测
`/data/params/zzztest`），clear_all() 只清隔离目录。真正危险的是 **`manager.main()` /
`teardown_method → manager_cleanup()` 会启停真实 manager 栈**（能把在跑的进程干掉），
所以护栏照加，理由改准。实机复跑：`OK (skipped=4)`，manager/logmessaged 未受影响。

### 五、④ webui 子模块不再长挂 ` M webui` → 已修
- 根因：`webui/server/bridge/data/cache/`（osm 区域缓存，运行时生成）未跟踪。
- `webui/.gitignore` 追加 `server/bridge/data/cache/` → `git status` 从 `?? …/cache/` 变干净。

### 六、顺手：sunnylink_uploader 403 不再无限重试（唯一还在刷的 ERROR）
- 实锤日志：`upload_failed with content … stat=<Response [403]> …
  error={"detail":"Upload only allowed for sponsors temporarily."}`，对象始终是同一个
  `boot/00000004--0ac3964c96--149.zst`，每 ~1h 一条 ERROR，队列后面的文件永远排不上。
- 改：`PERMANENT_REJECT_CODES = (403, 404)`。命中即视作**已处理**（打
  `user.sunny.upload` 标记 → 跳过），只记一条 `upload_skipped_rejected`（带服务器原文），
  不再记 ERROR；`main()` 里 401 仍走 3600s 长退避（可恢复，别 hammer）。
- 新增单测 `sunnypilot/sunnylink/tests/test_uploader_skip_rejected.py`（4 passed）：
  403→True+打标+`upload_skipped_rejected`；404→True；401→False+`upload_failed`；200→原样。
- 生效时机：该进程是长驻进程，**下次重启后**才跑新代码。

### 七、推送与密钥
- 密钥自检：本次全部 diff（主仓 + webui）扫 `github_pat_/ghp_/AKIA/api_key/secret/
  password/token/amap/高德/私钥/40-hex` → **零命中**；高德 key 仍只在设备 Param `AmapApiKey`。
- **未**把任何 token 写进 `.git/config` / 提交物：推送用临时 credential helper
  （token 取自已存在的 `ai_github_actions_pat`，只经环境变量传给 helper，不落盘、不进 argv）。
- 已知卫生问题（未动、待用户决定）：`webui/.git/config` 的 `origin.pushurl` 里还有**明文 PAT**
  —— 之前只修了主仓。建议把那枚 PAT 直接轮换，之后两边都改用 credential helper。
