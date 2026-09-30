## 2026-10-01 sp-macan-re 启动构建挂：pandad/SConscript 错并重复块 → opendbc NameError

### 现象
重启后 op助手 / manager 起不来，scons 报：

```
NameError: name 'opendbc' is not defined:
  File "/data/openpilot/SConstruct", line 289:
    SConscript([
  File "/data/openpilot/openpilot/selfdrive/pandad/SConscript", line 13:
    pandad_env['CPPPATH'] += [libusb.INCLUDE_DIR, opendbc.INCLUDE_PATH]
```

### 根因
②③类「扁平化」合并时，同一个文件把两个版本**叠在了一起**：

- 上半段是旧写法：`import libusb` → `env = env.Clone()` → `env.Library('panda', …)`
- 下半段是新写法：`pandad_env` + `opendbc.INCLUDE_PATH`

旧段没有 `import opendbc`，新段却引用它 → NameError；而且两段会各自构造同一个 `panda` 目标。

### 修复
删掉错并进来的旧段，恢复成单段实现；该文件与 `macanlong-test` 上已验证可编译的同名文件**逐字节一致**。

### 验证
- `python3 -c "ast.parse(...)"` 语法通过；`diff` 只含本 hunk。
- 该文件所需 include 都有来源：`panda/board/can.h` 的 `#include "opendbc/safety/can.h"` 由 SConstruct
  CPPPATH 里的 `#opendbc_repo` 提供；`opendbc.INCLUDE_PATH` 指向同一个 `opendbc_repo/`。
- 分支上其余 SConscript 均已核对：每个文件只有一个 `Import(...)`，没有同类重复块。

### 生效条件
改的是**构建脚本**：设备 `git pull` 后要重启（或重跑 scons）才生效，否则仍按旧 SConscript 报错。
