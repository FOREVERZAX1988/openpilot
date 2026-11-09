# DAY_LOG 2026-10-02 — card 订阅表回退(onroad 必崩) + cruise 参数 None 崩溃（步骤3 定向单测带出的两个真 bug）

## 结论（一句话）
本轮做「步骤3 全量定向单测」时，`test_leads.py` 在真机上**不是慢，是永久挂死**；追下去发现两个真 bug：
1. **`card.py` 的 SubMaster 订阅表被 ②类扁平化回退成短表**，而同一文件保留了上游 `carrotNaviSP` 的读法
   ⇒ **onroad 时 card 起步第一步就 KeyError 崩**（每次点火必崩，即"无法控车"）；
2. `cruise.py` 里 26 处 `params.get("KEY")` 在参数未写入时返回 `None`，随后参与比较/乘法 ⇒ `TypeError`。

两个都已修，测试从「挂死 8h」变成「9.87s 通过」。

---

## 1. 现象：test_leads 不是慢，是挂死
- 起先以 `>250s 未完成` 被归为「长尾用例」，但实测：
  - pytest 进程 **0% CPU、输出文件 0 字节、持续 7h54m**；
  - 子进程 `[openpilot.selfd] <defunct>`（僵尸），父进程 `poll_schedule_timeout` 永久等待。
- 机制：`process_replay` 的 `get_output_msgs()` → `ReplayContext.wait_for_recv_called()` **没有超时**；
  被 replay 的 card 进程一启动就崩（僵尸），父进程便永久等它 recv。

## 2. 用 `-s` 抓子进程 stderr，拿到两层崩溃
```bash
PYTHONPATH=/data/pytest_deps:/data/openpilot pytest openpilot/selfdrive/controls/tests/test_leads.py -q -s
```
**第 1 层**（`cruise.py:280`，`VCruiseCarrot.__init__`）：
```
self._lat_enabled = self.params.get("AutoEngage") > 0
TypeError: '>' not supported between instances of 'NoneType' and 'int'
```
`Params.get(key, return_default=False)` 在键为空时返回 `None`（默认值只有 `return_default=True` 才取）。

**第 2 层**（`card.py:229`，`state_update`）：
```
if self.sm.updated['carrotNaviSP'] and self.sm.valid['carrotNaviSP']:
KeyError: 'carrotNaviSP'
```

## 3. 根因：`d8f44429a8` 把 SubMaster 打成短表
`git log -L 79,79:openpilot/selfdrive/car/card.py`：
| 提交 | 时间 | 行内容 |
|---|---|---|
| `7b8214bf8f`（mouxan「适配c3」） | 2026-09-29 | 长表：`...'longitudinalPlan','radarState','drivingModelData'] + ['carControlSP','longitudinalPlanSP','carrotManSP','carrotNaviSP'] + ['customReservedRawData0']` |
| **`d8f44429a8`（我方 ②类扁平化）** | **2026-09-30** | **短表：`['pandaStates','carControl','onroadEvents','radarState'] + ['carControlSP','longitudinalPlanSP']`** |

即：②类扁平化是从上游合并前的旧快照生成的，**把卡片的订阅表整体退回**，却保留了上游新代码里对
`carrotNaviSP` 的访问 ⇒ 自相矛盾。`carrotManSP` 那处因为写的是 `self.sm.valid.get('carrotManSP', False)`
（`.get()` 带默认）才没立刻炸。

**它与「上游缺陷修补」无关——这是本 fork 自己引入的回归**，且后果是最严重的一类：行车必崩。
（实机 `crashes/` 里目前只有本次测试产生的 `carrotNaviSP` 记录，没有真实行车记录，说明自 09-30 之后尚未上路验证。）

## 4. 修复（两处，均为最小改动）
### 4.1 `openpilot/selfdrive/car/card.py`（1 行）
把第 79 行恢复成上游 `master-c3` 逐字一致的列表：
```python
self.sm = messaging.SubMaster(['pandaStates', 'carControl', 'onroadEvents', 'longitudinalPlan', 'radarState', 'drivingModelData'] + ['carControlSP', 'longitudinalPlanSP', 'carrotManSP', 'carrotNaviSP'] + ['customReservedRawData0'])
```
（找回 `longitudinalPlan` / `drivingModelData` / `carrotManSP` / `carrotNaviSP` / `customReservedRawData0`）

