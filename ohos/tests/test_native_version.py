"""Native 版本门禁轻量检查；夹具保留在本仓 .local，不运行 Gradle。"""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("grid_port_native_version", HERE / "GridPort.py")
grid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grid)
grid.physical = Path
grid.load = lambda path: json.loads(Path(path).read_text(encoding="utf-8-sig"))
EXPECTED = grid.load(HERE / "port-config.json")["kotlin"]


class NativeVersionTest(unittest.TestCase):
    def setUp(self):
        local = HERE / ".local"
        local.mkdir(exist_ok=True)
        self.home = Path(tempfile.mkdtemp(prefix="native-version-check-", dir=local))
        self.properties = self.home / "konan/konan.properties"
        self.properties.parent.mkdir()

    def write_properties(self, text):
        self.properties.write_text(text, encoding="utf-8", newline="\n")

    def test_matching_version_is_accepted(self):
        self.write_properties("# 兼容 properties 中等号两边的空白\ncompilerVersion = " + EXPECTED + "\n")
        grid.verify_native_home(self.home, EXPECTED)

    def test_other_native_versions_are_rejected(self):
        for actual in ("2.4.20-0.1.0-07", "2.4.20-0.1.0-09", "2.4.20"):
            with self.subTest(actual=actual):
                self.write_properties("compilerVersion=" + actual + "\n")
                with self.assertRaisesRegex(RuntimeError, "compilerVersion mismatch") as caught:
                    grid.verify_native_home(self.home, EXPECTED)
                self.assertIn("expected " + EXPECTED, str(caught.exception))
                self.assertIn("got " + actual, str(caught.exception))

    def test_missing_or_empty_version_is_rejected(self):
        for content in ("targetSysRoot.ohos_x64=fixture\n", "compilerVersion=   \n"):
            with self.subTest(content=content):
                self.write_properties(content)
                with self.assertRaisesRegex(RuntimeError, "compilerVersion is missing") as caught:
                    grid.verify_native_home(self.home, EXPECTED)
                self.assertIn(EXPECTED, str(caught.exception))

    def test_missing_properties_file_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "properties file is missing"):
            grid.verify_native_home(self.home, EXPECTED)

    def test_missing_native_home_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Set --native-home or CPF_NATIVE_HOME"):
            grid.verify_native_home(None, EXPECTED)

    def test_wrong_version_stops_cli_before_gradle_invocation(self):
        self.write_properties("compilerVersion=2.4.20-0.1.0-09\n")
        with patch.object(grid, "cache_paths", return_value={"nativeHome": str(self.home)}), \
                patch.object(grid, "java_executable", return_value=self.home / "java"), \
                patch.object(grid.subprocess, "run") as launch:
            with self.assertRaisesRegex(RuntimeError, "compilerVersion mismatch"):
                grid.run_gradle({"work": str(self.home)}, "Tasks", 1, False)
            launch.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
