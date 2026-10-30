# -*- coding: utf-8 -*-
"""构建 Windows 发布产物（单文件 + 便携目录版）。

用法::

    python scripts/build_release.py
    python scripts/build_release.py --skip-tests

产物写入 ``dist/``：

* ``MelodyGap.exe``：单文件版；
* ``MelodyGap-windows-x64.zip``：单文件版 + 配置示例 + 文档；
* ``MelodyGap-portable-windows-x64.zip``：目录版（推荐，误报更少）；
* ``SHA256SUMS.txt`` / ``MelodyGap.exe.sha256``：校验值。

脚本不依赖 PowerShell，Windows 与 Wine 下的 Windows Python 均可运行。
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "scripts" / "MelodyGap.spec"
DIST = ROOT / "dist"
WORK = ROOT / "build" / "pyinstaller"
STAGE = ROOT / "build" / "release-stage"
DOC_FILES = (
    ("config.ini.example", "config.ini.example"),
    ("README.md", "README.md"),
    ("LICENSE", "LICENSE"),
    ("docs/FALSE_POSITIVES.md", "docs/FALSE_POSITIVES.md"),
)


def _load_version() -> str:
    """从 app.constants 读取版本号，保持单一来源。"""
    sys.path.insert(0, str(ROOT))
    try:
        from app.constants import APP_VERSION as version
    finally:
        sys.path.pop(0)
    return version


APP_VERSION = _load_version()


def run(command: list, env: dict = None) -> None:
    """运行子命令，失败时抛出异常。"""
    print("+", " ".join(str(item) for item in command), flush=True)
    subprocess.run(command, cwd=str(ROOT), env=env, check=True)


def sha256(path: Path) -> str:
    """计算文件 SHA256（小写）。"""
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _zip_add(zip_file: zipfile.ZipFile, source: Path, arcname: str) -> None:
    """把文件加入 ZIP，使用固定的 UTF-8 文件名。"""
    zip_file.write(source, arcname)


def make_onefile_zip(exe: Path, target: Path) -> None:
    """打包单文件版与说明文件。"""
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zip_file:
        _zip_add(zip_file, exe, "MelodyGap.exe")
        for relative, arcname in DOC_FILES:
            _zip_add(zip_file, ROOT / relative, arcname)


def make_portable_zip(portable_dir: Path, target: Path) -> None:
    """打包目录版；所有文件位于 ``MelodyGap/`` 内。"""
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for path in sorted(portable_dir.rglob("*")):
            if path.is_file():
                relative = path.relative_to(portable_dir)
                _zip_add(zip_file, path, "MelodyGap/" + relative.as_posix())
        for relative, arcname in DOC_FILES:
            _zip_add(zip_file, ROOT / relative, "MelodyGap/" + arcname)


def build(mode: str, dist_dir: Path) -> None:
    """调用 PyInstaller 构建指定模式。"""
    env = os.environ.copy()
    env["MELODYGAP_MODE"] = mode
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--workpath",
            str(WORK / mode),
            "--distpath",
            str(dist_dir),
            str(SPEC),
        ],
        env=env,
    )


def verify_executable(exe: Path) -> None:
    """确认版本资源和清单确实写入了 EXE。"""
    data = exe.read_bytes()
    checks = {
        "ProductName": "MelodyGap".encode("utf-16-le"),
        "ProductVersion": APP_VERSION.encode("utf-16-le"),
        "asInvoker": b"asInvoker",
    }
    missing = [name for name, marker in checks.items() if marker not in data]
    if missing:
        raise SystemExit("构建产物缺少元信息: %s" % ", ".join(missing))
    print("元信息校验通过: %s" % exe.name)


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 MelodyGap Windows 发布包")
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="跳过单元测试（CI 已单独运行测试时使用）",
    )
    parser.add_argument(
        "--only",
        choices=("onefile", "onedir"),
        help="只构建一种模式，默认两种都构建",
    )
    args = parser.parse_args()

    if not args.skip_tests:
        run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])

    for path in (DIST, WORK, STAGE):
        shutil.rmtree(path, ignore_errors=True)
    DIST.mkdir(parents=True, exist_ok=True)

    modes = [args.only] if args.only else ["onefile", "onedir"]
    built = {}
    for mode in modes:
        dist_dir = WORK / "out" / mode
        build(mode, dist_dir)
        built[mode] = dist_dir

    artifacts = []

    if "onefile" in built:
        source_exe = built["onefile"] / "MelodyGap.exe"
        verify_executable(source_exe)
        final_exe = DIST / "MelodyGap.exe"
        shutil.copy2(source_exe, final_exe)
        onefile_zip = DIST / "MelodyGap-windows-x64.zip"
        make_onefile_zip(final_exe, onefile_zip)
        artifacts.extend([final_exe, onefile_zip])

    if "onedir" in built:
        source_dir = built["onedir"] / "MelodyGap"
        source_exe = source_dir / "MelodyGap.exe"
        verify_executable(source_exe)
        portable_stage = STAGE / "MelodyGap"
        shutil.copytree(source_dir, portable_stage)
        portable_zip = DIST / "MelodyGap-portable-windows-x64.zip"
        make_portable_zip(portable_stage, portable_zip)
        artifacts.append(portable_zip)

    lines = ["%s  %s" % (sha256(path), path.name) for path in artifacts]
    (DIST / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="ascii")
    if (DIST / "MelodyGap.exe").exists():
        (DIST / "MelodyGap.exe.sha256").write_text(
            "%s  MelodyGap.exe\n" % sha256(DIST / "MelodyGap.exe"),
            encoding="ascii",
        )

    print("\n构建完成：")
    for path in sorted(DIST.iterdir()):
        print("  %-40s %8.1f MB" % (path.name, path.stat().st_size / 1024 / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
