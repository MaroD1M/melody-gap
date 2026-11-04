# Contributing

感谢你愿意改进 MelodyGap。提交前请确认变更不包含真实账号、服务器地址、密码、
日志或其他个人数据。

## 开发环境

需要 Windows 10/11、Rust stable（MSVC toolchain）、Node.js 24+、pnpm 12+ 与
Microsoft Edge WebView2 Runtime。

```bash
git clone https://github.com/MaroD1M/melody-gap.git
cd melody-gap/rust
pnpm install --frozen-lockfile
pnpm desktop:dev
```

只调试前端界面时可以运行 `pnpm dev`；播放器检测、托盘、通知和单实例行为必须在
Windows 上通过 `pnpm desktop:dev` 或打包后的 EXE 验证。

## 提交前检查

```bash
cd rust
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
pnpm check
pnpm build
```

新增行为请补充离线测试；修复 Bug 时优先先写能复现问题的测试。测试不得依赖
真实播放器、真实 Subsonic 服务器或网络。

Windows Release 打包后建议执行：

```powershell
.\release\MelodyGap\MelodyGap.exe --smoke-test
```

## 代码约定

- Rust 使用 `edition 2021`，公共数据结构通过 `serde` 点对点传递；
- 业务逻辑放在 `crates/melodygap-core`，平台相关代码放在 `src-tauri/src/platform`；
- 网络请求、磁盘写入和播放器枚举不得阻塞 UI 线程；
- 不在日志中输出密码、token 或完整认证 URL；
- 配置默认值必须是占位内容，不得提交任何真实凭据；
- 前端使用 Svelte 5 runes 与 TypeScript，新增状态优先放进现有组件，避免无必要全局状态；
- 所有用户可见文案使用中文，错误信息应能直接展示。

## Pull Request

- 描述变更目的、用户可见影响与测试方式；
- 一次 PR 尽量只解决一个问题；
- 不提交 `config.ini`、`melodygap.log`、`missing_songs.json`、`dist/`、`target/`、
  `node_modules/`、`release/` 或临时文件；
- 如果变更涉及界面，请附截图，并尽量同时更新 `docs/previews/`；
- 发布相关变更需同步更新版本号、`CHANGELOG.md` 与文档。

## 安全问题

请不要在公开 Issue 中披露凭据或可利用细节，按 [SECURITY.md](SECURITY.md) 私下报告。
