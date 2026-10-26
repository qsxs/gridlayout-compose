#!/usr/bin/env bash
# 所有环境接线与受控构建阶段在同一安装 shell 中执行。
set -euo pipefail
PORT_HOME="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPOSITORY_HOME="$(CDPATH= cd -- "$PORT_HOME/.." && pwd)"
: "${HOME:?JitPack HOME is required}"
: "${JAVA_HOME:?JitPack JDK 17 JAVA_HOME is required}"
: "${GROUP:?JitPack GROUP is required}"
: "${ARTIFACT:?JitPack ARTIFACT is required}"
: "${VERSION:?JitPack VERSION is required}"
: "${GIT_COMMIT:?JitPack GIT_COMMIT is required}"
if [[ "$GROUP" != com.github.* || "$ARTIFACT" != gridlayout-compose ]]; then
    printf '%s\n' 'Unexpected JitPack GROUP/ARTIFACT' >&2
    exit 1
fi
if [[ ! "$VERSION" =~ ^[A-Za-z0-9_][A-Za-z0-9_.+-]*$ || "${VERSION^^}" == *SNAPSHOT* ]]; then
    printf '%s\n' 'JitPack VERSION must be an immutable commit or tag, without SNAPSHOT' >&2
    exit 1
fi
# 以服务提供的 commit 核对当前 checkout；浅 checkout 无需保留本地 tag ref。
checkout_commit="$(git -C "$REPOSITORY_HOME" rev-parse HEAD)"
if [[ "${GIT_COMMIT,,}" != "$checkout_commit" ]]; then
    printf '%s\n' 'JitPack GIT_COMMIT does not identify this checkout' >&2
    exit 1
fi
if [[ "$VERSION" =~ ^[0-9a-fA-F]{7,40}$ && "$checkout_commit" != "${VERSION,,}"* ]]; then
    printf '%s\n' 'JitPack commit VERSION does not identify this checkout' >&2
    exit 1
fi
# 在下载大归档之前确认公共工具已锁真实 commit。
python3 -B - "$PORT_HOME/tooling-lock.json" <<'PY'
import json
from pathlib import Path
import re
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10+ is required")
lock = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not re.fullmatch(r"[0-9a-f]{40}", lock.get("revision") or ""):
    raise SystemExit("A reviewed immutable tooling commit is required before JitPack install")
PY
native_home="$(python3 -B "$PORT_HOME/bootstrap-native.py" --destination "${CPF_BOOTSTRAP_ROOT:-$PORT_HOME/.local/bootstrap}")"
export CPF_NATIVE_HOME="$native_home"
export KONAN_DATA_DIR="$PORT_HOME/.local/konan"
unset CPF_PORT_TOOLING CPF_MAVEN_CACHE
port_args=(--jdk "$JAVA_HOME" --native-home "$CPF_NATIVE_HOME" --konan-data "$KONAN_DATA_DIR"
           --repository "$HOME/.m2/repository" --group "${GROUP}.${ARTIFACT}" --version "$VERSION")
for stage in Prepare Tasks Resolve Metadata NativeX64 NativeArm64 PublishLocal Verify; do
    python3 -B "$PORT_HOME/GridPort.py" "$stage" "${port_args[@]}" --online
done
