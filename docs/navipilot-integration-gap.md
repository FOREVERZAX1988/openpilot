# navipilot（CP 搭子）对接缺口

`navipilot`（`github.com/jixiexiaoge/navipilot`）是本车机配套的 Android App。它**不是**
CarrotNavi APK：端口布局与主通道都不同，排查前必须先分清，否则会得出错误结论。

本文记录 2026-09-27 实测 + 源码核对的结果。

## 1. 「7705 Active = 未激活 — CEM暂停」的成因（已确认，非故障）

App 侧指示器的取值（`ui/components/AutoSwitchExperimentPage.kt`）：

```kotlin
val isActive = carrotManFields?.value?.active ?: false
Text(if (isActive) "已激活 — CEM可工作" else "未激活 — CEM暂停")
```

`active` **只**来自设备 UDP 7705 广播的 JSON（`CarrotManDataModels.kt`：

> `// comma3 7705 接收状态（仅 active 被 app 读取）`

而设备侧这个字段就是 openpilot 的接管状态（`carrot_man.make_send_message`）：

```python
active = False
if self.sm.alive.get('selfdriveState', False):
  active = bool(self.sm['selfdriveState'].active)
msg['active'] = active
```

**激活条件 = 设备 7705 广播里 `active == true`，即车在行车上且 openpilot 已接管
（`selfdriveState.active`）。** 停车或未接管时为 `false`。

2026-09-27 实测（设备 192.168.2.246，停车）——信标本身完全正常，5 秒收到 8 个报文：

```json
{"Carrot2":"2026.003.000","IsOnroad":false,"CarrotRouteActive":false,
 "ip":"192.168.2.246","port":7706,"active":false,"xState":0,
 "v_ego_kph":0,"v_cruise_kph":0,"tbt_dist":0,"sdi_dist":0,
 "navi_http_port":7713,"nRoadLimitSpeed":0,"vTurnSpeed":55, ...}
```

字段齐全（sp 的信标是 CarrotPilot 的**超集**：cp 16 键 + `goalPosX/goalPosY/
szGoalName/nRoadLimitSpeed/vTurnSpeed`），所以「未激活」不是发现失败、不是缺字段、
也不是网络问题——**上路接管后会自动变成「已激活 — CEM可工作」**。

CEM 的前置条件同样印证（`ConditionalExperimentManager.kt`）：

```kotlin
if (!prefs.getBoolean("cem_enabled", false)) return false
// 前提：7705 active 必须为 true
if (carrotManFields == null || !carrotManFields.active) return false
```

## 2. 端口矩阵（sp 现状 vs navipilot 需求）

| 端口 | navipilot 用途 | sp 现状 |
|---|---|---|
| UDP 7705 | App 监听设备发现广播，读 `active` | ✅ 已实测在发（carrot_man + carrot_navi 双源） |
| UDP 7706 | 导航数据上行（GPS/限速/TBT/电子眼，5 Hz） | ✅ |
| TCP 7709 | 路线点 | ✅ |
| ZMQ 7710 | 控制命令（超车变道） | ✅ `carrot_man` `bind tcp://*:7710` |
| TCP 7711 | 车辆/模型数据（旧版接收器保留） | ✅ `xiaoge_data` |
| HTTP 7713 | sinf 交通灯上行 | ✅ `carrot_man._navi_http_port` |
| 7714 | v2 navi | ✅ |
| **WS 7000 `/ws/raw_multiplex?services=`** | 实时 cereal 数据（主要通道） | ❌ **缺** |
| **WS 7000 `/ws/camera/road`** | 摄像头 H.264 预览 | ❌ **缺** |
| **HTTP 7000 `/api/param_set`、`/api/params_bulk`** | 参数读写 | ❌ **缺** |
| **HTTP 8082 `/store_toggle_values`** | 下发设置 | ❌ 8082 是小鸽 V-ASM 页面，无此端点 |

**这就是 App 弹「❌ 切换失败: 设备未连接」的原因**：CEM 切换走的是
`paramClient.setParam("ExperimentalMode", …)` → HTTP 7000（`CarrotParamClient.kt`
`private const val PORT = 7000`），而本仓库没有任何 7000 服务。

## 3. 待补的 7000 层（来自 CarrotPilot 的对应模块）

navipilot 实际只用 4 个端点，对应 cp 的路由表（`server/features/ws.py`）：

```
/ws/compact_state      (可选，App 未使用)
/ws/raw_multiplex      <- App 主通道
/ws/raw/{service}
/ws/camera/{camera}    <- App 用 road
```

