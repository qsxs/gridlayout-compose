#!/usr/bin/env bash
# 由安装 shell source；仅在系统解释器不足时选择隔离的固定便携运行时。
if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
    return 0
fi
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
    printf '%s\n' 'Portable Python bootstrap requires Linux x86_64' >&2
    return 1
fi
python_bootstrap_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$python_bootstrap_dir/bootstrap-python.env"
python_bootstrap_root="${CPF_PYTHON_BOOTSTRAP_ROOT:-$python_bootstrap_dir/.local/python-$CPF_PYTHON_VERSION-$CPF_PYTHON_RELEASE}"
mkdir -p "$python_bootstrap_root"
python_archive="$python_bootstrap_root/$CPF_PYTHON_ARCHIVE"
if [[ ! -f "$python_archive" ]]; then
    curl --fail --location --proto '=https' --tlsv1.2 --output "$python_archive" "$CPF_PYTHON_URL" || return 1
fi
if [[ "$(wc -c < "$python_archive")" -ne "$CPF_PYTHON_BYTES" ]]; then
    printf '%s\n' 'Portable Python archive size mismatch; preserved; choose a fresh bootstrap root' >&2
    return 1
fi
if ! printf '%s  %s\n' "$CPF_PYTHON_SHA256" "$python_archive" | sha256sum --check --status; then
    printf '%s\n' 'Portable Python archive SHA256 mismatch; preserved; choose a fresh bootstrap root' >&2
    return 1
fi
python_ready="$python_bootstrap_root/bundle.ready"
if [[ -f "$python_ready" ]]; then
    if [[ "$(< "$python_ready")" != "$CPF_PYTHON_SHA256" ]]; then
        printf '%s\n' 'Portable Python ready SHA256 mismatch; preserved; choose a fresh bootstrap root' >&2
        return 1
    fi
else
    if [[ -e "$python_bootstrap_root/python" ]]; then
        printf '%s\n' 'Portable Python extraction is incomplete; preserved; choose a fresh bootstrap root' >&2
        return 1
    fi
    tar -xzf "$python_archive" -C "$python_bootstrap_root" || return 1
fi
python_runtime="$python_bootstrap_root/python/bin/python3"
if [[ ! -x "$python_runtime" ]] || ! "$python_runtime" -c 'import sys; raise SystemExit(sys.version_info[:3] != tuple(map(int, sys.argv[1].split("."))))' "$CPF_PYTHON_VERSION"; then
    printf '%s\n' 'Extracted portable Python version does not match the fixed host runtime' >&2
    return 1
fi
printf '%s\n' "$CPF_PYTHON_SHA256" > "$python_ready"
export PATH="$python_bootstrap_root/python/bin:$PATH"
hash -r
