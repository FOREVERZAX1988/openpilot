# proclogd 进程身份与继承堆共享 — 2026-10-20

## 两个独立缺陷

1. **缓存以 PID 为键**（`_get_proc_extra`、`_get_smaps_cached`）。`_parse_proc_stat` 明明已经
   解析了 `starttime`，却没有用它做身份判据。后果：
   - 短命 helper 的 `exe` / `cmdline` 会驻留到 daemon 退出（无淘汰）；
   - PID 被复用且同名时，返回**上一个进程的 argv**；
   - smaps 缓存同理，复用 PID 会继承上一进程的 PSS/Anon/Shmem。

2. **`main()` 缺 `gc.freeze()`**。manager 先 import 再 fork，子进程继承的堆一旦被一次 GC
   遍历就会 copy-on-write 私有化（shared → private）。上游在两小时 1412 次采样的记录里抓到
   了这个转变；机制成立，但他们也明确说明"该时刻没有 GC 回调轨迹"，所以这是**支持性证据，
   不是直接归因**。

## 改动

- `ProcExtra` 增加 `starttime`；`_get_proc_extra(pid, name, starttime)` 与
  `_get_smaps_cached(pid, starttime)` 都以身份为键。
- 新增 `_prune_proc_cache(identities)`，每帧按 `{pid: starttime}` 淘汰退出的进程，并同步清理
  `_smaps_cache` / `_smaps_identity`。
- `main()` 在 `PubMaster` 创建之前 `gc.freeze()`。

## 验证

`openpilot/system/tests/test_proclog_identity.py`：8 例 —— 重复读取复用同一条目、同 PID 新
`starttime` 视为新进程、改名刷新、退出淘汰、PID 复用淘汰、smaps 缓存随身份失效、`main()`
中 `gc.freeze()` 必须先于 `PubMaster`（AST 顺序断言）。

本机 8 例全 skip（缺 cereal/opendbc）；车机（`comma tizi` `a821bfb2`，代码 `6c337d05`）8 例
全部执行并通过（`Ran 8 tests ... OK`）。同机 `openpilot/system/tests` 17 例：`test_big_log`
仍报错（`/data/log/swaglog.*` 在活设备上被轮转删除，与本次改动无关）；
`BootNetworkDependencyTest.setUpClass` 因无外网报 error；`InstallerTemplateTest` 3 例报模板与
已装脚本不一致（这台 tizi 的 `/data/launch*` 是本地自定义版，属既有偏差，非本轮引入）。
**未做**：长时（小时级）内存曲线对比，因此不声称改善了总内存占用——只修正身份
正确性与无界增长。
