## 2026-09-29 首启 AGNOS 更新器缺 pyserial：补齐（cherry-pick 上游 587ed051fb）

### 起因
复核上游时发现 `mouxan/test`（= `mouxan/master-c3` = `mouxan/tn-c3`，三者同指 `838cd92b47`）
比我们多 2 个提交，其中 `587ed051fb` 我们**没有**。按 9/29 触摸事故的教训，
**按上游原意 cherry-pick，不做整分支 merge**（那次 merge 把 9/19 的触摸修复带回了旧实现）。

### 上游 587ed051fb 修的是什么
AGNOS 更新器是自包含 zipapp，**没有自带 site-packages**；`#!/usr/bin/env python3` 落到 venv
解释器，其运行时路径 = `launch_chffrplus.sh` 的 `PY_PATH`。它 bundled 的
`system/hardware/tici/lpa.py` 在**模块级** `import serial`，链路：

```
updater -> ui/updater -> ui/lib/application -> common/swaglog
        -> system/hardware/__init__ -> tici/hardware -> tici/lpa -> import serial
```

缺 pyserial 时更新器**立刻** ModuleNotFoundError，而 `agnos_init` 的 `while true` 永远
恢复不了 → 设备卡在「装不进 AGNOS」的循环里（首启/全新刷机最危险）。

上游做法：
- `pip_requirement_for()` 增加 `serial) -> echo pyserial` 映射。
- `bootstrap_deps()` 依赖组补 `serial`（AGNOS 已最新时也会跑，保证 `/data/.pydeps` 有）。
- 新增 `ensure_updater_deps()`：进 `agnos_init` 的 while 之前 + `launch()` 里
  `ensure_bluez` 之后各调一次；**优先随包离线 wheel**，其次 pip 镜像，最终仍失败也
  返回 0（非致命，不阻断整条启动链）。
- 随包携带 `third_party/wheels/pyserial-3.5-py2.py3-none-any.whl`（90KB）。

### 本 fork 必须补的一刀
上游那段新代码里的 3 处网络/安装调用是**裸的**，违反本 fork 的启动路径硬化规则
（`openpilot/system/tests/test_launch_boot_bootstrap.py`
`test_every_network_call_in_the_script_is_bounded`：curl 必须有
`--max-time`+`--connect-timeout`，pip 必须有 `--timeout`+`--retries 0`）。
cherry-pick 后该测试立刻挂了 3 项（行 500/512/516）。按既有写法补齐：

| 调用 | 补 |
| --- | --- |
| 离线 wheel 的 pip | `--timeout 15 --retries 0`（规则不分是否联网） |
| get-pip 的 curl | `--connect-timeout 5 --max-time 30` |
| 走镜像的 pip | `--timeout 15 --retries 0` |

### 验证
- `system.tests.test_launch_boot_bootstrap` → **7/7 通过**（含上面那条兜底规则）。
- 离线 wheel 实测：`pip --no-index --target <tmp> pyserial-3.5-*.whl` → `import serial` = **3.5** ✅
- `bash -n launch_chffrplus.sh` 语法通过。
- 顺带确认 `ensure_updater_deps()` 依赖的 helper 在本脚本里都存在：
  `WHEEL_DIR`(8) / `find_python`(27) / `setup_python_path`(34) / `wait_for_dns`(82) /
  `pip_scratch_dir`(105) / `PYDEPS_DIR`(4) / `PY`(731)。`setup_python_path` 会在
  `$PYDEPS_DIR` 存在时把它并进 `PY_PATH`，与上游注释一致。

### 生效条件
改的是**启动脚本**，需重启设备（或重跑 launcher）才生效；不影响已在跑的 manager/ui。

### 顺带核对（本次未改）
- **`838cd92b47 更新系统镜像包` 故意不拉**：它把 `AGNOS_VERSION` 从
  `19.8-carrot-bt1` 提到 `19.8-carrot-bt2`，并整表替换 `agnos.json`/`agnos_tici.json`
  的 url/hash/compressed_size（system 镜像 ~1.0GB，boot 分区 url 从
  `github.com/ajouatom` 改到 `gitee.com/mouxan`）。一旦拉下来，所有设备的 AGNOS
  都会被判定为过期并触发系统镜像更新——这是**用户可见的大动作**，需要人工确认后再拉。
- 子模块 gitlink 与各自 origin 一致：`ai` = `3be6a6d`（origin 同）、
  `webui` = `c0f8a11`（origin 同）。
