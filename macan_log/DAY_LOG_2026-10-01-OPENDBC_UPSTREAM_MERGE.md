# DAY_LOG 2026-10-01 — opendbc 子模块并入上游 master-c3（步骤2）

## 结论
opendbc fork（`FOREVERZAX1988/opendbc`，分支 `sp-macan-re`）把上游 tip **6580582cc「适配c3」** 合并进来：

- 合并提交：`b5ee1ecb7`（父：`341e046c2` 我方 Macan 分支 tip），已推送
- openpilot 侧指针：`341e046c2 → b5ee1ecb7`，提交 `4f8ce616a3`，已推送
- 相对上游的差异从 **66 文件** 收敛到 **18 文件 / +2587 / -214**，且 18 个文件全部是 Macan/VW-MLB 内容
  （car.capnp 我方字段、vw/{carcontroller,carstate,mlbcan,mebcan,mqbcan,pqcan,radar_interface,values,interface}、
  vw/tests/test_macan_mlb.py、safety/{volkswagen_common.h,volkswagen_mlb.h,test_volkswagen_mlb.py}、
  sunnypilot/car/volkswagen/{stop_and_go.py,values_ext.py}、vehicle_model.py、tests/routes.py）

> 说明：why not 直接"把指针顶到上游 6580582cc"？实测那样会：
> 1) 删掉 `opendbc/sunnypilot/car/volkswagen/values_ext.py`，而 openpilot 的
>    `sunnypilot/mads/helpers.py` / `sunnypilot/selfdrive/car/car_specific.py` 正在 import 它（ImportError）；
> 2) 丢掉 Macan 起步跟停/MLB 纵向整条链（stop_and_go / mlbcan / carcontroller ≈ 2500 行）。
> 所以采用「并入上游 + 保留最小 Macan 差异」。

## 冲突与两处静默损坏
7 个文件冲突，全部是上游新增内容（我方无本地修改），取上游即可：
docs/CARS.md、sunnypilot/car/car_list.json、car/tests/routes.py、car/torque_data/substitute.toml、
car/toyota/{carcontroller,fingerprints,values}.py

合并中额外修掉两处 git 无法感知的损坏：
1. `car.capnp`：我方早前误删 `SafetyModel` 的 `byd/volvo/bmw/mg` 四个枚举值 → 恢复；
   否则上游 `opendbc/car/byd/interface.py` 引用 `SafetyModel.byd` 直接 ImportError。
2. `car.capnp`：我方 `steerRatioV2 @78` 与上游新增 `extFlags @78` **序号撞车**（capnp 编译期
   Duplicate ordinal）→ 我方字段移到 `@80`，并在行内注明"每次并上游需重挑序号"。
3. `tests/routes.py`：上游 master-c3 自身缺一个逗号（`BYD.BYD_YUAN_PLUS_DMI_22,`）导致该文件
   是 SyntaxError、test_routes/test_models 完全无法收集 → 补上（1 字符，唯一一处非 Macan 的本地差异）。

## 验证（与上游 pin 同口径对跑）
| 套件 | 上游 6580582cc | 合并后 | 旧 pin 341e046c2 |
|---|---|---|---|
| opendbc/car/tests | 144 failed / 759 passed / 411 skipped / 11128 subtests | **完全一致** | 75 failed + 66 error / 771 passed / 8675 subtests |
| opendbc/car/volkswagen/tests | — | 37 passed / 96 subtests | 37 passed |
| openpilot 侧 Macan 相关 | — | 28 passed / 6 skipped（longcontrol、cruise_speed、vcruise×2、carrot_speed_cmd） | — |

→ 合并**零新增失败**，且把旧 pin 的 66 个 collection error 全部消掉；Hyundai 40 例失败与上游逐字一致。

## 继承下来的上游自身缺陷（非我方引入，按"严格对齐上游"不本地修）
- `opendbc/car/hyundai/carstate.py:95`：把 `self.params = CarControllerParams(CP)` 后调用
  `self.params.get_int("VehicleNaviCanControl")` → `AttributeError`；上游同样复现（Hyundai 40 例）。
  ⚠️ 这会让 Hyundai 车在真机 car 进程直接崩（我们开 Macan/MLB，不受影响）。
- `opendbc/car/toyota/carstate.py` 缺 `get_virtual_cruise_button`，而 openpilot 的
  `sunnypilot/selfdrive/car/tests/test_custom_cruise.py` 互相 import 它 → 该测试文件收集即 ImportError。
- 上游 `opendbc/car/tests/routes.py` SyntaxError（已本地补逗号，见上）。
- `openpilot/selfdrive/controls/tests/test_leads.py::test_radar_fault`（与上游逐字节一致）极慢，
  单跑 >250s 未完成 —— 长尾用例，单独长跑处理。

## 步骤3 现状：openpilot 主仓 vs 上游 master-c3 仍差 205 文件
71 新增（我方）/ 132 修改 / 2 删除。按类别（文件数 +行/-行）：

| 类别 | 文件 | +/- |
|---|---|---|
| openpilot/selfdrive/ui（carrot/mici UI） | 49 | +45476/-27507 |
| openpilot/sunnypilot（SP/MADS/sunnylink） | 22 | +653/-186 |
| openpilot/system/ui（mici 组件） | 16 | +389/-260 |
| 仓库根/.github/子模块 | 17 | +399/-146 |
| selfdrived（事件/告警） | 4 | +228/-220 |
| system/*（loggerd/manager/webrtc/athena） | 14 | +199/-130 |
| selfdrive/controls | 6 | +247/-56 |
| common/*（params/hardware/api） | 8 | +159/-131 |
| selfdrive/car | 3 | +70/-74 |
| pandad | 5 | +102/-42 |
| assets（字体/音效） | 3 | +2/-16 |
| CI/同步基础设施（我方新增） | 22 | — |
| DAY_LOG_*.md | 19 | — |
| tools/macan/*（扫描工具） | 12 | — |

删除的 2 个：`.github/workflows/lfs-maintenance.yaml`、`sunnypilot-build-prebuilt.yaml`（我方无 LFS 权限，保留删除）。
