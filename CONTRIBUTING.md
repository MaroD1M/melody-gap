# Contributing

感谢你愿意改进 MelodyGap。提交前请确认变更不包含真实账号、服务器地址、密码、
日志或其他个人数据。

## 开发环境

```bash
git clone https://github.com/MaroD1M/melody-gap.git
cd melody-gap
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

## 提交前检查

```bash
python -m unittest discover -s tests -v
ruff check .
python -m compileall -q app main.py
```

新增行为请补充离线测试；修复 Bug 时优先先写能复现问题的测试。测试不得依赖
真实播放器、真实 Subsonic 服务器或网络。

## 代码约定

- 兼容 Python 3.9，使用 `typing.Optional/List/Dict`，不使用 `str | None`。
- 业务逻辑放在 `app/services`，Tk 控件操作只在主线程执行。
- 不在日志中输出密码、token 或完整认证 URL。
- 配置默认值必须是占位内容，不得提交任何真实凭据。
- UI 颜色与 ttk 样式集中在 `app/ui/theme.py`。

## Pull Request

- 描述变更目的、用户可见影响与测试方式；
- 一次 PR 尽量只解决一个问题；
- 不提交 `config.ini`、`melodygap.log`、`missing_songs.json`、`dist/` 或临时文件；
- 如果变更涉及界面，请附截图。

## 安全问题

请不要在公开 Issue 中披露凭据或可利用细节，按 [SECURITY.md](SECURITY.md) 私下报告。
