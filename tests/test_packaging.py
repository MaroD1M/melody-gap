# -*- coding: utf-8 -*-
"""Rust/Tauri 发布配置回归测试。

这些测试不依赖 Windows 或真实构建，只检查版本号、Tauri 便携目录配置
以及 CI/Release 工作流是否仍然满足 v2 的发布约束。
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUST = ROOT / "rust"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class RustVersionTests(unittest.TestCase):
    def test_workspace_and_app_versions_match(self):
        cargo = read(RUST / "Cargo.toml")
        workspace = re.search(
            r"\[workspace\.package\](.*?)(?:\n\[|\Z)", cargo, re.S
        )
        self.assertIsNotNone(workspace)
        cargo_version = re.search(
            r'^version = "([^"]+)"', workspace.group(1), re.M
        ).group(1)

        tauri = json.loads(read(RUST / "src-tauri" / "tauri.conf.json"))
        package = json.loads(read(RUST / "package.json"))
        constants = read(
            RUST / "crates" / "melodygap-core" / "src" / "constants.rs"
        )
        app_version = re.search(
            r'APP_VERSION: &str = "([^"]+)"', constants
        ).group(1)

        versions = {
            cargo_version,
            tauri["version"],
            package["version"],
            app_version,
        }
        self.assertEqual(len(versions), 1, versions)
        self.assertRegex(versions.pop(), r"^\d+\.\d+\.\d+$")


class RustPackagingFilesTests(unittest.TestCase):
    def test_tauri_uses_portable_webview_data_directory(self):
        config = json.loads(read(RUST / "src-tauri" / "tauri.conf.json"))
        override = config["app"].get("appDirectoriesOverride", {})
        self.assertEqual(override.get("localData"), "./webview2-data")
        self.assertFalse(config["bundle"]["active"])

    def test_release_workflow_builds_rust_portable_zip_and_hashes(self):
        workflow = read(ROOT / ".github" / "workflows" / "release.yml")
        self.assertIn("--features custom-protocol", workflow)
        self.assertIn("custom-protocol", read(RUST / "src-tauri" / "Cargo.toml"))
        for needle in (
            "cargo build --release",
            "pnpm build",
            "cargo test --workspace",
            "MelodyGap-portable-windows-x64.zip",
            "SHA256SUMS.txt",
            "--smoke-test",
            "/assets/index-",
            "CompanyName",
            "OriginalFilename",
        ):
            self.assertIn(needle, workflow)
        self.assertNotIn("pyinstaller --onefile", workflow.lower())
        self.assertNotIn("setup-python", workflow.lower())

    def test_ci_runs_rust_quality_checks(self):
        workflow = read(ROOT / ".github" / "workflows" / "ci.yml")
        for needle in (
            "cargo fmt --all -- --check",
            "cargo clippy --workspace --all-targets -- -D warnings",
            "cargo test --workspace",
            "pnpm check",
            "pnpm build",
            "/assets/index-",
        ):
            self.assertIn(needle, workflow)
        self.assertNotIn("setup-python", workflow.lower())


if __name__ == "__main__":
    unittest.main()
