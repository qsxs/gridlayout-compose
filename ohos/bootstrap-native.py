"""固定 Linux Native bundle 的最小下载与解压入口；不编译或修改 Konan 配置。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from urllib.request import urlopen

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bootstrap(destination):
    if platform.system() != "Linux" or platform.machine().lower() not in ("x86_64", "amd64"):
        raise RuntimeError("This bootstrap requires Linux x86_64")
    manifest_path = HERE / "bootstrap-linux.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    config = json.loads((HERE / "port-config.json").read_text(encoding="utf-8"))
    if manifest["kotlinVersion"] != config["kotlin"]:
        raise RuntimeError("Bootstrap Kotlin version differs from the port lock")
    bundle = manifest["nativeBundle"]
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / (bundle["directory"] + ".tar.gz")
    if not archive.exists():
        print("Downloading pinned Kotlin/Native " + manifest["kotlinVersion"], file=sys.stderr)
        # 失败归档保留；再次尝试应指定新的 bootstrap 输出根，不自动清理。
        with urlopen(bundle["url"], timeout=60) as response, archive.open("xb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    actual_bytes, actual_sha256 = archive.stat().st_size, sha256(archive)
    if actual_bytes != bundle["bytes"] or actual_sha256 != bundle["sha256"]:
        raise RuntimeError("Native bundle size/SHA256 mismatch; retained at " + str(archive) +
                           "; select a fresh bootstrap root")
    native_home = destination / bundle["directory"]
    receipt_path = destination / "bootstrap-receipt.json"
    if not receipt_path.is_file():
        if native_home.exists():
            raise RuntimeError("Existing Native extraction has no completion receipt; select a fresh bootstrap root")
        subprocess.run(["tar", "-xzf", str(archive), "-C", str(destination)], check=True)
    properties = dict(line.split("=", 1) for line in (native_home / "konan/konan.properties")
                      .read_text(encoding="utf-8").splitlines() if "=" in line)
    compiler_version = properties.get("compilerVersion", "").strip()
    if compiler_version != manifest["kotlinVersion"]:
        raise RuntimeError("Extracted Native compilerVersion differs from the fixed bundle version")
    receipt = {"status": "PINNED_NATIVE_BUNDLE_READY_PRODUCER_NOT_RUN", "url": bundle["url"],
               "bytes": actual_bytes, "sha256": actual_sha256, "compilerVersion": compiler_version,
               "nativeHome": str(native_home), "manifestSha256": sha256(manifest_path),
               "configurationPolicy": manifest["configurationPolicy"], "cloudBuild": "NOT_RUN"}
    data = (json.dumps(receipt, indent=2) + "\n").encode()
    if receipt_path.exists() and receipt_path.read_bytes() != data:
        raise RuntimeError("Existing bootstrap receipt differs; select a fresh bootstrap root")
    receipt_path.write_bytes(data)
    return native_home


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, default=HERE / ".local/bootstrap")
    args = parser.parse_args()
    print(bootstrap(args.destination))
