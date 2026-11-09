# pandad 旧二进制 × health_t 新布局 → pandaStates 枚举越界（2026-10-03）

结论先行：车上那个周期性 ERROR
`hardwared.py hardware_thread: RuntimeError: Member was null.`
（`failed to build STATUS_PACKET`，每 10 分钟一次）**不是 hardwared 的代码问题，也不是 panda 固件问题**，
而是 `openpilot/selfdrive/pandad/pandad` 这个**可执行文件没跟着 `panda/board/health.h` 重新链接**：
它按旧 `health_t` 布局解析 health 包，`fault_status_pkt` 落在错误的字节上，
读出一个越界值（实测 210），于是 `PandaState.faultStatus` 成了本地 schema 里不存在的枚举序号，
`p.to_dict()` 在 `capnp._DynamicEnum._as_str` 抛 `RuntimeError("Member was null.")`。

---

## 1. 现象与证据

* swaglog（`/data/log/swaglog.*`）稳定复现：
  `hardwared.py:502 hardware_thread` → `RuntimeError: Member was null.`，
  即 bfd72ce53e 加的兜底 `cloudlog.exception("failed to build STATUS_PACKET ...")`。
  最后一次出现：`2026-10-03 08:28:26`（重建 pandad 之前）。
* 直接订阅 `pandaStates` 逐字段探测，定位到唯一越界字段：

  ```
  pandaType    raw 9   -> tres        OK
  harnessStatus raw 0  -> notConnected OK
  safetyModel  raw 19  -> noOutput     OK
  faultStatus  ERROR RuntimeError: Member was null.      <-- 越界
  faults       ['relayMalfunction','interruptRateCan2','interruptRateUart7','sirenMalfunction']  <-- 也是错位垃圾
  p.to_dict()  FAIL  RuntimeError: Member was null.
  ```

  `p.faultStatus.raw == 210`，而本地 `cereal/PandaState.FaultStatus` 只有 `none@0 / faultTemp@1 / faultPerm@2`。

## 2. 根因

`panda/board/health.h` 在上游 **panda#2425「health packet cleanup」**（panda 子模块 `75aa44bec`，经 `42643dec1` 并入本仓）里被**改了字段布局**：

| 偏移 | 旧 health_t（cleanup 之前） | 现 health_t（本仓） |
|---|---|---|
| 4  | `uint32_t voltage_pkt` | `uint16_t voltage_pkt` |
| 6  | `uint32_t current_pkt` | `uint16_t current_pkt` |
| 28 | `uint32_t faults_pkt` | `uint16_t flags_pkt` |
| 32 | `uint8_t ignition_line_pkt` | `uint16_t safety_param_pkt` |
| 34 | `uint8_t ignition_can_pkt` | `uint8_t fault_status_pkt` |
| 39 | `uint8_t fault_status_pkt` | `uint16_t alternative_experience_pkt` |
| … | `float interrupt_load_pkt` / `float temperature` | `uint8_t interrupt_load_pkt` / `uint8_t temperature_pkt` |

`pandad.cc` 与该头文件一起编译（`panda.h: #include "panda/board/health.h"`）。
实机上：

* `panda/board/health.h` mtime = 2026-10-01 23:19
* `openpilot/selfdrive/pandad/*.o` mtime = 2026-10-01 23:2x（已按新头文件重编）
* **`openpilot/selfdrive/pandad/pandad` mtime = 2026-07-28 23:05（始终没被重新链接）**

所以运行时那个二进制仍按旧偏移读包：它以为的 `fault_status_pkt`（旧偏移 39）在新布局里是
`interrupt_load_pkt`/`fan_power` 一带的字节 → 240~255 之类越界值；`faults`（旧偏移 28）读到的
是新的 `flags_pkt` + `car_harness_status_pkt` → 于是出现「relay/siren 故障」这种不可能的组合。

> 这也解释了为什么它只在 `to_dict()` 里炸：`pandaStates` 的其它消费方（mads/card/selfdrived）
> 只读具体字段，不会因为一个越界枚举报错。

## 3. 修复

重新链接 pandad（无需改代码、无需重刷 panda 固件）：

```bash
cd /data/openpilot
scons -j$(nproc) openpilot/selfdrive/pandad/pandad
```

git 不跟踪该二进制（`openpilot/selfdrive/pandad/.gitignore` 里第一个就是 `pandad`），
所以这一步**没有对应 commit**，属于构建产物修复；`ai/scripts/rebuild_pandad.sh`
（工具 `rebuild_pandad`）就是干这个的。

⚠️ 教训：以后凡是 `panda/board/health.h`（或 `can.h`）随子模块更新，**必须重新链接 pandad**，
否则就是这个「编译通过、跑起来字段错位」的静默故障。

## 4. 验证

重新链接（mtime 2026-10-03 08:35，6743248 → 6759768 字节）后，重启 pandad：

```
pandaType    tres      raw 9   OK
faultStatus  none      raw 0   OK      <-- 修好
harnessStatus notConnected OK
safetyModel  noOutput  raw 19  OK
voltage 12078mV  current 0  faults []  OK
to_dict OK, keys: 32
```

`hardwared` 的 `failed to build STATUS_PACKET` 不再出现（重建前最后一条 08:28:26）。
`hardwared.py` 里的 try/except 保留为兜底，注释已更新指向本文。

## 4.5 为什么二进制会一直没被重新链接

同日的 `DAY_LOG_2026-10-01-PANDAD_SCONSCRIPT_NAMEERROR.md` 记了 10-01 那次
`pandad/SConscript` 的 `NameError`（`opendbc` 未 import + 重复块）——那次构建脚本是坏的，
`.o` 在 10-01 23:2x 重编过，但 `pandad` 可执行文件始终没更新（mtime 停在 07-28 的检出时间）。
即「源码/对象文件是新的，链接产物是旧的」。这类不一致只有跑起来读健康包才会暴露，
静态编译、单测都不会报。

## 5. 复查命令

```bash
cd /data/openpilot
stat -c '%y %n' panda/board/health.h openpilot/selfdrive/pandad/pandad   # 二进制须不旧于头文件
/usr/local/venv/bin/python3 - <<'PY'
import time
from openpilot.cereal import messaging as m
sm = m.SubMaster(['pandaStates'])
while not (sm.updated['pandaStates'] and len(sm['pandaStates'])):
    sm.update(100)
p = sm['pandaStates'][0]
print('faultStatus', p.faultStatus.raw, '| to_dict ->', end=' ')
p.to_dict(); print('OK')
PY
```
