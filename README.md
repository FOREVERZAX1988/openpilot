# mouxancnb/openpilot — 我们的 openpilot 定制软件分支

这是运行在我们 comma 设备上的 openpilot 定制分支，基于 sunnypilot / zoompilot 系，配合自建的 **Toyota AGNOS**（定制系统固件）使用，带 Toyota Space 品牌界面与完善的中文支持。

> 上游项目：[sunnypilot](https://github.com/sunnypilot/sunnypilot)（特征集与调校框架） / [zoompilot](https://github.com/zoompilot/zoompilot)（Mazda 转向与雷达巡航调校） / [openpilot](https://github.com/commaai/openpilot)。上游特性说明见各自仓库。

## 三个项目怎么配合

我们的整套方案由三个仓库组成（详见 [agnos-builder README](https://cnb.cool/mouxancnb/agnos-builder)）：

```
┌─────────────────────────────┐
│  mouxancnb/agnos-builder     │
│  构建 Toyota AGNOS 固件镜像  │
│  + 刷机清单，发布到 release  │
└──────────────┬──────────────┘
               │ 发布 boot/system/清单
               ▼
┌─────────────────────────────┐
│  mouxancnb/openpilot  ←本仓库│
│  设备上运行的驾驶软件；同时   │
│  托管 all-partitions-tici.json│
│  （flash 工具「预设」的来源） │
└──────────────┬──────────────┘
               │ 预设清单 / 固件下载
               ▼
┌─────────────────────────────┐
│  mouxancnb/flash             │
│  网页刷机工具（Win/Android）  │
└─────────────────────────────┘
```

| 仓库 | 干什么 |
| --- | --- |
| [mouxancnb/flash](https://cnb.cool/mouxancnb/flash) | 网页刷机工具：把 AGNOS 固件线刷进设备 |
| [mouxancnb/agnos-builder](https://cnb.cool/mouxancnb/agnos-builder) | 构建 Toyota AGNOS（kernel/system/boot/横版开机画面）并发布刷机清单 |
| **mouxancnb/openpilot**（本仓库） | 设备上跑的驾驶软件；托管固件清单 |

## 安装到设备

1. 先用 flash 工具把设备刷到我们的 Toyota AGNOS（见 [flash 仓库 README](https://cnb.cool/mouxancnb/flash)）
2. 设备开机引导 / 设置里的「安装自定义仓库」，仓库地址填：
   ```
   https://cnb.cool/mouxancnb/openpilot
   ```
   分支留空默认 `master`（界面已中文化：「自定义仓库地址…」「滑动安装 自定义仓库」）

## 本仓库的双重职责

1. **设备软件**：openpilot 定制分支本体，master 分支是可安装的成品源树。
2. **固件清单托管**：`openpilot/common/hardware/comma/all-partitions-tici.json` 与 `all-partitions.json` 是 flash 工具**预设**清单的来源（`*-tici` 给 comma three，无后缀给 3X/four）。清单内容随 AGNOS 版本一起同步（`dump 20.6.x` 提交），boot/system 指向 agnos-builder 发布的最新构建。

## 我们的定制内容

* **Toyota Space 品牌界面**：开机 spinner 动画（Toyota logo glow）、品牌文字烘焙进 glow atlas
* **中文字体管线**：BMFont `.fnt` 字图运行时加载 + UNIFONT 兜底、字重运行时烘焙（不再依赖离线字图）
* **中文翻译完善**：设置/安装界面全量中文化（简繁双语，含自定义仓库安装流程）
* **稳定性修复**：语言选择器多字符崩溃修复等
* **固件清单管理**：`dump 20.6.x` 同步 AGNOS 清单，`agnos-tici.json` OTA 派生说明见提交历史

## 开发

* **源仓库在 GitHub**（Actions 构建环境），CNB 仓库是发布/镜像出口：
  * 用户侧直接维护 CNB `master`（固件清单、dump、UI 修改）
  * GitHub 上跑 `打包发布 CNB`（release.yaml，手动触发）把 master 精简打包后发布到 CNB `staging` 分支（精简树为大文件裁剪版，适配设备端拉取）
* 构建脚本见 `release/`（`build_release.sh` / `build_stripped.sh` / `build_carrot.sh`），submodules 用 `git submodule update --init` 拉全
* 固件侧（boot/system 镜像本身）不在本仓库构建，见 [mouxancnb/agnos-builder](https://cnb.cool/mouxancnb/agnos-builder)

## 免责声明

这是实验性软件。开车的是你，请遵守当地法律，风险自负，不提供任何担保。
