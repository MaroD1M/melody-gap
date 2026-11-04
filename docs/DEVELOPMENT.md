# MelodyGap 开发与维护手册

> 版本：2.0.0
> 状态基线：2026-11-04
> 适用范围：`melody-gap/rust/`
> 目标读者：后续维护者、二次开发者、代码审查者、发布负责人

v2.0.0 起，桌面端由 Python/Tkinter 迁移到 Rust + Tauri 2 + Svelte 5。根目录的
`app/`、`main.py` 与 `tests/` 是 v1.x 行为参考，不再参与 Release 构建；本文只
描述当前 Rust 桌面端。

## 1. 目录结构

```text
rust/
├── Cargo.toml                     # workspace + release profile
├── package.json                   # 前端脚本与依赖
├── crates/melodygap-core/         # 纯 Rust 业务库
│   ├── src/constants.rs           # 播放器、匹配、SMTC 映射、导出表头
│   ├── src/models.rs              # SongInfo / PlayRecord / MissingSong
│   ├── src/title_parser.rs        # 窗口标题清洗、解析、择优
│   ├── src/matcher.rs             # 标准化 + 相似度 + 加权匹配
│   ├── src/subsonic.rs            # Subsonic client / token 认证 / 搜索
│   ├── src/monitor.rs             # 轮询、去重、缓存、未知重试、核验
│   ├── src/config.rs              # config.ini 读写与损坏备份
│   ├── src/missing_repository.rs  # missing_songs.json 原子持久化
│   ├── src/reminder.rs            # 提醒模式与冷却判断
│   └── tests/                     # 核心、监控、Subsonic 行为测试
├── src-tauri/
│   ├── src/lib.rs                 # Tauri 构建、窗口恢复、退出
│   ├── src/commands.rs            # 18 个 invoke 命令与记录回调
│   ├── src/state.rs               # AppState / Snapshot 序列化
│   ├── src/events.rs              # state-changed 广播
│   ├── src/notifications.rs       # 通知窗、队列、6 秒计时
│   ├── src/tray.rs                # 托盘菜单与监控开关
│   ├── src/paths.rs               # EXE 同目录数据路径
│   ├── src/logging.rs             # 1 MB × 3 滚动日志
│   ├── src/platform/smtc.rs       # Windows SMTC 后台线程
│   ├── src/platform/window.rs     # Win32 窗口枚举 + 进程名反查
│   ├── src/platform/hybrid.rs     # SMTC 优先、窗口补齐
│   ├── tauri.conf.json            # 窗口、图标、便携数据目录
│   └── capabilities/default.json  # 主窗口/通知窗权限
├── src/
│   ├── App.svelte                 # 主窗口 / 通知窗路由
│   ├── app.css                    # 主题、表格、通知、响应式
│   ├── lib/MainApp.svelte         # 主界面
│   ├── lib/SettingsDialog.svelte  # 设置弹窗
│   ├── lib/NotificationWindow.svelte
│   └── lib/{api,types,utils}.ts
└── dist/                          # pnpm build 产物，构建时嵌入 EXE
```

## 2. 架构与线程模型

```text
Tauri 事件循环（主线程）
├── 主窗口 WebView（MainApp.svelte，每秒 get_snapshot）
├── 通知窗 WebView（NotificationWindow.svelte，监听 notification）
├── 托盘菜单
└── 命令处理（get_snapshot / save_settings / recheck_* / export_* ...）

后台线程
├── MusicMonitor        每 2 秒读取混合检测器、查询曲库、写记录
├── SmtcDetector        每 2 秒刷新 Windows 媒体会话快照
├── NotificationTimer   每条通知 6 秒后调用 dismiss_if
└── spawn_blocking      recheck_missing / recheck_current / test_connection
```

线程规则：

- 共享状态只通过 `Arc<Mutex<...>>` / `AtomicBool` / `Arc<MusicMonitor>` 访问；
- 检测器返回不可变 `PlaybackCandidate`，SMTC 的 WinRT 对象不跨线程；
- Tauri `AppHandle` 可在后台线程安全地 `emit`；
- 任何可能阻塞的网络请求放入 `spawn_blocking`；
- 应用退出时 `RunEvent::Exit` 保存窗口状态并停止监控。

