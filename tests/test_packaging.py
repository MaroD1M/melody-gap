# -*- coding: utf-8 -*-
"""打包配置回归测试。

这些测试不依赖 Windows，只检查版本资源生成逻辑、清单与发布脚本是否
仍然满足“可核验、低误报”的约束。
"""

import sys
import unittest
from pathlib import Path

from app.constants import APP_VERSION
from scripts.win_version import build_version_info, version_tuple

ROOT = Path(__file__).resolve().parent.parent


class VersionTupleTests(unittest.TestCase):
    def test_three_part_version_is_padded(self):
        self.assertEqual(version_tuple("1.2.0"), (1, 2, 0, 0))

    def test_version_with_suffix_uses_numbers(self):
        self.assertEqual(version_tuple("1.2.3-rc4"), (1, 2, 3, 4))

    def test_short_version_is_padded(self):
        self.assertEqual(version_tuple("2"), (2, 0, 0, 0))


@unittest.skipUnless(sys.platform == "win32", "版本资源结构仅在 Windows 可导入")
class WindowsVersionInfoTests(unittest.TestCase):
    def test_resource_contains_identity_and_version(self):
        info = build_version_info(APP_VERSION, "MelodyGap 曲库补漏")
        text = str(info)
        for value in ("MaroD1M", "MelodyGap", "MelodyGap.exe", APP_VERSION):
            self.assertIn(value, text)


class PackagingFilesTests(unittest.TestCase):
    def test_manifest_requests_as_invoker_and_version_matches(self):
        manifest = (ROOT / "scripts" / "MelodyGap.manifest").read_text(encoding="utf-8")
        self.assertIn('level="asInvoker"', manifest)
        self.assertIn('version="%s.0"' % APP_VERSION, manifest)
        self.assertIn("dpiAware", manifest)
        self.assertIn("longPathAware", manifest)

    def test_spec_embeds_metadata_and_disables_upx(self):
        spec = (ROOT / "scripts" / "MelodyGap.spec").read_text(encoding="utf-8")
        self.assertIn("build_version_info", spec)
        self.assertIn("manifest=MANIFEST_PATH", spec)
        self.assertIn("upx=False", spec)
        self.assertIn('collect_submodules("winrt")', spec)
        self.assertIn('collect_dynamic_libs("winrt")', spec)

    def test_release_builds_both_modes(self):
        script = (ROOT / "scripts" / "build_release.py").read_text(encoding="utf-8")
        self.assertIn('["onefile", "onedir"]', script)
        self.assertIn("MelodyGap-portable-windows-x64.zip", script)
        self.assertIn("SHA256SUMS.txt", script)

    def test_release_workflow_uses_build_script_and_hashes(self):
        workflow = (
            ROOT / ".github" / "workflows" / "release.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("scripts/build_release.py", workflow)
        self.assertIn("MelodyGap-portable-windows-x64.zip", workflow)
        self.assertIn("SHA256SUMS.txt", workflow)
        self.assertNotIn("pyinstaller --onefile", workflow.lower())

    def test_version_is_semver_like(self):
        self.assertRegex(APP_VERSION, r"^\d+\.\d+\.\d+$")
        parts = [int(part) for part in APP_VERSION.split(".")]
        self.assertGreaterEqual(parts[0], 1)


if __name__ == "__main__":
    unittest.main()