| cp 模块 | 行数 | 作用 |
|---|---|---|
| `realtime/raw_protocol.py` | 37 | 多路复用帧格式（`encode_raw_multiplex_frame` / `build_raw_multiplex_hello`） |
| `realtime/raw_services.py` | 45 | 可用服务清单 |
| `realtime/transports/raw_ws.py` | 325 | `RawWsHub` |
| `realtime/transports/camera_ws.py` | 471 | `CameraWsHub` |
| `server/features/ws.py` | 99 | 4 条 ws 路由 |
| `server/features/params.py` | 310 | `/api/param_set`、`/api/params_bulk` |
| （可选）`realtime/compact_state.py` | 652 | 紧凑状态 + C++/Cython 原生部分 |

**合计约 1,290 行**（不含 compact_state）。注意这**远小于** cp 的 `server/`(30k) +
`web/`(148k)——那些是它自己的网页管理台，navipilot 并不需要。也就是说给 navipilot
补一个**最小 7000 服务**是可行且有边界的，不必整套搬。

另需在 8082 上补一个 `POST /store_toggle_values`（sp 的 `v_asm_server` 目前只有
`/`、`/api/status`、`/api/config`、`/api/snapshot`、`POST /api/config`、`POST /api/settings`）。

## 4. 结论

- **7705「未激活」= 没接管，不是故障**，无需修设备端。
- App 真正缺的是 **7000 端口的实时数据 + 参数 API**，以及 8082 的
  `/store_toggle_values`。
- ZMQ 7710、7706、7709、7711、7713、7714 都已具备。


## 5. 2026-10-11 复核：第 2 节表格里「缺」的四个端点，现在都齐了

上游（mouxan）把 CarrotPilot 的 7000 服务整体移植进本 fork 后，navipilot 需要的东西全部就位：

| 端点 | 2026-09-27 状态 | 2026-10-11 状态 |
|---|---|---|
| WS 7000 `/ws/raw_multiplex?services=` | ❌ 缺 | ✅ `carrot/server/features/ws.py`（另有 `/ws/raw/{service}`、`/ws/compact_state`）|
| WS 7000 `/ws/camera/road` | ❌ 缺 | ✅ `carrot/server/features/camera.py`（`/ws/camera/{camera}`；`road` → 本 fork 的 `narrowRoad` 做映射，hello/metadata 仍回客户端要的名字）|
| HTTP 7000 `/api/params_bulk`、`/api/param_set` | ❌ 缺 | ✅ `carrot/server/features/params.py` + `params_extra.py` |
| HTTP 8082 `/store_toggle_values` | ❌ 缺 | ⏳ 未复核（8082 仍是小鸽 V-ASM 页面）|

结论：App 侧「设备未连接 / 切换失败」（CEM 走 `CarrotParamClient` → 7000）的根因**已消除**。
App 端判据没变：`7705.active` 仍是「行车上 + `selfdriveState.active`」，停车显示「未激活」是正常。

### 5.1 App 摄像头预览（`/ws/camera/road`）什么时候才有画面

`carrot/server/services/camera_relay.py` 是**纯中继**：只订阅本 fork 已有的 cereal 编码流
（`livestreamNarrowRoadEncodeData` / `narrowRoadEncodeData`），**自己不起编码器**——"the manager owns that"。

- 行车中：segment 编码器在跑 → 有帧；
- 停车：只有 `IsLiveStreaming` 为真时 manager 才起 `stream_encoderd` → 否则 `/api/camera/status` 只报
  `{"cameras":{},"idle":true}`（最后一帧的年龄/原因），App 侧表现就是**点开摄像头没画面**。这是数据源没发布，不是 bug。

## 6. 我们 fork 的「不生成 APK」是怎么来的（已定位）

事实（GitHub API 实测，`FOREVERZAX1988/navipilot`）：

```
GET /actions/workflows -> total_count 0        # 一个 workflow 都没注册
GET /actions/runs      -> total_count 0        # 从没跑过
GET /actions/secrets   -> total_count 0        # 4 个签名 secret 一个都没有
tags: r260725 / r260726 / r260901；releases: 空
repo: fork=true, default_branch=master, archived=false, actions permissions enabled=true/all
对照：FOREVERZAX1988/jetlink 同 token 查 → 4 个 workflow、11 条 run（说明查法/权限没问题）
```

- 我们的 `Amapauto` **有** CI：`.github/workflows/release.yml`（`assembleRelease` 多 ABI + `bundleRelease` + zip + `gh release create`），
  且 `master`（默认分支）上也有这个文件；但它的触发器只有 **`r*` tag push** 或 **`workflow_dispatch`**，
  **普通分支 push 什么都不做**。
