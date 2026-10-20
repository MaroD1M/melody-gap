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
- `config.ini`、日志和待补清单默认被 `.gitignore` 忽略；
- 日志不应记录密码或认证 token；
- 不要把 `config.ini`、日志或导出的清单提交到公开仓库；
- 建议使用仅能访问音乐库的独立账号，并限制服务器暴露范围。

## 非安全范围

- 播放器窗口标题解析错误；
- 曲库匹配误判；
- 需要物理访问用户机器才能利用的问题；
- 第三方播放器、Subsonic 服务端或网络环境自身的漏洞。
