# MelodyGap 开发与维护手册

> 版本：1.0.0
> 适用范围：`melody-gap/` 全部源码
> 目标读者：后续维护者、二次开发者、代码审查者
> 最后更新：2026-10-20

本文档是项目的**唯一技术基准**。修改代码前请先阅读「线程模型」「数据流」
「扩展指南」三节；新增功能后请同步更新本文档与「变更记录」。

---

## 1. 项目定位

### 1.1 要解决的问题

用户同时使用 QQ 音乐 / 网易云音乐在线听歌，但本地另有一台 Subsonic /
Navidrome 音乐服务器。程序需要在不侵入播放器的前提下，自动判断“当前播放的
这首歌是否已经在自己的曲库里”，并记录播放历史。

### 1.2 设计目标

| 目标 | 说明 |
|------|------|
| 无侵入 | 只读取进程名和窗口标题，不注入、不抓包、不修改播放器 |
| 低资源 | 进程扫描 5 秒缓存；窗口枚举 2 秒一次；无数据库依赖 |
| 可维护 | 业务逻辑与 UI 分离；纯函数可单测；模块职责单一 |
| 可诊断 | 全部关键路径写日志；异常带上下文；不吞异常 |
| 可扩展 | 新增播放器、调整匹配参数、替换 UI 不需改核心流程 |

### 1.3 非目标（当前版本不做）

- 不支持 macOS / Linux 播放器检测（`ctypes.windll` 仅 Windows）
- 不提供 Web 界面 / 多用户 / 远程控制
- 不做音频指纹识别（仅基于标题文本匹配）
- 不做播放历史持久化（重启即清空，已列入技术债）
- 不获取或下载音源，不绕过平台限制，不操作 QQ 音乐/网易云界面
- 不做自动入库；待补清单只负责发现、记录、复制/导出与人工核验

---

## 2. 架构总览

### 2.1 分层

```text
┌──────────────────────────────────────────────────────────────┐
│ 入口层        main.py                                       │
│               日志初始化 → 单实例锁 → 构造 TrayApp            │
├──────────────────────────────────────────────────────────────┤
│ UI 层         app/ui/                                       │
│               main_window / settings_window / notification   │
│               tray（组合根 + 托盘 + UI 事件队列）             │
├──────────────────────────────────────────────────────────────┤
│ 服务层        app/services/                                  │
│               monitor（线程/流程编排）                        │
│               player_detector（Win32）                       │
│               title_parser / matcher（纯逻辑）               │
│               subsonic（HTTP 客户端）                        │
│               missing_repository / reminder（待补/提醒）      │
├──────────────────────────────────────────────────────────────┤
│ 基础层        app/config_manager / models / constants /      │
│               paths / logging_setup / utils                  │
└──────────────────────────────────────────────────────────────┘
```

**依赖方向**：入口 → UI → services → 基础层。
**硬性规则**：`services/` 不得导入 `ui/`；纯逻辑模块（`title_parser`、
`matcher`、`models`）不得导入 `requests`/`psutil`/`tkinter`。

### 2.2 目录与职责

| 路径 | 职责 | 关键约束 |
|------|------|----------|
| `main.py` | 进程入口、日志、单实例、异常兜底 | 不写业务逻辑 |
| `app/constants.py` | 常量、播放器表、阈值、接口参数 | 禁止依赖任何项目模块 |
| `app/models.py` | `SongInfo` / `PlayRecord` / `MissingSong` | 只做数据与展示派生，不做 IO |
| `app/paths.py` | 可写目录 / 资源目录 | 兼容 PyInstaller |
| `app/config_manager.py` | INI 读写、配置校验 | 不打印密码 |
| `app/logging_setup.py` | 日志 handler | 幂等 |
| `app/services/title_parser.py` | 标题过滤/解析/择优 | 纯函数，无平台依赖 |
| `app/services/matcher.py` | 标准化/相似度/评分 | 纯逻辑，无网络 |
| `app/services/subsonic.py` | 认证、search2/search3、重试与错误映射 | 只依赖 requests |
| `app/services/player_detector.py` | 进程缓存、窗口枚举 | 仅 Windows 生效 |
| `app/services/monitor.py` | 轮询循环、历史、查询缓存、事件回调 | 不碰 Tk |
| `app/services/missing_repository.py` | 待补清单 JSON 持久化、去重、状态 | 线程安全、原子写入 |
| `app/services/reminder.py` | 提醒模式与冷却判断 | 纯逻辑，不读系统时间 |
| `app/ui/*` | 窗口与托盘 | 只在主线程操作控件 |
| `app/utils/single_instance.py` | 文件锁 | 跨平台 |
| `tests/` | 纯逻辑单测 | 不依赖 GUI |

---

## 3. 启动与生命周期

### 3.1 启动流程

```text
python main.py
  │
  ├─ get_app_dir()                  # 源码=项目根；exe=exe 所在目录
  ├─ setup_logging(app_dir)         # 控制台 + melodygap.log
  ├─ 平台检查（仅 Windows）
  ├─ SingleInstanceLock.acquire()
  │    └─ 失败：提示“程序已在运行” → return 1
  ├─ TrayApp(app_dir)
  │    ├─ ConfigManager             # 读取/创建 config.ini
  │    ├─ tk.Tk() + withdraw()      # 隐藏根窗口，仅用于事件循环
  │    ├─ NotificationWindow(root)
  │    ├─ MusicMonitor(...)         # 立即尝试初始化 Subsonic 客户端
  │    └─ MainWindow(root, ...)     # 尚未创建 Toplevel
  └─ TrayApp.run()
       ├─ setup_tray()              # 失败则降级为纯窗口模式
       ├─ monitor.start()           # 启动监控线程
       ├─ main_window.show_window() # 创建并显示主 Toplevel
       ├─ root.after(100, drain)    # 启动 UI 队列消费
       ├─ 启动托盘线程（daemon）
       └─ root.mainloop()
```