## 3. 播放检测

### 3.1 支持播放器

| key | 进程名（小写比较） | SMTC AppId 片段 | 显示名 |
|-----|-------------------|-----------------|--------|
| `qq` | `qqmusic.exe` | `qqmusic` / `tencent.qqmusic` / `tencent.qqmusicpc` | QQ音乐 |
| `netease` | `cloudmusic.exe` / `neteasecloudmusic.exe` / `neteasemusic.exe` | `cloudmusic` / `neteasecloudmusic` / `netease.cloudmusic` | 网易云音乐 |

定义在 `crates/melodygap-core/src/constants.rs`。新增播放器时同步补充进程名、
AppId 片段、显示名、排除关键词与测试。

### 3.2 SMTC 优先

`platform/smtc.rs`：

1. 在独立线程初始化 `GlobalSystemMediaTransportControlsSessionManager`；
2. 每 2 秒枚举会话，按 AppId 映射到播放器；
3. 读取 `Title` / `Artist` / `PlaybackStatus`；
4. 同一播放器多个会话时优先 `playing`，其次 `paused`、`stopped`、未知；
5. 发布不可变快照；读取失败清空快照并记录 `last_error`。

`SmtcState` 向 UI 暴露 `smtc_available` 与 `smtc_error`。非 Windows 平台返回空快照。

### 3.3 窗口标题回退

`platform/window.rs` 不扫描全部进程，而是：

1. `EnumWindows` 枚举有标题的窗口；
2. `GetWindowThreadProcessId`；仅对候选窗口反查进程名；
3. 进程名映射到 `qq` / `netease`；
4. 用 `is_valid_song_title` 过滤功能页；
5. 可见窗口优先，隐藏窗口兜底；
6. 对同一播放器的多个标题调用 `select_best_title` 择优。

进程名缓存 TTL 为 10 秒，降低重复 `OpenProcess` 开销。

`platform/hybrid.rs` 的合并规则：每个播放器最多一个候选；SMTC 有结果时忽略该
播放器的窗口标题；SMTC 未覆盖的播放器才走窗口回退；最终顺序固定为
`SUPPORTED_PLAYERS`。

### 3.4 标题解析

`title_parser.rs`：

- 剥离末尾播放器名，如 ` - 网易云音乐`；
- 支持 ` - `、` — `、` – `、` | ` 四种分隔符；
- 排除整段等于功能页关键词的标题（设置、搜索、歌单等）；
- 前半为歌名、后半为歌手；
- `select_best_title` 偏好包含分隔符、非括号、非纯功能页的候选。

## 4. 监控与三态查询

`monitor.rs` 每 2 秒轮询一次：

```text
detect candidates
  → 按播放器解析
  → 与上次 key 比较，去重
  → Subsonic 查询（结果缓存）
  → 写 current_songs / current_records / history
  → 触发 on_record 回调
```

规则：

- 三态：`Some(true)` 在库、`Some(false)` 不在库、`None` 未知；
- 未知不进入待补清单，不触发提醒；
- 同一播放器同一首歌不重复记录；
- SMTC 与窗口来源切换但歌名相同，不新增历史；
- 短暂漏检 10 秒内恢复原记录，超过 10 秒后重新播放会新增记录；
- 未知状态每 15 秒最多自动重试 5 次，成功或失败都会更新当前记录；
- 查询结果按 `(artist, title)` 缓存；修改服务器配置后清空；
- `recheck_song` 绕过缓存；`update_current_result` 只更新仍匹配的当前记录；
- `recheck_missing` 的单曲结果会弹通知，多曲/全部核验只返回汇总。

`RecordCallback` 由 `commands::install_record_callback` 安装，负责待补清单、
提醒判断与 `state-changed` 广播。

## 5. 匹配算法

### 5.1 标准化

按顺序执行：

