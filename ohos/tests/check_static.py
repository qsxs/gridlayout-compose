"""只检查源、锁与可迁移身份；不运行 Gradle 或下载。"""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parents[1]
if len(sys.argv) != 2:
    raise SystemExit("usage: python -B tests/check_static.py <explicit-tooling-directory>")
spec = importlib.util.spec_from_file_location("grid_port_static", HERE / "GridPort.py")
grid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grid)
grid.PORT = grid.load_tooling(sys.argv[1])
for name in ("load", "record", "write", "physical", "copy_exact"):
    setattr(grid, name, getattr(grid.PORT, name))
grid.OPTIONS = SimpleNamespace(group=None, version=None, work_root=None, repository=None)
first = grid.plan()
grid.OPTIONS.work_root = str(HERE / ".local/relocated-output")
grid.OPTIONS.repository = str(HERE / ".local/relocated-maven")
relocated = grid.plan()
assert first["fingerprint"] == relocated["fingerprint"]
assert first["work"] != relocated["work"] and first["repository"] != relocated["repository"]
assert not any(row["path"].endswith(".md") for row in first["recipe"])
assert len(first["sources"]) == 18
assert not any(Path(row["path"]).is_absolute() for row in first["recipe"])
grid.OPTIONS.group = "example.grid"
assert grid.plan()["fingerprint"] != first["fingerprint"]
for path in HERE.rglob("*"):
    if ".local" in path.parts:
        continue
    if path.suffix == ".py":
        ast.parse(path.read_text(encoding="utf-8-sig"))
    elif path.suffix == ".json":
        json.loads(path.read_text(encoding="utf-8-sig"))
pins = grid.load(HERE / "dependency-pins.json")
metadata = grid.load(HERE / "metadata-pins.json")
launcher = grid.load(HERE / "metadata-toolchain.json")
assert len(pins) == 117 and len(metadata) == 15
assert len(launcher["launcherPins"]) == len(launcher["launcherArtifacts"]) == 8
print(json.dumps({"status": "STATIC_CHECKS_PASSED_PRODUCER_NOT_RUN", "sourceCount": 18,
                  "nativePins": len(pins), "metadataPins": len(metadata), "metadataLaunchers": 8,
                  "fingerprint": first["fingerprint"], "relocationIdentity": "equal", "documentationExcluded": True}, indent=2))