### 3.2 退出流程

```text
托盘“退出程序” / 无托盘时关闭主窗口
  └─ TrayApp.quit_app() → 队列 ("quit", None)
        └─ 主线程 _drain_ui_queue → _do_quit()
              ├─ is_quitting = True（阻止重复退出）
              ├─ 取消 UI 队列定时器
              ├─ cleanup_resources()
              │    ├─ monitor.stop()          # join ≤ 3s
              │    ├─ main_window.destroy_window()
              │    ├─ notification.close()
              │    └─ icon.stop()
              ├─ root.quit(); root.destroy()
              └─ 回到 main() → lock.release()
```

`cleanup_resources()` 幂等，同时注册到 `atexit`，防止异常路径漏清理。

### 3.3 关闭按钮策略

- 托盘图标可用：关闭主窗口 = `withdraw()` 隐藏，程序继续后台监控；
- 托盘不可用：关闭主窗口 = 退出，避免窗口隐藏后无法恢复。

---

## 4. 线程模型（修改代码前必读）

### 4.1 线程清单

| 线程 | 创建位置 | 允许做的事 | 禁止做的事 |
|------|----------|-----------|-----------|
| 主线程（Tk） | `main.py` | 创建/操作所有 Tk 控件、消费 UI 队列、调度 `after` | 执行阻塞网络请求 |
| 监控线程 | `MusicMonitor.start()` | 读进程/窗口、HTTP 查询、写历史、投递队列 | 直接操作 Tk / 弹窗 |
| 托盘线程 | `TrayApp.run()` | pystray 消息循环、把菜单事件放入队列 | 直接操作 Tk |
| 核验线程 | `TrayApp.request_recheck()` | 逐首重查曲库、投递结果/汇总 | 直接操作 Tk、修改 UI |

### 4.2 跨线程通信

**唯一合法通道**：`TrayApp._ui_queue`（`queue.Queue`）。

```python
# 监控线程
self._ui_queue.put(("record", (record, entry, created)))

# 核验线程
self._ui_queue.put(("recheck_result", (key, title, artist, result, quiet)))
self._ui_queue.put(("recheck_done", counts))

# 托盘线程
self._ui_queue.put(("show", None))
self._ui_queue.put(("show_missing", None))
self._ui_queue.put(("quit", None))

# 主线程：每 100ms 消费一次
root.after(100, self._drain_ui_queue)
```

**为什么不用 `root.after(0, callback)` 从后台线程投递？**
Tkinter 的线程安全边界并不保证跨线程调用 `after` 一定安全；在窗口销毁、
主循环未启动等时序下可能抛 `RuntimeError: main thread is not in main loop`。
队列 + 主线程轮询是确定性最高的方案。

### 4.3 共享数据

| 数据 | 写线程 | 读线程 | 保护方式 |
|------|--------|--------|----------|
| `_history` | 监控线程 | 主线程 | `threading.Lock`；对外返回副本 |
| `_current_song` | 监控线程 | 主线程 | 同一把锁 |
| `running` | 主/托盘线程 | 主线程 | GIL + 简单布尔值，可接受 |
| `_last_titles` | 监控线程 | 监控线程 | 单线程写，无需锁 |
| `_result_cache` | 监控/核验线程 | 监控/核验线程 | `_cache_lock` |
| `_last_query_error` / `_query_ok` | 监控/核验线程 | 主线程 | `_history_lock` |
| `_unknown_retry_*` | 监控线程 | 监控线程 | 仅监控线程访问 |
| `missing_repo` | 监控/主线程 | 主线程 | 仓库内部锁；读写均返回副本 |
| `_rechecking` | 主线程 | 主线程 | 仅主线程读写，防止重复批量任务 |

新增共享状态时必须明确：谁写、谁读、如何同步。禁止在 UI 线程遍历监控线程
正在修改的原始列表，统一调用 `monitor.play_history`（返回副本）。

---

## 5. 数据模型

### 5.1 `SongInfo`（不可变）

```python
SongInfo(title="晴天", artist="周杰伦", player="qq")
```

- `player` 取值：`"qq"` / `"netease"`；
- `player_name` / `player_short_name` 从常量表派生；
- 不可变（`frozen=True`），可安全跨线程传递。

### 5.2 `PlayRecord`

| 字段 | 类型 | 说明 |
|------|------|------|
| `timestamp` | `str` | `YYYY-MM-DD HH:MM:SS` |
| `title` | `str` | 解析后的歌名 |
| `artist` | `str` | 解析后的歌手 |
| `in_library` | `Optional[bool]` | True 在库、False 不在库、None 未知 |
| `full_title` | `str` | 原始窗口标题，排障用 |
| `player` | `str` | 播放器标识 |

派生属性：`status_key`、`status_text`、`is_missing`、`is_unknown`、
`player_name`、`player_short_name`、`csv_row()`。

