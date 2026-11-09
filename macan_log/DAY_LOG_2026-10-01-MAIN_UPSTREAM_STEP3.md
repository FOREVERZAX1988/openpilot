# DAY_LOG 2026-10-01 — 主仓（openpilot）对齐上游 master-c3（步骤3）+ opendbc 复核（步骤2 收尾）

## 结论（一句话）
- **② opendbc**：合并后对 **6580582cc** 的差异 = 18 文件，全是 Macan/VW-MLB 有意内容 → **无需回退**；但发现一个 ref 口径问题（见下）。
- **③ 主仓**：只落后上游 **1 个 commit**（`df61c8fd9f` locationd IMU 自标定），已并入（`d77a6cead7`）并用其自带测试验证 **25 passed**。
  相对上游的 **205 文件差异 = 全部是有意的 fork 内容**，不是"没合并干净"；本次只清掉 1 处手滑残留。

## ①（前序，已收尾）
webui：`sp-macan-re` = upstream/main(`406cd29`) + 11 提交、0 behind；残留从 7 文件收敛到 **4 文件**（全是 bug 修复）。
见 `DAY_LOG_2026-10-01-WEBUI_UPSTREAM_MERGE.md` 末尾「步骤1b」。

---

## ② opendbc 复核

### 差异账本（口径不同，数字不同 —— 这是"为什么还有这么多"的根源之一）
| 对比基准 | 文件 | +/- | 含义 |
|---|---|---|---|
| `6580582cc`（步骤2 合并时引用的 ref） | **18** | +2587/-214 | 只剩我们的 Macan/MLB |
| `upstream/master-c3`（真·上游分支 tip） | **66** | +5505/-273 | 还多出 6580582cc 那一批 c3 适配 |

18 个文件逐条核对：`car/car.capnp`（我们的 `steerRatioV2 @80`）、`car/vehicle_model.py`、
`car/tests/routes.py`（补上游少的一个逗号，1 字符）、
`car/volkswagen/{carcontroller,carstate,mlbcan,mebcan,mqbcan,pqcan,radar_interface,values,interface}.py`、
`car/volkswagen/tests/test_macan_mlb.py`、`safety/modes/{volkswagen_common.h,volkswagen_mlb.h}`、
`safety/tests/test_volkswagen_mlb.py`、`sunnypilot/car/volkswagen/{stop_and_go.py,values_ext.py}`。

→ **全部是我们有意保留的 Macan / VW-MLB 纵向工作，没有可回退项。**

### ⚠️ 发现：步骤2 合并引用的「上游 tip」并不在 master-c3 上
```
git ls-remote upstream refs/heads/master-c3 → 3ce9c30b18   (2026-09-14, mouxan)
6580582cc 「适配c3」 (2026-09-29) 只存在于  upstream/tn-c3
git merge-base --is-ancestor 3ce9c30b 6580582cc → 否（两条线无祖先关系）
```
即：步骤2 实际并入的是 mouxan 的 **`tn-c3`** 分支，而 daylog 里写成了「master-c3 适配c3」。
若「严格对齐上游」的口径是 `master-c3`，则我们相对 master-c3 是 **0 behind / 188 ahead**
（master-c3 的内容在 0919 那次 `cb943a5c6` 就并过了）；多出来的 6580582cc 那批属于**另一条分支**。

**处理：暂不回退**（回退会丢掉约 2500 行 c3 适配），先把口径记在这里，等确认「上游 = master-c3 还是 tn-c3」。

---

## ③ 主仓（本步骤）

### 落后 / 领先
```
merge-base(sp-macan-re, upstream/master-c3) = df61c8fd9f   ← 上游 tip
git rev-list --left-right --count upstream/master-c3...HEAD →  0  behind / 35 ahead
```
上游自 `838cd92b47` 以来只多了 **1 个** commit：`df61c8fd9f fix(locationd): repair IMU auto-calibration`
→ 已并入 `d77a6cead7`（只带 `imu_calibrationd.py` + 它的 test；`locationd/helpers.py` 我们已与上游逐字节一致，无冲突）。