1. NFKC 归一化；
2. 转小写；
3. 标点替换为空格；
4. 删除英文修饰词（remix / remaster / acoustic / live / demo / instrumental / cover / feat / ft / featuring）；
5. 删除中文修饰词（重制版 / 混音版 / 伴奏 / 现场版）；
6. 压缩空白。

### 5.2 相似度与评分

```text
sim = difflib 兼容的 SequenceMatcher.ratio()
若 min(len(a), len(b)) >= 4 且短串是长串子串：
    sim = max(sim, 0.8)
score = artist_similarity * 0.4 + title_similarity * 0.6
命中：score >= 0.75
```

权重与阈值在 `constants.rs`。修改后必须补充边界测试，尤其是：
空串、全半角、`Olive`/`Deliver` 不被 `live` 规则误伤、版本后缀、中文修饰词。

## 6. Subsonic

`subsonic.rs`：

- 服务器地址规范化，兼容 `http://` / `https://` 与末尾 `/rest`；
- token 认证（`t` + `s`），密码不写进 URL；
- `search3` 优先，旧服务器回退 `search2`；
- 按 song id 去重；
- 兼容单条 `dict` 与列表响应；
- 精确匹配先返回，否则使用 `SongMatcher`；
- 错误统一映射为可展示的中文 `SubsonicError`。

本地测试用假 HTTP 服务器，不依赖真实服务器或网络。

## 7. 配置、待补仓库与提醒

### 7.1 config.ini

`ConfigManager`：

- 使用 `configparser` 兼容格式，禁用插值，密码可含 `%`；
- 读取 UTF-8 BOM；
- 损坏时备份为 `config.corrupt_<时间>.ini`，再重建默认配置；
- 写入使用同目录 `.tmp` + rename；
- 默认服务器为占位地址，`is_subsonic_configured()` 会排除占位内容；
- `window_geometry` 格式 `宽x高+x+y`，支持负坐标。

### 7.2 missing_songs.json

`MissingRepository`：

- 去重键为标准化后的 `artist|title`；
- 记录首次/最后发现时间、播放次数、播放器、状态；
- 只统计“播放”，核验动作不增加次数；
- 原子写回；损坏文件备份后从空清单恢复；
- 兼容 v1 数组格式并补全 key；
- 批量 `set_status_many` / `remove_many` 一次落盘。

### 7.3 提醒

`should_notify` 支持：

- `new_missing`：仅新缺失；
- `missing`：所有不在库歌曲（受冷却）；
- `all`：在库/不在库都提醒（受冷却）；
- `off`：关闭；
- 未知状态永不提醒；
- 非法模式回退 `new_missing`；
- 冷却范围 0～1440 分钟。

## 8. Tauri 后端

### 8.1 命令

注册在 `src-tauri/src/lib.rs`：

```text
get_snapshot
start_monitoring / stop_monitoring
save_last_tab
save_settings / test_connection
recheck_current / recheck_missing
set_missing_status / set_missing_status_many
delete_missing / delete_missing_many
clear_history
get_current_notification / dismiss_notification
export_missing / export_history
```

`recheck_missing` 参数：`keys?: string[]` 与 `quiet?: boolean`。`keys` 为空时只
处理 pending；`quiet=false` 时逐条弹通知（前端仅在单曲核验时使用）。

### 8.2 事件

| 事件 | 方向 | 载荷 |
|------|------|------|
| `state-changed` | 后端 → 主窗口 | 完整 `Snapshot` |
| `navigate` | 托盘 → 主窗口 | `missing` / `history` |
| `notification` | 后端 → 通知窗 | `NotificationItem` |
| `notification-fallback` | 后端 → 主窗口 | 通知窗不可用时的 toast 数据 |

主窗口同时每秒调用 `get_snapshot`，避免停止播放或查询失败时界面停留旧状态。

### 8.3 通知窗

`NotificationManager`：

- 启动时创建隐藏的 `notification` WebView；
- 队列最多 5 条，相同内容去重；
- 每条通知 6 秒后由后台线程 `dismiss_if(id)` 关闭；
- 前端计时器关闭时携带当前 id，避免误关下一条；
- 通知窗加载晚于首条事件时，通过 `get_current_notification` 恢复；
- 窗口位置固定右下角，按主显示器缩放计算物理坐标；
- 通知窗透明背景由 `App.svelte` 添加 `notification-mode` 类实现。