**三态语义**：未配置服务器、网络失败、认证失败统一记为 `None`，不会写入
待补清单，也不会弹出缺失提醒。

### 5.3 `MissingSong` 与待补清单

`MissingSong` 字段：`key`、`title`、`artist`、`player`、`first_seen`、
`last_seen`、`play_count`、`status`（`pending` / `ignored`）。

- `key = make_song_key(artist, title)`，基于标准化文本，跨播放器去重；
- 只记录 `in_library is False` 的歌曲；
- 同一首歌再次播放只增加 `play_count`、更新 `last_seen`；
- 歌曲后续被判定在库时自动移除；
- 数据保存在 `get_app_dir()/missing_songs.json`，临时文件 + 替换写入；
- 文件损坏时备份为 `missing_songs.corrupt_<时间>.json` 并从空清单开始。

---

## 6. 配置管理

### 6.1 文件位置

| 运行方式 | `get_app_dir()` | 配置文件 |
|----------|-----------------|----------|
| `python main.py` | 项目根目录 | `<项目根>/config.ini` |
| PyInstaller exe | `MelodyGap.exe` 所在目录 | 与 exe 同级 |

只读资源（`icon.ico`）通过 `get_resource_path()` 读取；打包后位于
`sys._MEIPASS`，不能用于写配置。

### 6.2 格式

```ini
[SUBSONIC]
server_url = https://your-server.com:port/
username = your_username
password = your_password
verify_ssl = 1

[APP]
reminder_mode = new_missing
reminder_cooldown_minutes = 10
window_geometry = 1080x760+100+100
window_zoomed = 0
last_tab = 0
```

- `configparser` 使用 `interpolation=None`，避免密码含 `%` 时解析崩溃；
- 文件不存在时自动写入默认占位值；
- `is_subsonic_configured()` 的判断：三项非空且地址不以占位前缀
  `https://your-server.com` 开头；
- `verify_ssl=0` 仅用于自签名 HTTPS 服务器，默认值为 `1`；
- `[APP]` 段保存提醒模式、冷却时间、窗口位置/大小和上次页签；
- 非法提醒模式回退为 `new_missing`，非法冷却时间回退为 10 分钟。

### 6.3 安全说明（技术债）

密码当前以**明文**写入 INI。请勿把 `config.ini` 提交到版本库
（`.gitignore` 已忽略）。后续可迁移到 Windows Credential Manager
（`keyring`）或 DPAPI 加密。

---

## 7. Subsonic 接入

### 7.1 认证

```text
salt  = 6 位随机字母数字（secrets 生成）
token = MD5(password + salt).hexdigest()
GET /rest/<endpoint>?u=<user>&t=<token>&s=<salt>&v=1.16.1&c=...&f=json
```

密码不出现在请求 URL 中。每次请求重新生成 salt/token。

服务器地址会先规范化：去掉末尾斜杠，以及误填的 `/rest`、`/rest/ping`、
`/rest/search3` 等路径，保留反向代理子路径。单次请求超时为 10 秒；超时或
连接失败会自动重试一次。设置窗口提供“测试连接”，可单独验证证书与账号。

### 7.2 搜索策略

`SubsonicClient.search_song(artist, title)` 依次执行：

| 顺序 | query | songCount | 目的 |
|------|-------|-----------|------|
| 1 | `artist title` | 50 | 精确组合，优先命中 |
| 2 | `title` | 30 | 歌手名带翻译/后缀时的兜底 |
| 3 | `artist` | 30 | 歌名带版本后缀时的兜底 |

匹配时优先执行第 1 种查询；若综合评分 ≥ `EARLY_STOP_SCORE`（0.90），
直接返回，跳过后两种兜底查询。`search_song()` 仍会执行完整三次搜索，供
调试/测试使用；`searchResult3.song` 可能是 dict 或 list，代码已兼容。

`search3` 返回错误码 `0/10/70`（通用错误、缺少参数、不支持该接口）时，
自动回退到 `search2`；认证与网络错误不会回退。任一策略失败会记录 warning；
若最终没有命中且存在失败，则抛出 `SubsonicError`，由 monitor 标记为“未知”，
避免把网络故障误判为不在库。

### 7.3 错误映射

| 场景 | 异常消息 |
|------|----------|
| 超时 | 连接超时，请检查服务器地址和网络连接 |
| 连接失败 | 连接失败，请检查服务器地址是否正确 |
| HTTPS 证书失败 | HTTPS 证书校验失败，请检查证书，或在设置中关闭证书校验 |
| HTTP 401 | 认证失败，请检查用户名和密码 |
| HTTP 404 | 服务器地址不存在或路径错误 |
| API code 40 | 用户名或密码错误 |
| API code 50 | 用户未授权访问此资源 |
| JSON 解析失败 | 服务器响应格式错误，请检查服务器地址 |

统一抛出 `SubsonicError`，上层（monitor）捕获后标记为“未知”并记录日志。
未知状态不会写入待补清单；当前歌曲每隔 15 秒最多自动重试 5 次，成功后会更新
原记录并重新触发回调，不产生重复历史。

---

## 8. 歌曲匹配算法

### 8.1 标准化 `SongMatcher.normalize_text`

按顺序执行：