### 4.2 `openpilot/selfdrive/car/cruise.py`（26 行）
`__init__`（`AutoEngage`、`UseLaneLineSpeed`）与 `update_params`（24 处）里的
`self.params.get("KEY")` → `self.params.get("KEY", return_default=True)`。
- 语义 = 用 `params_keys.h` 里**已声明的默认值**（`AutoEngage=0`、`CruiseSpeedUnit=10`、`CruiseSpeed1..5=10` 等，已逐个核对）；
- 参数**已写入**时行为完全不变（`return_default` 只在键为空时起作用）；
- 注意：同样的裸 `get()` 写法在 `cruise.py` 还有 4 处（`LongitudinalPersonalityMax`、`CruiseGapLevels`、`LongitudinalPersonality`、`MyDrivingMode`，765/766/770/802 行），
  本轮**未动**（属另一条按流派路径），留待决定。

## 5. 验证（真机 C3，`PYTHONPATH=/data/pytest_deps:/data/openpilot`）
| 套件 | 修复前 | 修复后 |
|---|---|---|
| `controls/tests/test_leads.py::test_radar_fault` | 永久挂死（8h 无输出） | **1 passed in 9.87s** |
| 定向批量（car/tests 4 个 + system/tests + manager + controls 全量 + sunnylink 6 个） | — | **123 passed / 11 skipped / 1 failed in 257s** |

唯一失败 = `system/tests/test_logmessaged.py::test_big_log`：
`assert 590985798 < (10*(3145728+1024))` —— `_get_log_files()` glob 的是 `Paths.swaglog_root()/swaglog.*`，
真机上就是**设备自身的历史 swaglog**（590MB），与本用例写入的 ~31MB 无关 ⇒ **环境相关，非代码缺陷**
（与本会话前次结论一致）。另一处环境缺依赖：`sunnylink/tests/test_compile_settings_ui.py` 收集失败（`No module named 'yaml'`），已从批量中排除。

## 6. 顺带确认的两个口径问题
1. **opendbc 的 master-c3 vs tn-c3 不是一回事**：`master-c3`=3ce9c30b1(09-14)、`tn-c3`=6580582cc(09-29)，
   差 **33 提交 / 50 文件 / +2918**。但 openpilot 的 `master-c3` 把 opendbc pin 到 **6580582cc（= tn-c3 tip）**
   ⇒ 我们 opendbc 并入 `6580582cc` 正是「跟随上游 master-c3 的 pin」，无需再动。
2. **③类补丁必须保留**：上游 `master-c3`(df61c8fd9f, 2026-10-01) 里依然**没有** `logmessaged.py` 的统一写入修
   / `test_logmessaged.py` / 两个 uploader 回归测试（`git diff upstream/master-c3..HEAD` 仍 +227/-2）；
   `xiaoge/assets/v_asm_model.onnx`、`.gitattributes` 与上游**零差异** ⇒ 前者无需处理，后者上游也没有（跟随即可）。
   与 webui 的结论一致：**上游没有自修，补丁不能删**。

## 7. 待决策 / 未完成
1. 本提交是否推送（本地已提交，未推）。
2. `test_big_log` 的处理：改成「只统计测试期间新增的量」（在 `_get_log_files()` 前后各取一次 size）或按设备 `skipIf(COMMA_HARDWARE)`。
3. `cruise.py` 另 4 处同类裸 `get()`（765/766/770/802）是否一并修。
4. **rednose / tinygrad 子模块指针仍与上游 `master-c3` 不同**（本轮才发现，之前只核了 panda/opendbc/webui/ai 四个）：
   - rednose：我方 `8671c17`（多一行 `.gitattributes: * text=auto eol=lf`）vs 上游 `28d4a7f`，**内容差异仅这 1 行**；
   - tinygrad：我方 `66ee3cfb`(2026-08-10, sunnypilot fork merge) vs 上游 `f6fc4e3f`，**293 文件 / +14626 / -7394**，
     且与 `modeld_v2/compile_modeld.py` 相关 ⇒ 跟随上游会真实影响模型编译，需在 PC/CI 验证后再动。
5. CI「整链构建」：`build.yaml` 不在 `sp-macan-re` 上自动触发，只能手动 `workflow_dispatch`（且需要自建 runner）——按用户选择「先做其他事，runner 之后再说」，本轮未做。
