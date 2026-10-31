#!/usr/bin/env python3
"""用 schema/index.v1.schema.json 校验 index.json。

运行：uv run --with jsonschema python scripts/validate_index.py dist/index.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="校验 Iris 插件仓库 index.json")
    parser.add_argument("index", type=Path, help="要校验的 index.json")
    parser.add_argument(
        "--schema",
        type=Path,
        default=repo_root / "schema" / "index.v1.schema.json",
        help="JSON Schema 路径",
    )
    args = parser.parse_args(argv)

    try:
        schema = json.loads(args.schema.read_text(encoding="utf-8"))
        index = json.loads(args.index.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        print(f"错误：schema 自身不合法：{exc.message}", file=sys.stderr)
        return 1

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(index), key=lambda error: list(error.path))
    if errors:
        for error in errors:
            location = "/".join(str(part) for part in error.path) or "<root>"
            print(f"{location}: {error.message}", file=sys.stderr)
        print(f"失败：{len(errors)} 个错误", file=sys.stderr)
        return 1
    print(f"通过：{args.index} 符合 {args.schema}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