1. **NFKC 归一化**：全角字母/数字/空格转半角；
2. **转小写**；
3. **标点替换为空格**：正则 `[^\w\s\u4e00-\u9fff]` → `" "`；
4. **删除英文修饰词**：`remix / remaster(ed) / acoustic / live / demo /
   instrumental / cover / feat / ft / featuring`，使用 `\b` 单词边界；
5. **删除中文修饰词**：`重制版 / 混音版 / 伴奏 / 现场版`；
6. **压缩连续空白**。

示例：

| 输入 | 输出 |
|------|------|
| `Song (Live Remix)` | `song` |
| `Olive` | `olive`（不会被 `live` 规则破坏） |
| `ＡＢＣ　１２３` | `abc 123` |
| `晴天（现场版）` | `晴天` |

### 8.2 相似度 `calculate_similarity`

```text
sim = difflib.SequenceMatcher(None, a, b).ratio()          # 0~1
若 min(len(a), len(b)) >= 4 且 短串是长串的子串：
    sim = max(sim, 0.8)
```

旧版没有长度限制，歌名为 `"a"` 时会与大量候选形成子串关系，导致误判。

### 8.3 综合评分

```text
score = artist_similarity * 0.4 + title_similarity * 0.6
命中条件：score >= 0.75
```

权重与阈值定义在 `app/constants.py`：

```python
MATCH_THRESHOLD = 0.75
ARTIST_WEIGHT = 0.4
TITLE_WEIGHT = 0.6
```

调参建议：

- 误报多（把不在库判为在库）：提高阈值到 `0.80~0.85`；
- 漏报多（在库判为不在库）：降低到 `0.70`，或提高歌名权重；
- 歌手名噪声大（如 `周杰伦 / Jay Chou`）：适当降低歌手权重。

修改后请补充对应测试用例（见 `tests/test_matcher.py`）。

### 8.4 返回值

`SongMatcher.find_best_match()` 返回 `MatchResult(matched, song, score)`：

- `song` 为最高分候选（可能为 `None`）；
- 日志记录每个候选的艺人/歌名/综合分，便于排查误判；
- `SubsonicClient.find_exact_match()` 保留布尔返回，兼容旧调用。

---

## 9. 播放器检测与标题解析

### 9.1 支持的播放器

| key | 进程名（小写比较） | 显示名 |
|-----|-------------------|--------|
| `qq` | `qqmusic.exe` | QQ音乐 |
| `netease` | `cloudmusic.exe` / `neteasecloudmusic.exe` / `neteasemusic.exe` | 网易云音乐 |

新增播放器只需修改 `app/constants.py` 的 `SUPPORTED_PLAYERS`，并在
`PLAYER_EXCLUDED_KEYWORDS` 中补充主界面关键词（如有）。

### 9.2 检测流程

```text
MusicMonitor._poll_once()
  └─ PlayerDetector.get_current_playing()
       ├─ update_process_cache()      # 5s TTL，psutil 扫描 PID
       └─ 对每个已运行播放器：
            ├─ EnumWindows             # 枚举可见窗口
            ├─ GetWindowThreadProcessId# 窗口归属 PID
            ├─ GetWindowTextW          # 读取标题
            ├─ is_valid_song_title()   # 关键词过滤 + 分隔符检查
            └─ select_best_title()     # 多窗口择优
```

### 9.3 标题清洗与过滤规则

**第一步：剥离末尾应用名**（`PLAYER_TITLE_SUFFIXES`）

```text
"晴天 - 周杰伦 - 网易云音乐" -> "晴天 - 周杰伦"
"晴天 - 周杰伦 - QQ音乐"     -> "晴天 - 周杰伦"
```

旧版规则是“标题包含播放器名就丢弃”，会误杀带应用名后缀的正常播放标题。

**第二步：必须包含分隔符**

`" - "`、`" — "`、`" – "`、`" | "`。不使用中文冒号，因为歌名本身常含冒号
（如 `Love Story: Part 2`），且解析正则并不支持冒号。

**第三步：排除功能页**

- 清洗后仍包含播放器名（`QQ音乐` / `网易云音乐` / `CloudMusic` 等）→ 功能页；
- 按分隔符切段后，任一段与功能页关键词**完全相等** → 功能页。

功能页关键词：`设置 / 搜索 / 登录 / 选项 / 偏好 / 关于 / 帮助 / 更新 /
歌单 / 我的歌单 / 我的音乐 / 我的收藏 / 播放列表 / 本地音乐 / 下载管理 /
发现音乐 / 每日推荐 / 私人漫游 / 云盘 / 历史记录`。

注意这里是“整段完全相等”，不是子串匹配，因此《我的天空 - 南征北战》不会
因为包含“我的”而被误杀。

### 9.4 解析与去重

- 清洗后的标题用正则惰性匹配第一个分隔符，前半为歌名、后半为歌手；
- 同一播放器记录 `_last_titles`，标题不变则不重复记录；
- 标题变化但解析失败时不更新 `_last_titles`，下一轮仍会尝试；
- 没有检测到任何歌曲时，`current_song` 置为 `None`（暂停时窗口标题仍在，
  因此仍会显示当前歌曲）。

### 9.5 已知限制

- 窗口标题格式由播放器决定，不同版本/皮肤可能不同。若某版本使用
  “歌手 - 歌名”顺序，当前会解析反。届时需要在 `parse_title()` 中按
  `player_key` 增加分支，并补充测试。
