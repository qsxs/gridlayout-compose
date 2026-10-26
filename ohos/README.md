# Grid 2.8.0 OHOS 构建入口

本目录在上游 Grid 历史布局之外提供独立的 OHOS producer。固定上游 commit 为 `cdc87301e25c85639ae2b52603e08915f2d38610`（`v2.8.0`）。构建直接读取 `../grid/src/commonMain/kotlin` 的全部 18 份原源，不解包、复制、裁剪或修改 Kotlin 源码，也不改 Android/iOS、samples 或上游根构建。

HorizontalGrid、VerticalGrid、BoxGrid、所有 cells/track/scope/span/modifier 与注解均保留。`source-inputs.json` 保留原 JAR 成员名、逐源大小/SHA256、完整源集合摘要与声明索引；Prepare 逐字节对照官方 sources JAR 和上游文件。`vendor` 内的 sources/POM/GMM/build 与 `legal/LICENSE.txt` 为固定原件，构建与发布保留追溯材料。

## 工具链与编译语义

Kotlin/KGP/Native/Compose compiler 固定 `2.4.20-0.1.0-08`，Compose 依赖固定 `1.12.0-0.1.0-11`，Gradle 固定 `9.5.0`（wrapper 原件和分发 SHA256 均锁定）。三条上游 runtime/foundation/ui-util 的 `implementation` 声明保留；117 个 Native/root pins 和 15 个 common metadata 补充 pins 没有降级。

冻结原端口曾因原 JvmInline 注解触发标准 common metadata 的 OptionalExpectation 错误，故仅 common metadata 沿用同版本公共 `KotlinMetadataCompiler` JavaExec；双 ABI 继续标准 KGP。八个 launcher 的 GAV、大小、SHA256 锁保留，JavaExec 继承原 KGP 的 sources、libraries、插件、插件参数与所有语言/API/optIn/freeCompilerArgs/explicitApi 语义。原 metadata 任务禁用，common 输出和 builtBy 唯一绑定公共 CLI 的真实 Klib；验证继续核对参数文件、退出码、launcher、绑定、真实产物和十八原源。此为既有端口编译入口的迁移，不表示已确定 CPF 编译器前端根因。

## 独立使用

需要 Python 3.10+、JDK 17 和固定 `.08` Kotlin/Native 分发。本入口只编译 Kotlin klib，标准 Konan 使用分发原有配置按需下载其固定 OHOS sysroot/LLVM 依赖，不要求安装 DevEco 或外部 SDK。外部 SDK 仅供显式需要它的扩展入口可选透传；不改 `konan.properties`，不替换依赖版本。路径通过参数或环境注入，不读取应用仓库配置：

| 输入 | 参数或环境 |
| --- | --- |
| 工具仓 | `--tooling` / `CPF_PORT_TOOLING`（显式本地目录，仍核内容锁） |
| JDK | `--jdk` / `JAVA_HOME` |
| Kotlin/Native | `--native-home` / `CPF_NATIVE_HOME` |
| 外部 OHOS SDK（可选） | `--ohos-sdk` / `OHOS_SDK_HOME`；仅显式提供时检查目录并透传 |
| Konan 数据 | `--konan-data` / `KONAN_DATA_DIR`；默认 work 内 `konan` |
| Gradle 分发 | 默认独立 wrapper 正常下载；`--gradle-distribution` 可指向现有 Gradle 9.5.0 home |
| Gradle user home | `--gradle-user-home`；默认 work 内隔离目录 |
| Maven 缓存来源 | `--maven-cache` / `CPF_MAVEN_CACHE` 指向 `modules-2/files-2.1`；可省略 |
| 构建输出根 | `--work-root` / `CPF_WORK_ROOT`；默认本目录 `.local` |
| 本地 Maven 输出 | `--repository`；默认 work 内 `maven` |
| 发布坐标 | `--group` / `CPF_PUBLISH_GROUP`，`--version` / `CPF_PUBLISH_VERSION` |

`tooling-lock.json` 固定独立 `cpf-port-tooling` 仓库、真实 commit 和所需文件内容。当前锁定公开 commit `d063c7c70ffbc3f241d7e8bdd184add33dc9a009`。省略 `--tooling` 会从该固定 GitHub 公共归档匿名下载已声明且逐文件校验的工具，保留在 `.local/tooling/<commit>`；显式本地工具目录也核对同一内容锁，不从相邻库随意导入。

在本目录执行（PowerShell 用 `python`，POSIX 可用 `python3`）：

```powershell
# 当前可做的轻量检查；工具目录必须显式指定。
python -B .\tests\check_static.py <tooling-checkout>
python -B .\GridPort.py Plan --tooling <tooling-checkout>
python -B .\GridPort.py Prepare --tooling <tooling-checkout>
```

维护者补齐工具锁并允许真实资源窗口后，按同一套参数串行执行：

```powershell
$portArgs = @('--tooling', '<tooling-checkout>', '--jdk', '<jdk17>', '--native-home', '<cpf08-native>')
python -B .\GridPort.py Tasks @portArgs --online
python -B .\GridPort.py Resolve @portArgs --online
python -B .\GridPort.py Metadata @portArgs --online
python -B .\GridPort.py NativeX64 @portArgs --online
python -B .\GridPort.py NativeArm64 @portArgs --online
python -B .\GridPort.py Publish @portArgs --online
python -B .\GridPort.py Verify @portArgs
```

每次重试使用新的 `--attempt N`，失败和夹具均保留。默认一个 worker、关闭 Gradle parallel；不清理共享缓存，不复制整套 Native/SDK 缓存。可显式复用现有缓存目录。Maven snapshot 只暴露 pins/工具白名单内且所有必需文件均核对完整的组件，保留原 GMM/POM 字节和 URL；缺件交给同版本正常远端解析。未指定 `--online` 时沿用离线模式。

