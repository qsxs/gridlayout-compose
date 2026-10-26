"""仅用 shell stub 验证宿主选择和失败日志边界；不下载或运行 producer。"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
BASH = sys.argv.pop(1) if len(sys.argv) > 1 else "bash"
INSTALL = (HERE / "jitpack-install.sh").read_text(encoding="utf-8")
assert 'port_work=""\nfor stage in ' in INSTALL
STAGE_LOOP = 'port_work=""\nfor stage in ' + INSTALL.split('port_work=""\nfor stage in ', 1)[1]
assert "bootstrap-native.py" not in STAGE_LOOP and "bootstrap-python.sh" not in STAGE_LOOP

BOOTSTRAP_STUBS = r"""
python3() {
    if [[ "$TEST_SYSTEM_OK" == 1 ]]; then return 0; fi
    unset -f python3
    return 1
}
uname() { if [[ "$1" == -s ]]; then printf Linux; else printf x86_64; fi; }
wc() { printf '%s\n' 35356674; }
curl() {
    printf '%s\n' curl >> "$TEST_EVENTS"
    local output=""
    while [[ "$#" -gt 0 ]]; do
        if [[ "$1" == --output ]]; then output="$2"; break; fi
        shift
    done
    printf fixture > "$output"
}
sha256sum() {
    printf '%s\n' sha256sum >> "$TEST_EVENTS"
    local checksum filename
    read -r checksum filename
    [[ "$checksum" == f829adc9d888e76c8801b4799ed444188d35239fcae3a9808a99ec5cb0d8d92c && "$TEST_BAD_SHA" != 1 ]]
}
tar() {
    printf '%s\n' tar >> "$TEST_EVENTS"
    mkdir -p "$CPF_PYTHON_BOOTSTRAP_ROOT/python/bin"
    printf '#!/bin/sh\nif [ "$1" = --version ]; then printf "Python 3.13.17\\n"; fi\n' > "$CPF_PYTHON_BOOTSTRAP_ROOT/python/bin/python3"
    chmod +x "$CPF_PYTHON_BOOTSTRAP_ROOT/python/bin/python3"
}
"""

STAGE_STUB = r"""
python3() {
    if [[ "$1" == -c ]]; then printf '%s\n' "$TEST_WORK"; return 0; fi
    local requested_stage="$3"
    printf '%s\n' "$requested_stage" >> "$TEST_EVENTS"
    if [[ "$requested_stage" == "$TEST_FAILURE_STAGE" ]]; then return 42; fi
    if [[ "$requested_stage" == Prepare ]]; then
        printf '{"work":"%s"}\n' "$TEST_WORK"
    else
        printf '{"stage":"%s"}\n' "$requested_stage"
    fi
}
port_args=(--test-only)
"""


class JitPackHostTest(unittest.TestCase):
    def setUp(self):
        local = HERE / ".local"
        local.mkdir(exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="host-python-check-", dir=local))
        self.events = self.root / "events.log"
        self.env = os.environ.copy()
        self.env.update(TEST_EVENTS=self.events.as_posix(), TEST_SYSTEM_OK="0", TEST_BAD_SHA="0",
                        CPF_PYTHON_BOOTSTRAP_ROOT=(self.root / "portable").as_posix(),
                        TEST_BOOTSTRAP=(HERE / "bootstrap-python.sh").as_posix(),
                        TEST_WORK=(self.root / "work").as_posix(), TEST_FAILURE_STAGE="", PORT_HOME=HERE.as_posix(),
                        TEST_PYTHON_RELATIVE=(self.root.relative_to(HERE) / "portable").as_posix())

    def shell(self, script):
        return subprocess.run([BASH, "-s"], input='set -euo pipefail\nCPF_PYTHON_BOOTSTRAP_ROOT="$PWD/$TEST_PYTHON_RELATIVE"\n' + script, cwd=HERE,
                              env=self.env, text=True, capture_output=True)

    def recorded(self):
        return self.events.read_text(encoding="utf-8").splitlines() if self.events.exists() else []

    def test_sufficient_system_python_skips_download_and_extraction(self):
        self.env["TEST_SYSTEM_OK"] = "1"
        result = self.shell(BOOTSTRAP_STUBS + '\nsource "$TEST_BOOTSTRAP"\nprintf SYSTEM_SELECTED\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded(), [])
        self.assertIn("SYSTEM_SELECTED", result.stdout)

    def test_old_system_python_selects_isolated_portable_runtime(self):
        result = self.shell(BOOTSTRAP_STUBS + '\nsource "$TEST_BOOTSTRAP"\npython3 --version\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded(), ["curl", "sha256sum", "tar"])
        self.assertIn("Python 3.13.17", result.stdout)
        self.assertTrue((self.root / "portable/bundle.ready").is_file())

    def test_bad_checksum_preserves_archive_and_does_not_extract(self):
        self.env["TEST_BAD_SHA"] = "1"
        result = self.shell(BOOTSTRAP_STUBS + '\nsource "$TEST_BOOTSTRAP"\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.recorded(), ["curl", "sha256sum"])
        self.assertIn("SHA256 mismatch", result.stderr)
        self.assertTrue(any((self.root / "portable").glob("*.tar.gz")))
        self.assertFalse((self.root / "portable/python").exists())

    def test_existing_ready_digest_controls_cached_runtime_reuse(self):
        fixed_sha = "f829adc9d888e76c8801b4799ed444188d35239fcae3a9808a99ec5cb0d8d92c"
        cached_fixture = r"""
