# DAY_LOG 2026-10-19 —— jetlink 无线大模型：家里「行车预览」稳、上路几秒就交还小模型

> 一句话：不是 Wi-Fi 差、不是超时阈值太小，而是本 fork 多了一道 `preview` 门，
> 把三条救 Wi-Fi 的帧循环机制只挂在预览路径上；上路后它们全部失效，帧循环退回
> 「一帧在飞、等自己回包」的串行形态，Wi-Fi 上帧周期 45–56 ms 对 50 ms 相机，
> **余量为零**，几秒内被判 lag → 交还小模型。

## 一、现场证据（同一台机器、同一条链路，swaglog 23:16–23:23）

预览段（家里，静止、画面基本不变）：

```
jetlink: trips frames 4402 over 0 held 0 pipelined 4401 span_s 210 p50_ms 7.7 p99_ms 8.6 max_ms 10.2
```

上路段：

```
23:22:42 jetlink: in control, a preview's silence rule and its frame pipeline no longer apply
23:22:46 jetlink: modeld dropped 0.97 % of camera frames behind the large model, the small model drives from this one
23:22:46 jetlink: next attempt in 5 s (failure 4, link held 7 s, drop 0, lag 7 this drive)
23:22:46 jetlink: leaving (b...
```

同一链路，`p50` 从 7.7 ms 变成「帧周期 45–56 ms」，说明变的不是链路，是**帧循环的形态**。

## 二、根因：`preview` 门 vs 上游的「按介质」

- 上游（`mouxangithub/jetlink`）把每一条 Wi-Fi 放宽都钉在介质上：joining 时读
  `mode == 'wifi'` 决定 `WIFI_HOLD_FRAME`、`WIFI_SETTLING_FRAMES`、
  `WIFI_HOLDS_IN_A_ROW`、`WIFI_HOLDS_ALLOWED`，所以**预览和行车在同一套规则上**。
- 本 fork 另加了一道门 `preview`，并把**帧流水线（pipelining）**放到这道门后面；
  再叠加两条同样只属于预览的兜底：patient 写超时、5 秒静默宽限（silence rule）。
- 于是：`IsOnroadPreview` 一清零，三条全部失效 → 串行帧循环 → 零余量 → 判 lag。

## 三、修复（jetlink `cn`，已推送）

| 提交 | 内容 |
|---|---|
| `a4e0d93` | Wi-Fi 手机「落后一帧」是常态，不再每秒把大模型链路交还 |
| `84de735` | 被 hold 帧的迟到答复由下一帧读走（host 确实答了） |
| `904e041` | stop 信号由 handler 接管（不再有线程先吃掉它）→ 0.8.7-1019-1 |
| `f09a8b7` | Wi-Fi hold 窗口收回到相机帧内 |
| `b8cbb92` | **帧循环由介质决定，不再由 preview 决定**（与上游同构）→ 0.8.7-1019-2 |

父仓 `FOREVERZAX1988/openpilot` 的 `sp-macantest-1018` = `ae4e66ce80` 把 jetlink 指针
钉到 `b8cbb92`（设备端跑的就是这一版）。

## 四、兼容性：手机 APK 没变协议，不必为新 APK 焦虑

- 没有新增/改动线上协议字段：仍是本地读 `client.deadline`、只改帧预算与 hold 判定。
- 所以 **0.8.7-1019-1 的手机端与 0.8.7-1019-2 等价**；真正含修复的是**设备端**
  （openpilot 里 `jetlink_repo = b8cbb92`）。反过来：只换手机 APK 不更新设备端，等于没修。
- 0.8.7-1019-2 仍建议装上，理由只有一个：tag/version 对齐，避免下次又从 APK 版本开始怀疑。

## 五、上路验收判据（唯一还缺的一步：实测）

```sh
grep -h "jetlink:" /data/log/swaglog.* | grep -E "trips|held|lag|small model drives" | tail -30
```

- 通过：`held` 不再持续增长；`p99_ms` 稳在帧预算内；**不再出现**
  `next attempt in 5 s (… lag N this drive)` 与 `the small model drives from this one`。
- 若仍偶发 held 增长，下一步不是加超时阈值，而是继续压缩 Wi-Fi 上的 settling 帧数
  （让第一帧就出答案），以及确认手机侧 0.2 s deadline 是否先到。

## 六、CI 现状（2026-10-19 09:1x 核对）

- `b8cbb92`：`cn` 与 `sp-macan-long-dev` 两个 push 的 CI 均 **success**。
- `904e041`（0.8.7-1019-1）：两个 push 均 success。
- `853c4ca`（0.8.7-1017-6）：`sp-macantest-1018` 上失败，失败 job 是
  **Swift on Linux (aarch64) → Run the Swift tests**（同提交在 `cn` 上是 success）。
  这是旧点上的单点失败，后续 `904e041` / `b8cbb92` 已全绿，不再复现。

## 七、分支与产物对应关系

| 分支/产物 | 指向 |
|---|---|
| jetlink `cn` = `sp-macan-long-dev` | `b8cbb92` |
| release `0.8.7-1019-2`（prerelease，release key 签名 APK） | `b8cbb92` |
| release `0.8.7-1019-1` | `904e041` |
| openpilot `sp-macantest-1018` = `sp-macan-long-dev` | `ae4e66ce80`（钉 jetlink `b8cbb92`） |