### 8.4 托盘与单实例

- 托盘菜单：显示主界面、待补清单、开始/停止监控、退出；
- 左键单击托盘直接显示主窗口；
- 待补数量文本随 `state-changed` 刷新；
- 关闭主窗口时：托盘存在则隐藏，否则退出；
- 单实例由 `tauri-plugin-single-instance` 提供，第二次启动只唤起主窗口。

### 8.5 便携数据目录

`paths.rs` 以 `current_exe` 所在目录为根：

```text
config.ini
missing_songs.json
melodygap.log / melodygap.log.1..3
webview2-data/
```

`tauri.conf.json` 的 `appDirectoriesOverride.localData` 指向 `./webview2-data`，
同时设置 `WEBVIEW2_USER_DATA_FOLDER` 作为兜底，避免 WebView2 写入用户目录。

`--smoke-test` 在创建 Tauri 应用前检查便携数据目录可创建，便于 CI 发现打包/权限问题。

## 9. 前端

### 9.1 状态

`MainApp.svelte` 使用 Svelte 5 runes：

- `snapshot`：后端完整快照；
- `activeTab`：`missing` / `history`；
- `selectedMissingKeys`：多选集合；`missingAnchorKey` 支持 Shift 范围选择；
- `selectedHistoryKey`：播放记录单选；
- `missingSearch` / `missingStatus` / `historySearch` / `historyStatus`；
- `missingSort`：默认按首次发现倒序；
- `contextMenu` / `toasts` / `busy` / `settingsOpen`。

### 9.2 交互

- 主窗口 `onMount` 启动 1 秒 `get_snapshot` 轮询，同时监听 `state-changed`；
- 统计卡可点击：总记录/在库/待补/QQ/网易云；
- 待补表支持 `Ctrl` / `Meta` 切换选择、`Shift` 范围选择、`Ctrl+A` 全选、
  `Ctrl+C` 复制；输入框/下拉框聚焦时不拦截快捷键；
- 右键未选中行会先选中该行；多选时复制、核验、忽略/恢复、删除按选中数量显示；
- 双击行复制歌曲信息；
- 设置弹窗在首次打开时读取快照，避免轮询覆盖正在编辑的表单；
- 通知窗点击复制 `copy_text`，无文本时只关闭。

### 9.3 样式

`src/app.css` 定义主题变量、按钮、输入、表格、统计卡、菜单、弹窗、通知与响应式
断点。通知窗使用 `html.notification-mode` 将背景设为透明。

## 10. 测试

```bash
cd rust
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
pnpm check
pnpm build
```

当前 122 项 Rust 测试：

| 文件 | 数量 | 覆盖 |
|------|------|------|
| `crates/melodygap-core/tests/core_parity.rs` | 76 | 标题解析、匹配、模型、提醒、配置、待补仓库、SMTC 映射 |
| `crates/melodygap-core/tests/monitor_parity.rs` | 31 | 去重、切歌、三态、缓存、双播放器、未知重试、核验、启停 |
| `crates/melodygap-core/tests/subsonic_parity.rs` | 12 | token、search3/search2、去重、错误映射 |
| `src-tauri` 单元测试 | 3 | 窗口几何、URL 校验、CSV BOM/CRLF |

测试全部离线，不依赖真实播放器、真实 Subsonic 服务器或网络。

## 11. 构建与发布

### 11.1 本地

```powershell
cd rust
pnpm install --frozen-lockfile
pnpm check
pnpm build
cargo test --workspace
cargo build --release --target x86_64-pc-windows-msvc -p melodygap
```

MSVC 构建静态链接 WebView2 Loader；GNU target 需要把
`target/<target>/release/WebView2Loader.dll` 一起分发。

便携目录至少包含 `MelodyGap.exe`、`config.ini.example`、`LICENSE`。GitHub
Release 工作流会自动压缩并生成 `SHA256SUMS.txt`。

### 11.2 CI

`.github/workflows/ci.yml`：

