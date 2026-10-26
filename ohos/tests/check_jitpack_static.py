"""JitPack 候选入口的静态清单检查；不下载或构建。"""
import ast
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parents[1]
manifest = json.loads((HERE / "bootstrap-linux.json").read_text(encoding="utf-8"))
config = json.loads((HERE / "port-config.json").read_text(encoding="utf-8"))
bundle = manifest["nativeBundle"]
assert manifest["kotlinVersion"] == config["kotlin"] == "2.4.20-0.1.0-08"
assert bundle["url"] == ("https://maven.eazytec-cloud.com/nexus/repository/maven-develop/org/jetbrains/kotlin/"
                         "kotlin-native-prebuilt/2.4.20-0.1.0-08/kotlin-native-prebuilt-2.4.20-0.1.0-08-linux-x86_64.tar.gz")
assert bundle["bytes"] == 177306208
assert bundle["sha256"] == "014411e74a0a0733aaf5cdcf7883e1b43c66f5b0a9fec390866bb8d459acad9f"
assert bundle["directory"] == "kotlin-native-prebuilt-linux-x86_64-2.4.20-0.1.0-08"
assert manifest["configurationPolicy"] == "UNMODIFIED_ARCHIVE_KONAN_PROPERTIES_STANDARD_ON_DEMAND_DEPENDENCIES"
install = (HERE / "jitpack-install.sh").read_text(encoding="utf-8")
assert '--repository "$HOME/.m2/repository"' in install
assert '--group "${GROUP}.${ARTIFACT}" --version "$VERSION"' in install
assert re.search(r"for stage in (.+); do", install).group(1).split() == [
    "Prepare", "Tasks", "Resolve", "Metadata", "NativeX64", "NativeArm64", "PublishLocal", "Verify"]
assert "${GIT_COMMIT,,}" in install and "SNAPSHOT" in install
assert "refs/tags/" not in install and "git -C \"$REPOSITORY_HOME\" rev-parse HEAD" in install
assert "export CPF_NATIVE_HOME=" in install and "export KONAN_DATA_DIR=" in install
assert install.index('source "$PORT_HOME/bootstrap-python.sh"') > install.index('checkout_commit=')
assert 'python3 --version' in install and 'tail -n 80 "$stage_log"' in install
assert 'port_work="$(printf' in install and 'invocations/$stage-1.$stream.log' in install
python_source = dict(re.findall(r"^(CPF_PYTHON_[A-Z0-9_]+)='([^']*)'$", (HERE / "bootstrap-python.env").read_text(encoding="utf-8"), re.MULTILINE))
assert python_source["CPF_PYTHON_RELEASE"] == "20261021"
assert python_source["CPF_PYTHON_VERSION"] == "3.13.17"
assert python_source["CPF_PYTHON_BYTES"] == "35356674"
assert python_source["CPF_PYTHON_SHA256"] == "f829adc9d888e76c8801b4799ed444188d35239fcae3a9808a99ec5cb0d8d92c"
assert python_source["CPF_PYTHON_URL"] == ("https://github.com/astral-sh/python-build-standalone/releases/download/20261021/"
    "cpython-3.13.17%2B20261021-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz")
assert not re.search(r"(?:^|\n)(?:export )?HOME=", install)
yaml_lines = [line for line in (HERE.parent / "jitpack.yml").read_text(encoding="utf-8").splitlines()
              if line and not line.startswith("#")]
assert yaml_lines == ["jdk:", "  - openjdk17", "install:", "  - bash ohos/jitpack-install.sh"]
for name in ("bootstrap-native.py", "bootstrap-linux.json", "bootstrap-python.sh", "bootstrap-python.env", "jitpack-install.sh", "tests/test_optional_sdk.py", "tests/check_jitpack_static.py"):
    path = HERE / name
    assert b"\r\n" not in path.read_bytes()
    if path.suffix == ".py":
        ast.parse(path.read_text(encoding="utf-8"))
print(json.dumps({"status": "JITPACK_CANDIDATE_STATIC_CHECKS_PASSED_CLOUD_NOT_RUN", "nativeBundleIdentity": "pinned",
                  "controlledStages": 8, "mavenLocal": "JitPack HOME/.m2/repository", "immutableVersionChecks": True}, indent=2))