- 同时运行 QQ 音乐和网易云音乐时，按 `SUPPORTED_PLAYERS` 顺序返回第一个
  有歌曲标题的窗口（当前 QQ 优先）。暂停的播放器窗口标题通常不变，可能被
  误报为“当前播放”。后续可结合前台窗口或 Windows 媒体会话（SMTC）判断。
- 标题末尾应用名的剥离依赖 `PLAYER_TITLE_SUFFIXES`；播放器改名后需同步维护。
- 功能页关键词采用“整段完全相等”匹配，若某首歌名恰好等于关键词（例如
  一首歌就叫《设置》），会被误过滤。

---

## 10. UI 设计

### 10.1 主窗口

- 顶部：深色品牌栏、监控状态、待补数量徽标；
- 当前播放 Hero 卡：大号歌名 + `歌手 · 播放器` + 在库/不在库/未知/查询中
  状态，“复制歌名”和“复制信息”分离；当前歌曲未知或不在库时可“重新查询”；
- 统计卡片：总播放、在库、待补、QQ音乐、网易云；点击卡片跳转到对应筛选；
- 页签 1「待补清单」：搜索、状态筛选、复制选中/列表、导出、核验选中/
  核验待补、忽略、恢复、删除；双击单行只复制该行；
- 页签 2「播放记录」：按全部/在库/不在库/未知筛选、关键词搜索、按当前
  筛选导出、清空；双击单行复制“歌名 - 歌手”；
- 底部：服务器配置状态、最后查询时间、操作提示、设置/最小化。

### 10.2 待补清单数据流

```text
监控线程发现 in_library=False
  └─ TrayApp._on_record
       ├─ MissingRepository.add_missing(record)   # 去重 + 落盘
       └─ UI 队列 ("record", (record, entry, created))
            └─ 主线程按提醒策略决定是否弹窗

用户点击“核验选中/核验待补”
  └─ TrayApp.request_recheck(entries, quiet=True)
       └─ 后台线程逐首 monitor.recheck_song()
            ├─ 结果 True  -> 从清单移除
            ├─ 结果 False -> 保留，计数“仍缺失”
            └─ 结果 None  -> 保留，计数“查询失败”
       └─ 队列 ("recheck_done", counts)
            └─ 主窗口显示汇总并刷新
```

手动核验当前歌曲为“不在库”时使用 `MissingRepository.ensure_missing()`，
只确保清单中存在该歌曲，不把核验动作计入播放次数。

### 10.3 刷新策略

- 每 `UI_REFRESH_INTERVAL_MS`（1000ms）刷新一次；
- 统计和当前播放每次都更新；
- 待补清单与播放记录分别维护内容签名，仅在签名变化时重建；
- 筛选/搜索变化时强制刷新当前表格；
- 重建前记录 `tree.yview()[0]`，重建后恢复滚动位置。

### 10.4 表格配色

播放记录每行只打一个状态 tag：

| tag | 背景 | 前景 |
|-----|------|------|
| `in_library` | `#F0FDF4` | `#047857` |
| `not_in_library` | `#FFF1F2` | `#BE123C` |
| `unknown` | `#F8FAFC` | `#64748B` |

待补清单使用 `pending`（浅红/玫红）和 `ignored`（浅灰/灰）两个 tag。
播放器通过“播放器”列文本区分。

### 10.5 通知窗口

- 右下角无边框 Toplevel，置顶，95% 不透明；
- 6 秒自动关闭；点击任意位置复制 `歌名 - 歌手` 后关闭；
- 可点击区域使用手型光标，并显示“单击复制歌曲信息 · 6 秒后自动关闭”；
- 绿色 = 在库，红色 = 不在库/新待补，灰色 = 无法查询；
- 提醒模式：仅新缺失（默认）、所有缺失、全部歌曲、关闭；
- “所有缺失/全部歌曲”受同曲冷却时间限制；未知状态不提醒；
- 由主线程消费 UI 队列后调用，**禁止在监控线程直接调用**。

### 10.6 托盘

- 左键默认菜单项“显示主界面”；
- “开始/停止监控”文本动态变化；
- “待补清单 (N)”直接打开待补页签；
- 退出走队列，确保在主线程完成 Tk 资源释放；
- 设置保存后通过主窗口底栏提示配置已生效；
- `pystray` 采用延迟导入，导入失败时程序降级为纯窗口模式。

### 10.7 复制、右键菜单与快捷键

- 待补清单双击只复制点击行的“歌名 - 歌手”；播放记录双击行为相同；
- 待补清单右键菜单：复制歌名、复制歌曲信息、QQ 音乐/网易云搜索、核验选中、
  核验待补、忽略、恢复、删除；多选时复制项显示数量，搜索仅单选可用，
  忽略/恢复按所选状态动态禁用；
- 播放记录右键菜单：复制歌名、复制歌曲信息、QQ 音乐/网易云搜索；
- `Ctrl+A` 仅用于待补清单全选；`Ctrl+C` 在待补清单复制选中项，在播放记录
  复制当前行歌曲信息；
- 所有剪贴板写入统一走 `app/utils/clipboard.py`，失败只更新底栏提示，不弹窗。

### 10.8 主题

颜色/字体/ttk 样式集中在 `app/ui/theme.py`，采用“深色顶栏 + 浅色内容区 +
高饱和强调色”的现代风格：

