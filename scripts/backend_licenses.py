"""Collect installed Python license texts; reject missing or unreviewed metadata."""

import argparse
import json
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--python", required=True, help="Python executable in the environment to inventory"
)
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
allowed = json.loads((root / "scripts/license-policy.json").read_text())["backend"]
result = subprocess.run(
    [
        "uvx",
        "pip-licenses==5.5.5",
        "--python",
        args.python,
        "--format=json",
        "--with-system",
        "--with-license-file",
        "--with-notice-file",
        "--no-license-path",
        "--ignore-packages",
        "fuma-backend",
    ],
    check=True,
    capture_output=True,
    text=True,
)
packages = json.loads(result.stdout)
if not packages:
    raise SystemExit("The Python dependency license inventory is empty")
for package in packages:
    if package["License"] not in allowed or package.get("LicenseText", "").strip() in {
        "",
        "UNKNOWN",
    }:
        raise SystemExit(f"Review license metadata/text for {package['Name']}@{package['Version']}")
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(packages, ensure_ascii=False, indent=2) + "\n")
print(f"Included license texts for {len(packages)} Python dependencies")
