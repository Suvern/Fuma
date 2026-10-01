"""Render the design-first YAML contract; never replace it with a partial runtime schema."""

import argparse
import json
from pathlib import Path

import yaml

IDL_DIRECTORY = Path(__file__).resolve().parents[3] / "idl"
DEFAULT_SOURCE = IDL_DIRECTORY / "openapi.yaml"
DEFAULT_OUTPUT = IDL_DIRECTORY / "openapi.json"
HTTP_METHODS = {"get", "put", "post", "delete", "patch", "head", "options", "trace"}


def load_schema(source: Path = DEFAULT_SOURCE) -> dict:
    schema = yaml.safe_load(source.read_text(encoding="utf-8"))
    validate_schema(schema)
    return schema


def operations(schema: dict) -> dict[tuple[str, str], dict]:
    return {
        (path, method): operation
        for path, item in schema["paths"].items()
        for method, operation in item.items()
        if method in HTTP_METHODS
    }


def validate_schema(schema: dict) -> None:
    if schema.get("openapi") != "3.1.0":
        raise ValueError("Expected OpenAPI 3.1.0")
    seen = set()
    for (path, method), operation in operations(schema).items():
        operation_id = operation.get("operationId")
        if not operation_id or operation_id in seen:
            raise ValueError(f"Missing or duplicate operationId: {method} {path}")
        seen.add(operation_id)
        if not operation.get("responses"):
            raise ValueError(f"Missing responses: {operation_id}")

    def walk(value: object) -> None:
        if isinstance(value, dict):
            if "$ref" in value:
                pointer = value["$ref"]
                if not pointer.startswith("#/"):
                    raise ValueError(f"External references are not permitted: {pointer}")
                target = schema
                for segment in pointer[2:].split("/"):
                    target = target[segment.replace("~1", "/").replace("~0", "~")]
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(schema)


def render_schema(source: Path = DEFAULT_SOURCE) -> str:
    return json.dumps(load_schema(source), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def check_implementation(*, require_complete: bool = True) -> list[str]:
    # Import only for runtime checks: generation must not initialize application configuration.
    from app.main import create_app

    designed = operations(load_schema())
    implemented = operations(create_app().openapi())
    problems = []
    for key, operation in implemented.items():
        if key not in designed:
            problems.append(f"Undocumented operation: {key[1].upper()} {key[0]}")
        elif operation["operationId"] != designed[key]["operationId"]:
            problems.append(f"operationId differs: {key[1].upper()} {key[0]}")
    if require_complete:
        for path, method in sorted(designed.keys() - implemented.keys()):
            problems.append(f"Not implemented: {method.upper()} {path}")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description="Render or check the authoritative Fuma YAML IDL")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--check-implementation",
        action="store_true",
        help="Require all designed routes and operationIds in the runtime API (M1 release gate)",
    )
    args = parser.parse_args()
    if args.check_implementation:
        problems = check_implementation()
        if problems:
            raise SystemExit("\n".join(problems))
        print("All designed operations exist in the runtime API.")
    rendered = render_schema(args.source)
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != rendered:
            raise SystemExit("OpenAPI snapshot is stale. Run make idl.")
        print("OpenAPI YAML and JSON snapshot are synchronized.")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"Rendered {args.output}")


if __name__ == "__main__":
    main()
