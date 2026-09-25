## 2026-09-20（再续）用户手动重启后的核验 + 两个新发现

### 一、核验：代码/推送都在，但设备功能没起来
| 项 | 实测 |
|---|---|
| 运行代码 | `/data/openpilot` HEAD=`fd61a750e7`，分支 `macan-long-0919`，**工作区干净**，与 `origin/macan-long-0919` 一致 |
| `sp-macan-long-dev` | 远端 `fd61a750e7`（= HEAD）→ 上次的备份推送**确实到位** |
| 数字框直接输入 | `webui/web/static/js/panels.js:2004 renderIntRow()` 已是 `<input inputmode=numeric>`（注释写明 1024→7706 原本要点 ~6700 次）；UI 侧 `option_control.py` 同步 |
| 融合控制锁死 | `volkswagen.py:371-375` `set_enabled(False)`+`set_state(True)`+自愈回写；`cruise.py:46` 与 opendbc `carcontroller.py:92/94` 均为**常量**（读参数的旧行已注释保留） |
| Param | `MacanFusionMode=1`、`MacanStartStopDistance=3`、`Brightness=5`（上次写回的两项**保住了**） |
| 进程 | manager/ui/modeld/mapd/pandad/logmessaged/webuid 均在；开机**无 Traceback** |

### 二、发现的阻塞问题：Carrot 总开关被关掉了（已恢复）
- 现象：**没有 `carrot_man` 进程**，UDP 7706/7705 无监听，8088 无响应 → 手机 App 仍搜不到设备、Carrot 面板/功能全灭。
- 根因：`system/manager/process_config.py:114-117 carrot_enabled()` 返回 `params.get_bool("CarrotEnabled")`，而
  `params/d/CarrotEnabled = 0`。07:02:23 那一刻 manager 日志连着三行
  `killing carrot_man` → `sending signal 2` → `carrot_man is dead with 0`（param 与该 kill 同一秒）。
  **注意：清退后不再重启**——`restart_if_crash=True` 只处理非 0 退出，退出码 0 直接被当成"正常退出"。
- 同一秒被写成 0 的还有 `CarrotAmapBlindSpotEnabled`；`CarrotWebEnabled` 在 07:08:35 也成 0
  （8088 面板由此关闭，`web_interface.py:179 DEFAULT_PORT=8088`）。这几项是**用户级开关**，未擅自改动。
- 处理：`CarrotEnabled=1`（走 Params API，`put_bool(..., block=True)`）。实测 10s 内 manager 拉起
  `carrot_man`（pid 107733），日志 `listening on UDP port 7706` / `broadcast thread started` /
  7710、7709、7712、12345 各线程就绪；抓包 `0.0.0.0:7705` 8s 收到 **5 包**，
  payload `{"Carrot2":"2026.003.000","ip":"192.168.10.79","port":7706,...}`。
- 另留一个健壮性问题（未改）：00:12-00:14 那波 `MultiplePublishersError: Messaging failure :
  Address already in use`（`carrot_man.py:1118 self.pm.send('carrotManSP')`）是**同名校验**报出来的——
  当时有两个 carrot_man 并存（kill 后新实例抢在旧实例释放 socket 之前 publish）。全仓只有
  `carrot_man.py:602` 一个 carrotManSP 发布者，所以只可能是实例重叠。

### 三、新 bug：上传队列被一个"服务器永远不收"的文件堵死（本次已修）
- 实测：`crash/2026-09-19--17-50-30_473338fe_openpilot_system_loggerd_encoder`（373853B，**无扩展名**）
  每 ~2 分钟一条 ERROR：`upload_failed with content … <Response [400]> …
  "Invalid file extension: crash/2026-09-19--17-50-30_…_loggerd_encoder"`。
  35 分钟内 19 条 ERROR，最后一次 13:10。
- 为什么堵死整条队列：`immediate_folders = ["crash/", "boot/"]`，`next_file_to_upload()` **第一遍就返回**
  crash/ 里的文件；该文件永远拿不到 `user.sunny.upload` 标记 → 每次都被重新选中，后面所有日志永远排不上。
  上一次的 403 修复（`PERMANENT_REJECT_CODES=(403,404)`）**漏了 400**，于是退化成
  `elif stat is not None: success=False` → 退避 `min(backoff*2,120)` 无限重试。
