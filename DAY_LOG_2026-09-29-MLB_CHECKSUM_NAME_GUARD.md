# 2026-09-29 MLB 校验信号名复核：CHECKSUM vs ACC_05_CHK/TSK_04_CHK + 防回归断言落地

## 起因
两个问题被一起复核：
1. 远端 `origin/sp-macan-long-dev`（= `origin/macan-long-0919`）的 `vw_mlb.dbc` 是否把
   `CHECKSUM` 改名成了 `ACC_05_CHK` / `TSK_04_CHK`？
2. 若上游/他分支确实改名，我们跟不跟？

## 结论：我们这支**没有**改名，跟本分支一模一样

先纠正一个前提：本地**没有** `sp-macan-long-dev` 这个本地分支，只有远端
`origin/sp-macan-long-dev = 136b336c08`（与 `origin/macan-long-0919` 同一提交）。

| 分支 / ref | opendbc 子模块指针 | `vw_mlb.dbc` blob |
|---|---|---|
| `origin/sp-macan-long-dev` (136b336c08) | `341e046c2` | `5a512b562` |
| `macanlong-test`（本分支，2781bd33be） | `d42c6e455` | `5a512b562` ✅ 同一个 |
| `mouxan/master-c3` / `mouxan/tn-c3`（我们追随的 C3 线） | — | `5a512b562` ✅ 同一个 |
| `mouxan/master` | — | `4f7bb05a0` ❌ 改名版 |
| `mouxan/update-uv-lock` | — | `4f7bb05a0` ❌ 改名版 |

- `341e046c2` 只是 `d42c6e455` 往前 5 个提交（同一条 opendbc fork 线）；
  `git diff 341e046c2 HEAD -- opendbc/dbc/` = **空** → 两边 dbc 目录完全一致。
- 改名的 diff 只有 2 行，且**只出现在 `mouxan/master` 这条非 C3 线**：
  `BO_269 ACC_05` 的 `CHECKSUM→ACC_05_CHK`、`BO_270 TSK_04` 的 `CHECKSUM→TSK_04_CHK`。
- 我们代码里唯一的字面串 `"CHECKSUM"` 在 `ai/tools/sim_test_macan_sng.py:23`，
  那是 `LS_01/GRA` 的 mock，**不在这两条被改名的报文里**，不受影响。

### `mouxan/update-uv-lock` 是什么
是**上游 bot 的依赖锁分支**（tip `f269e3f43 "[bot] Update uv.lock"`，基于 `mouxan/master`
而非 C3 线）。它带改名版 DBC 只是因为**基座是 master 线**，与 uv.lock 本身无关。
结论：**不 merge / 不 rebase 它**，我们对 opendbc 子模块的现有站位不变
（导航控车不需要动 opendbc 子模块；本次也没有任何 DBC/车控代码改动）。

## 重要更正：这个改名**不能单独跟**（旧记忆里“改不改都无所谓”是错的）
链路是这样的：
- `opendbc/can/dbc.py::set_signal_type()` —— `sig.name == "CHECKSUM"` 是**唯一**
  把 `SignalType.VOLKSWAGEN_MLB_CHECKSUM` + `volkswagen_mlb_checksum` 挂到信号上的地方；
- `opendbc/can/packer.py::make_can_msg()` —— 打包时按 `sig.type > SignalType.COUNTER`
  自动回填校验字节；
- 我们 `mlbcan.py` —— `packer.make_can_msg("ACC_05", bus, acc_05_values)`，
  而 `acc_05_values` **不手填 CHECKSUM**，完全靠上面那条自动填充。

所以：**哪天把 `vw_mlb.dbc` 换成 master 那版却不改 `dbc.py`，OP 发出的 ACC_05/TSK_04
校验字节会恒为 0，原厂 ACC/网关 CRC 校验过不去** —— 正是最怕的“原厂不认 OP 帧”。
上游 commaai 线不主动 TX 这两条报文，所以对他们无害；对我们（Macan 纵向靠 OP 代发
ACC_05/TSK_04）是有害的。

## 处置（4 条）
1. 两支都不动：`sp-macan-long-dev` 保持与当前分支一致（都还是 `CHECKSUM`），无需修改。
2. opendbc 维持现状，继续不 merge/rebase `update-uv-lock`（旧结论仍成立）。
3. 将来若必须吸收含该改名的上游提交：**必须同一提交里**把 `can/dbc.py` 放宽为
   `sig.name == "CHECKSUM" or sig.name.endswith("_CHK")`，并跑 MLB 打包回归。
4. **本次落地**：把第 3 条的约束变成**被动红**的防回归断言（见下）。

## 本次改动：防回归断言（opendbc 子模块）
新增 `opendbc/car/volkswagen/tests/test_macan_mlb_checksum_wiring.py`（2 个用例）：
1. `test_checksum_signal_name_and_type`
   - `ACC_05(0x10D)` / `TSK_04(0x10E)` 里必须**仍存在**名为 `CHECKSUM` 的信号；
   - 该报文必须**恰好一个**信号被挂上校验类型（`type > SignalType.COUNTER`），
     且 `type == SignalType.VOLKSWAGEN_MLB_CHECKSUM`、`calc_checksum` 非空、占首字节；
   - 失败信息里直接给出修复指引（改成 `*_CHK` 就同一提交放宽 `set_signal_type`）。
2. `test_packer_autofills_checksum_bytes`
   - `CANPacker("vw_mlb")` 打包 ACC_05/TSK_04 必须产出**非 0**且与
     `volkswagen_mlb_checksum` 算得一致的校验字节（覆盖“名字对但 packer 不回填”的旁路）。

### 验证证据
- 本分支 DBC（未改名）：**2/2 通过**；`ruff check` **All checks passed**。
- 既有 `test_macan_mlb`（Macan 纵向仿真回归）：**36/36 OK**（未被影响）。
- **主动证明会红**：把两条 `SG_ CHECKSUM` 临时改成 `ACC_05_CHK`/`TSK_04_CHK` 后
  - 打包实测：`ACC_05`、`TSK_04` 校验字节均 `0x00`（`wired=[]`）→ 印证危害；
  - 跑该测试文件：**4 项失败**，且报错里带“必须同一提交放宽 dbc.py”的指引；
  - 验证后已 `git checkout --` 还原，`git rev-parse HEAD:opendbc/dbc/vw_mlb.dbc`
    = `5a512b562b7fe3c16a053b3b97c12e2cd690ce6d`（与改动前一致，DBC 文件零改动）。

## 推送状态
- **opendbc**（`origin` = `FOREVERZAX1988/opendbc`，`macanlong-test`）：
  `d42c6e455 → 469c8ceb7`（本次新测试提交，已 push 并设 upstream）。
- **openpilot**（本仓）：子模块 `opendbc_repo` gitlink 随之 bump
  `d42c6e455 → 469c8ceb7`，与本文档同一提交。

## 记录一个工具坑（避免再犯）
`/data/openpilot/opendbc` 是软链 → `opendbc_repo/opendbc`。在它下面用 pathspec
（`-- opendbc/dbc/...`）会被当成相对 cwd，**匹配不到而静默返回空**，容易误判
“两边相同”。比较文件一致性统一用：
`git -C /data/openpilot/opendbc_repo rev-parse <rev>:opendbc/<path>`（blob hash），
或 `git -C /data/openpilot/opendbc_repo diff <a> <b> -- opendbc/dbc/`。
