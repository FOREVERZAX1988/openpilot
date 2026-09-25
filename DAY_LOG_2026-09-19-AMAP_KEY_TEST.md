## 2026-09-19 高德密钥自检按钮（commit b6b55f75d3，已推送 origin/macan-long-0919）

### 用户问题
1. 重启后「新的生效没」？
2. 加个测试按钮，方便确认 key 是否生效。

### 重启后核验（15:37 重启，15:47 核查）
- mapd 已是新代码路径：swaglog 出现 `mapd: using Amap online provider`（启动即按 key 选 Amap）。
  旧代码那种「1 秒内 ping-pong：switching→falling back for this session」在重启后未再出现
  → ba162db422（健康检查宽限 60s + 冷却 600s、运行中填 key 可热切）实际在跑。
- 参数：`AmapMapDataEnabled=True`、`AmapApiKey` 已设置（32 位 hex）。
- key 实测有效：`check_api_key()` → ok=True，
  `OK - road name (reverse geocoding): OK` / `OK - speed limit (driving route): OK`
  → 该 key 是「Web 服务」类，且已开通逆地理编码 + 路径规划。
- 时间自动校准仍在（未被合并覆盖）：`/etc/timezone=Asia/Shanghai`、`/data/etc/localtime` mtime=15:39（本次开机写入）、
  `date`=CST、`openpilot.system.timed` 在跑；AI 层（ai 子模块 infra/timezone.py）为唯一时区权威，
  carrot 手机 epochTime 同步仍为兜底（`CarrotNtpTimeSync=False`）。
- 内存（3.6Gi 总，无 swap）：used 1618MB / free 303MB / buff-cache 1777MB / **available 1989MB**。
  Top RSS：ai.aid 285MB、ui 231MB、webuid 94MB、mapd 64MB、models.manager 61MB、manager 51MB。

### 实施：设置页「测试高德API密钥」按钮
- 新增 `openpilot/sunnypilot/mapd/live_map_data/amap_map_data.py::check_api_key()`
  - 对 live provider **实际调用的两个接口**各发一次探针：`v3/geocode/regeo`（路名）、`v3/direction/driving`（限速）；
  - 固定 GCJ-02 探针点（天安门 → 附近路口 500m），不依赖 GPS / 是否在国内；
  - Amap 的 `info`/`infocode` 原样回传 + 常见码提示（10001 key 无效 / 10002 服务未开通 / 10009 平台不匹配 /
    10021 IP 白名单 / 10003 配额用尽 …）；网络失败与「无 key」分别单独区分；
  - 关键点：**必须两个接口都探**——Web 服务 key 可按服务单独限制，只测一个会把「部分可用」误判为可用。
- `navigation.py`（设置 → 导航）新增 TEST 按钮（在 Amap API Key 编辑行下方）：
  - 点击后 HTTP 在后台线程跑（不阻塞渲染，参照 osm.py 既有做法），按钮显示 `TESTING...`；
  - 结果经 `_update_state()` 在主线程用 `HtmlModalSP` 弹窗展示
    （避免在工作线程里构造 pyray 控件；osm.py 那种在 worker 里 push_widget 的写法有线程安全风险）；
  - 弹窗内容：标题「高德API密钥有效 / 存在问题」+ 每个服务一行 OK/FAIL + 原始 info(infocode)。
- 测试：`openpilot/sunnypilot/mapd/tests/test_amap_key_check.py` 9 例
  （无 key 不发请求 / 全通 / 部分服务被拒不能算通过 / 无效 key 提示 / 网络失败 / 异常不外抛 /
  两个 provider 端点都被探到且带 key / 设置页接线守卫）。mapd+translations 合计 **62 passed**，ruff 无新增告警。
- 翻译：手工补 zh-CHS/zh-CHT 各 7 条。
  **不要**用 `run_update_translations.py`：它会把 13 个 po 文件整体重排（每个 2818 行改动 /
  合计 1.8 万行噪声），无法评审——已回滚该路径。

### 生效条件
UI 是常驻进程，改 `navigation.py` 需**再次重启设备**（或重启 ui 进程）后按钮才出现。

### 备注
- 高德 key 类别：必须是**「Web 服务」**（restapi.amap.com），不是 Android/iOS/JS API 类；
  实测 REST 可用即证明类别正确（类别不匹配会返回 10009 USERKEY_PLAT_NOMATCH）。
- 地图领航本身不依赖高德 key：carrot 导航数据走手机 7706 UDP；key 只影响 mapd 的限速/路名（无 key 回退 OSM）。