Plan 身份只包含源码、必需配方、工具锁和会影响 metadata 的 GAV 输入；本机路径、输出位置、缓存、凭据和普通 README 不进入指纹。命令、环境路径和实际工具信息仅记录在本地 invocation/evidence。Prepare 不运行 Gradle。

## 发布与消费

group/version 同时作用于 `grid`、`grid-ohosx64`、`grid-ohosarm64`。`Publish` 写 `--repository` 指定的本地 Maven；完整 `publishToMavenLocal` 也已接线，CLI 的 `PublishLocal` 会将 `maven.repo.local` 设为同一 `--repository` 并执行完整校验。JitPack 若以后确认可用，需要显式指向其约定的 MavenLocal 目录，而非依赖任意开发机的 MavenLocal 内容。

Gradle repository 还可由 `-PportRepository=<URL-or-path>` 配置；公开远端必须在本地完整 Verify 通过后单独实测。生产发布任务（包括 MavenLocal）都保留来源哈希、metadata/x64/arm64 evidence 门禁。Verify 检查同套 GAV、root/leaf owner 与 available-at 相对 URL、实际文件大小/hash、root POM runtime 与 Native POM compile scope、common metadata/Native kotlin-api 依赖集合，以及准确 Native target、metadata 与 IR；不把源声明的 implementation 改称 api。

JitPack 候选坐标为 `com.github.qsxs.gridlayout-compose:grid:<immutable-commit-or-tag>`，另有两项 Native leaf。根 `jitpack.yml` 选择 OpenJDK 17 并调用 `ohos/jitpack-install.sh`。安装脚本在同一 shell 中配置 NativeHome/KonanData，按 JitPack 的 `GROUP/ARTIFACT/VERSION` 显式传入发布 group/version，并将 MavenLocal 定位到读取 `HOME` 得到的 `~/.m2/repository`；不会改写 `HOME`。发布版本遵循 JitPack 的不可变 commit/tag 约定并拒绝 SNAPSHOT；来源以服务提供的 `GIT_COMMIT` 与当前 HEAD 精确核对。commit 形式的 VERSION 另核对 HEAD 前缀，tag 形式保留为发布标识，不要求浅 checkout 内存在本地 tag ref。

`bootstrap-linux.json` 固定已核实的 Linux `.08` Native bundle URL、177306208 字节及 SHA256 `014411e74a0a0733aaf5cdcf7883e1b43c66f5b0a9fec390866bb8d459acad9f`。`bootstrap-native.py` 只下载并校验这一个 bundle，解压其原始分发并记录来源、实际 compilerVersion 与本地 receipt；全部归档与输出留在已忽略的 `.local`。标准 Konan 自行按需取得原配置的依赖，不手工填缓存或预装完整 SDK。公共工具必须先锁真实 commit，安装脚本会在大归档下载前检查此门禁，然后完整调用 Prepare/Tasks/Resolve/Metadata/NativeX64/NativeArm64/PublishLocal/Verify；源码、双 ABI 和发布验证均保留。

首轮 JitPack legacy 宿主实际停在 Python 3.10+ 前置检查，尚未进入 producer。第二候选入口在来源 commit 核对成功后，先复用系统 `python3 >= 3.10`；不足时由 `bootstrap-python.sh` 使用 `bootstrap-python.env` 固定的 Astral `20261021` CPython `3.13.17` Linux x86_64 包，核对 35356674 字节与 SHA256 后解压到独立 `.local`。只调整当前安装 shell 的 PATH 并打印真实 Python 版本，不使用 apt/sudo、源码编译或 pip，不改系统 Python。归档自带许可证与运行时保留在本地构建目录，不进入库制品或 Git。

安装脚本从成功 Prepare 的现有摘要取得实际 work 路径；仅某阶段失败时，将该阶段 stdout/stderr 文件的最后各 80 行输出到云日志，并保留原失败退出码。不会输出 invocation JSON 或环境，也不把日志放入 Maven。成功路径保持原八阶段链和双 ABI 校验。

这些文件是第二个候选入口。JitPack 修正后的实际冷构建、15 分钟上限、Konan 按需下载、最终 root/leaf 重定向 GMM/klib 下载和匿名消费均为 NOT_RUN，不能据此宣布 JitPack 已支持。最终验收需要匿名、隔离的远端 consumer，既不使用应用源码、producer 工作区，也不输入开发机 MavenLocal；metadata 和双 ABI 均须通过。

## 上游同步与来源

同步上游时先更新上游源，再重新确认 18 源清单、sources/POM/GMM/build 原件、API 与许可证；不要把本目录构建规则混进上游根构建。若上游 API 变化，按仓库 AGENTS 要求更新 API dump；当前迁仓没有 API 变化。

原构建配方与校验取自应用冻结 commit `fe48ee6140d9224adf56b4b09efcfdc468ae8aa0` 的 `harmony-build/ports/grid`，公共工具最小闭包从同 commit 的 `ports/materialkolor/MaterialKolorPort.py` 抽取并参数化，未带入应用业务或凭据。工具来源、Apache-2.0 授权和原作者署名说明见独立工具仓 `PROVENANCE.json` 与 `NOTICE`。Grid 原源遵循 Apache-2.0，原许可证不变。

当前交付边界：完成独立入口的静态实现；Python/JSON 与轻量 helper 语义检查不能替代 Resolve、metadata、双 ABI、Publish/Verify、公开匿名下载或运行验证。所有真实 producer/发布/运行结论均等待维护者复审和资源窗口。
