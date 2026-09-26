## 2026-09-20（四续）encoderd 硬 assert 改造落地 + 凭据清理

### 一、复核发现：上轮以为已修的 encoderd assert **其实没落地**
- `git diff upstream-mx/master -- openpilot/system/loggerd/encoder/v4l_encoder.cc` = **空**
  （该文件最后一次改动是上游 `cf790746cc`）→ 设备上跑的仍是上游原版
  `line 126: assert(extra.timestamp_eof/1000 == ts); // stay in sync`
- 影响（仍在）：三路相机流里任意一路失步 → **整进程 abort（SIGABRT）**
  → 三路流全断 + 当前 segment 报废 + 留下无扩展名坏 crash 文件堵死 sunnylink 上传队列

### 二、改造（已编译验证）
- `v4l_encoder.cc`：硬 assert → `if (extra.timestamp_eof/1000 != ts) LOGE_100(...)`
  - **保留 `e->extras.pop()` 的 1:1 配对语义**（失步时帧配对依然正确，只丢时间戳一致性）
  - `LOGE_100` = swaglog 自带限频宏（前 2 次 + 每 100s），不会刷屏
  - **同步时（正常路径）逐字节行为不变**；livestream/web 解码代码在 `encoderd.cc`，**本轮未动**
- 构建：`scons -j1 openpilot/system/loggerd/encoderd` → `SCONS_EXIT=0`（仅重编 v4l_encoder.o + relink）
- 验证：`strings encoderd | grep -c 'timestamp desync'`=1、`'stay in sync'`=0；ELF aarch64 8,383,328 B
- 回滚物：旧二进制 `/data/encoderd.bak-20260920-225733`
- **未动**：`line 41` / `line 342` 两处 assert（取帧/停流路径，风险更高，先只修稳态最可疑的一处）

### 三、凭据清理（"别把密钥传上去"）
- **更正上轮结论**：`.git/config` 与 `.git/modules/{ai,opendbc,webui}/config` 的 `pushurl`
  **只有用户名、无 token**（`has_password=False`）→ 上轮"明文 PAT 躺在 git config"是误判
- **真实暴露**：`/data/ai/` 下 **9 个备份**仍含明文 token（共 **16 处**）
  → 已就地打码 `***REDACTED-BY-AI-20260920***`；**live `config.json` 未动**（仍 1 处，推送不受影响）
- 鉴权走 op助手存量 token（`forge_auth_status`: configured / valid / FOREVERZAX1988），无需新 token

### 四、测试边界（不上车能测到什么）
- 能测：编译通过、二进制含新日志点、无旧断言、加载即起（本例全部通过）
- 不能测：失步本身**无法人工构造**（需真机 camerad + V4L2 硬件时间戳偏移）
- 上车后判据：若再失步 → 坏 crash 文件不再产生，swaglog 出现
  `v4l/visionipc timestamp desync` 一行，**而不是** SIGABRT
