"""静态核对 Compose host 插件与三类真实编译输入接线；不运行构建。"""
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parents[1]
read = lambda name: json.loads((HERE / name).read_text(encoding="utf-8"))
lock = read("compiler-plugin-toolchain.json")
launcher, commonizer = read("metadata-toolchain.json"), read("commonizer-toolchain.json")
ga, version = "org.jetbrains.kotlin:kotlin-compose-compiler-plugin-embeddable", "2.4.20-0.1.0-08"
assert lock["pins"] == {ga: version}
assert lock["compilerTasks"] == ["compileCommonMainKotlinMetadata", "compileKotlinOhosX64", "compileKotlinOhosArm64"]
assert lock["artifacts"][ga]["size"] == 870498
assert lock["artifacts"][ga]["sha256"] == "4ffe7f38089fa4acdda5d67fa3a858b9fc2fe7ed1f2e58bedbf8d3447c15df39"
assert len(launcher["launcherPins"]) == 8 and len({**launcher["launcherPins"], **commonizer["pins"]}) == 9
assert ga not in launcher["launcherPins"] and ga not in read("dependency-pins.json") and ga not in read("metadata-pins.json")
assert len(read("dependency-pins.json")) == 117 and len(read("metadata-pins.json")) == 15
pom = lock["sourcePom"]
data = (HERE / pom["path"]).read_bytes()
assert len(data) == pom["size"] and hashlib.sha256(data).hexdigest() == pom["sha256"]
xml = ET.fromstring(data)
ns = {"m": "http://maven.apache.org/POM/4.0.0"}
assert xml.findtext("m:groupId", namespaces=ns) + ":" + xml.findtext("m:artifactId", namespaces=ns) == ga
assert xml.findtext("m:version", namespaces=ns) == version
assert not xml.findall("m:dependencies/m:dependency", ns) and lock["directRuntimeDependencies"] == []
build = (HERE / "build.gradle.kts").read_text(encoding="utf-8")
plugins = [line.strip() for line in build.split("plugins {", 1)[1].split("\n}", 1)[0].splitlines() if line.strip()]
assert plugins == ['kotlin("multiplatform")', 'kotlin("plugin.compose")', '`maven-publish`']
assert 'val files = compiler.compilerPluginClasspath?.files.orEmpty()' in build
assert '"compilerPlugins" to compilerPluginRecords()' in build
assert 'hash == expected.getValue("sha256") && file.length() ==' in build
assert 'artifacts.size == compilerPluginPins.size' in build
settings = (HERE / "settings.gradle.kts").read_text(encoding="utf-8")
assert settings.count("+ compilerPluginPins.entries") == 2 and "includeGroup(" not in settings
cli = (HERE / "GridPort.py").read_text(encoding="utf-8")
assert '"compiler-plugin-toolchain.json"' in cli and 'recipe_names.append(plugin_pom["path"])' in cli
assert '**load(HERE / "compiler-plugin-toolchain.json")["pins"]' in cli
print(json.dumps({"status": "COMPOSE_COMPILER_PLUGIN_STATIC_CHECKS_PASSED_CI_NOT_RUN", "compilerTasks": 3,
                  "composePluginArtifactsPerTask": 1, "metadataLaunchers": 8, "commonizerClosure": 9,
                  "nativePins": 117, "metadataPins": 15}, indent=2))