- 所以「分支上推了代码却没 APK」是**设计如此**：要出包必须打 tag 或手动 dispatch。
- 而现在连 tag 触发也没产物，卡在两处前置：
  1. GitHub 侧 Actions 在这个 fork 上**从未注册**（`GET /actions/workflows` → `total_count 0`，dispatch → 404）——
     需要在仓库 Actions 页点一次「I understand my workflows, go ahead and enable them」再打 tag。
     **2026-10-11 实测：不必点网页 —— 向默认分支推一次 workflow 文件改动即完成注册**（见 §6.1）。
  2. **4 个 secret 全缺**：`RELEASE_KEYSTORE_BASE64` / `RELEASE_STORE_PASSWORD` / `RELEASE_KEY_PASSWORD` / `RELEASE_KEY_ALIAS`。
     第一步 `echo "$RELEASE_KEYSTORE_BASE64" | base64 -d > app/release.keystore` 只会写出空文件 → release 签名必失败。
     （上游 `Amapauto` 仓库里带 `app/release.keystore`，我们 fork 去掉了；上游的密码只在 Windows 的
     `deploy_release.bat`/`generate_keystore.bat` 流程里，仓库没有。）
- **要出包的正确顺序**：① 在 fork 上启用 Actions；② 用 `keytool`（或 `generate_keystore.bat`）生成一把自己的 keystore，
  把 base64 + 三个密码写进 4 个 secret；③ 打 tag `r<新 versionCode>`（当前 `versionCode = 260724`，最新 tag 是 `r260901`，
  要 ≥ 260902）或手动 dispatch。
- ⚠️ 换 keystore = 换签名：旧 APK 无法覆盖安装，`AppUpdater` 的 OTA 也会因签名不符失败，需要卸载重装。
  想保留旧签名就必须找到原来那把 keystore 和密码。
- 轻量替代：`assembleDebug` 用内置 debug key，不需要任何 secret，装得上但不是 release 签名（不能作为 OTA 基线）。


### 6.1 2026-10-11 实操：出包链路已打通（A 方案：自建 release 签名 + 云端出包）

**两个真根因（都不是「分支不生成 APK」的设计行为，是 bug）**

| # | 症状 | 根因 | 处置 |
|---|---|---|---|
| 1 | Actions 列表 `total_count 0`、`workflow_dispatch` → 404 | workflow 文件只存在于**非默认分支** `Amapauto`；默认分支 `master` 上那份虽然存在但从未被 push 触发注册 | 把 workflow 改动 push 到 `master`（默认分支）→ 立刻 `total_count 1 / state active`，dispatch → **204** |
| 2 | 任务起跑后 `./gradlew assembleRelease` 立即失败 | 仓库内 `gradle/gradle-daemon-jvm.properties`（`gradle updateDaemonJvm` 生成物）把 daemon JVM 钉在 **Java 18(EOL)**，而 CI 用 JDK 17 → `Cannot find a Java installation … Compatible with Java 18` | **删除该文件**（Gradle 改用启动 JVM：本地 `JAVA_HOME`、CI `setup-java` 均可） |
| 3 | （潜伏）tag 触发时版本号解析 | `VERSION_CODE = github.ref_name`（形如 `r260902`）→ `toInt()` 抛异常 | workflow 增加 `Resolve version`：剥离前导 `r` + 纯数字校验，`version_name` 缺省回退 `v<code>` |
| 4 | （潜伏）secret 缺失时失败原因不可读 | `echo "${{ secrets.X }}" \| base64 -d > app/release.keystore` 会写出**空文件**，后续报「签名失败」 | 改为：secret 为空则保留仓库内 keystore，最终 `test -s` 显式报错 |
| 5 | `:app:packageRelease` 失败：`Failed to read key  from store … Keystore was tampered with, or password was incorrect`（**key 名位置是空的**）| 签名参数当**普通 env** 传（`RELEASE_STORE_PASSWORD`…），而 `build.gradle.kts` 用 `project.findProperty()` 读 —— Gradle 只把 `-P` / `gradle.properties` / `ORG_GRADLE_PROJECT_*` 当 project property，普通 env **读不到** → 三个值全空 | workflow 改用 `ORG_GRADLE_PROJECT_RELEASE_*`（已加注释说明）|
| 6 | CI 早段失败：`Could not resolve … Received status code 502 from server: Bad Gateway`（maven.aliyun.com）| `settings.gradle.kts` 把阿里云镜像排在最前；GitHub runner 上镜像 502 会让 Gradle **禁用该 repo** 直接失败 | `settings.gradle.kts`：CI（`System.getenv("CI")`）下不注册 aliyun 镜像，直连 `google()/mavenCentral()`；**本机行为不变** |

**签名（自己出一把，密码自持）**

