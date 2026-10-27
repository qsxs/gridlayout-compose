# Grid 2.8.0 OHOS 独立端口

Grid 迁仓的完整 producer、Pages 匿名字节与隔离 metadata/双 ABI 编译消费验收已通过。当前坐标只用于**独立 OHOS 构建**；Android/iOS 保持原上游坐标与 SDK，应用引用等 CPF 整体适配完成后另行切换。本批文档提交发布后安全暂停，不进入其他库。

## 已验坐标与证据

- 仓库：[GitHub Pages 临时 Maven](https://qsxs.github.io/cpf-maven/)。
- 根 GAV：`com.github.qsxs.gridlayout-compose:grid:2.8.0-cpf11-preview-ed3472803fdb-40432726650-1`。只依赖 `grid`，由根 GMM 选择 `grid-ohosx64`/`grid-ohosarm64`，不要直接引 leaf。
- 源提交：[`ed3472803fdb637d601391f62f43aba1bfea551f`](https://github.com/qsxs/gridlayout-compose/commit/ed3472803fdb637d601391f62f43aba1bfea551f)，上游固定为 [`v2.8.0 / cdc87301e25c`](https://github.com/cheonjaeung/gridlayout-compose/tree/cdc87301e25c85639ae2b52603e08915f2d38610)。
- [producer 40432726650/1](https://github.com/qsxs/cpf-port-tooling/actions/runs/40432726650/attempts/1) 八阶段通过；115 文件、474253B staging 及 Pages 全量匿名 hash 核验一致，[Maven 制品提交](https://github.com/qsxs/cpf-maven/commit/7aeb4841317a4db677a365bab458c5b281a31915) 不被后续 README 修改替代。
- [consumer 40440852307/1](https://github.com/qsxs/cpf-port-tooling/actions/runs/40440852307/attempts/1) 成功：标准 `compileCommonMainKotlinMetadata`、`compileKotlinOhosX64`、`compileKotlinOhosArm64` 均有真实源码/非空输出回执；HTTP 根 metadata/双 Klib 与 Gradle 输入、GMM owner/target 及 metadata 转换追溯匹配。

以下仅展示独立 OHOS 工程的消费入口。构建插件与完整 CPF 精确过滤配置以[已验 settings](https://github.com/qsxs/cpf-port-tooling/blob/5ee338b3847ae0395726a46b9d95bb7f8c5fb3e4/consumers/grid/settings.gradle.kts)、[build](https://github.com/qsxs/cpf-port-tooling/blob/5ee338b3847ae0395726a46b9d95bb7f8c5fb3e4/consumers/grid/build.gradle.kts)为准，固定 Kotlin/Compose compiler/Native `.08`、Compose runtime `.11` 和 Gradle9.5；不要直接复制为 Android/iOS 通用配置。

```kotlin
// settings.gradle.kts：保留公开 CPF 仓和所需标准远端；Grid group 只走 Pages。
dependencyResolutionManagement {
    repositories {
        exclusiveContent {
            forRepository { maven("https://qsxs.github.io/cpf-maven/") }
            filter { includeGroup("com.github.qsxs.gridlayout-compose") }
        }
        maven("https://maven.eazytec-cloud.com/nexus/repository/maven-develop/")
        maven("https://maven.eazytec-cloud.com/nexus/repository/maven-public/")
        google()
        mavenCentral()
    }
}
// 仅独立 OHOS source set。
kotlin {
    sourceSets {
        val commonMain by getting {
            dependencies {
                implementation("com.github.qsxs.gridlayout-compose:grid:2.8.0-cpf11-preview-ed3472803fdb-40432726650-1")
            }
        }
    }
}
```

## 编译语义与边界

直接编译 `../grid/src/commonMain/kotlin` 全部 18 份上游原源，源码、实现、注解和 API 未改，未另存 Kotlin 源码副本。`source-inputs.json`/vendor 原件与 Apache-2.0 许可证保留来源。完整 18 源已整体生产 metadata 与双 ABI 制品；这不表示每个 API 都做过运行测试。

Producer 保留冻结端口已验的同版本公共 `KotlinMetadataCompiler` JavaExec：继承原 KGP sources/libraries/插件/参数/语言选项，唯一绑定输出与 builtBy，八个 launcher 内容锁不变；仅此 Grid producer 因原 source 的 OptionalExpectation 问题沿用该入口，不泛化为所有库都需替换 metadata。Consumer 本次**标准 KGP metadata 入口已通过**，未替换其入口或删改注解。

库图仍为 117 Native/root pins、15 metadata 补充 pins。commonizer 九项工具、单项 Compose compiler 插件与独立 14 项 Native compiler host 闭包按精确 GAV/size/SHA256 在 Resolve 校验，Native 任务必经 host 门禁。新 host 选 annotations23.0.0、stdlib `.08`，原 metadata/commonizer 的 annotations13.0 独立保留；不改 SDK、sysroot/LLVM 版本或 Konan 原配置。

Consumer 仅一个 `VerticalGrid(columns = SimpleGridCells.Fixed(2))` 编译探针，三任务均输入同一 332B 文件；metadata 输出3文件，Native 两项各19文件。未做其他未用 API 专用夹具、UI、设备、可执行链接或 Android/iOS 回归；`link=NOT_RUN`、`runtime=NOT_RUN`。不声称全部 API 已运行。

## 复现与独立 producer

[已验 producer 工作流](https://github.com/qsxs/cpf-port-tooling/blob/30c5b7079193ae26440f6dc80fe6047df102348e/.github/workflows/grid-producer.yml)使用 tooling `30c5b7079193ae26440f6dc80fe6047df102348e`；[已验 consumer 工作流](https://github.com/qsxs/cpf-port-tooling/blob/5ee338b3847ae0395726a46b9d95bb7f8c5fb3e4/.github/workflows/grid-consumer.yml)使用 `5ee338b3847ae0395726a46b9d95bb7f8c5fb3e4`。helper 内容锁仍为 `d063c7c70ffbc3f241d7e8bdd184add33dc9a009`，它与工作流提交不是同一角色。工作流默认分支为 `codex/initial-port-tooling`，只手动触发。

- Producer 输入 `grid_sha=ed3472803fdb637d601391f62f43aba1bfea551f`，执行 Prepare→Tasks→Resolve→Metadata→NativeX64→NativeArm64→Publish→Verify。重跑得到带新 run id/attempt 的新唯一版本，不覆盖旧 GAV。
- Consumer 输入 `version=2.8.0-cpf11-preview-ed3472803fdb-40432726650-1` 与 `source_sha=ed3472803fdb637d601391f62f43aba1bfea551f`。source_sha 是验收标识；构建工具仍由 consumer 的 `toolchain-inputs.json` 固定到源提交与逐文件 SHA，不能指向 producer work 或库源码。
- `GridPort.py --repository` 是**本地 staging 目录**；它不部署 Pages。Root 完整核对后手动发布到 Pages 的实际 `codex/initial-maven` 分支，Actions artifacts 仅作中转。

常用本地 CLI 阶段为 `Plan/Prepare/Tasks/Resolve/Metadata/NativeX64/NativeArm64/Publish/Verify`。环境由 `--jdk`/`JAVA_HOME`、`--native-home`/`CPF_NATIVE_HOME`、`--konan-data`/`KONAN_DATA_DIR`、`--gradle-user-home`、`--work-root` 注入；默认 wrapper 正常取得固定 Gradle9.5，`--gradle-distribution` 可复用显式同版分发。`--maven-cache` 可选，外部 `--ohos-sdk` 仅显式需要时透传；纯 klib 构建使用 Native 原配置按需取得固定依赖。无参数路径读取应用仓。失败证据保留，重试换新 `--attempt`，不自动清理缓存或目录。

## 历史偏差与维护

参照冻结应用 `fe48ee6140d9224adf56b4b09efcfdc468ae8aa0` 的 `harmony-build/ports/grid` 与原 `harmony-build/ports/materialkolor/MaterialKolorPort.py`、初始 `plan-grid.json`、JitPack 试点计划、用户 Pages 决策及 `plan-pages-acceptance.json`：本端口把 JAR 展开源改为直接上游原源；暖缓存依赖改为冷云构建并补齐各自 host 工具锁；三轮 JitPack 试点停止后改为 Actions＋手动 Pages；Pages 使用既有 `codex/initial-maven`，而非初拟 main。Consumer 前两轮只修私有验收 DSL 可空类型/冗余检查与合法 JSON null，未动库或已发制品。

Windows urllib 的6890B截断被保留为本机传输观察：无认证 curl 已完整匹配，云 consumer 匿名 HTTP 也已完整成功，不能归因库或原件损坏。

维护时先选不可变上游 ref，对比原源/API/license 与来源原件，按变化更新 `source-inputs.json`/vendor；API 变化遵守上游 AGENTS 的 apiDump 规范。工具/SDK 基线不随上游自动升级；重新完成远程 producer、无覆盖 Pages 发布与独立 metadata/双 ABI consumer 后，才发新唯一版本，保留当前坐标用于回退。本批暂停不自动启动维护。

只有真实官方坐标提供所需完整 OHOS 双 ABI/API、兼容届时项目工具链，并通过独立消费核验后，才另行决定替换；不预填官方 GAV，不把现有非 OHOS 上游包视为已满足，也不自动升级其他库。App 引用仍等 CPF 整体完成。
