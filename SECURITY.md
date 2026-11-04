# Security Policy

## 支持范围

安全修复会优先进入最新 Release。请尽量在最新版本上复现问题。

## 报告安全问题

请通过 GitHub 仓库的 **Security → Advisories → Report a vulnerability** 私下报告，
不要创建公开 Issue。

报告中请说明：

- 受影响版本与操作系统；
- 复现步骤与影响；
- 是否涉及凭据、日志或本地文件；
- 你希望的修复方式（可选）。

请勿在报告中附带真实服务器地址、用户名、密码或完整认证 URL。必要时请先脱敏。

## 凭据与数据

- MelodyGap 将 Subsonic / Navidrome 密码以明文保存在本地 `config.ini`；
- `config.ini`、日志、待补清单和 WebView2 数据默认被 `.gitignore` 忽略；
- 日志不应记录密码或认证 token；
- 不要把 `config.ini`、日志或导出的清单提交到公开仓库；
- 建议使用仅能访问音乐库的独立账号，并限制服务器暴露范围。

## 构建与发布

- 发布包由 GitHub Actions 从公开源码构建，工作流为
  `.github/workflows/release.yml`；
- 桌面端使用 Rust + Tauri 2；Windows MSVC 构建静态链接 WebView2 Loader，
  GNU 交叉构建则随便携包分发 `WebView2Loader.dll`；
- 每个 Release 提供 `SHA256SUMS.txt`，下载后可自行核对；
- 当前发布版本未使用商业代码签名证书，安全软件可能误报；处理方式见
  [docs/FALSE_POSITIVES.md](docs/FALSE_POSITIVES.md)。
- `cargo audit` 当前无已知漏洞；仅有 Linux 端传递依赖（glib/zbus 等）的
  unmaintained/unsound 警告，Windows 发布包不包含这些依赖。
- `pnpm audit` 当前剩 1 条低危构建期告警（`deepmerge` 原型污染，上游暂无修复版本），
  仅经 `vite-plugin-svelte` 在开发/构建阶段使用，不进入发布 EXE；将持续跟踪上游。

## 非安全范围

- 播放器窗口标题解析错误；
- 曲库匹配误判；
- 未签名的开源构建被个别安全软件误报（可按误报流程反馈）；
- 需要物理访问用户机器才能利用的问题；
- 第三方播放器、Subsonic 服务端、WebView2 Runtime 或网络环境自身的漏洞。
