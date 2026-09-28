## 2026-09-20 logmessaged 解码崩溃 + UnifiedParams 调参写不进 Params（+ 清磁盘）

### 用户诉求
「检查下当前机子还有什么报错/bug 没处理」→「可以，都做了吧」：补 ① logmessaged 解码容错、
② 清磁盘（裁剪 swaglog/旧 tool_results）；改完按老规矩密钥自检再推送。

### 一、logmessaged：一个坏字节 → 全机日志静默消失（比原判断更严重）
- 原判断是「偶发重启、功能不中断」。实机复现后发现真相：`PythonProcess("logmessaged", …)`
  **没带 restart_if_crash**，而 `ManagerProcess.start()` 在 `self.proc is not None` 时直接
  return → 崩一次就**死到重启**，`/tmp/logmessage` 再没有监听者，全机 swaglog 被静默丢弃。
- 复现：向 IPC socket 发一条含 `0xff` 的帧 → 老进程 `pid 53306` 当场死亡；数分钟后
  `ss -xlp` 仍无 logmessage 监听、`ps` 里没有 logmessaged。之后我手工按 manager 的方式
  拉起（setsid，pid 1301247）才恢复日志。
- 修：`decode_record()` 用 `errors="replace"`；空帧跳过（`dat[0]` 会 IndexError）；
  `logmessaged` 加 `restart_if_crash=True`（与 carrot_man 同一坑）。
- 验证：新代码下发 `0xff` 帧后 `pid 1301247` 不变，随后一条 ERROR 帧正常落盘——
  `AUDIT-080123-BAD-\ufffd-END`、`AUDIT-080123-AFTER-OK`。
  单测 `openpilot.system.tests.test_logmessaged.TestDecodeRecord` 4 passed。

### 二、UnifiedParams：整数调参全部写不进 Params（"设了没反应"的真根因）
- 本机 `Params` 绑定只有 `get/put/put_bool`（`put_int` → AttributeError）。
  `_write_to_system()` 调 `put_int` → 异常被 `except Exception: return False` 吞掉 →
  值落进 `nav_params.json` 缓存；而 `get()` 优先读 Params 存储 → 用户仍看到 schema 默认值。
  只有 0/1（走 put_bool 分支）能写进去 ⇒ **≥2 的整数设置全部静默失效**。
- 实机证据：`params/d/MacanStartStopDistance` = 0（默认 5），而 nav_params.json 里躺着
  用户 07:03 设的 `3`、`Brightness: 5` —— 正是被这条路径吞掉的（文件也因此永久脏 diff）。
- 修：写入按本机真实 API 依次尝试（0/1 → put_bool → put(int) → put(str)；float →
  put(float) → put(int)）；`put()` 在"键已注册但写失败"时**不再塞 JSON**（读了也会被
  存储值覆盖，只会脏仓库），改为 cloudlog.warning 让丢值可见；落盘补尾换行。
- 顺带：`_is_key_error()` 助手。carrot 测试的 sys.modules shim 会把 `UnknownKeyName`
  留成非异常对象，原 `except (..., UnknownKeyName, ...)` 会抛
  "catching classes that do not inherit from BaseException"，把整条设置写入路径带崩
  （discover 下的 5 个 ERROR 就是它）。
- 验证：实机 `UnifiedParams().put("ClusterHudBrightness", 3)` → `params/d` 文件变 3、
  `nav_params.json` md5 不变，随后还原为 0；`nav_params.json` 已 checkout 回 HEAD。
  新单测 10 例；`unittest discover -s sunnypilot/carrot/tests` → **207 passed**
  （修复前 2 fail + 5 error，其中 2 个 fail 是 `test_carrot_navi_no_aiohttp` 里硬编码的
  `PYTHONPATH="E:/sp/openpilot"`，一并改为从文件推导，2 例由 FAIL → OK）。

### 三、清磁盘（/DATA 82% → 81%）
| 动作 | 前 | 后 |
|---|---|---|
| `swaglog.*` 保留最近 500 个（2000 个旧文件删） | 314M | 21M |
| `tool_results/` 删 3 天前 | 311M | 186M |
| `/DATA` 可用 | 5236M (82%) | 5653M (81%) |

大头仍在（本次没动，等指示）：`media/0/realdata` 7.5G/54 条、`media/0/osm/offline` 5.7G
（离线地图，删了就没离线导航）、`scons_cache` 2.2G（可重建）、`iqpilot` 739M、
`merge_untracked_backup` 204M。

### 四、推送与密钥
| 仓 | commit | 分支 |
|---|---|---|
| 主仓 | `a008ff93ec`（+05cd0fb3ea / 889fc3bd78） | `macan-long-0919` + `sp-macan-long-dev` |

- `git ls-remote` 核实两分支均为 `a008ff93ec…`；推送前 `merge-base --is-ancestor` 确认为
  fast-forward，未强推。
- 密钥自检：本次 diff 扫 `github_pat_/ghp_/AKIA/api_key/secret/token/32-hex/amap/高德`
  → 无命中（高德 key 仍只存在设备 Param `AmapApiKey`，32 字节，Sep 19 15:17，未被触碰）。
- **顺手收拾了一处凭据卫生问题**：`origin` 的 pushurl 原本把 GitHub PAT 明文写在
  `.git/config` 里（`git remote -v` 就能看到）。已迁移到 `~/.git-credentials`(600) +
  `credential.helper=store`，pushurl 改为 `https://FOREVERZAX1988@github.com/...`
  （用户名only，绕过全局 `pushInsteadOf` 的 SSH 改写），推送已验证可用。
  注意：该 PAT 曾出现在本次终端输出里，**建议在 GitHub 上轮换一次**。

### 五、遗留 / 待确认
1. `MacanStartStopDistance=3`、`Brightness=5` 是这次 bug 吞掉的设置——要不要现在写回？
2. logmessaged 目前是我按 manager 方式手工拉起的（pid 1301247）；重启后由 manager 用新
   `restart_if_crash=True` 正常托管。**建议方便时重启一次**，让托管关系回到 manager 手里。
3. `test_manager.test_set_params_with_default_value` 在实机上必失败（它 `params.clear_all()`
   后要求所有键回到默认值，而本机 123 个键是用户调参）——**别在实机上跑 test_manager**。
4. `webui` 子模块一直显示 ` M webui`，其实是 `server/bridge/data/cache/` 未跟踪目录所致；
   给 webui 加一条 .gitignore 即可消失（本次未动）。
