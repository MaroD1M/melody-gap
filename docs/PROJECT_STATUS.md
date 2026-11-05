# MelodyGap 项目现状、路线图与交接说明

> 当前版本：2.0.2
> 状态基线：2026-11-05
> 适用仓库：`MaroD1M/melody-gap`
> 目标读者：项目维护者、二次开发者、接手者、发布负责人

本文回答四个问题：**项目现在是什么、已经完成了什么、还缺什么、下一步做什么**。
技术细节以 [DEVELOPMENT.md](DEVELOPMENT.md) 为准；本文负责状态、优先级、验收标准
和交接决策。

## 1. 结论摘要

- v2.0.0 将桌面端从 Python/Tkinter 重写为 Rust + Tauri 2 + Svelte 5；v2.0.1 修复发布版误连接开发服务器并补全版本资源；v2.0.2 修复启动 state 竞态、DPI 窗口恢复与自适应布局。
- 核心功能保持完整：SMTC/窗口标题检测、双播放器并行、三态曲库查询、待补清单、
  播放记录、提醒、托盘、导出与人工核验。
- Rust 测试共 133 项，全部离线；`cargo clippy -D warnings`、`pnpm check`、
  `pnpm build` 通过（v2.0.1 发布时为 122 项，v2.0.2 发布时为 128 项）。
- CI/Release 已切换为 Windows + Rust + pnpm，并增加便携包 `--smoke-test`。
- v2.0.2 Windows CI、Release 构建、便携包打包与 `--smoke-test` 已通过；
  **播放器检测、托盘、通知窗和长时间运行仍需按验收清单逐项确认**，本地 Linux
  交叉编译不能替代 Windows Runner 和真实播放器测试。
- 剩余技术债包括：播放历史不持久化、网络查询仍在监控线程、密码明文、未签名、
  仅支持 Windows。

## 2. 当前发布状态

| 项目 | 当前值 |
|------|--------|
| 版本 | `2.0.2` |
| 分支 | `main` |
| 主要实现 | `rust/`（Tauri 2 + Svelte 5） |
| 标签 | `v2.0.2` |
| Release | <https://github.com/MaroD1M/melody-gap/releases/tag/v2.0.2> |
| 发布时间 | 2026-11-05 05:21 UTC |
| CI | `41972369450`，成功 |
| Release 构建 | `41972432358`，成功 |
| 推荐产物 | `MelodyGap-portable-windows-x64.zip` |
| 测试 | 128 项 Rust 测试 |

发布资产：

| 文件 | 大小 | SHA256 |
|------|------|--------|
| `MelodyGap-portable-windows-x64.zip` | 3,599,996 B | `dfbb1ed0510578d69f30af40cd444cb9d5b43664ced9fc17958179d8cc5b7098` |
| `MelodyGap.exe` | 8,162,304 B | `307191f575d339c28a8a95392e094320fee27bf60334f9ebf0e2ad5a55ba950b` |
| `SHA256SUMS.txt` | 191 B | 见 Release 页面 |

官方 Windows Runner 使用 MSVC 构建，EXE 静态链接 WebView2 Loader，因此 ZIP 内只有
EXE、配置示例与 LICENSE；本地 Linux 交叉编译（GNU）产物需要额外携带
`WebView2Loader.dll`，哈希不会与官方 Release 一致。

v2.0.2 修复内容：

- 主窗口改为在 `AppState` 与通知管理器注册后创建，修复启动时 `state not managed`
  且必须保存设置才能恢复的问题；
- 窗口几何改存逻辑尺寸与物理坐标，旧格式按物理像素兼容；恢复时按当前显示器
  工作区和缩放系数限制，修复 DPI 缩放与越界；
- 主窗口默认隐藏，恢复尺寸/位置后显示，首次运行居中；
- 底部状态栏改为可换行分组，默认窗口高度下保持可见，长文本不再挤乱按钮；
- 设置弹窗改为固定头尾、内容区滚动，小窗口下保存按钮始终可见；
- 主布局改为全高自适应，默认 1120×800 下表格内部滚动，最大宽度提升至 1440px；
- 窗口标题版本号改为构建时读取；版本号升级至 2.0.2。

上一版 `v2.0.1` 修复了发布版误连接开发服务器并补全 Windows 版本资源；`v2.0.0`
存在启动后连接开发服务器的缺陷，请勿继续使用。

## 3. 产品定位与边界

### 3.1 要解决的问题

用户同时使用 QQ 音乐/网易云音乐在线听歌，但音乐库放在 Subsonic、Navidrome 或
Airsonic。项目自动判断当前播放歌曲是否已在自建曲库中，并把缺失歌曲整理成
可核验、可导出的待补清单。

### 3.2 目标用户

- 有自建 Subsonic/Navidrome 曲库的个人用户；
- 使用 Windows 10 1809+ / Windows 11；
- 愿意自行配置服务器，并能接受未签名开源软件的安全提示。

### 3.3 产品边界

