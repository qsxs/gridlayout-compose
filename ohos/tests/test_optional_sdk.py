"""仅检查可选 SDK 的环境接线；拦截子进程，不运行 Gradle。"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("grid_port_optional_sdk", HERE / "GridPort.py")
grid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grid)
grid.physical = Path


class LaunchIntercepted(Exception):
    pass


class OptionalSdkTest(unittest.TestCase):
    def setUp(self):
        local = HERE / ".local"
        local.mkdir(exist_ok=True)
        self.work = Path(tempfile.mkdtemp(prefix="optional-sdk-check-", dir=local))
        self.native = self.work / "native"
        properties = self.native / "konan/konan.properties"
        properties.parent.mkdir(parents=True)
        config = json.loads((HERE / "port-config.json").read_text(encoding="utf-8"))
        properties.write_text("compilerVersion=" + config["kotlin"] + "\n", encoding="utf-8", newline="\n")
        self.cache = {"nativeHome": str(self.native), **{key: str(self.work / key) for key in
                     ("projectCache", "kotlinCache", "GRADLE_USER_HOME", "KONAN_DATA_DIR", "TEMP", "TMP")}}
        self.value = {"work": str(self.work), "fingerprint": "0" * 64, "group": "example.grid",
                      "versions": {"grid": "fixed-commit"}, "repository": str(self.work / "maven")}
        self.environment = None
        grid.OPTIONS = SimpleNamespace(ohos_sdk=None, gradle_distribution=None)

    def load(self, path):
        if Path(path).name == "tooling-lock.json":
            return {"revision": "1" * 40}
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def intercept(self, argv, **kwargs):
        self.environment = kwargs["env"]
        raise LaunchIntercepted("No child process is started")

    def invoke(self):
        with patch.object(grid, "load", side_effect=self.load, create=True), \
                patch.object(grid, "cache_paths", return_value=self.cache), \
                patch.object(grid, "java_executable", return_value=self.work / "jdk/bin/java"), \
                patch.object(grid.subprocess, "run", side_effect=self.intercept):
            grid.run_gradle(self.value, "Tasks", 1, False)

    def test_no_sdk_required_for_standard_native_dependencies(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LaunchIntercepted):
                self.invoke()
        self.assertNotIn("OHOS_SDK_HOME", self.environment)
        self.assertEqual(self.environment["KONAN_DATA_DIR"], self.cache["KONAN_DATA_DIR"])

    def test_explicit_sdk_is_forwarded(self):
        sdk = self.work / "external-sdk"
        sdk.mkdir()
        grid.OPTIONS.ohos_sdk = str(sdk)
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LaunchIntercepted):
                self.invoke()
        self.assertEqual(self.environment["OHOS_SDK_HOME"], str(sdk.resolve()))

    def test_missing_explicit_sdk_is_rejected(self):
        grid.OPTIONS.ohos_sdk = str(self.work / "missing-sdk")
        with self.assertRaisesRegex(RuntimeError, "Configured OHOS SDK directory does not exist"):
            self.invoke()
        self.assertIsNone(self.environment)


if __name__ == "__main__":
    unittest.main(verbosity=2)