- `apply_modern_style()` 统一配置 Notebook、Treeview、Combobox、Spinbox、
  Scrollbar 的 clam 样式；
- 统计卡使用浅色底 + 彩色数值/顶部色条，Hero 卡使用靛蓝渐变主色；
- 按钮悬停色由 `darken_color()` 按 RGB 计算，不维护硬编码颜色映射表；
- 通知窗使用深色卡片 + 状态色强调条。

换肤只需修改该文件并重新调用 `apply_modern_style()`。

---

## 11. 日志与错误处理

### 11.1 日志

- 位置：`get_app_dir()/melodygap.log`；
- 轮转：单文件 1MB，保留 3 份；
- 格式：`时间 | 级别 | 模块 | 消息`；
- 控制台同步输出，打包为 `--windowed` 时控制台不可见，以文件为准。

按级别约定：

| 级别 | 使用场景 |
|------|----------|
| DEBUG | 标题解析细节、每个候选匹配分数、进程 PID |
| INFO | 启停、检测到新歌、配置变更、匹配成功 |
| WARNING | 搜索失败、配置缺失、托盘不可用、线程未按时退出 |
| ERROR | 配置保存失败、初始化失败、UI 事件处理异常 |
| EXCEPTION | 未预期异常，必须带堆栈 |

### 11.2 错误处理原则

- 禁止裸 `except:`；至少 `except Exception` 并记录日志；
- 可恢复错误（单次搜索失败、单个窗口读取失败）降级继续；
- 不可恢复错误（配置无法写入、Tk 初始化失败）向用户提示并退出；
- 用户可见消息统一中文，技术细节写入日志；
- `SubsonicError` 携带可直接展示的中文原因。

### 11.3 旧代码清理清单

本次重构删除/修正的过旧与冗余内容：

| 旧代码 | 问题 | 处理 |
|--------|------|------|
| 2095 行单文件 | 职责混杂、无法单测 | 拆分为 15 个模块 |
| 监控线程直接创建通知 Toplevel | 跨线程操作 Tk，随机崩溃 | UI 队列 + 主线程消费 |
| `children['!label2']` 取 Label | 依赖 Tk 内部命名，脆弱 | 直接返回数值 Label |
| `replace('live','')` | 破坏 Olive/Deliver | 单词边界正则 |
| 多 tag 同时设背景 | 状态色被播放器色覆盖 | 单状态 tag |
| `__file__ in cmdline` 单实例 | 打包后失效 | 文件锁 |
| `session.timeout = 5` | requests 不读取该属性 | 显式传 timeout |
| 手动拼接 CSV | 逗号/换行破坏格式 | `csv.DictWriter` |
| 三处重复图标绘制 | 维护成本高 | `ui/icons.py` 统一 |
| `player_key` 未使用参数 | 冗余 | 删除 |
| README 引用不存在文件 | 误导 | 重写 |
| 通知漏绑播放器标签 | 点击该区域不关闭 | 递归绑定 |
| `import random/string` 在方法内 | 局部导入、非加密随机 | 顶层 `secrets` |
| 处处 `print` | 无级别、无落盘 | `logging` |
| 配置 `configparser` 默认插值 | 密码含 `%` 崩溃 | `interpolation=None` |
| `os._exit(0)` 强杀 | 跳过清理 | 正常退出流程 |

---

## 12. 单实例机制

`SingleInstanceLock` 对 `%TEMP%/<APP_NAME>.lock` 加 OS 级文件锁：

- Windows：`msvcrt.locking(..., LK_NBLCK, 1)`；
- Linux/macOS：`fcntl.flock(..., LOCK_EX | LOCK_NB)`。

优点：

1. 打包后同样有效；
2. 进程崩溃时锁由内核释放，不会留下“死锁文件”；
3. 无需遍历进程列表。

锁文件中的 PID 仅用于人工排查，不参与判定。

---

## 13. 测试

### 13.1 运行

```bash
python -m unittest discover -s tests -v
```

默认不创建 Tk 窗口；依赖 Tk 的少量用例会在无 GUI 环境自动跳过。
Windows 原生播放器检测与真实托盘交互不在单元测试范围内。

### 13.2 现有覆盖

| 文件 | 覆盖内容 |
|------|----------|
| `tests/test_title_parser.py` | 应用名后缀剥离、关键词过滤、四种分隔符、择优、非法输入 |
| `tests/test_matcher.py` | NFKC/大小写/标点/修饰词、Olive 回归、子串阈值、加权评分、命中/未命中 |
| `tests/test_config_manager.py` | 默认配置创建、读写、占位地址判断、密码含 `%` |
| `tests/test_models.py` | 派生字段、CSV 行、时间戳构造 |
| `tests/test_subsonic.py` | 本地假服务器验证 token 认证、三种搜索策略、去重、单条 dict、错误映射 |
| `tests/test_missing_repository.py` | 待补清单去重、持久化、忽略/恢复、移除、损坏备份 |
| `tests/test_reminder.py` | 四种提醒模式、冷却、未知状态、非法配置回退 |
| `tests/test_monitor.py` | 假检测器/假曲库验证记录、去重、切歌、清空、启停、三态、缓存、重查 |
| `tests/test_clipboard.py` | 复制歌名/歌曲信息、播放记录复制、剪贴板异常 |
| `tests/test_settings_form.py` | 密码空格、URL 大小写、内联校验与字段聚焦 |
| `tests/test_context_menu.py` | 多选菜单文案、搜索禁用、忽略/恢复状态、历史菜单标题 |