项目**不做**以下事情：

- 不下载音源、不抓取版权内容、不绕过平台限制；
- 不注入播放器进程、不模拟点击、不修改播放器收藏；
- 不自动把歌曲加入 Subsonic 曲库；
- 不提供 Web 界面、多用户、远程控制或云同步；
- 不做音频指纹识别，只做标题/歌手文本匹配；
- 当前不做 macOS/Linux 的播放器检测。

### 3.4 隐私与安全原则

- 配置、日志、待补清单和 WebView2 数据只写本地程序目录；
- 只访问用户填写的 Subsonic/Navidrome 服务器；
- 不收集遥测，不上传歌名、账号或密码；
- 日志不记录密码或认证 token；
- 发布包提供 SHA256，便于核验。

## 4. 架构与关键流程（速览）

详细说明见 [DEVELOPMENT.md](DEVELOPMENT.md) 第 2～9 节。

```text
Tauri 事件循环
  ├── 主窗口（Svelte 5，每秒 get_snapshot + state-changed）
  ├── 通知窗（队列 + 6 秒自动关闭）
  ├── 托盘与单实例
  └── 命令层（get_snapshot / save_settings / recheck_* / export_*）
       └── AppState
            ├── MusicMonitor（监控线程）
            │    ├── HybridDetector
            │    │    ├── SmtcDetector（SMTC 线程）
            │    │    └── WindowDetector（Win32 窗口回退）
            │    ├── SubsonicClient + SongMatcher
            │    └── MissingRepository / Reminder
            ├── ConfigManager
            └── NotificationManager
```

关键流程：

```text
播放器播放
  → SMTC 优先，窗口标题回退
  → 解析歌名/歌手
  → Subsonic search3（必要时 search2）
  → 加权文本匹配
  → True 在库 / False 不在库 / None 未知
  → 播放记录 + 待补清单 + 可选通知
```

线程规则：

- 网络查询与批量核验不得阻塞 Tauri 事件循环；
- SMTC 的 WinRT 对象只在自己的线程读取；
- 共享状态必须明确写线程、读线程与锁；
- 退出时停止监控、保存窗口状态并完成日志收尾。

## 5. 已完成内容

### 5.1 版本里程碑

| 版本 | 日期 | 主要内容 |
|------|------|----------|
| 1.0.0 | 2026-10-20 | 窗口标题检测、三态查询、待补清单、播放记录、设置、提醒、托盘 |
| 1.1.0 | 2026-10-21 | SMTC 主检测、窗口回退、双播放器并行、通知队列 |
| 1.2.0 | 2026-10-30 | 目录版、版本资源、asInvoker 清单、禁用 UPX、误报文档 |
| 2.0.0 | 2026-11-04 | Rust + Tauri 2 + Svelte 5 重写、便携 WebView2 数据、多选、CI/Release 切换 |
| 2.0.1 | 2026-11-04 | 修复 custom-protocol、补全 Windows 版本资源、新图标、依赖与测试稳定性 |
| 2.0.2 | 2026-11-05 | 修复启动 state 竞态、DPI 窗口恢复、底栏与设置弹窗布局 |

### 5.2 当前功能清单

- SMTC 与窗口标题混合检测，约 2 秒轮询；
- QQ 音乐、网易云音乐同时播放时分别维护状态；
- 三态曲库查询，未知状态不污染待补清单；
- 待补清单跨播放器去重、持久化、搜索、排序、多选、忽略、恢复、删除；
- 批量核验选中/全部 pending，已入库自动移出；单曲核验有通知反馈；
- 播放记录内存保存、筛选、搜索、复制、CSV 导出、清空；
- 提醒模式与同曲冷却；
- 通知窗队列、点击复制、6 秒自动关闭、首条恢复；
- 系统托盘、最小化隐藏、开始/停止监控、待补数量；
- 窗口状态记忆、DPI/缩放适配、单实例、滚动日志、配置损坏备份；
- 便携目录 ZIP、SHA256、`--smoke-test`、Windows CI/Release 工作流。

### 5.3 质量基线

- Rust `cargo fmt --check`；
- `cargo clippy --workspace --all-targets -- -D warnings`；
- `cargo test --workspace`：133 项离线测试；
- `pnpm check`：0 errors / 0 warnings；
- `pnpm build`：前端产物嵌入 EXE；
- Windows MSVC Release 构建 + 便携包冒烟测试。

## 6. 未完成方案与已知限制