- 修：`PERMANENT_REJECT_CODES = (400, 403, 404)` + 注释说明 400 是"按路径校验"语义；
  新增单测 `test_bad_request_is_handled_too`（用真实 400 body 造例）。
  设备上 `python3 -m unittest`：**5 passed**。
- 生效时机：uploader 是长驻进程，**下次重启后**才会跑到新代码（届时那个 crash 文件会被打标跳过，
  队列开始正常排空）。
- 附带观察：这个 crash 文件本身是 `loggerd/encoderd` 崩了留下的**无扩展名**残留
  （正常 crash 物是 `.zst`），根因在 loggerd 那一侧，本次没动。

### 四、其他
- `sunnylink` 的 `upload_skipped_rejected` **仍然是 ERROR 级别**：`common/logging_extra.py:159 event()`
  只在传了 `error=` kwarg 时走 `self.error()`，而调用处正是 `error=detail`。
  → 上一份 DAY_LOG 写的"不再记 ERROR"不准确（**次数**确实从"每退避窗口一次"降为"每文件一次"）。
  想真正降级，把 `error=` 换成别的键名（如 `detail=`）即可。
- athenad 每 1-3 分钟一对 `ws_recv/ws_send.exception` + 立刻重连成功（`athena.konik.ai`），
  属网络抖动，非 bug。
- **凭据/推送链路（未修，需用户决定）**——实测 4 个 config：
  - `./.git/config`：`pushurl = https://FOREVERZAX1988@github.com/...` → **只有用户名、没有 token**。
    结果：主仓 `git push` 会停在 `could not read Password for 'https://FOREVERZAX1988@github.com'`
    （非交互下表现为**挂死**，我这边第一次卡了 300s 才定位到）。也就是说主仓的"推送"必须先有
    外部 token（临时 credential helper），裸 `git push` 走不通。
  - `.git/modules/ai|opendbc|webui/config`：`pushurl = https://FOREVERZAX1988:<明文 PAT>@github.com/...`
    —— **3 个子仓配置文件里躺着同一枚明文 `github_pat_...`**。
  - 上一份 DAY_LOG 写"webui/.git/config 里还有明文 PAT —— 之前只修了主仓"，方向对（主仓确实清过），
    但**漏了 ai / opendbc 两个子仓**，且没提主仓已变成"无 token 推不出去"。
  - 另外 `params/d/ai_github_actions_pat` **不存在**（上一份 DAY_LOG 说 token 取自它，存疑）。
  - ⚠️ 我在本轮排查中把该 PAT 打进了输出（我的脱敏正则 `://[^@]*@` 把 `user:token@` 一并替换，
    反而把 token 带进了替换文本）→ **这枚 PAT 应立即轮换**，并同步更新 3 个子仓配置。
  - 建议：轮换后统一改成 credential helper（或 `git@github.com:` SSH），别再往 config 里写明文。

### 五、navipilot（手机 App）能否编译出 APK
- 仓库 `mouxangithub/navipilot`（Kotlin），分支只有 `master` / `Amapauto`，唯一 workflow
  `.github/workflows/release.yml`（Build and Release）。
- **最新版编译不出来**：tag `r260901`（2026-09-09，push 触发）run #6 → `failure`；
  `Amapauto` run #5（workflow_dispatch）→ `failure`。两次都卡在同一处：
  第 4 步 `Decode release keystore` 成功，第 7 步 **`Build signed Release APK (multi-ABI)` 失败**
  （`Process completed with exit code 1`），后续 AAB / artifacts / Release 全部 skipped。
- 最后一次成功的 APK 是 09-08 的 `master`（run #3/#4，job 名 `release`/`Build APK`，**不带签名**），
  产物 = Release `r260726` / `r260725`（各带 `app-debug.apk`）。**没有 `r260901` 的 Release。**
- 怀疑点：新版 workflow 要求仓库 secrets（`RELEASE_KEYSTORE_BASE64` / `RELEASE_STORE_PASSWORD` /
  `RELEASE_KEY_PASSWORD` / `RELEASE_KEY_ALIAS`），文件里自己就写着"如果仓库没有配置 secrets，这里会失败"
  ——但 `Decode release keystore` 那步对空 secret 也会 exit 0，所以**不能据此断定是缺 secret**。
  精确原因要看 run 的第 7 步日志（`/actions/jobs/<job_id>/logs` 需仓库权限，本机匿名 403 拿不到）。
  用最新可用版就先装 `r260726`。
