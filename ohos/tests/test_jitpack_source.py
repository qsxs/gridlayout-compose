"""只执行安装脚本的来源检查前缀；git 由 stub 替代，不下载或启动 producer。"""
import os
from pathlib import Path
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parents[1]
BASH = sys.argv.pop(1) if len(sys.argv) > 1 else "bash"
INSTALL = (HERE / "jitpack-install.sh").read_text(encoding="utf-8")
assert "# 在下载大归档之前" in INSTALL
INSTALL_PREFIX = INSTALL.split("# 在下载大归档之前", 1)[0]
assert "bootstrap-native.py" not in INSTALL_PREFIX and "python3 -B" not in INSTALL_PREFIX
HEAD = "1234567890abcdef1234567890abcdef12345678"
STUB = """git() {
    if [[ "$#" == 4 && "$3" == rev-parse && "$4" == HEAD ]]; then
        printf '%s\n' "$TEST_CHECKOUT_COMMIT"
    else
        printf '%s\n' 'Unexpected Git call; tag refs are unavailable' >&2
        return 99
    fi
}
"""


class JitPackSourceTest(unittest.TestCase):
    def check_source(self, version, commit=HEAD):
        env = os.environ.copy()
        env.update(JAVA_HOME="test-jdk", GROUP="com.github.qsxs", ARTIFACT="gridlayout-compose",
                   VERSION=version, TEST_CHECKOUT_COMMIT=HEAD)
        if commit is None:
            env.pop("GIT_COMMIT", None)
        else:
            env["GIT_COMMIT"] = commit
        return subprocess.run([BASH, "-s"], input=STUB + INSTALL_PREFIX + "printf '%s\n' SOURCE_CHECK_PASSED\n",
                              cwd=HERE, env=env, text=True, capture_output=True)

    def test_tag_checkout_without_local_tag_refs_is_accepted(self):
        result = self.check_source("v2.8.0-cpf11")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SOURCE_CHECK_PASSED", result.stdout)

    def test_matching_commit_versions_are_accepted(self):
        for version in (HEAD, HEAD[:10]):
            with self.subTest(version=version):
                result = self.check_source(version)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_service_commit_mismatch_is_rejected(self):
        result = self.check_source("v2.8.0-cpf11", "f" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GIT_COMMIT does not identify", result.stderr)

    def test_missing_service_commit_is_rejected(self):
        result = self.check_source("v2.8.0-cpf11", None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GIT_COMMIT is required", result.stderr)

    def test_mismatched_commit_version_is_rejected(self):
        result = self.check_source("f" * 10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("commit VERSION does not identify", result.stderr)

    def test_snapshot_is_rejected(self):
        result = self.check_source("main-SNAPSHOT")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("without SNAPSHOT", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