1. Windows + pnpm 12 + Node 24 + Rust stable；
2. `pnpm install --frozen-lockfile`；
3. `pnpm check` / `pnpm build`；
4. `cargo fmt --check` / `cargo clippy -D warnings` / `cargo test`；
5. `cargo build --release`；
6. 打包目录版、生成 SHA256、执行 `--smoke-test`、上传 artifact。

`.github/workflows/release.yml` 在 `v*` 标签时重复检查并创建 GitHub Release。

## 12. 手动验收清单（Windows）

1. 启动程序，托盘出现，主窗口显示；
2. 未配置服务器时播放歌曲 → 记录“未知”，不进入待补清单；
3. 设置中“测试连接”成功，保存后播放歌曲，通知颜色与统计正确；
4. 不在库歌曲进入待补清单，重启后仍存在；
5. 待补清单搜索/筛选/多选/复制/导出/忽略/恢复/删除正常；
6. 补歌后核验选中/核验待补，已入库项移出并显示汇总；
7. 播放记录筛选、搜索、导出、清空正常；
8. 最小化 → 托盘恢复；托盘“待补清单”跳转正确；
9. 托盘停止/开始监控，状态与菜单文案同步；
10. 关闭主窗口隐藏到托盘；托盘退出后进程结束、日志收尾；
11. 重复启动 EXE 只唤起已运行窗口；
12. 临时断开服务器 → 当前歌曲“未知”，恢复后自动重试且不重复记录；
13. 双播放器同时播放 → 两行并列、互不覆盖，通知逐条展示；
14. 关闭主窗口/悬浮歌词 → SMTC 继续识别；无 SMTC 时验证隐藏窗口回退；
15. 导出 CSV → Excel 打开无乱码、含逗号歌名完整；
16. 设置留空服务器地址/非法冷却 → 表单内联提示，不保存。

## 13. 扩展指南

### 13.1 新增播放器

在 `SUPPORTED_PLAYERS` 增加进程名、SMTC AppId 片段、显示名与短名；补充
`PLAYER_EXCLUDED_KEYWORDS`；若标题顺序不是“歌名 - 歌手”，在 `parse_title`
增加分支；补充标题解析、SMTC 映射与窗口检测测试。

### 13.2 调整匹配灵敏度

修改 `MATCH_THRESHOLD` / `ARTIST_WEIGHT` / `TITLE_WEIGHT`，运行全部测试，并用
真实曲库样本做误报/漏报回归。

### 13.3 新增命令

1. 在 `commands.rs` 定义 `#[tauri::command]`；
2. 在 `lib.rs` 的 `generate_handler!` 注册；
3. 在 `src/lib/api.ts` 与 `types.ts` 增加类型和封装；
4. 需要刷新界面时调用 `events::broadcast`；
5. 补充 Rust 测试与手动验收项。

### 13.4 新增前端页面

保持 `Snapshot` 为唯一后端数据源；通过 `get_snapshot` + `state-changed` 同步；
避免在组件内保存从后端派生的长期状态。

## 14. 已知限制与技术债

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| 1 | 仅 Windows | 无法跨平台检测 | 抽象检测器，macOS 用 Now Playing |
| 2 | SMTC 覆盖依赖播放器版本 | 旧版只能回退标题 | 按版本维护 AppId 与验收矩阵 |
| 3 | 播放历史仅内存 | 重启丢失 | JSON/SQLite 持久化 |
| 4 | 网络查询在监控线程同步执行 | 慢服务器会拖慢轮询 | 查询线程池/队列 |
| 5 | 密码明文 | 本地泄露风险 | DPAPI / Credential Manager |
| 6 | 未签名 | SmartScreen/杀软误报 | SignPath 或商业证书 |
| 7 | 窗口标题解析可能反向 | 误判 | 按播放器版本增加分支与样本 |
| 8 | 历史与通知内存无上限 | 长时间运行增长 | 历史上限/分页，通知计数清理 |
| 9 | UI 自动化测试缺失 | 重构风险 | Playwright + Tauri 驱动 |
| 10 | 无国际化 | 仅中文 | 文案表与语言选择 |