source "${TEST_BOOTSTRAP%/*}/bootstrap-python.env"
mkdir -p "$CPF_PYTHON_BOOTSTRAP_ROOT/python/bin"
printf fixture > "$CPF_PYTHON_BOOTSTRAP_ROOT/$CPF_PYTHON_ARCHIVE"
printf '%s\n' "$TEST_READY_SHA" > "$CPF_PYTHON_BOOTSTRAP_ROOT/bundle.ready"
printf '#!/bin/sh\nprintf "runtime\\n" >> "$TEST_EVENTS"\n' > "$CPF_PYTHON_BOOTSTRAP_ROOT/python/bin/python3"
chmod +x "$CPF_PYTHON_BOOTSTRAP_ROOT/python/bin/python3"
"""
        for label, digest, accepted in (("mismatch", "0" * 64, False), ("match", fixed_sha, True)):
            with self.subTest(label=label):
                target = self.root / label
                self.env["TEST_PYTHON_RELATIVE"] = target.relative_to(HERE).as_posix()
                self.env["TEST_READY_SHA"] = digest
                recorded_before = len(self.recorded())
                result = self.shell(BOOTSTRAP_STUBS + cached_fixture + '\nsource "$TEST_BOOTSTRAP"\n')
                if accepted:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(self.recorded()[recorded_before:], ["sha256sum", "runtime"])
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("ready SHA256 mismatch", result.stderr)
                    self.assertEqual(self.recorded()[recorded_before:], ["sha256sum"])
                self.assertEqual((target / "bundle.ready").read_text(encoding="utf-8"), digest + "\n")
                self.assertTrue((target / "python/bin/python3").is_file())

    def test_failure_outputs_only_current_stage_last_80_lines_and_exit_code(self):
        self.env["TEST_FAILURE_STAGE"] = "Metadata"
        logs = self.root / "work/invocations"
        logs.mkdir(parents=True)
        (logs / "Metadata-1.stdout.log").write_text("".join(f"stdout{i:03}\n" for i in range(1, 101)), encoding="utf-8")
        (logs / "Metadata-1.stderr.log").write_text("".join(f"stderr{i:03}\n" for i in range(1, 91)), encoding="utf-8")
        (logs / "Tasks-1.stdout.log").write_text("OTHER_STAGE_MARKER\n", encoding="utf-8")
        (logs / "Metadata-1.json").write_text('{"env":"RECEIPT_PRIVATE_MARKER"}', encoding="utf-8")
        result = self.shell(STAGE_STUB + STAGE_LOOP)
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual(self.recorded(), ["Prepare", "Tasks", "Resolve", "Metadata"])
        self.assertIn("stdout021", result.stderr)
        self.assertNotIn("stdout020", result.stderr)
        self.assertIn("stderr011", result.stderr)
        self.assertNotIn("stderr010", result.stderr)
        self.assertNotIn("OTHER_STAGE_MARKER", result.stderr)
        self.assertNotIn("RECEIPT_PRIVATE_MARKER", result.stderr)
        self.assertEqual(sum(line.startswith("stdout") or line.startswith("stderr") for line in result.stderr.splitlines()), 160)

    def test_success_keeps_all_eight_stages_without_log_tails(self):
        result = self.shell(STAGE_STUB + STAGE_LOOP)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded(), ["Prepare", "Tasks", "Resolve", "Metadata", "NativeX64", "NativeArm64", "PublishLocal", "Verify"])
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