当前共 103 个用例，全部为离线测试（数量变化时以实际运行为准）。

### 13.3 手动验收清单（Windows）

1. 启动程序，托盘出现图标，主窗口显示；
2. 不配置 Subsonic 时播放歌曲 → 记录显示“未知”，不进入待补清单；
3. 设置中点“测试连接” → 显示服务器类型/版本；保存后播放任意歌曲，通知颜色与统计正确；
4. 不在库歌曲 → 进入待补清单，重启程序后仍存在；
5. 待补清单搜索/筛选/复制/导出/忽略/恢复/删除正常；右键复制、搜索项与 `Ctrl+A`/`Ctrl+C` 正常；
6. 把歌曲补进服务器后点击“核验选中/核验待补” → 已入库项移出，汇总正确；
7. 播放记录按在库/不在库/未知筛选、搜索正常；
8. 最小化 → 托盘恢复 → 表格/统计仍正常；
9. 托盘“待补清单 (N)” → 打开对应页签；
10. 托盘“停止监控”后再“开始监控” → 状态标签正确切换；
11. 重复启动 exe → 提示“程序已在运行”；
12. 关闭主窗口 → 隐藏到托盘；托盘退出 → 进程结束、日志正常收尾；
13. 临时断开服务器 → 当前歌曲显示“未知”，恢复后自动重试成功且不产生重复记录；
14. 导出 CSV → Excel 打开无乱码、含逗号的歌名完整；
15. 播放记录右键复制、按当前筛选导出、清空确认默认“否”；
16. 设置留空服务器地址 → 表单内联提示并聚焦该字段，不弹警告框。

### 13.4 新增测试要求

- 修 bug：先写能复现的测试，再改实现；
- 改匹配参数：补充边界分数用例；
- 新增播放器：补充进程名/排除词/标题格式用例；
- 测试不得依赖网络、真实 Tk 窗口、真实 Subsonic 服务器。

---

## 14. 打包发布

```bat
pip install -r requirements-dev.txt

pyinstaller --onefile --windowed ^
  --name MelodyGap ^
  --icon icon.ico ^
  --add-data "icon.ico;." ^
  main.py
```

产物：`dist/MelodyGap.exe`。

#### 14.1 GitHub Actions 自动发布

- `.github/workflows/ci.yml`：推送与 PR 自动运行 ruff + 单元测试；
- `.github/workflows/release.yml`：推送 `v*` 标签时在 Windows Runner 上运行测试、
  打包单文件 exe、生成 ZIP 与 SHA256，并自动创建 GitHub Release；
- GitHub 会自动附带源码 zip/tar 包，用户可直接下载源码或构建好的 exe；
- 发布新版本：更新 `APP_VERSION` 与 `CHANGELOG.md`，提交后推送同名标签：

```bash
git tag v1.0.0
git push origin v1.0.0
```

注意：

- `--add-data` 分隔符 Windows 用 `;`，Linux/macOS 用 `:`；
- 配置和日志写在 exe 同目录，发布时目录需可写（不要放 `Program Files`）；
- 若使用自定义版本信息，可追加 `--version-file version_info.txt`；
- 打包后先用 `--console` 版本跑一次，确认无缺失 DLL/隐式导入问题。

---

## 15. 编码规范

### 15.1 基本

- Python 3.8 兼容：使用 `typing.Optional/List/Dict`，不用 `str | None`；
- 文件头 `# -*- coding: utf-8 -*-` + 模块 docstring；
- 命名：模块/函数/变量 `snake_case`，类 `PascalCase`，常量 `UPPER_SNAKE`；
- 类型注解覆盖公共 API；回调类型用 `Callable[...]` 别名；
- 行宽建议 100 字符以内。

### 15.2 注释

- 模块 docstring：说明职责、依赖、线程/平台约束；
- 类 docstring：说明参数、生命周期、使用禁忌；
- 函数 docstring：说明参数、返回值、异常、副作用；
- 行内注释只解释“为什么”，不复述“做了什么”；
- 修改算法/线程模型/配置格式时，同步更新本文档。

### 15.3 异常与日志

- 不使用裸 `except:`；
- 捕获后要么处理，要么 `logger.exception` 后重新抛出；
- 用户可见错误用中文，技术细节进日志；
- 不在日志中输出密码、token、完整认证 URL。

### 15.4 线程

- 任何 Tk 调用必须在主线程；
- 跨线程只通过队列传递不可变数据（`PlayRecord`/`SongInfo`）；
- 新增后台线程必须是 `daemon=True`，并提供停止事件；
- 阻塞操作必须设置超时。

---

## 16. 扩展指南

### 16.1 新增播放器

1. 在 `constants.SUPPORTED_PLAYERS` 增加条目（进程名、显示名、短名）；
2. 在 `PLAYER_EXCLUDED_KEYWORDS` 增加主界面排除词；
3. 若标题顺序不是“歌名 - 歌手”，在 `title_parser.parse_title()` 增加分支；
4. 若窗口标题有额外后缀（如 ` - QQ音乐`），在解析前清洗；
5. 补充 `tests/test_title_parser.py` 用例；
6. 更新 README「支持的播放器」与本文档。

### 16.2 调整匹配灵敏度

