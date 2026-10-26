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
assert not re.search(r"(?:^|\n)(?:export )?HOME=", install)
yaml_lines = [line for line in (HERE.parent / "jitpack.yml").read_text(encoding="utf-8").splitlines()
              if line and not line.startswith("#")]
assert yaml_lines == ["jdk:", "  - openjdk17", "install:", "  - bash ohos/jitpack-install.sh"]
for name in ("bootstrap-native.py", "bootstrap-linux.json", "jitpack-install.sh", "tests/test_optional_sdk.py", "tests/check_jitpack_static.py"):
    path = HERE / name
    assert b"\r\n" not in path.read_bytes()
    if path.suffix == ".py":
        ast.parse(path.read_text(encoding="utf-8"))
print(json.dumps({"status": "JITPACK_CANDIDATE_STATIC_CHECKS_PASSED_CLOUD_NOT_RUN", "nativeBundleIdentity": "pinned",
                  "controlledStages": 8, "mavenLocal": "JitPack HOME/.m2/repository", "immutableVersionChecks": True}, indent=2))
