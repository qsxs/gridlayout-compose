import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import java.security.MessageDigest
import org.gradle.api.artifacts.Configuration
import org.gradle.api.artifacts.component.ModuleComponentIdentifier
import org.gradle.api.artifacts.result.ResolvedDependencyResult
import org.gradle.api.artifacts.result.UnresolvedDependencyResult
import org.gradle.api.attributes.Category
import org.gradle.api.attributes.Usage
import org.gradle.api.publish.maven.MavenPublication
import org.gradle.api.publish.maven.tasks.AbstractPublishToMaven
import org.gradle.jvm.tasks.Jar
import org.jetbrains.kotlin.gradle.dsl.ExplicitApiMode
import org.jetbrains.kotlin.gradle.dsl.KotlinMultiplatformExtension
import org.jetbrains.kotlin.gradle.tasks.KotlinNativeCompile

plugins {
    kotlin("multiplatform")
    kotlin("plugin.compose")
    `maven-publish`
}
fun readMap(path: File) = (JsonSlurper().parse(path) as Map<*, *>).entries.associate { it.key.toString() to it.value }
fun asMap(value: Any?) = (value as Map<*, *>).entries.associate { it.key.toString() to requireNotNull(it.value) }
fun sha(path: File) = MessageDigest.getInstance("SHA-256").digest(path.readBytes()).joinToString("") { "%02x".format(it) }
fun leaves(path: File): List<File> = if (path.isDirectory) path.walkTopDown().filter(File::isFile).toList() else listOf(path)
fun records(files: Iterable<File>) = files.filter(File::isFile).distinct().sortedBy { it.path }.map {
    mapOf("path" to it.absolutePath, "size" to it.length(), "sha256" to sha(it))
}
val config = readMap(file("port-config.json"))
val model = asMap(asMap(config.getValue("modules")).getValue("grid"))
val sourceInputs = readMap(file("source-inputs.json"))
val pins = readMap(file("dependency-pins.json"))
val metadataPins = if (file("metadata-pins.json").isFile) readMap(file("metadata-pins.json")) else emptyMap()
val metadataTools = readMap(file("metadata-toolchain.json"))
val launcherPins = asMap(metadataTools.getValue("launcherPins"))
val launcherArtifacts = asMap(metadataTools.getValue("launcherArtifacts"))
val commonizerTools = readMap(file("commonizer-toolchain.json"))
val commonizerPins = launcherPins + asMap(commonizerTools.getValue("pins"))
val commonizerArtifacts = launcherArtifacts + asMap(commonizerTools.getValue("artifacts"))
check(commonizerTools["compilerVersion"] == config["kotlin"])
val fingerprint = providers.gradleProperty("portFingerprint").get()
val work = file(providers.gradleProperty("portWork").get()).canonicalFile
check(fingerprint.matches(Regex("[0-9a-f]{64}")))
val upstreamSources = rootDir.resolve("../grid/src/commonMain/kotlin").canonicalFile
fun upstreamSource(member: String) = upstreamSources.resolve(member.removePrefix("commonMain/"))
val manifestFile = work.resolve("source-manifest.json")
val manifest = readMap(manifestFile)
check(manifest["fingerprint"] == fingerprint)
group = providers.gradleProperty("portGroup").get()
version = providers.gradleProperty("portVersion").get()
layout.buildDirectory.set(work.resolve("build"))
kotlin {
    ohosX64()
    ohosArm64()
    sourceSets {
        val commonMain by getting {
            kotlin.setSrcDirs(listOf(upstreamSources))
            dependencies {
                // 与官方固定 commit 的三个 implementation 声明一致，不伪改公开 scope。
                implementation("org.jetbrains.compose.runtime:runtime:1.12.0-0.1.0-11")
                implementation("org.jetbrains.compose.foundation:foundation:1.12.0-0.1.0-11")
                implementation("org.jetbrains.compose.ui:ui-util:1.12.0-0.1.0-11")
            }
        }
        matching { it.name.endsWith("Test") }.configureEach { kotlin.setSrcDirs(emptyList<File>()) }
    }
}
configurations.configureEach {
    // 仅锁定标准 commonizer 的 JVM 工具配置，不进入库的 Native 业务图。
    if (name == commonizerTools.getValue("configuration").toString()) resolutionStrategy.eachDependency {
        val ga = "${requested.group}:${requested.name}"
        val fixed = commonizerPins[ga]?.toString() ?: error("Unreviewed commonizer tool dependency: $ga")
        if (requested.version != fixed) useVersion(fixed)
    }
    val metadata = name.endsWith("ResolvableDependenciesMetadata") || name == "allSourceSetsCompileDependenciesMetadata"
    val runtime = metadata || name.endsWith("CompileKlibraries") || name.endsWith("CompilationDependenciesMetadata")
    if (runtime && !name.contains("Test", ignoreCase = true)) resolutionStrategy.eachDependency {
        val ga = "${requested.group}:${requested.name}"
        val fixed = (if (metadata) metadataPins[ga] ?: pins[ga] else pins[ga])?.toString()
            ?: error("Unpinned Grid dependency: $requested")
        if (requested.version != fixed) useVersion(fixed)
    }
}
fun evidence(name: String, value: Any) {
    val target = work.resolve("evidence/$name.json")
    target.parentFile.mkdirs()
    target.writeText(JsonOutput.prettyPrint(JsonOutput.toJson(value)) + "\n")
}
fun toolchain() = mapOf(
    "gradle" to gradle.gradleVersion,
    "javaVersion" to System.getProperty("java.version"),
    "javaRuntimeVersion" to System.getProperty("java.runtime.version"),
    "javaHome" to System.getProperty("java.home"),
    "nativeHome" to providers.gradleProperty("kotlin.native.home").get(),
    "konanDataDir" to System.getenv("KONAN_DATA_DIR"),
    "gradleUserHome" to gradle.gradleUserHomeDir.absolutePath,
    "temp" to System.getenv("TEMP"),
    "plugins" to buildscript.configurations.getByName("classpath").resolvedConfiguration.resolvedArtifacts.map {
        mapOf("component" to it.moduleVersion.id.toString(), "files" to records(listOf(it.file)))
    },
)
fun metadataLauncherRecords(configuration: Configuration): List<Map<String, Any>> {
    val artifacts = configuration.resolvedConfiguration.resolvedArtifacts.map { artifact ->
        val id = artifact.moduleVersion.id
        val ga = "${id.group}:${id.name}"
        check(launcherPins[ga] == id.version) { "Unpinned metadata launcher: $id" }
        val expected = asMap(launcherArtifacts.getValue(ga))
        val hash = sha(artifact.file)
        check(hash == expected.getValue("sha256") && artifact.file.length() == (expected.getValue("size") as Number).toLong()) {
            "Metadata launcher bytes differ: $id"
        }
        mapOf("gav" to id.toString(), "path" to artifact.file.absolutePath, "sha256" to hash, "size" to artifact.file.length())
    }
    check(artifacts.map { it.getValue("gav") }.toSet() == launcherPins.map { "${it.key}:${it.value}" }.toSet()) {
        "Metadata launcher artifact set differs"
    }
    return artifacts.sortedBy { it.getValue("gav").toString() }
}
// 标准入口真实报 OptionalExpectation 后，只替换 common metadata；双 ABI 继续使用标准 KGP。
gradle.projectsEvaluated {
    check(metadataTools["compilerVersion"] == config["kotlin"])
    val gridProject = project
    val kmp = gridProject.extensions.getByType<KotlinMultiplatformExtension>()
    val compilation = kmp.targets.getByName("metadata").compilations.getByName("commonMain")
    val original = gridProject.tasks.named<KotlinNativeCompile>("compileCommonMainKotlinMetadata").get()
    gridProject.tasks.getByName("allMetadataJar")
    val originalDependencies = gridProject.provider { original.taskDependencies.getDependencies(original).toList() }
    val launcher = gridProject.configurations.create("commonMetadataCliLauncher") {
        isCanBeConsumed = false
        isCanBeResolved = true
        isVisible = false
        attributes {
            attribute(Usage.USAGE_ATTRIBUTE, gridProject.objects.named(Usage.JAVA_RUNTIME))
            attribute(Category.CATEGORY_ATTRIBUTE, gridProject.objects.named(Category.LIBRARY))
        }
        resolutionStrategy.eachDependency {
            val ga = "${requested.group}:${requested.name}"
            val fixed = launcherPins[ga]?.toString() ?: error("Unreviewed metadata launcher dependency: $ga")
            if (requested.version != fixed) useVersion(fixed)
        }
    }
    gridProject.dependencies.add(launcher.name, "org.jetbrains.kotlin:kotlin-compiler-embeddable:${metadataTools.getValue("compilerVersion")}")
    val output = gridProject.layout.buildDirectory.dir("metadata-cli/commonMain/klib")
    val argumentsFile = gridProject.layout.buildDirectory.file("metadata-cli/commonMain/arguments.txt")
    val producerFile = gridProject.layout.buildDirectory.file("metadata-cli/commonMain/producer.json")
    val libraries = gridProject.files(gridProject.provider { original.libraries })
    val plugins = gridProject.files(gridProject.provider { original.compilerPluginClasspath })
    val sourceFiles = gridProject.files(gridProject.provider { original.sources })
    val compilerArguments = gridProject.provider {
        val options = original.compilerOptions
        buildList {
            addAll(listOf("-classpath", libraries.files.sortedBy { it.path }.joinToString(File.pathSeparator) { it.invariantSeparatorsPath },
                "-d", output.get().asFile.invariantSeparatorsPath, "-module-name", "${gridProject.group}:${gridProject.name}_commonMain",
                "-Xtarget-platform=${metadataTools.getValue("targetPlatform")}", "-Xmulti-platform"))
            options.languageVersion.orNull?.let { addAll(listOf("-language-version", it.version)) }
            options.apiVersion.orNull?.let { addAll(listOf("-api-version", it.version)) }
            options.optIn.get().sorted().forEach { add("-opt-in=$it") }
            val freeArguments = options.freeCompilerArgs.get()
            addAll(freeArguments)
            if (freeArguments.none { it.startsWith("-Xexplicit-api=") }) {
                when (kmp.explicitApi) {
                    ExplicitApiMode.Strict -> add("-Xexplicit-api=strict")
                    ExplicitApiMode.Warning -> add("-Xexplicit-api=warning")
                    else -> Unit
                }
            }
            if (!plugins.isEmpty) add("-Xplugin=" + plugins.files.sortedBy { it.path }.joinToString(",") { it.invariantSeparatorsPath })
            original.compilerPluginCommandLine.forEach { addAll(listOf("-P", it)) }
            addAll(sourceFiles.files.sortedBy { it.path }.map { it.invariantSeparatorsPath })
        }
    }
    val cli = gridProject.tasks.register<JavaExec>("compileCommonMainWithMetadataCli") {
        group = "build"
        description = "使用同版本公共 metadata 编译器编译完整十八份 commonMain 原源。"
        dependsOn(originalDependencies)
        dependsOn("transformCommonMainDependenciesMetadata")
        classpath = launcher
        mainClass.set(metadataTools.getValue("mainClass").toString())
        setExecutable(File(System.getProperty("java.home"), "bin/" + if (System.getProperty("os.name").startsWith("Windows")) "java.exe" else "java").absolutePath)
        inputs.files(sourceFiles, libraries, plugins, launcher)
        inputs.file(manifestFile)
        inputs.file(rootProject.file("source-inputs.json"))
        inputs.file(rootProject.file("metadata-toolchain.json"))
        inputs.property("compilerArguments", compilerArguments)
        outputs.dir(output)
        outputs.file(argumentsFile)
        outputs.file(producerFile)
        args("@" + argumentsFile.get().asFile.absolutePath)
        var actualLauncher = emptyList<Map<String, Any>>()
        doFirst {
            val binding = compilation.output.classesDirs
            check(binding.files == setOf(output.get().asFile) &&
                binding.buildDependencies.getDependencies(this).map { it.path }.toSet() == setOf(path) && !original.enabled) {
                "Common metadata output/builtBy was not replaced exclusively"
            }
            val expected = (sourceInputs.getValue("sourceMembers") as List<*>).map(::asMap)
                .associate { upstreamSource(it.getValue("member").toString()).canonicalFile to it.getValue("sha256").toString() }
            check(expected.size == 18 && sourceFiles.files.map { it.canonicalFile }.toSet() == expected.keys &&
                expected.all { (source, hash) -> sha(source) == hash }) { "Complete original common compiler sources differ" }
            actualLauncher = metadataLauncherRecords(launcher)
            val argFile = argumentsFile.get().asFile
            argFile.parentFile.mkdirs()
            argFile.writeText(compilerArguments.get().joinToString("\n", postfix = "\n") {
                "\"" + it.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
            })
        }
        doLast {
            check(executionResult.get().exitValue == 0)
            val root = output.get().asFile
            check(root.resolve("default/manifest").isFile && root.resolve("default/linkdata/module").length() > 0) {
                "Public metadata compiler did not produce a Klib"
            }
            val data = mapOf("fingerprint" to fingerprint, "kind" to metadataTools.getValue("producer"), "module" to gridProject.name,
                "task" to path, "exitCode" to executionResult.get().exitValue, "compilerVersion" to metadataTools.getValue("compilerVersion"),
                "targetPlatform" to metadataTools.getValue("targetPlatform"), "mainClass" to mainClass.get(), "javaExecutable" to executable,
                "launcherArguments" to args, "arguments" to compilerArguments.get(), "argumentsFile" to records(listOf(argumentsFile.get().asFile)).single(),
                "launcher" to actualLauncher, "sources" to records(sourceFiles.files), "sourceManifestSha256" to sha(manifestFile),
                "sourceSetSha256" to sourceInputs.getValue("sourceSetSha256"), "plugins" to records(plugins.files),
                "pluginOptions" to original.compilerPluginCommandLine,
                "languageOptions" to mapOf("languageVersion" to original.compilerOptions.languageVersion.orNull?.version,
                    "apiVersion" to original.compilerOptions.apiVersion.orNull?.version, "optIns" to original.compilerOptions.optIn.get().sorted(),
                    "freeCompilerArgs" to original.compilerOptions.freeCompilerArgs.get(), "explicitApi" to kmp.explicitApi?.name),
                "libraries" to libraries.files.sortedBy { it.path }.map { mapOf("path" to it.absolutePath, "files" to records(leaves(it))) },
                "libraryBuiltBy" to libraries.buildDependencies.getDependencies(this).map { it.path }.sorted(),
                "output" to root.absolutePath, "outputs" to records(leaves(root)),
                "outputBinding" to mapOf("roots" to compilation.output.classesDirs.files.map { it.absolutePath },
                    "builtBy" to compilation.output.classesDirs.buildDependencies.getDependencies(this).map { it.path }.sorted()),
                "retiredTask" to mapOf("path" to original.path, "enabled" to original.enabled))
            producerFile.get().asFile.writeText(JsonOutput.prettyPrint(JsonOutput.toJson(data)) + "\n")
        }
    }
    original.enabled = false
    compilation.output.classesDirs.setFrom(output)
    compilation.output.classesDirs.setBuiltBy(listOf(cli))
}
fun resolution() = listOf("commonMainResolvableDependenciesMetadata", "ohosX64CompileKlibraries", "ohosArm64CompileKlibraries").map { name ->
    val configuration = configurations.getByName(name)
    val metadata = name.endsWith("ResolvableDependenciesMetadata")
    mapOf("configuration" to name, "edges" to configuration.incoming.resolutionResult.allDependencies.map { edge ->
        if (edge !is ResolvedDependencyResult) throw GradleException("Unresolved Grid dependency: $edge", (edge as? UnresolvedDependencyResult)?.failure)
        mapOf("from" to edge.from.id.displayName, "requested" to edge.requested.displayName, "selected" to edge.selected.id.displayName)
    }, "artifacts" to configuration.incoming.artifacts.artifacts.map { artifact ->
        val id = artifact.id.componentIdentifier
        check(id is ModuleComponentIdentifier)
        val ga = "${id.group}:${id.module}"
        check((if (metadata) metadataPins[ga] ?: pins[ga] else pins[ga]) == id.version)
        val attrs = artifact.variant.attributes.keySet().associate { it.name to artifact.variant.attributes.getAttribute(it).toString() }
        if (metadataPins.containsKey(ga)) {
            val common = attrs["org.gradle.usage"] == "kotlin-metadata" && attrs["org.jetbrains.kotlin.platform.type"] == "common"
            val javaAlias = ga == "androidx.arch.core:core-common" && id.version == "2.2.0" &&
                attrs["org.gradle.usage"] in listOf("java-api", "java-runtime") &&
                attrs["org.jetbrains.kotlin.platform.type"] in listOf(null, "jvm") && attrs["org.gradle.category"] == "library"
            check(metadata && (common || javaAlias) && attrs["org.jetbrains.kotlin.native.target"] == null) {
                "Grid metadata supplement selected outside common metadata: $id"
            }
        }
        mapOf("component" to id.displayName, "attributes" to attrs, "files" to records(leaves(artifact.file)))
    })
}
fun commonizerRecords(): Map<String, Any> {
    val configuration = configurations.getByName(commonizerTools.getValue("configuration").toString())
    val artifacts = configuration.resolvedConfiguration.resolvedArtifacts.map { artifact ->
        val id = artifact.moduleVersion.id
        val ga = "${id.group}:${id.name}"
        check(commonizerPins[ga] == id.version) { "Unpinned commonizer tool: $id" }
        val expected = asMap(commonizerArtifacts.getValue(ga))
        val hash = sha(artifact.file)
        check(hash == expected.getValue("sha256") && artifact.file.length() == (expected.getValue("size") as Number).toLong()) {
            "Commonizer tool bytes differ: $id"
        }
        mapOf("gav" to id.toString(), "path" to artifact.file.absolutePath, "sha256" to hash, "size" to artifact.file.length())
    }
    check(artifacts.map { it.getValue("gav") }.toSet() == commonizerPins.map { "${it.key}:${it.value}" }.toSet()) {
        "Commonizer tool artifact set differs"
    }
    val edges = configuration.incoming.resolutionResult.allDependencies.map { edge ->
        if (edge !is ResolvedDependencyResult) throw GradleException("Unresolved commonizer tool dependency: $edge", (edge as? UnresolvedDependencyResult)?.failure)
        mapOf("from" to edge.from.id.displayName, "requested" to edge.requested.displayName, "selected" to edge.selected.id.displayName)
    }
    return mapOf("configuration" to configuration.name, "edges" to edges,
        "artifacts" to artifacts.sortedBy { it.getValue("gav").toString() })
}