| # | 事项 | 当前状态 | 影响 | 完成标准 |
|---|------|----------|------|----------|
| 1 | 真实 Windows 全项验收 | 启动已通过，其余未完成 | 播放器/托盘/通知兼容性仍需逐项确认 | 按 DEVELOPMENT 第 12 节逐项通过 |
| 2 | 播放历史持久化 | 未开始 | 重启后记录丢失 | JSON/SQLite 保存与恢复 |
| 3 | 异步曲库查询 | 未开始 | 慢服务器可能拖慢轮询 | 查询队列/线程池 |
| 4 | 手动纠正匹配 | 未开始 | 误判无法修正 | 右键标记在库/不在库 |
| 5 | 密码安全存储 | 未开始 | config.ini 明文 | DPAPI / Credential Manager |
| 6 | 代码签名 | 未开始 | SmartScreen/杀软误报 | 接入签名并校验 |
| 7 | 跨平台检测 | 未开始 | macOS/Linux 只能跑核心逻辑 | 抽象检测器接口 |
| 8 | 国际化 | 未开始 | 仅中文 | 文案表与语言选择 |
| 9 | UI 自动化测试 | 未开始 | 重构风险 | Playwright/WebDriver 覆盖关键流程 |
| 10 | 历史/通知内存上限 | 未开始 | 长时间运行增长 | 上限、分页或清理策略 |

## 7. 路线图与优先级

### P0：发布闭环

1. v2.0.2 Windows CI 与 Release 已通过；
2. 在 Windows 10/11 上完成剩余实机验收清单（启动与打包冒烟已通过）；
3. 核对 EXE 版本资源、SHA256、托盘/通知/播放器检测；
4. 记录已知兼容性问题后再扩大宣传。

### P1：稳定性与用户价值

1. **播放历史持久化**：启动恢复最近记录，支持清理与迁移；
2. **异步曲库查询**：查询不阻塞监控线程；
3. **手动纠正匹配**：写回缓存并记录来源；
4. **数据上限**：历史、通知去重表、日志轮转策略可配置。

### P2：安全与分发

1. Windows Credential Manager / DPAPI；
2. SignPath 或商业代码签名；
3. 更新检查与下载校验（不自动静默更新）；
4. 完善误报申诉材料。

### P3：扩展能力

1. 跨平台检测接口与 macOS 实现；
2. 国际化；
3. 匹配灵敏度高级设置；
4. 可观测性面板（候选分数、耗时、SMTC 状态）。

## 8. 维护与发布检查清单

### 8.1 日常开发

```bash
cd rust
pnpm install --frozen-lockfile
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
pnpm check
pnpm build
```

涉及界面时重新生成 `docs/previews/` 截图；涉及 Rust 命令/字段时同步更新
`DEVELOPMENT.md` 与 `src/lib/types.ts`。

### 8.2 发布新版本

1. 更新版本号：
   - `rust/Cargo.toml` 的 `workspace.package.version`
   - `rust/src-tauri/tauri.conf.json`
   - `rust/package.json`
   - `rust/crates/melodygap-core/src/constants.rs` 的 `APP_VERSION`
2. 更新 `CHANGELOG.md`、README 状态与本文档；
3. 运行 8.1 的全部检查；
4. 提交并推送 `main`；
5. 创建并推送同名标签 `vX.Y.Z`；
6. 等待 CI/Release 成功；
7. 核对 Release 资产、SHA256、`--smoke-test` 结果；
8. 记录 Release 链接、运行 ID 与已知问题。

### 8.3 交接检查

- 能说明主窗口、监控线程、SMTC 线程、通知计时线程、核验任务职责；
- 能定位配置、日志、待补清单、WebView2 数据与导出文件；
- 能解释三态语义和“未知不污染待补清单”；
- 能复现一次完整发布并核对产物；
- 知道未完成项与不做的边界，不把待补清单当成自动入库。

## 9. 关键决策与约束

| 决策 | 原因 | 代价/后续 |
|------|------|-----------|
| Rust + Tauri 2 | 体积小、启动快、无 PyInstaller 自解压 | 需要 WebView2 Runtime |
| Svelte 5 + TypeScript | 轻量、类型清晰、构建简单 | 需要 Node/pnpm |
| 仅 Windows | SMTC/Win32 检测依赖系统 API | 跨平台需抽象检测器 |
| 目录版便携 ZIP | 避免安装器与自解压误报 | 用户需解压到可写目录 |
| JSON 存待补清单 | 文件小、易排查 | 大量数据时需迁移 |
| 播放历史仅内存 | 降低首版复杂度 | 重启丢失，P1 处理 |
| 不做自动入库 | 版权与安全边界 | 用户需人工补歌与核验 |
| 中文文档优先 | 目标用户与维护者 | 国际化留到 P3 |

## 10. 相关文档

- [DEVELOPMENT.md](DEVELOPMENT.md)：架构、线程、检测、算法、命令、测试、打包；
- [FALSE_POSITIVES.md](FALSE_POSITIVES.md)：误报原因、SHA256/版本核验、申诉模板；
- [../README.md](../README.md)：安装、配置、使用、FAQ；
- [../CHANGELOG.md](../CHANGELOG.md)：版本变更历史；
- [../SECURITY.md](../SECURITY.md)：凭据、漏洞报告与安全边界；
- [../CONTRIBUTING.md](../CONTRIBUTING.md)：开发环境、代码约定与 PR 要求。
