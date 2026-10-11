# DAY_LOG 2026-10-11 —— 对齐上游 `mouxangithub/openpilot` test（逐条评估 + 部分移植）

> 背景：上游 `test` 上又出现 5 个更新（用户从网页看到）。问题：**能不能直接拉取对齐？**
> 结论：**不能直接 merge**；逐条评估后移植了 2 条（carrot-web、webui 桥），
> 另外 2 条（opendbc pin、Mazda feat）**主动不取**，1 条（ruff lint）**留作独立清理**。

## 一、为什么不能直接 merge

```
git merge-base HEAD upstream/test   -> 20be508f66      # 上游被 force-push，历史无共同祖先
git rev-list --left-right --count HEAD...upstream/test -> 239  9
```

- 上游 `test` 的 9 个「他们独有」提交里，前 3 个（`c10b6340b2` / `a6156bb030` / `f4aead756e`）
  我们已在此前的 `af951e89d3` 里**按内容并入**（那个动控 PID 双积分 / MPC NaN 种子那次）。
- 剩下 6 个才是这次要判断的。直接 `git merge` 会因为基线不可用而变成「拿上游整棵树覆盖我们」，
  实际后果是把本仓的 Macan 专有工作删掉（见第三节 opendbc）。

## 二、逐条评估

| # | 上游提交 | 内容 | 结论 |
|---|---|---|---|
| 1 | `fe2ceb3bb9` 更新jetlink | jetlink 子模块指针 → `51217933` | **无需动作**：`51217933` 已是我们 `fd0e3e9` 的祖先（我们 jetlink 在上游 cn 之后又走了 6 个提交） |
| 2 | `b39c7ae56c` chore(opendbc) | opendbc pin → `6b999db3`（zoompilot develop / Mazda） | **不取**，会删本仓 Macan MLB 代码 |
| 3 | `ba84f8fe65` feat(mazda) | Mazda steer-to-zero 扭矩默认值 + ICBM 适用性重构；`params_keys.h` 4 键；`manager.py` offroad 播种 | **不取**（Mazda 专属，本车 Macan）。其中 `icbm_applicable()` 重构部分如需可单独评估 |
| 4 | `e9b9a24a5a` feat(carrot-web) | 8088 面板新增 `/settings`、`/actions` 两页（新增 `web_settings.py`） | **已移植**（见第四节） |
| 5 | `c237180526` fix(webui) | webui pin → `75dac813`：清地图写的是未声明的 `OsmDbDelete`（`UnknownKeyName`，实际啥也没删） | **已移植**（见第四节） |
| 6 | `2f5c41653e` style(lint) | `ruff check openpilot` 清零，87 文件 302 findings | **留作独立清理**（见第五节） |

## 三、为什么 opendbc 这个 pin 不能跟

我们的 opendbc（`FOREVERZAX1988/opendbc` @ `9b88156a2`）是「上游 tn-c3 `a378bf0aa` + 本仓 Macan MLB 增补」。
把 pin 换成上游 `6b999db3`（zoompilot develop）等于用他们的树覆盖我们的：

```
opendbc/car/volkswagen/radar_interface.py                    -69
opendbc/car/volkswagen/tests/test_macan_mlb.py              -780
opendbc/sunnypilot/car/volkswagen/macan_calib.py             -50
opendbc/sunnypilot/car/volkswagen/stop_and_go.py            -376
opendbc/sunnypilot/car/params_access.py                      -78
opendbc/sunnypilot/car/volkswagen/values_ext.py              -12
```

换来的只有 Mazda（`mazda_2017.dbc`、`safety/modes/mazda.h`）与 Toyota 刹车进点。
**本车用不到 → 一律不取**，保持现状（与「跟我们无关的上游内容才严格对齐」的原则一致：
这里的「对齐」代价是删掉我们的功能，不是对齐）。

## 四、这次移植的两条

### 1. `e9b9a24a5a` carrot-web 设置页 / 操作页（commit `39f2fe1ad0`）

- 我们的 `carrot/web_interface.py` 与上游父版本**逐字一致**，所以按上游原文移植：
  新增 `carrot/web_settings.py`（扫描车机设置页源码 → 用页面自己的参数键分节；控件类型以
  params 二进制声明为准，绝不渲染未声明的键；配对/日志这类非写入页归到「操作」），
  `web_interface.py` 接上 `/settings`、`/actions`、`/settings_save`、`/action_run`。
- **修掉上游这个提交自身的一处缺陷**：`Params.all_keys()` 返回的是 **bytes**（二进制自己的
  缓冲），而页面扫描出来的是 `str`；`set()` 比对为空集 → 630 个键全落进「内部参数（other）」
  一节，且 `render_control()` 对 bytes 键调 `html.escape()` 会抛 `TypeError`，整页 500。
  已在 `collect()` 里解码；新增 `tests/test_carrot_web_settings.py`（7 例）钉住这个回归。
- 验证：`openpilot/sunnypilot/carrot/tests` **432 passed**（含新增 7 例）。

### 2. `c237180526` webui 桥的地图清理修复（webui `ac6662e`，指针 `b32d62b → ac6662e`）

- 经比对，我们 webui fork 与上游 `75dac813` 的 **merge-base 就是 `0cb1b00`**，也就是说上游
  只比我们多这一个提交 → 直接 cherry-pick，落成 `ac6662e`（保持上游作者与提交信息）。
- 内容：`osm_api` / `storage_api` / `system_api` 三处清地图从**未声明**的 `OsmDbDelete`
  改成已声明的 `Mapd_ClearCache`（否则 `UnknownKeyName`，点了删地图其实没删）；并清掉
  mem 侧 `OSMDownloadLocations` / `OSMDownloadBounds`，避免用户清完又被半截下载自动续上；
  `osm_download_progress()` 现在同时看「地点列表」和「边界框」两种下载。