修改 `constants.py` 中 `MATCH_THRESHOLD` / `ARTIST_WEIGHT` / `TITLE_WEIGHT`，
运行 `tests/test_matcher.py`，再按第 8.3 节建议做小样本回归。

### 16.3 替换 UI

服务层不依赖 UI。若改用 PyQt/Web 前端：

- 复用 `MusicMonitor`、`SubsonicClient`、`SongMatcher`；
- 通过 `on_record` 回调接收新记录；
- 自行保证 UI 线程亲和性；
- 不要把网络请求放到 UI 线程。

### 16.4 播放历史持久化（仍建议下一步）

当前待补清单已持久化到 JSON，但播放历史仍只在内存中。若需要跨重启统计，
推荐 SQLite：

```text
records(id INTEGER PK, timestamp TEXT, title TEXT, artist TEXT,
        in_library INTEGER, full_title TEXT, player TEXT)
索引：timestamp、in_library
```

- 在 `MusicMonitor` 中通过 repository 写入，保持 UI 只读；
- 保留 CSV 导出；
- 增加“按日期清理”配置。

### 16.5 匹配缓存（已实现）

`MusicMonitor` 已增加运行期缓存：

```text
key = (artist, title)
value = True / False
```

只缓存确定结果；查询失败不缓存；修改服务器配置后自动清空。待补清单的
“核验待补/核验全部”会绕过缓存并更新缓存。

---

## 17. 已知限制与技术债

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| 1 | 仅 Windows | 无法跨平台运行 | 抽象 `PlayerDetector` 接口，macOS 用 AppleScript |
| 2 | 依赖窗口标题 | 播放器改版可能失效 | 预留 Media Session / SMTC 方案 |
| 3 | ~~曲库结果只有布尔~~ | 已改为三态 `Optional[bool]` | 已完成 |
| 4 | 历史仅内存 | 退出即丢 | SQLite 持久化 |
| 5 | 网络慢时监控线程阻塞 | 查询仍在监控线程同步执行 | 异步请求/线程池；已加入缓存与提前终止 |
| 6 | 密码明文 | 本地泄露风险 | keyring / DPAPI |
| 7 | ~~匹配无缓存~~ | 已加入运行期缓存 | 已完成（跨重启缓存可按需扩展） |
| 8 | 不支持手动纠正匹配 | 误判无法修正 | 表格右键“标记为在库/不在库” |
| 9 | 无国际化 | 仅中文 | 抽取文案表 |
| 10 | 无自动更新 | 依赖手动发布 | 接入版本检查 |

---

## 18. 常见问题（FAQ）

**Q1：托盘不显示？**
查看日志是否出现“加载 pystray 失败”。程序会降级为纯窗口模式，此时关闭
窗口即退出。

**Q2：所有歌都显示“不在库”？**
先检查 `config.ini` 是否仍为占位地址；再确认服务器地址可访问、账号密码
正确、服务器支持 `search3`（或可回退 `search2`）。日志中会有“Subsonic 配置不完整”或搜索失败记录。

**Q3：明明在曲库却判为不在？**
查看日志中的候选列表与分数。常见原因：标题解析反了（歌手/歌名互换）、
服务器返回的歌手字段为空、相似度略低于 0.75。可临时降低阈值验证。

**Q4：播放时没有反应？**
确认播放器进程名在支持列表内；窗口未最小化到托盘；窗口标题包含分隔符；
日志中是否有“标题解析失败”。

**Q5：为什么暂停后“当前播放”还在？**
暂停时窗口标题通常不变，检测逻辑无法区分暂停/播放。这是标题方案的固有限制。

**Q6：日志在哪里？**
源码运行在项目根目录，exe 运行在 exe 同目录，文件名
`melodygap.log`。

---

## 19. 变更记录

### 1.0.0（首个公开版本，2026-10-20）

- 首个公开版本，统一版本号与应用元信息；
- 通过窗口标题识别 QQ 音乐 / 网易云音乐当前播放歌曲，约每 2 秒检测一次；
- 三态曲库查询（在库 / 不在库 / 未知），未知状态不污染待补清单；
- 待补清单去重、持久化、忽略/恢复、搜索、排序、复制与导出；
- 播放记录筛选、搜索、复制、按当前筛选导出与清空；
- 当前播放卡片支持复制歌名、复制歌曲信息与手动重查；
- 待补清单与播放记录支持右键菜单，待补清单支持 `Ctrl+A` / `Ctrl+C`；
- 设置窗口支持连接测试、HTTPS 证书校验与表单内联校验；
- 提醒模式、同曲冷却、系统托盘与窗口状态记忆；
- 103 项离线单元测试，CI 运行 lint 与测试，标签推送自动构建 Windows 发布包。

## 20. 下一步优化路线（待讨论）

按优先级建议：

1. **播放历史持久化**：SQLite 保存历史 + 启动恢复 + 按日期清理；
2. **异步查询**：网络请求放入队列/线程池，避免阻塞监控轮询；
3. **手动纠正**：播放记录右键标记在库/不在库，写回缓存；
4. **配置安全**：Windows 凭据管理器存储密码；
5. **可观测性**：显示匹配详情与查询耗时（设置页测试连接、最近错误已完成）；
6. **跨平台**：抽象检测器，支持 macOS（AppleScript / Now Playing）。

每项落地前先确认：是否改变用户可见行为、是否需要数据迁移、是否需要新增
测试与文档章节。