| 项 | 值 |
|---|---|
| 文件 | `release.keystore`（**JKS**，RSA 2048，`CN=sp-dazi`，alias `spdazi`），2208 B |
| 设备侧备份 | `/data/ainav/keys/`（`release.keystore` / `store.password`(600) / `release.keystore.b64` / `key.pem` / `cert.pem`）——**请拷到 PC 另行保存** |
| cert SHA-256 | `c67158605571ed61ea0a868d103e6592f2dcda46f3120619df6d00a1367d8bac` |
| repo secrets | `RELEASE_KEYSTORE_BASE64` / `RELEASE_STORE_PASSWORD` / `RELEASE_KEY_PASSWORD` / `RELEASE_KEY_ALIAS`（4 个，已写入 `FOREVERZAX1988/navipilot`）|

- **keystore 自检**：workflow 在 decode 之后先 `keytool -importkeystore` 回写一遍 ——
  ① 验证 store/key 密码 + alias 对 Java 可读（失败从 6 分钟缩到**秒级**）；
  ② 顺带把免 keytool 生成的 JKS 规范成 Java 原生 JKS。
- 生成手法（设备无 JDK，全程免 keytool）：`openssl req -x509` → `openssl pkcs12` → `pyjks` 重建为 **JKS**（`PrivateKeyEntry.new(alias, [certDER], pkcs8DER)`），
  因为 AGP 的 `signingConfigs` 未写 `storeType` → 走 `jks` 默认，PKCS12 文件会被判「Invalid keystore format」。
- ⚠️ **换 keystore = 换签名**：旧 APK 无法覆盖安装，`AppUpdater` 的 OTA 从本包起才有基线，需要卸载重装一次。
  想保留旧签名 → 必须找回上游 `Amapauto:app/release.keystore`（JKS，2774 B，仓库里有）的密码；
  **密码不在仓库里**（`deploy_release.bat` 只有构建流程、`gradle.properties` 无 `RELEASE_*`，全历史 `git log -S` 也无），只在原作者本机。

**出包方式**（第三次复现：不需要网页操作、不需要本地 Android SDK）

```bash
# 触发（version_code 必须 > 现网最新 tag r260901）
POST /repos/FOREVERZAX1988/navipilot/actions/workflows/release.yml/dispatches
  {"ref":"Amapauto","inputs":{"version_code":"260902","version_name":"v260902","notes":"..."}}
# 或：push tag r260902（workflow 的 `on.push.tags: r*` 已修好版本号解析）
```

产物：Release `r260902` = `sunnypilot-dazi-r260902.zip` + 多 ABI APK（arm64-v8a / armeabi-v7a / x86_64）+ AAB。

**结果（2026-10-11 19:55，run `38133390647` → SUCCESS）**：Release **`r260902`**
<https://github.com/FOREVERZAX1988/navipilot/releases/tag/r260902>

| 产物 | 大小 |
|---|---|
| `sunnypilot-dazi-r260902.zip`（APK+AAB 全打包）| 172.54 MB |
| `app-arm64-v8a-release.apk` | 67.02 MB |
| `app-armeabi-v7a-release.apk` | 54.91 MB |
| `app-x86_64-release.apk` | 72.44 MB |
| `app-release.aab` | 91.97 MB |

从「分支推了代码也不出包」到真出包，共 **6 个真原因**（上表 1–6），**全部是仓库/CI 配置问题，与 App 代码无关**。

**待办**：真机装一次新签名包，确认 OTA（`AppUpdater` → GitHub Release 镜像轮询）能认出 `r260902`；旧包需先卸载。

## 7. 上游（原作者）那两条侧分支能不能借鉴

| 分支 | 内容 | 判断 |
|---|---|---|
| `claude/fix-led-related-bug`（`d732274` 灯带）| 建在**旧代码线**上（包名 `com.example.navipilot`，README 写 v260516）：高德/腾讯/Google 导航桥、`CameraOverlay`、`SshConnectionManager`、`XiaogeDataReceiver`、腾讯 NTRIP/RTK SDK（`TencentNtripSDK`）、`AppAnalytics`、车道图标/转向推断、`PreferenceRepository`/DI 全套 | 与现线（`com.jixiexiaoge.drivingassist`，已「移除导航/评分/投射模块」）差异 601 文件，**不能 merge，只能当零件库**：将来要恢复导航投射、摄像头叠加、RTK 时按文件挑；「灯带」本身只是 1 个 commit |
| `copilot/research-android-desktop-app`（`f848eb9` AI 改 UI）| 同一条旧线 + `new.png` + UI 试验 | 同上，研究性质 |
| 上游 `Amapauto` | 我们的 fork **已领先 8 条**（默认投屏+自动发现、可隐藏侧边栏、S 启动页/图标、GitHub Release OTA 镜像轮询、命名统一 sp搭子、多 ABI/AAB + CI/CD、`AppUpdater`、`ScreenMirrorActivity`、`QuickButtons`）| 上游 Amapauto 没有新东西可拉（`compare` = ahead 8 / behind 0），反过来是**我们该往上提** |