- 交叉核对：`openpilot/common/params_keys.h:296` 确有 `Mapd_ClearCache`，全树无 `OsmDbDelete`。
- 验证：`webui/server/bridge/tests` **74 passed / 3 failed**；那 3 个失败在**移植前**
  （`b32d62b`）完全相同（`carrot__egpu` 子面板空、group 行 8→9 未同步测试），是上游自身缺陷，
  与本次改动无关（已用「回退这 4 个文件再跑」直接证实）。

## 五、lint 那条为什么留作独立清理

`2f5c41653e` 是 `ruff check openpilot` 清零（87 文件 302 findings）。本机现状：

```
ruff check openpilot  -> 317 findings
  ISC002 128  F401 51  RUF100 39  E501 22  F841 18  TID251 12  W29x 15  C420 7  B007 5  ...
```

- **真 bug 那部分上一提交已经修了**（`6af61382cc`：未定义名 / 重复定义 / 重复键）。
- 剩下 317 条里 `ruff --fix` 只覆盖 130 条；`ISC002`（多行隐式字符串拼接）128 条要人工重排。
- 本仓 CI（`.github/workflows/`）**不跑 ruff**，所以它不阻塞任何东西。
- 结论：纯风格、零行为收益、一次动 ~90 个文件 → **不与功能改动混在一起**，需要时单独一个提交做。

## 六、本次落地

| 仓库 | 提交 | 内容 |
|---|---|---|
| `FOREVERZAX1988/webui` | `ac6662e` | 地图清理改用 `Mapd_ClearCache`（移植上游 `75dac81`） |
| `FOREVERZAX1988/openpilot` | `39f2fe1ad0` | carrot-web 设置页 / 操作页（移植上游 `e9b9a24a5a` + 修 bytes 缺陷） |
| `FOREVERZAX1988/openpilot` | 见下一条 | webui 指针 `b32d62b → ac6662e` |

未动：`panda`（仍 `d84b110fc`）、`opendbc_repo`（仍 `9b88156a2`）、`jetlink_repo`（仍 `fd0e3e9`）。

## 七、同日再拉一次：上游又动了 3 个提交（carrot 全站移植）

写上面这份评估时本地 `upstream/test` 停在 `2f5c41653e`。当天 13:37 之后上游又推了 3 个提交
（`git fetch https://github.com/mouxangithub/openpilot.git test`，SSH remote 权限不足，走 https）：

| 上游提交 | 内容 | 体量 |
|---|---|---|
| `b161d88a44` feat(carrot) | 6999 恢复终端（`sunnypilot/carrot/recovery/server.py`），**上游改为 `CarrotRecoveryEnabled` 门控、默认关** | 5 文件 / +2728 |
| `b57fdcc4d6` feat(carrot) | CarrotPilot 的 `server/` 全树 + `web/` 前端整包移植（7000 面板）；新增 `realtime/`（C++/Cython 加速器）、`web_upload.py`、`carrot_settings.json` | 730 文件 / +188577 |
| `aae89bbea0` docs(carrot) | 记档：7000 面板、6999 恢复、plan-C 移植 | 3 文件 / +320 |

### 能不能 cherry-pick？—— dry run 结果

```
git worktree add --detach /tmp/cp-test HEAD          # 不动主工作树
GIT_LFS_SKIP_SMUDGE=1 git cherry-pick -n b161d88a44 # 冲突 1 个
GIT_LFS_SKIP_SMUDGE=1 git cherry-pick -n b57fdcc4d6 # 冲突 1 个
GIT_LFS_SKIP_SMUDGE=1 git cherry-pick -n aae89bbea0 # 干净
```

| 提交 | 冲突文件 | 增/删/改 |
|---|---|---|
| `b161d88a44` | `openpilot/system/manager/process_config.py` | 3 A / 1 M / 1 UU |
| `b57fdcc4d6` | `pyproject.toml` | 698 A / 3 D / 20 M / 1 UU |
| `aae89bbea0` | 无 | 3 M |

**结论：可以 cherry-pick，两个冲突都好解**，但**不是零代价**：

1. **两个冲突点**
   - `process_config.py`：只是插入位置相撞，把上游那段 `carrot_recovery_enabled` 门 + 
     `carrot_recovery` 进程登记塞进去即可。
   - `pyproject.toml`：上游那次把同一段「vendored from CarrotPilot」注释**重复贴了 10 遍**（上游自身缺陷，
     别照抄），实际内容是 `[tool.ruff.lint.per-file-ignores]` 给 carrot 树加豁免；
     解冲突时要**同时保住本仓自己加的三条依赖**（`shapely`、`aiohttp`、`opencv-python-headless`）。
2. **`b57fdcc4d6` 会删掉本仓 3 个文件**
   `server/features/{carrot_navi,intro,tools}.py` 被上游改成同名**目录包**；
   另有 `carrot/tests/test_carrot_web_settings.py`（我们为 `Params.all_keys()` 返回 bytes 那个 500 写的回归测试）
   上游没有——**要单独保住**，别跟着删。
3. **产品决策：面板搬到 7000**
   上游这一版是「CarrotPilot 的整站」落在 7000；本仓 8088 的面板 + `39f2fe1ad0`
   （移植 `e9b9a24a5a` 的设置页/操作页）会被它**整体取代**。要 7000 还是留 8088，得先定。
4. **未取的老三样仍然不取**：`b39c7ae56c`（opendbc pin）、`ba84f8fe65`（Mazda）、
   `2f5c41653e`（ruff 全量）——理由见第三、五节，与这次无关。

> 状态：**评估完成，移植未做**（等 7000/8088 的决定）。