tasks.register("resolveGrid") {
    doLast {
        check(gradle.gradleVersion == config.getValue("gradle"))
        listOf("compileCommonMainKotlinMetadata", "compileCommonMainWithMetadataCli", "allMetadataJar", "compileKotlinOhosX64", "compileKotlinOhosArm64").forEach { tasks.getByName(it) }
        evidence("resolve", mapOf("fingerprint" to fingerprint, "toolchain" to toolchain(),
            "metadataLauncher" to metadataLauncherRecords(configurations.getByName("commonMetadataCliLauncher")),
            "commonizer" to commonizerRecords(), "configurations" to resolution()))
    }
}
fun recordStage(name: String, target: String?) {
    tasks.register(name) {
        val compilerName = if (target == null) "compileCommonMainKotlinMetadata" else "compileKotlin$target"
        val producerName = if (target == null) "compileCommonMainWithMetadataCli" else compilerName
        dependsOn(producerName)
        if (target == null) dependsOn("allMetadataJar")
        outputs.upToDateWhen { false }
        doLast {
            val compiler = tasks.getByName(compilerName) as KotlinNativeCompile
            val sources = compiler.sources.files.filter { it.isFile && it.extension == "kt" }.map { it.canonicalFile }.toSet()
            // 从配方中的官方清单推导路径与hash，不把可变work manifest当作原源真值。
            val expected = (sourceInputs.getValue("sourceMembers") as List<*>).map(::asMap)
                .associate { upstreamSource(it.getValue("member").toString()).canonicalFile to it.getValue("sha256").toString() }
            check(expected.size == 18 && sources == expected.keys && expected.all { (path, hash) -> sha(path) == hash }) {
                "Complete Grid compiler source set or original bytes differ"
            }
            val producers = listOf(tasks.getByName(producerName)) + if (target == null) listOf(tasks.getByName("allMetadataJar")) else emptyList()
            producers.forEach { producer ->
                val state = producer.state
                check(state.executed && producer.enabled && !state.noSource && state.failure == null &&
                    state.skipMessage in listOf(null, "UP-TO-DATE", "FROM-CACHE")) { "Grid producer did not execute: ${producer.path}" }
                check(records(producer.outputs.files.files.flatMap(::leaves)).any { (it.getValue("size") as Long) > 0 })
            }
            val stage = if (target == null) "metadata" else if (target == "OhosX64") "native-x64" else "native-arm64"
            evidence(stage, mapOf("fingerprint" to fingerprint, "stage" to stage, "sourceCount" to 18,
                "sourceSetSha256" to sourceInputs.getValue("sourceSetSha256"), "sourceManifest" to records(listOf(manifestFile)).single(),
                "sources" to records(sources), "publicApi" to sourceInputs.getValue("publicApi"), "toolchain" to toolchain(),
                "compilerPlugins" to records(compiler.compilerPluginClasspath?.files.orEmpty()), "pluginOptions" to compiler.compilerPluginCommandLine,
                "metadataProducerReceipt" to if (target == null) records(listOf(layout.buildDirectory.file("metadata-cli/commonMain/producer.json").get().asFile)).single() else null,
                "commonMetadataCli" to if (target == null) readMap(layout.buildDirectory.file("metadata-cli/commonMain/producer.json").get().asFile) else null,
                "metadataLanguageOptions" to if (target == null) mapOf("languageVersion" to compiler.compilerOptions.languageVersion.orNull?.version,
                    "apiVersion" to compiler.compilerOptions.apiVersion.orNull?.version, "optIns" to compiler.compilerOptions.optIn.get().sorted(),
                    "freeCompilerArgs" to compiler.compilerOptions.freeCompilerArgs.get(),
                    "explicitApi" to project.extensions.getByType<KotlinMultiplatformExtension>().explicitApi?.name) else null,
                "metadataLibraries" to if (target == null) compiler.libraries.files.sortedBy { it.path }.map {
                    mapOf("path" to it.absolutePath, "files" to records(leaves(it)))
                } else null,
                "producers" to producers.map { mapOf("task" to it.path, "outputs" to records(it.outputs.files.files.flatMap(::leaves))) },
                "configurations" to resolution(), "runtime" to "NOT_RUN"))
        }
    }
}
recordStage("recordGridMetadata", null)
recordStage("recordGridX64", "OhosX64")
recordStage("recordGridArm64", "OhosArm64")
publishing {
    repositories { maven { name = "Port"; url = uri(providers.gradleProperty("portRepository").orElse(work.resolve("maven").absolutePath).get()) } }
    publications.withType<MavenPublication>().configureEach {
        artifact(file("legal/LICENSE.txt")) { classifier = "license"; extension = "txt" }
        if (name == "kotlinMultiplatform") {
            listOf("sources" to ("upstream-sources" to "jar"), "pom" to ("upstream-pom" to "xml"),
                "gmm" to ("upstream-module" to "json"), "upstreamBuild" to ("upstream-build" to "gradle.kts")).forEach { (key, format) ->
                artifact(file(asMap(sourceInputs.getValue(key)).getValue("path"))) { classifier = format.first; extension = format.second }
            }
        }
        pom {
            name.set("Grid Layout for Compose")
            description.set("Complete unmodified Grid 2.8.0 common sources for CPF OHOS dual ABI")
            licenses { license { name.set("Apache License, Version 2.0"); url.set("https://www.apache.org/licenses/LICENSE-2.0.txt") } }
            scm { url.set(model.getValue("repository").toString()) }
        }
    }
}
tasks.withType<AbstractPublishToMaven>().configureEach {
    doFirst {
        listOf("sources", "pom", "gmm", "upstreamBuild", "license").forEach { key ->
            val original = asMap(sourceInputs.getValue(key))
            check(sha(file(original.getValue("path"))) == original.getValue("sha256"))
        }
        listOf("metadata", "native-x64", "native-arm64").forEach { check(readMap(work.resolve("evidence/$it.json"))["fingerprint"] == fingerprint) }
    }
}
tasks.withType<Jar>().configureEach {
    isPreserveFileTimestamps = false
    isReproducibleFileOrder = true
    from(file("legal")) { into("META-INF/licenses/grid") }
    from(manifestFile) { into("META-INF/upstream") }
}
tasks.register("publishGrid") { dependsOn("publishAllPublicationsToPortRepository") }
