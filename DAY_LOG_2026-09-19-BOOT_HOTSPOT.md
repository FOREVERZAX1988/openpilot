## 2026-09-19 开机卡逗号图标（连手机热点）——开机路径上的「联网 pip」

### 用户问题
1. 上楼连无线开机不卡 UI；刚上车连手机热点开机就卡在逗号图标不动。
2. 启动日志里还有个错误，是不是跟这个卡 UI 有关系？

### 结论：两个问题是同一个根因，而且正好被「热点」放大
- 屏幕上那个逗号 = 开机时 `openpilot/system/manager/build.py` 的 Spinner（`spinner_sunnypilot.png`），
  以及它关闭后留在屏上的开机 logo 最后一帧；在 `./manager.py`（真正拉起 UI）之前，画面上就是它。
- `launch_chffrplus.sh` 在 `./manager.py` **之前**同步调用 `start_webui` / `start_op_assistant`，两者的 aiohttp 探针写法不一致：
  - `start_webui`：`if ! "$web_py" -c "import aiohttp"` —— **没有 PYTHONPATH**
  - `start_op_assistant`：`if ! PYTHONPATH="$py_path" "$aid_py" -c "import aiohttp"`
- AGNOS rootfs 只读，aiohttp 装在 `.pydeps` 里，所以 webui 的探针**永远看不到它** →
  **每次开机都必进联网分支**，就在 UI 起来之前跑 `pip install aiohttp`。
- pip 默认 15s connect timeout × 5 重试（实测打不通的索引：40s 时仍在重试，总共 90s+），`curl` 也没有 `--max-time`。
  家里无线：网络好，几十秒内过去；手机热点 / 刚上车热点还没通 = 「已关联但不可用」，正好是最慢的场景 → 逗号图标一停就是几分钟。
- 用户看到的那条错误就是它：
  `/tmp/webui.log: ERROR: Could not find a version that satisfies the requirement aiohttp (from versions: none)`
  —— 同一次 pip 在没网时留下的记录。**是同一个问题，不是两个。**
- 附带：45s 看门狗 `while true; do sleep 45; start_webui; done` 因为探针一直失败，
  会在开机后**每 45s 再把 aiohttp 下载一遍**（本次 webui.log 里 15 组完整 pip 下载）。

### 证据（本次开机：内核 17:23:53 → manager 17:26:10，共 137s）
- `/tmp/webui.log` 第 1-2 行 = 本次开机第一次 pip 失败（当时还没网）；第 3 行 `[webui] starting :5080 TLS (17:26:06)`；
  其后每 45s 一组 `Collecting aiohttp … Downloading …`。
- `.sconsign.dblite` mtime `17:25:02`（scons 结束）→ `17:26:06` webui 起：中间这 64s = `os.sync()` + 那次 pip。
- pip 限时实测（指向打不通的索引）：默认 = 40s 仍在重试；`--timeout 5 --retries 0` = 7.1s 退出。
- 反证：`PYTHONPATH=…:.pydeps python3.12 -c "import aiohttp"` → 0；
  不带 PYTHONPATH → `ModuleNotFoundError`（旧探针不可能成功）。

### 实施
1. `launch_chffrplus.sh`
   - webui 探针补 `PYTHONPATH="$py_path"`（与 aid 写法对齐）→ 正常情况下开机路径**完全不碰网络**。
   - 联网兜底全部限时：`curl --max-time 20`；
     `pip install --timeout 5 --retries 0 --disable-pip-version-check`（aid 侧同样限时）。
     只在 aiohttp 真的缺失时才走，且最多 ~25s，不再是几分钟。
2. 安装器同步（新装/修复的源头）：`webui/install/integrate_openpilot.py`、`ai/install/integrate_openpilot.py`
   - 函数模板与真机脚本逐字一致；`pydeps` 统一为 `$root/.pydeps`（脚本实际用的就是这个目录）。
   - 升级判据由「内容里有 .pydeps 字样」改成版本标记 `webui-bootstrap-v2` / `aid-bootstrap-v2`，
     **已装好的机器能被重新 patch**（在 /tmp 用 HEAD 旧脚本实测：跑一次即修好）。
3. 新增回归测试 `openpilot/system/tests/test_launch_boot_bootstrap.py`（8 例）
   - 两个 `start_*` 必须在 `./manager.py` 之前被调用（否则本类隐患位置变了，守卫要重看）；
   - 探针必须带 PYTHONPATH，且旧的无限时写法不得再出现；
   - pip 必须在探针**之后**（探针过了就不该联网）且带 `--timeout 5 --retries 0`；
   - 脚本里任何 `curl`/`pip install`/`wget` 都必须限时（防止下次有人再塞一个无超时的网络调用进来）；
   - 功能验证：带 .pydeps 的探针通过、不带的失败（把旧 bug 钉住）；
   - 安装器模板与真机脚本函数体逐字相同 + 修复标记仍在。
   - 回放 HEAD 旧脚本：5 失败 1 error（改前必挂）；改后 8 全过。

### 生效条件
`launch_chffrplus.sh` 只在开机时读取 → **下次重启生效**（不需要重启 UI 进程）。

### 备注 / 后续
- 逗号图标本身仍会停留约 30-60s：`$DIR/prebuilt` 不存在 → 每次开机都跑 `build.py`
  （scons 无事可做也要 30-60s + `os.sync()`）。这是「慢」，不是「卡死」，与网络无关；
  想更快可以后续再处理 prebuilt 标记。
- 手机热点下 `athenad.ws_recv/ws_send.exception`、sunnylink `upload_failed KeyError('url')`
  是另一件事（17:35:44 联网后才出现），与开机 UI 无关；`KeyError('url')` 是 sunnylink 上传接口
  返回体里没有 `url`，可另开一轮排查。
