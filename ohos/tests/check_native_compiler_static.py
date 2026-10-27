"""独立 Native compiler 宿主闭包/POM/门禁静态核对；不运行 Gradle。"""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
if len(sys.argv) != 2:
    raise SystemExit("usage: python -B tests/check_native_compiler_static.py <explicit-tooling-directory>")
read = lambda name: json.loads((HERE / name).read_text(encoding="utf-8"))
host, launcher = read("native-compiler-toolchain.json"), read("metadata-toolchain.json")
pins, artifacts = host["pins"], host["artifacts"]
assert host["configuration"] == "kotlinCompilerClasspath"
assert host["scope"] == "NATIVE_COMPILER_HOST_JVM_ONLY"
assert host["compilerTasks"] == ["compileKotlinOhosX64", "compileKotlinOhosArm64"]
assert len(pins) == len(artifacts) == len(host["sourcePoms"]) == 14
assert set(pins) == set(artifacts)
assert pins["org.jetbrains.kotlin:kotlin-stdlib"] == host["compilerVersion"] == read("port-config.json")["kotlin"] == "2.4.20-0.1.0-08"
assert pins["org.jetbrains:annotations"] == "23.0.0"
assert launcher["launcherPins"]["org.jetbrains:annotations"] == "13.0"
assert len(launcher["launcherPins"]) == 8 and len({**launcher["launcherPins"], **read("commonizer-toolchain.json")["pins"]}) == 9
assert len(read("compiler-plugin-toolchain.json")["pins"]) == 1
assert len(read("dependency-pins.json")) == 117 and len(read("metadata-pins.json")) == 15
reused = 0
for ga, version in pins.items():
    item = artifacts[ga]
    assert isinstance(item["size"], int) and item["size"] > 0 and re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
    if ga in launcher["launcherPins"] and ga != "org.jetbrains:annotations":
        assert version == launcher["launcherPins"][ga]
        assert all(item[key] == launcher["launcherArtifacts"][ga][key] for key in ("size", "sha256"))
        reused += 1
assert reused == 7
ns = {"m": "http://maven.apache.org/POM/4.0.0"}
edges = {}
for pom in host["sourcePoms"]:
    data = (HERE / pom["path"]).read_bytes()
    assert len(data) == pom["size"] and hashlib.sha256(data).hexdigest() == pom["sha256"]
    xml = ET.fromstring(data)
    ga = xml.findtext("m:groupId", namespaces=ns) + ":" + xml.findtext("m:artifactId", namespaces=ns)
    assert ga + ":" + xml.findtext("m:version", namespaces=ns) == pom["gav"] == ga + ":" + pins[ga]
    edges[ga] = []
    for dep in xml.findall("m:dependencies/m:dependency", ns):
        if dep.findtext("m:scope", default="compile", namespaces=ns) not in ("compile", "runtime"):
            continue
        child = dep.findtext("m:groupId", namespaces=ns) + ":" + dep.findtext("m:artifactId", namespaces=ns)
        requested = dep.findtext("m:version", namespaces=ns)
        assert child in pins
        if requested != pins[child]:
            policy = host["versionSelection"]["stdlib" if child == "org.jetbrains.kotlin:kotlin-stdlib" else "annotations"]
            assert requested in policy["requested"] and pins[child] == policy["selected"]
        edges[ga].append(child)
seen, pending = set(), [gav.rsplit(":", 1)[0] for gav in host["roots"]]
while pending:
    ga = pending.pop()
    if ga not in seen:
        seen.add(ga)
        pending.extend(edges[ga])
assert seen == set(pins)
build = (HERE / "build.gradle.kts").read_text(encoding="utf-8")
assert 'if (name == nativeCompilerTools.getValue("configuration").toString()) resolutionStrategy.eachDependency' in build
assert 'check(nativeCompilerPins[ga] == id.version)' in build
assert '"Native compiler host bytes differ: $id"' in build
assert 'artifacts.size == nativeCompilerPins.size' in build
assert '"nativeCompiler" to nativeCompilerRecords()' in build
assert 'val verifyNativeCompilerHost = tasks.register("verifyNativeCompilerHost")' in build
assert 'if (name in (nativeCompilerTools.getValue("compilerTasks") as List<*>)) dependsOn(verifyNativeCompilerHost)' in build
assert 'evidence("native-compiler-host"' in build
settings = (HERE / "settings.gradle.kts").read_text(encoding="utf-8")
assert settings.count("+ nativeCompilerPins.entries") == 2 and "includeGroup(" not in settings
cli = (HERE / "GridPort.py").read_text(encoding="utf-8")
assert 'mirror_pins.setdefault(ga, version)' in cli and 'tool_allowlist=[*config["toolAllowlist"], *native_host_rules]' in cli
spec = importlib.util.spec_from_file_location("native_host_static", HERE / "GridPort.py")
grid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grid)
grid.PORT = grid.load_tooling(sys.argv[1])
for name in ("load", "record", "write", "physical", "copy_exact"):
    setattr(grid, name, getattr(grid.PORT, name))
grid.OPTIONS = SimpleNamespace(group=None, version=None, work_root=None, repository=None)
plan = grid.plan()
recipe = {item["path"] for item in plan["recipe"]}
assert "native-compiler-toolchain.json" in recipe and all(pom["path"] in recipe for pom in host["sourcePoms"])
assert len(plan["sources"]) == 18
ast.parse(cli)
print(json.dumps({"status": "NATIVE_COMPILER_HOST_STATIC_CHECKS_PASSED_BUILD_NOT_RUN", "hostArtifacts": 14,
                  "sourcePoms": 14, "reusedExactLauncherArtifacts": reused, "annotationsHost": "23.0.0",
                  "annotationsMetadataAndCommonizer": "13.0", "nativeTaskGates": 2,
                  "sourceCount": 18, "nativePins": 117, "metadataPins": 15, "fingerprint": plan["fingerprint"]}, indent=2))
