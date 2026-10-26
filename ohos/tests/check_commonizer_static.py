"""仅静态核对 commonizer 独立工具闭包与配方身份；不运行 Gradle 或下载。"""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
if len(sys.argv) != 2:
    raise SystemExit("usage: python -B tests/check_commonizer_static.py <explicit-tooling-directory>")
read = lambda name: json.loads((HERE / name).read_text(encoding="utf-8-sig"))
config = read("port-config.json")
commonizer = read("commonizer-toolchain.json")
launcher = read("metadata-toolchain.json")
native = read("dependency-pins.json")
metadata = read("metadata-pins.json")
ga = "org.jetbrains.kotlin:kotlin-klib-commonizer-embeddable"
version = "2.4.20-0.1.0-08"
assert commonizer["configuration"] == "kotlinKlibCommonizerClasspath"
assert commonizer["scope"] == "HOST_JVM_COMMONIZER_TOOL_ONLY"
assert commonizer["compilerVersion"] == config["kotlin"] == version
assert commonizer["inheritsLauncherToolchain"] == "metadata-toolchain.json"
assert commonizer["pins"] == {ga: version}
assert set(commonizer["artifacts"]) == {ga}
assert commonizer["artifacts"][ga]["size"] == 3843199
assert commonizer["artifacts"][ga]["sha256"] == "9ff11589b4ef1fab248928726e58a790bf082bc23ff8805ec2e59537dc909d58"
assert commonizer["artifacts"][ga]["url"].endswith("/" + ga.split(":")[1] + "/" + version + "/" + ga.split(":")[1] + "-" + version + ".jar")
assert len(native) == 117 and len(metadata) == 15
assert len(launcher["launcherPins"]) == len(launcher["launcherArtifacts"]) == 8
assert ga not in native and ga not in metadata and ga not in launcher["launcherPins"]
tool_pins = {**launcher["launcherPins"], **commonizer["pins"]}
tool_artifacts = {**launcher["launcherArtifacts"], **commonizer["artifacts"]}
assert len(tool_pins) == len(tool_artifacts) == 9
business_pins = {**native, **metadata}
assert all(business_pins.get(key, value) == value for key, value in tool_pins.items())
pom = commonizer["sourcePom"]
pom_path = HERE / pom["path"]
assert pom_path.stat().st_size == pom["size"]
assert hashlib.sha256(pom_path.read_bytes()).hexdigest() == pom["sha256"]
ns = {"m": "http://maven.apache.org/POM/4.0.0"}
xml = ET.fromstring(pom_path.read_bytes())
assert xml.findtext("m:groupId", namespaces=ns) + ":" + xml.findtext("m:artifactId", namespaces=ns) == ga
assert xml.findtext("m:version", namespaces=ns) == version
deps = xml.findall("m:dependencies/m:dependency", ns)
actual_deps = {dep.findtext("m:groupId", namespaces=ns) + ":" + dep.findtext("m:artifactId", namespaces=ns) + ":" + dep.findtext("m:version", namespaces=ns) for dep in deps}
assert actual_deps == set(commonizer["directRuntimeDependencies"]) == {
    "org.jetbrains.kotlin:kotlin-stdlib:" + version,
    "org.jetbrains.kotlin:kotlin-compiler-embeddable:" + version}
assert all(dep.findtext("m:scope", namespaces=ns) == "runtime" for dep in deps)
settings = (HERE / "settings.gradle.kts").read_text(encoding="utf-8")
assert settings.count("+ commonizerPins.entries") == 2
assert "includeGroup(" not in settings
build = (HERE / "build.gradle.kts").read_text(encoding="utf-8")
assert 'if (name == commonizerTools.getValue("configuration").toString()) resolutionStrategy.eachDependency' in build
assert 'val commonizerPins = launcherPins + asMap(commonizerTools.getValue("pins"))' in build
assert 'val commonizerArtifacts = launcherArtifacts + asMap(commonizerTools.getValue("artifacts"))' in build
resolve = build.split('tasks.register("resolveGrid") {', 1)[1].split("fun recordStage", 1)[0]
assert '"commonizer" to commonizerRecords()' in resolve
assert 'check(commonizerPins[ga] == id.version)' in build
assert 'artifact.file.length() == (expected.getValue("size") as Number).toLong()' in build
assert '"Commonizer tool artifact set differs"' in build
assert '"Commonizer tool bytes differ: $id"' in build
spec = importlib.util.spec_from_file_location("grid_commonizer_static", HERE / "GridPort.py")
grid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grid)
grid.PORT = grid.load_tooling(sys.argv[1])
for name in ("load", "record", "write", "physical", "copy_exact"):
    setattr(grid, name, getattr(grid.PORT, name))
grid.OPTIONS = SimpleNamespace(group=None, version=None, work_root=None, repository=None)
plan = grid.plan()
recipe = {row["path"] for row in plan["recipe"]}
assert "commonizer-toolchain.json" in recipe and pom["path"] in recipe
assert len(plan["sources"]) == 18
for name in ("GridPort.py", "tests/check_commonizer_static.py"):
    ast.parse((HERE / name).read_text(encoding="utf-8"))
print(json.dumps({"status": "COMMONIZER_TOOL_CLOSURE_STATIC_CHECKS_PASSED_GRADLE_NOT_RUN",
                  "commonizerArtifacts": len(tool_pins), "metadataLaunchers": 8,
                  "nativePins": 117, "metadataPins": 15, "sources": 18,
                  "pomRuntimeDependencies": sorted(actual_deps), "recipeIncludesToolLockAndPom": True,
                  "fingerprint": plan["fingerprint"]}, indent=2))
