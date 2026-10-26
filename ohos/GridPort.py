"""Grid 2.8.0 完整官方原源 producer；计划与静态检查不代表平台验收。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time
from urllib.request import urlopen
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
import zipfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
UPSTREAM = HERE.parent
OPTIONS = None
PORT = None


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def load_tooling(directory):
    """仅加载锁定内容；公共归档必须使用真实不可变 commit。"""
    lock = load_json(HERE / "tooling-lock.json")
    if directory:
        directory = Path(directory).resolve()
    else:
        revision = lock.get("revision")
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise RuntimeError("Tooling revision is pending; use an explicitly reviewed --tooling directory for static work")
        repository = lock["repository"]
        if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise RuntimeError("Tooling archive repository must be a public GitHub repository")
        directory = HERE / ".local/tooling" / revision
        if not all((directory / row["path"]).is_file() for row in lock["files"]):
            # 只读取声明文件，不解压任意归档路径，不使用凭据。
            import io
            with urlopen(repository + "/archive/" + revision + ".zip", timeout=60) as response:
                data = response.read(8 * 1024 * 1024 + 1)
            if len(data) > 8 * 1024 * 1024:
                raise RuntimeError("Tooling archive exceeds the allowed size")
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for row in lock["files"]:
                    relative = PurePosixPath(row["path"])
                    if relative.is_absolute() or ".." in relative.parts or "\\" in row["path"] or ":" in row["path"]:
                        raise RuntimeError("Unsafe tooling lock member")
                    matches = [name for name in archive.namelist() if "/" in name and name.split("/", 1)[1] == row["path"]]
                    if len(matches) != 1:
                        raise RuntimeError("Tooling archive member differs: " + row["path"])
                    content = archive.read(matches[0])
                    if len(content) != row["size"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
                        raise RuntimeError("Tooling archive bytes differ: " + row["path"])
                    target = directory / row["path"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists() and target.read_bytes() != content:
                        raise RuntimeError("Existing tooling bytes differ")
                    target.write_bytes(content)
    for row in lock["files"]:
        target = directory / row["path"]
        if target.stat().st_size != row["size"] or hashlib.sha256(target.read_bytes()).hexdigest() != row["sha256"]:
            raise RuntimeError("Locked tooling bytes differ: " + row["path"])
    spec = importlib.util.spec_from_file_location("cpf_port_tooling_locked", directory / "cpf_port_tooling.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_path(member):
    relative = PurePosixPath(member)
    if relative.is_absolute() or ".." in relative.parts or not member.startswith("commonMain/"):
        raise RuntimeError("Unsafe source member: " + member)
    return UPSTREAM / "grid/src/commonMain/kotlin" / Path(*relative.parts[1:])


def java_executable():
    home = OPTIONS.jdk or os.environ.get("JAVA_HOME")
    if not home:
        raise RuntimeError("Set --jdk or JAVA_HOME to JDK 17")
    executable = Path(home).resolve() / "bin" / ("java.exe" if os.name == "nt" else "java")
    if not executable.is_file():
        raise RuntimeError("Configured Java executable is missing")
    return executable


STAGES = (("Metadata", "metadata", "recordGridMetadata"), ("NativeX64", "native-x64", "recordGridX64"),
          ("NativeArm64", "native-arm64", "recordGridArm64"))


def source_digest(rows):
    compact = [{key: row[key] for key in ("member", "size", "sha256")} for row in sorted(rows, key=lambda row: row["member"])]
    return hashlib.sha256(json.dumps(compact, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def plan():
    config = load(HERE / "port-config.json")
    recipe_names = ["GridPort.py", "build.gradle.kts", "settings.gradle.kts", "gradle.properties",
                    "port-config.json", "source-inputs.json", "dependency-pins.json", "metadata-pins.json",
                    "metadata-toolchain.json", "commonizer-toolchain.json", "tooling-lock.json", "gradlew", "gradlew.bat",
                    "gradle/wrapper/gradle-wrapper.jar", "gradle/wrapper/gradle-wrapper.properties"]
    model = load(HERE / "source-inputs.json")
    recipe_names += [model[key]["path"] for key in ("sources", "pom", "gmm", "upstreamBuild", "license")]
    commonizer = load(HERE / "commonizer-toolchain.json")
    if commonizer["compilerVersion"] != config["kotlin"]:
        raise RuntimeError("Commonizer tool version differs from the Kotlin lock")
    pom = commonizer["sourcePom"]
    actual_pom = record(HERE / pom["path"], HERE)
    if any(actual_pom[key] != pom[key] for key in ("path", "size", "sha256")):
        raise RuntimeError("Commonizer source POM differs from the pinned original")
    recipe_names.append(pom["path"])
    recipe = [record(HERE / name, HERE) for name in sorted(set(recipe_names))]
    wrapper = config["gradleWrapper"]
    wrapper_inputs = [record(HERE / item["path"], HERE) for item in wrapper["inputs"]]
    if wrapper_inputs != wrapper["inputs"]:
        raise RuntimeError("Read-only Gradle wrapper identity differs")
    properties = dict(line.split("=", 1) for line in physical(HERE / "gradle/wrapper/gradle-wrapper.properties")
                      .read_text(encoding="utf-8").splitlines() if "=" in line)
    if (properties.get("distributionUrl", "").replace("\\:", ":") != wrapper["distributionUrl"] or
            properties.get("distributionSha256Sum") != wrapper["distributionSha256"]):
        raise RuntimeError("Pinned Gradle distribution identity differs")
    rows = [{"member": row["member"], "size": record(source_path(row["member"]))["size"],
             "sha256": record(source_path(row["member"]))["sha256"]} for row in model["sourceMembers"]]
    if rows != model["sourceMembers"] or len(rows) != 18 or source_digest(rows) != model["sourceSetSha256"]:
        raise RuntimeError("Complete upstream Grid source inventory differs")
    actual_paths = {path.resolve() for path in (UPSTREAM / "grid/src/commonMain/kotlin").rglob("*.kt")}
    if actual_paths != {source_path(row["member"]).resolve() for row in rows}:
        raise RuntimeError("Upstream contains unlisted Kotlin sources")
    publication = config["publication"]
    group = OPTIONS.group or publication["group"]
    version_input = OPTIONS.version or publication["versionPrefix"] + "-<fingerprint>"
    if not re.fullmatch(r"[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)*", group):
        raise RuntimeError("Invalid publication group")
    if OPTIONS.version and not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.+-]*", OPTIONS.version):
        raise RuntimeError("Invalid publication version")
    identity = {"recipe": recipe, "sources": rows, "gradleWrapperInputs": wrapper_inputs,
                "tooling": load(HERE / "tooling-lock.json"), "publication": {"group": group, "versionInput": version_input}}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    workroot = Path(OPTIONS.work_root or os.environ.get("CPF_WORK_ROOT") or HERE / ".local").resolve()
    work = workroot / ("grid-" + fingerprint[:24])
    repository = Path(OPTIONS.repository).resolve() if OPTIONS.repository else work / "maven"
    return {"fingerprint": fingerprint, "work": str(work), "repository": str(repository), "group": group,
            "versions": {"grid": OPTIONS.version or publication["versionPrefix"] + "-" + fingerprint[:12]}, **identity}


def prepare(value):
    work = physical(value["work"])
    existing = work / "prepared.json"
    if existing.is_file():
        prepared = load(existing)
        if prepared["fingerprint"] != value["fingerprint"] or prepared["repository"] != value["repository"]:
            raise RuntimeError("Prepared Grid identity or repository differs; choose another work root")
        return value
    model = load(HERE / "source-inputs.json")
    for key in ("sources", "pom", "gmm", "upstreamBuild", "license"):
        if record(HERE / model[key]["path"], HERE) != model[key]:
            raise RuntimeError("Official Grid input differs: " + key)
    members = []
    # 上游文件是唯一编译来源；JAR 只核对 provenance，不解包或复制 Kotlin 源码。
    with zipfile.ZipFile(physical(HERE / model["sources"]["path"])) as archive:
        if len(archive.infolist()) != model["archiveEntryCount"]:
            raise RuntimeError("Official Grid archive entry count differs")
        source_names = {entry.filename for entry in archive.infolist() if entry.filename.endswith(".kt")}
        if source_names != {row["member"] for row in model["sourceMembers"]}:
            raise RuntimeError("Official source archive Kotlin inventory differs")
        for source in model["sourceMembers"]:
            path = source_path(source["member"])
            if archive.read(source["member"]) != physical(path).read_bytes():
                raise RuntimeError("Upstream bytes differ from official archive: " + source["member"])
            members.append({"member": source["member"], "compile": True, **record(path)})
    write(work / "source-manifest.json", {"fingerprint": value["fingerprint"], "members": members,
          "sourceCount": 18, "sourceSetSha256": model["sourceSetSha256"], "publicApi": model["publicApi"],
          "upstream": model["upstream"], "license": model["license"]})
    pins = load(HERE / "dependency-pins.json")
    pins.update(load(HERE / "metadata-pins.json"))
    config = load(HERE / "port-config.json")
    # 冻结镜像另带 host 工具输入；库的 117/15 项清单保持原样。
    tool_pins = {**load(HERE / "metadata-toolchain.json")["launcherPins"],
                 **load(HERE / "commonizer-toolchain.json")["pins"]}
    mirror = PORT.mirror_cache(work, {**pins, **tool_pins}, cache_root=OPTIONS.maven_cache,
                              gradle_api=tuple(config["gradle"].split(".")), tool_allowlist=config["toolAllowlist"])
    write(existing, {**value, "frozenInputs": mirror, "cachePolicy": cache_paths(work, config),
          "gradleDistribution": "PINNED_WRAPPER_OR_EXPLICIT_DISTRIBUTION", "build": "NOT_RUN", "runtime": "NOT_RUN"})
    return value


def verify_metadata_producer(value, row):
    work = Path(value["work"])
    tools = load(HERE / "metadata-toolchain.json")
    config = load(HERE / "port-config.json")
    producer_path = work / "build/metadata-cli/commonMain/producer.json"
    receipt = row["metadataProducerReceipt"]
    if Path(receipt["path"]).resolve() != producer_path.resolve() or record(producer_path) != receipt:
        raise RuntimeError("Grid public metadata producer receipt differs")
    cli = load(producer_path)
    task = ":compileCommonMainWithMetadataCli"
    output = work / "build/metadata-cli/commonMain/klib"
    if (cli != row["commonMetadataCli"] or cli["fingerprint"] != value["fingerprint"] or cli["task"] != task or
            cli["kind"] != tools["producer"] or cli["mainClass"] != tools["mainClass"] or
            cli["compilerVersion"] != tools["compilerVersion"] or cli["targetPlatform"] != tools["targetPlatform"] or
            cli["exitCode"] != 0 or cli["sourceSetSha256"] != row["sourceSetSha256"] or
            cli["sourceManifestSha256"] != row["sourceManifest"]["sha256"]):
        raise RuntimeError("Grid public metadata compiler identity or exit differs")
    if {producer["task"] for producer in row["producers"]} != {task, ":allMetadataJar"}:
        raise RuntimeError("Grid metadata producers must be the real JavaExec and allMetadataJar")
    binding = cli["outputBinding"]
    if (Path(cli["output"]).resolve() != output.resolve() or
            {Path(path).resolve() for path in binding["roots"]} != {output.resolve()} or binding["builtBy"] != [task] or
            cli["retiredTask"] != {"path": ":compileCommonMainKotlinMetadata", "enabled": False}):
        raise RuntimeError("Grid common metadata output/builtBy is not exclusively bound to the public compiler")
    if not physical(output / "default/manifest").is_file() or physical(output / "default/linkdata/module").stat().st_size == 0:
        raise RuntimeError("Grid public metadata Klib payload is absent")
    if (cli["sources"] != row["sources"] or cli["plugins"] != row["compilerPlugins"] or cli["pluginOptions"] != row["pluginOptions"] or
            cli["languageOptions"] != row["metadataLanguageOptions"] or cli["libraries"] != row["metadataLibraries"]):
        raise RuntimeError("Grid public metadata sources/plugins/options/libraries differ from the original KGP task")
    for item in [*cli["plugins"], *cli["outputs"], cli["argumentsFile"],
                 *(item for library in cli["libraries"] for item in library["files"])]:
        if record(item["path"]) != item:
            raise RuntimeError("Grid public metadata compiler input/output bytes changed")
    launchers = cli["launcher"]
    expected_gavs = {ga + ":" + version for ga, version in tools["launcherPins"].items()}
    if len(launchers) != 8 or {item["gav"] for item in launchers} != expected_gavs:
        raise RuntimeError("Grid public metadata launcher set differs")
    for launcher in launchers:
        ga = launcher["gav"].rsplit(":", 1)[0]
        expected = tools["launcherArtifacts"][ga]
        actual = record(launcher["path"])
        if any(actual[key] != expected[key] or launcher[key] != expected[key] for key in ("size", "sha256")):
            raise RuntimeError("Grid public metadata launcher bytes differ: " + ga)
    # 按原 KGP 记录重建全部参数，避免只记录了插件或语言选项却未真正传给公共入口。
    language = row["metadataLanguageOptions"]
    normalized = lambda path: str(path).replace("\\", "/")
    arguments = ["-classpath", os.pathsep.join(normalized(item["path"]) for item in sorted(cli["libraries"], key=lambda item: item["path"])),
                 "-d", normalized(output), "-module-name", value["group"] + ":grid_commonMain",
                 "-Xtarget-platform=" + tools["targetPlatform"], "-Xmulti-platform"]
    for key, flag in (("languageVersion", "-language-version"), ("apiVersion", "-api-version")):
        if language[key] is not None:
            arguments.extend((flag, language[key]))
    arguments.extend("-opt-in=" + item for item in sorted(language["optIns"]))
    free = language["freeCompilerArgs"]
    arguments.extend(free)
    if not any(item.startswith("-Xexplicit-api=") for item in free) and language["explicitApi"] in ("Strict", "Warning"):
        arguments.append("-Xexplicit-api=" + language["explicitApi"].lower())
    if cli["plugins"]:
        arguments.append("-Xplugin=" + ",".join(normalized(item["path"]) for item in sorted(cli["plugins"], key=lambda item: item["path"])))
    for option in row["pluginOptions"]:
        arguments.extend(("-P", option))
    arguments.extend(normalized(item["path"]) for item in sorted(row["sources"], key=lambda item: item["path"]))
    arg_path = work / "build/metadata-cli/commonMain/arguments.txt"
    arg_bytes = "".join('"' + item.replace("\\", "\\\\").replace('"', '\\"') + '"\n' for item in arguments).encode()
    if (cli["arguments"] != arguments or Path(cli["argumentsFile"]["path"]).resolve() != arg_path.resolve() or
            cli["launcherArguments"] != ["@" + str(arg_path)] or physical(arg_path).read_bytes() != arg_bytes or
            Path(cli["javaExecutable"]).resolve() != java_executable().resolve()):
        raise RuntimeError("Grid public metadata argfile or Java launcher differs from inherited compiler semantics")


def cache_paths(work, config):
    native = OPTIONS.native_home or os.environ.get("CPF_NATIVE_HOME")
    konan = OPTIONS.konan_data or os.environ.get("KONAN_DATA_DIR") or str(work / "konan")
    return {"policy": "EXPLICIT_ENVIRONMENT_PER_FINGERPRINT_OUTPUT",
            "GRADLE_USER_HOME": str(Path(OPTIONS.gradle_user_home).resolve()) if OPTIONS.gradle_user_home else str(work / "gradle-user-home"),
            "KONAN_DATA_DIR": str(Path(konan).resolve()), "nativeHome": str(Path(native).resolve()) if native else None,
            "projectCache": str(work / "project-cache"), "kotlinCache": str(work / "kotlin-cache"),
            "TEMP": str(work / "temp"), "TMP": str(work / "temp"),
            "frozenMaven": str(work / "frozen-maven"), "privateMaven": str(value_repository(work)),
            "gradleDistribution": OPTIONS.gradle_distribution or "PINNED_WRAPPER"}


def value_repository(work):
    return Path(OPTIONS.repository).resolve() if OPTIONS.repository else work / "maven"


def verify_stage(value, evidence):
    work = Path(value["work"])
    model = load(HERE / "source-inputs.json")
    row = load(work / "evidence" / (evidence + ".json"))
    if (row["fingerprint"] != value["fingerprint"] or row["stage"] != evidence or row["sourceCount"] != 18 or
            row["sourceSetSha256"] != model["sourceSetSha256"] or row["sourceManifest"] != record(work / "source-manifest.json")):
        raise RuntimeError("Grid compile source identity differs: " + evidence)
    expected_sources = {}
    for source in model["sourceMembers"]:
        path = source_path(source["member"])
        actual = record(path)
        if actual["size"] != source["size"] or actual["sha256"] != source["sha256"]:
            raise RuntimeError("Grid original compile source bytes differ: " + source["member"])
        expected_sources[path.resolve()] = (source["size"], source["sha256"])
    if {Path(source["path"]).resolve(): (source["size"], source["sha256"]) for source in row["sources"]} != expected_sources:
        raise RuntimeError("Grid recorded compiler sources differ from the complete official source set")
    if evidence == "metadata":
        verify_metadata_producer(value, row)
    native_targets, has_metadata, has_ir = [], False, False
    for producer in row["producers"]:
        if not producer["outputs"] or not any(item["size"] > 0 for item in producer["outputs"]):
            raise RuntimeError("Grid producer outputs are empty")
        for item in producer["outputs"]:
            if record(item["path"]) != item:
                raise RuntimeError("Grid stage output bytes changed")
            path = physical(item["path"])
            props = None
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path) as archive:
                    names = archive.namelist()
                    has_metadata |= any(("/linkdata/" in name or name.endswith(".kotlin_metadata")) and archive.getinfo(name).file_size > 0 for name in names)
                    has_ir |= any("/ir/" in name and archive.getinfo(name).file_size > 0 for name in names)
                    if "default/manifest" in names:
                        props = archive.read("default/manifest").decode()
            elif path.as_posix().endswith("/default/manifest"):
                props = path.read_text(encoding="utf-8")
            if "/linkdata/" in path.as_posix() and item["size"] > 0:
                has_metadata = True
            if "/ir/" in path.as_posix() and item["size"] > 0:
                has_ir = True
            if props is not None:
                properties = dict(line.split("=", 1) for line in props.splitlines() if "=" in line)
                native_targets.extend(properties.get("native_targets", "").split())
    if not has_metadata:
        raise RuntimeError("Grid metadata payload is absent")
    if evidence != "metadata":
        expected = "ohos_x64" if evidence == "native-x64" else "ohos_arm64"
        if not native_targets or set(native_targets) != {expected} or not has_ir:
            raise RuntimeError("Grid Native target or IR payload differs: " + evidence)
    return row


def verify_publication(value):
    config = load(HERE / "port-config.json")
    model = load(HERE / "source-inputs.json")
    pins = load(HERE / "dependency-pins.json")
    stages = [verify_stage(value, evidence) for _, evidence, _ in STAGES]
    group, version = value["group"], value["versions"]["grid"]
    repo = physical(value["repository"]) / group.replace(".", "/")
    root_file = repo / "grid" / version / ("grid-" + version + ".module")
    root, rows, scopes = load(root_file), [], []
    ns = {"m": "http://maven.apache.org/POM/4.0.0"}
    expected_roots = {"org.jetbrains.kotlin:kotlin-stdlib", "org.jetbrains.compose.runtime:runtime",
                      "org.jetbrains.compose.foundation:foundation", "org.jetbrains.compose.ui:ui-util"}
    for suffix, target in (("", None), ("-ohosx64", "ohos_x64"), ("-ohosarm64", "ohos_arm64")):
        name = "grid" + suffix
        directory = repo / name / version
        gmm_file = directory / (name + "-" + version + ".module")
        gmm = load(gmm_file)
        if any(gmm["component"].get(k) != v for k, v in {"group": group, "module": "grid", "version": version}.items()):
            raise RuntimeError("Grid publication owner differs")
        if target:
            if (directory / gmm["component"]["url"]).resolve() != root_file.resolve():
                raise RuntimeError("Grid Native leaf owner URL differs")
            links = [variant["available-at"] for variant in root["variants"] if
                     variant.get("attributes", {}).get("org.jetbrains.kotlin.native.target") == target and "available-at" in variant]
            if not links or any(link["group"] != group or link["module"] != name or link["version"] != version or
                                (root_file.parent / link["url"]).resolve() != gmm_file.resolve() for link in links):
                raise RuntimeError("Grid root Native available-at differs")
        api = []
        for variant in gmm["variants"]:
            attrs = variant.get("attributes", {})
            if ((not target and attrs.get("org.gradle.usage") == "kotlin-metadata" and attrs.get("org.jetbrains.kotlin.platform.type") == "common") or
                    (target and attrs.get("org.gradle.usage") == "kotlin-api" and attrs.get("org.jetbrains.kotlin.native.target") == target)):
                api.append(variant)
            for dep in variant.get("dependencies", []):
                if pins.get(dep["group"] + ":" + dep["module"]) != dep.get("version", {}).get("requires"):
                    raise RuntimeError("Grid GMM dependency escaped frozen Native/root pins")
            for artifact in variant.get("files", []):
                path = (directory / artifact["url"]).resolve()
                if not path.is_relative_to(directory.resolve()):
                    raise RuntimeError("Grid artifact URL escaped its publication")
                item = record(path)
                if item["sha256"] != artifact["sha256"] or item["size"] != artifact["size"] or item["size"] == 0:
                    raise RuntimeError("Grid published artifact bytes differ")
        if not api or not all(variant.get("files") for variant in api):
            raise RuntimeError("Grid common metadata or Native API artifact is absent")
        if any({dep["group"] + ":" + dep["module"] for dep in variant.get("dependencies", [])} != expected_roots for variant in api):
            raise RuntimeError("Grid GMM API dependency set differs from the upstream model")
        pom = ET.fromstring((directory / (name + "-" + version + ".pom")).read_bytes())
        if any(pom.findtext("m:" + key, namespaces=ns) != expected for key, expected in
               (("groupId", group), ("artifactId", name), ("version", version))):
            raise RuntimeError("Grid POM coordinates differ")
        dependencies = pom.findall("m:dependencies/m:dependency", ns)
        expected_pom = {ga + (suffix if target and not ga.startswith("org.jetbrains.kotlin:") else "") for ga in expected_roots}
        actual_pom = set()
        for dep in dependencies:
            ga = dep.findtext("m:groupId", namespaces=ns) + ":" + dep.findtext("m:artifactId", namespaces=ns)
            scope = dep.findtext("m:scope", namespaces=ns)
            actual_pom.add(ga)
            if pins.get(ga) != dep.findtext("m:version", namespaces=ns) or scope != ("compile" if target else "runtime"):
                raise RuntimeError("Grid POM dependency version or publication-specific scope differs")
        if actual_pom != expected_pom:
            raise RuntimeError("Grid POM dependency closure differs")
        scopes.append({"publication": name, "pomScope": "compile" if target else "runtime",
                       "gmmUsage": "kotlin-api" if target else "kotlin-metadata", "dependencies": sorted(actual_pom)})
        if record(directory / (name + "-" + version + "-license.txt"))["sha256"] != model["license"]["sha256"]:
            raise RuntimeError("Grid publication license differs")
        if not suffix:
            for key, classifier in (("sources", "upstream-sources.jar"), ("pom", "upstream-pom.xml"), ("gmm", "upstream-module.json"),
                                    ("upstreamBuild", "upstream-build.gradle.kts")):
                if record(directory / (name + "-" + version + "-" + classifier))["sha256"] != model[key]["sha256"]:
                    raise RuntimeError("Grid publication official original differs: " + key)
        rows.extend(record(path) for path in sorted(directory.iterdir()) if path.is_file())
    result = {"status": "PUBLISHED_COMPLETE_GRID_BYTES_VERIFIED_RUNTIME_NOT_RUN", **value, "files": rows,
              "compilations": [{key: row[key] for key in ("stage", "sourceCount", "sourceSetSha256", "sourceManifest")} for row in stages],
              "dependencyScopes": scopes, "publicApi": model["publicApi"], "runtime": "NOT_RUN", "armRuntime": "NOT_RUN"}
    write(Path(value["work"]) / "publication.json", result)
    return result


def verify_native_home(home, expected_version):
    """启动 producer 前核对注入分发自报的精确编译器版本。"""
    if not home:
        raise RuntimeError("Set --native-home or CPF_NATIVE_HOME to Kotlin/Native " + expected_version)
    properties_path = Path(home) / "konan/konan.properties"
    if not physical(properties_path).is_file():
        raise RuntimeError("Kotlin/Native properties file is missing: " + str(properties_path))
    try:
        lines = physical(properties_path).read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as error:
        raise RuntimeError("Cannot read Kotlin/Native properties: " + str(properties_path)) from error
    properties = {key.strip(): value.strip() for line in lines if "=" in line
                  for key, value in [line.split("=", 1)]}
    actual_version = properties.get("compilerVersion")
    if not actual_version:
        raise RuntimeError("Kotlin/Native compilerVersion is missing in " + str(properties_path) +
                           "; expected " + expected_version)
    if actual_version != expected_version:
        raise RuntimeError("Kotlin/Native compilerVersion mismatch: expected " + expected_version +
                           ", got " + actual_version + " (" + str(properties_path) + ")")


def run_gradle(value, stage, attempt, online):
    config = load(HERE / "port-config.json")
    work = Path(value["work"])
    tasks = {"Tasks": ["tasks", "--all"], "Resolve": ["resolveGrid"], "Publish": ["publishGrid"], "PublishLocal": ["publishToMavenLocal"]}
    tasks.update({name: [task] for name, _, task in STAGES})
    if stage != "Tasks":
        discovery = load(work / "task-discovery.json")
        if discovery["fingerprint"] != value["fingerprint"] or discovery["stdout"] != record(discovery["stdout"]["path"]):
            raise RuntimeError("Grid actual task discovery identity differs")
    if stage in {row[0] for row in STAGES} or stage in ("Publish", "PublishLocal"):
        resolved = load(work / "evidence/resolve.json")
        if resolved["fingerprint"] != value["fingerprint"]:
            raise RuntimeError("Grid Resolve belongs to another recipe")
        for name, evidence, _ in STAGES:
            if name == stage:
                break
            verify_stage(value, evidence)
    cache = cache_paths(work, config)
    java = java_executable()
    verify_native_home(cache["nativeHome"], config["kotlin"])
    sdk = OPTIONS.ohos_sdk or os.environ.get("OHOS_SDK_HOME")
    if sdk and not Path(sdk).is_dir():
        raise RuntimeError("Configured OHOS SDK directory does not exist: " + str(sdk))
    if not re.fullmatch(r"[0-9a-f]{40}", load(HERE / "tooling-lock.json").get("revision") or ""):
        raise RuntimeError("Producer execution requires a reviewed immutable tooling commit")
    if OPTIONS.gradle_distribution:
        gradle_home = Path(OPTIONS.gradle_distribution).resolve()
        argv = [str(gradle_home / "bin" / ("gradle.bat" if os.name == "nt" else "gradle"))]
        if os.name != "nt":
            argv.insert(0, "sh")
    elif os.name == "nt":
        argv = [str(HERE / "gradlew.bat")]
    else:
        argv = ["sh", str(HERE / "gradlew")]
    argv += ["-p", str(HERE), "--project-cache-dir", cache["projectCache"],
             "-PportWork=" + str(work), "-PportFingerprint=" + value["fingerprint"],
             "-PportGroup=" + value["group"], "-PportVersion=" + value["versions"]["grid"],
             "-PportRepository=" + value["repository"], "-Dmaven.repo.local=" + value["repository"],
             "-Pkotlin.project.persistent.dir=" + cache["kotlinCache"], "-Pkotlin.native.home=" + cache["nativeHome"],
             "--console=plain", *tasks[stage]]
    if not online:
        argv.append("--offline")
    env = os.environ.copy()
    env.update(JAVA_HOME=str(java.parent.parent),
               **{key: cache[key] for key in ("GRADLE_USER_HOME", "KONAN_DATA_DIR", "TEMP", "TMP")})
    if sdk:
        env["OHOS_SDK_HOME"] = str(Path(sdk).resolve())
    physical(env["TEMP"]).mkdir(parents=True, exist_ok=True)
    receipt = physical(work / "invocations" / (stage + "-" + str(attempt) + ".json"))
    if receipt.exists():
        raise RuntimeError("Existing Grid invocation; select a new Attempt")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    row = {"stage": stage, "fingerprint": value["fingerprint"], "argv": argv, "cwd": str(HERE), "cache": cache,
           "configuredTools": {"jdk": str(java.parent.parent), **{key: config[key] for key in ("gradle", "kotlin", "compose")}},
           "started": time.time(), "exitCode": None}
    receipt.write_bytes((json.dumps(row, indent=2) + "\n").encode())
    with receipt.with_suffix(".stdout.log").open("wb") as out, receipt.with_suffix(".stderr.log").open("wb") as err:
        result = subprocess.run(argv, cwd=HERE, env=env, stdout=out, stderr=err)
    row.update(exitCode=result.returncode, finished=time.time())
    receipt.write_bytes((json.dumps(row, indent=2) + "\n").encode())
    if result.returncode:
        raise RuntimeError("Grid Gradle failed; see " + str(receipt))
    if stage == "Tasks":
        text = receipt.with_suffix(".stdout.log").read_text(encoding="utf-8-sig", errors="replace")
        names = set(re.findall(r"^\s*([\w:-]+)(?:\s+-|\s*$)", text, flags=re.MULTILINE))
        required = ["compileCommonMainKotlinMetadata", "compileCommonMainWithMetadataCli", "allMetadataJar", "compileKotlinOhosX64", "compileKotlinOhosArm64",
                    "recordGridMetadata", "recordGridX64", "recordGridArm64", "publishAllPublicationsToPortRepository", "publishToMavenLocal"]
        if not set(required).issubset({name.lstrip(":") for name in names}):
            raise RuntimeError("Expected Grid tasks absent from actual tasks --all; inspect before adjusting recipe")
        discovery = {"fingerprint": value["fingerprint"], "requiredTasks": required,
                     "stdout": record(receipt.with_suffix(".stdout.log")), "invocation": record(receipt)}
        if not physical(work / "task-discovery.json").exists():
            write(work / "task-discovery.json", discovery)
        write(work / "invocations" / (stage + "-" + str(attempt) + "-discovery.json"), discovery)
    elif stage in {row[0] for row in STAGES}:
        verify_stage(value, next(evidence for name, evidence, _ in STAGES if name == stage))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("Plan", "Prepare", "Tasks", "Resolve", "Metadata", "NativeX64", "NativeArm64", "Publish", "PublishLocal", "Verify"))
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--online", action="store_true")
    parser.add_argument("--tooling", default=os.environ.get("CPF_PORT_TOOLING"), help="Explicit locked tooling checkout")
    parser.add_argument("--jdk")
    parser.add_argument("--native-home")
    parser.add_argument("--ohos-sdk")
    parser.add_argument("--konan-data")
    parser.add_argument("--gradle-user-home")
    parser.add_argument("--gradle-distribution", help="Optional existing Gradle 9.5.0 home; wrapper is the default")
    parser.add_argument("--maven-cache", default=os.environ.get("CPF_MAVEN_CACHE"), help="Optional modules-2/files-2.1 source cache")
    parser.add_argument("--work-root")
    parser.add_argument("--repository", help="Local Maven output directory; PublishLocal also sets maven.repo.local")
    parser.add_argument("--group", default=os.environ.get("CPF_PUBLISH_GROUP"))
    parser.add_argument("--version", default=os.environ.get("CPF_PUBLISH_VERSION"))
    global OPTIONS, PORT, load, record, write, physical, copy_exact
    OPTIONS = parser.parse_args()
    args = OPTIONS
    PORT = load_tooling(args.tooling)
    load, record, write, physical, copy_exact = PORT.load, PORT.record, PORT.write, PORT.physical, PORT.copy_exact
    value = plan()
    if args.stage == "Plan":
        print(json.dumps(value, indent=2)); return
    if args.stage == "Verify":
        verify_publication(value)
    else:
        prepare(value)
        if args.stage != "Prepare":
            run_gradle(value, args.stage, args.attempt, args.online)
        if args.stage in ("Publish", "PublishLocal"):
            verify_publication(value)
    print(json.dumps({"stage": args.stage, "fingerprint": value["fingerprint"], "work": value["work"], "runtime": "NOT_RUN"}))


if __name__ == "__main__":
    main()
