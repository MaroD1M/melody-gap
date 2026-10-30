# 误报处理与文件核验

MelodyGap 是一个未签名的 Python 桌面工具。Windows Defender、SmartScreen 或
部分第三方杀毒软件可能把 **PyInstaller 打包的未签名 EXE** 误判为可疑文件。
这不代表程序包含恶意代码，但仅靠项目侧无法保证所有安全软件都不误报。

本文说明项目已经采取的零成本措施、如何自行核验下载文件，以及如何向厂商
提交误报。**请勿为了运行程序而直接关闭杀毒软件或添加全局排除项。**

## 为什么会误报

- **没有商业代码签名证书**：未知发布者的 EXE 天然缺少信誉；
- **单文件自解压**：`--onefile` 启动时会把依赖解压到临时目录，这个行为与部分
  恶意程序相似，是 PyInstaller 单文件版最常见的误报来源；
- **低流行度**：安全厂商的云端信誉需要下载量和时间积累；
- **行为敏感**：程序会枚举窗口标题、读取系统媒体会话、访问用户填写的服务器，
  这些 API 本身也是正常软件常用功能，但可能触发启发式规则。

## 已经采取的零成本措施

从 v1.2.0 起，发布构建包含以下改动：

1. **优先提供目录版（portable）**：`MelodyGap-portable-windows-x64.zip` 不会在
   运行时自解压，误报概率低于单文件版；
2. **写入完整 Windows 版本资源**：公司、产品名、文件说明、版本号、版权、
   `OriginalFilename` 等字段齐全；
3. **嵌入应用程序清单**：`asInvoker`（不请求管理员权限）、DPI 感知、
   受支持的 Windows 版本、Common Controls v6、长路径支持；
4. **禁用 UPX**：压缩壳会显著增加误报，构建时显式 `upx=False`；
5. **固定构建入口**：`scripts/MelodyGap.spec` 与 `scripts/build_release.py`
   保证本地与 CI 产物一致；
6. **发布 SHA256 校验值**：`SHA256SUMS.txt` 与 `MelodyGap.exe.sha256`；
7. **构建后自检**：确认版本资源与 `asInvoker` 清单确实写入 EXE；
8. **开源可审计**：全部源码、测试和构建脚本都在仓库中。

这些措施能减少误报，但**不能替代代码签名**，也不能保证所有厂商立即放行。

## 下载后如何核验

### 1. 校验 SHA256

在下载目录打开 PowerShell：

```powershell
Get-FileHash .\MelodyGap.exe -Algorithm SHA256
Get-Content .\MelodyGap.exe.sha256
```

两者应完全一致（忽略大小写）。ZIP 包可对照 `SHA256SUMS.txt`。

### 2. 查看版本信息

```powershell
(Get-Item .\MelodyGap.exe).VersionInfo | Format-List *
```

应能看到：

```text
CompanyName      : MaroD1M
FileDescription  : MelodyGap 曲库补漏
ProductName      : MelodyGap
ProductVersion    : 1.2.0
OriginalFilename : MelodyGap.exe
```

如果版本信息为空或与 Release 页面版本不符，请不要运行。

### 3. 查看数字签名（当前版本未签名）

```powershell
Get-AuthenticodeSignature .\MelodyGap.exe
```

当前发布版本为 `NotSigned`。这是预期结果；项目没有购买商业证书。若未来接入
免费开源签名服务，这里会显示签名者信息。

### 4. 可选：多引擎扫描

可以把文件上传到 [VirusTotal](https://www.virustotal.com/) 查看多引擎结果。
注意：上传即表示你同意 VirusTotal 的样本共享政策，**不要上传包含个人配置的
ZIP 或日志**，只上传官方 `MelodyGap.exe`。

## 向微软提交误报（免费）

如果 Windows Defender 拦截了官方 Release：

1. 打开 <https://www.microsoft.com/en-us/wdsi/filesubmission>；
2. 选择 **Home customer** → **Submit a file for malware analysis**；
3. 上传 `MelodyGap.exe`，类型选择 **Incorrectly detected as malware/other**；
4. 在说明中写明这是开源程序，并附上 GitHub Release 链接和 SHA256。

可直接使用下面的模板：

```text
This file is a false positive.

Product: MelodyGap - an open-source Windows utility that checks whether the song
currently playing in QQ Music / NetEase Cloud Music exists in the user's own
Subsonic/Navidrome music library.

Source code: https://github.com/MaroD1M/melody-gap
Release: https://github.com/MaroD1M/melody-gap/releases
SHA256: <paste SHA256SUMS.txt value>

The executable is built with PyInstaller on GitHub Actions from the public
source. It does not download music, inject into other processes, or modify the
player. It only reads window titles / Windows SMTC metadata and calls the
Subsonic API configured by the user. No telemetry.

Please review and remove the detection.
```

提交后微软通常会回复分析结果；处理时间从数小时到数天不等。

## 向其他厂商提交

多数厂商提供免费误报提交入口，搜索“厂商名 + false positive submit”即可。
提交时同样附上源码、Release、SHA256 和用途说明。常见入口：

- Microsoft Defender：<https://www.microsoft.com/en-us/wdsi/filesubmission>
- 360 / 火绒 / 腾讯电脑管家：各自官网的“误报反馈”或“申诉”页面；
- Kaspersky、Bitdefender、Avast 等：官方 false positive 表单。

## 长期方案：免费开源代码签名

商业代码签名证书（OV/EV）需要持续费用，不符合“零成本”要求。可以考虑：

- **SignPath Foundation**：为符合条件的开源项目提供免费代码签名；
- 其他开源签名计划：通常要求项目公开、构建可复现、许可证合规。

申请通过后，在 GitHub Actions 中接入签名步骤即可显著改善 SmartScreen 和
杀毒软件信誉。该项目当前未接入，属于后续可选项。

## 用户侧建议

- 优先下载 `MelodyGap-portable-windows-x64.zip`；
- 只从 GitHub Releases 下载，不要使用网盘转载；
- 运行前核对 SHA256 与版本信息；
- 遇到拦截时先提交误报，而不是关闭杀毒软件；
- 如确实需要临时运行，可在确认哈希与来源后，仅对**单个文件**添加排除，
  完成后立即移除。