验证：
```
PYTHONPATH=/data/pytest_deps:/data/openpilot \
  /data/pytest_deps/bin/pytest openpilot/selfdrive/locationd/test/test_imu_calibrationd.py -q
→ 25 passed
```

### 205 文件差异 = 有意保留的 fork 内容（**不是**待合并清单）
| 桶 | 文件数 |
|---|---|
| `selfdrive/ui`（carrot / mici） | 31 |
| `selfdrive/*`（controls / pandad / …） | 22 |
| `sunnypilot`（SP / MADS / sunnylink） | 22 |
| `DAY_LOG_*.md` | 21 |
| `.github/`（CI + `upstream_sync_*` 流水线） | 18 |
| `selfdrive/ui/translations`（`.po/.pot`） | 18 |
| `system/ui`（mici 组件） | 16 |
| `system/*`（loggerd / manager / webrtc / athena） | 14 |
| `tools/macan`（扫描工具） | 12 |
| 仓库根 / 杂项 | 8 |
| `common/*`（params / hardware / api） | 8 |
| `release/ci`（C3 runner） | 7 |
| 子模块指针（ai / webui / panda / opendbc / rednose / tinygrad） | 6 |
| `openpilot/*` 杂项 | 2 |

来源 = 3 个扁平化提交
`①8d760e5bce`（Macan 纵/横向整车适配）/ `②d8f44429a8`（系统功能性增补）/ `③a37968d0b5`（上游缺陷修补）
+ 其后 ~30 个收尾提交。

**结论：对齐的真正含义 = 保证这 205 个差异 100% 是「故意的」；把差异清零等于把 fork 删掉。**

### 本次清掉的 1 处「手滑」残留
- **`radar_handshake_report.txt`**（仓库根，34 行 0075 握手扫描转储）
  - 由 `8d760e5bce`（①类扁平化）误带入提交；
  - 而当天 `DAY_LOG_2026-09-19-TIME_SYNC.md` 明确写着「`radar_handshake_report.txt` …**未纳入提交**（保持仓库干净）」，
    且全仓无任何代码 / 脚本 / 测试引用它 → **删除**。
- 同类残留前序已清：`scan_0079_*.txt`、`translations/*.po.bak`、`app_zh-CHS.po.bak_20260906`、
  `DAY_LOG_2026-09-19-AMAP_KEY_TEST.md`（`6064ad608b`）。

### ③类：本地「上游缺陷修补」清单（**上游修好后可删本地补丁**）
来自 `a37968d0b5`（③类扁平化，11 文件 / +552/-2）：
| 文件 | 本地补的是什么 |
|---|---|
| `openpilot/system/logmessaged.py` | 统一参数写入（修日志进程的崩溃/竞态） |
| `openpilot/system/manager/test/test_manager.py` | 跟随上面的 manager 行为 |
| `openpilot/system/tests/test_logmessaged.py` | 上面两条的回归测试（**新增**） |
| `openpilot/sunnypilot/sunnylink/tests/test_uploader_no_permission_disable.py` | uploader 无权限自动关闭回归（**新增**） |
| `openpilot/sunnypilot/sunnylink/tests/test_uploader_skip_rejected.py` | uploader 拒绝路径回归（**新增**） |
| `.gitattributes` / `xiaoge/assets/v_asm_model.onnx` | 属性 / 资产 |
> 性质 = 「上游缺陷修补」：上游一旦自修，可整批删除本地补丁、回退到上游实现。

### 差异里的 2 个删除项（已确认**有意保留**）
`.github/workflows/lfs-maintenance.yaml`、`.github/workflows/sunnypilot-build-prebuilt.yaml`
（我方无 LFS 权限；C3 prebuilt 走自建 runner）。

---

## 下一步
1. **定口径**：opendbc 的「上游」是 `master-c3`(`3ce9c30b18`) 还是 `tn-c3`(`6580582cc`)？
   若前者，需要决定是否把 `tn-c3` 那批从「对齐基线」里单列出来。
2. **③类补丁收缩**：与上游 `master-c3` 逐一比对，确认哪些上游已自修 → 删除本地补丁。
3. 全量定向单测（controls / ui / carrot / sunnylink）+ 推送。
