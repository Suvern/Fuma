"""Generate backend DTOs from the reviewed, design-first OpenAPI contract."""

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    backend = Path(__file__).resolve().parents[2]
    command = [
        sys.executable,
        "-m",
        "datamodel_code_generator",
        "--input",
        str(backend.parent / "idl/openapi.yaml"),
        "--input-file-type",
        "openapi",
        "--output",
        str(backend / "app/api/contracts.py"),
        "--output-model-type",
        "pydantic_v2.BaseModel",
        "--target-python-version",
        "3.13",
        "--enum-field-as-literal",
        "all",
        "--use-standard-collections",
        "--use-union-operator",
        "--field-constraints",
        "--strict-nullable",
        "--disable-timestamp",
        "--formatters",
        "ruff-check",
        "ruff-format",
    ]
    if args.check:
        command.append("--check")
    subprocess.run(command, cwd=backend, check=True)


if __name__ == "__main__":
    main()
