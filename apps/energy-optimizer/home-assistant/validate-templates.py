#!/usr/bin/env python3
"""Parse every embedded Jinja template in the exported Home Assistant YAML.

Run this in a Home Assistant/Python environment that provides PyYAML and Jinja2,
or install those two parser-only dependencies into a temporary environment. This
does not render templates or contact Home Assistant; validate-contract.rb covers
the repository-specific safety invariants.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

try:
    import yaml
    from jinja2 import Environment, TemplateSyntaxError
except ImportError as error:
    print(
        "Missing parser dependency. Run with PyYAML and Jinja2 available: "
        f"{error}",
        file=sys.stderr,
    )
    raise SystemExit(2) from error


ROOT = Path(__file__).resolve().parent
ENVIRONMENT = Environment()
template_count = 0
failures: list[str] = []


def inspect(value: Any, path: list[str]) -> None:
    global template_count

    if isinstance(value, dict):
        for key, item in value.items():
            inspect(item, [*path, str(key)])
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            inspect(item, [*path, str(index)])
        return
    if not isinstance(value, str) or not any(
        marker in value for marker in ("{{", "{%", "{#")
    ):
        return

    template_count += 1
    try:
        ENVIRONMENT.parse(value)
    except TemplateSyntaxError as error:
        failures.append(
            f"{'/'.join(path)}:{error.lineno}: {error.message}"
        )


for yaml_path in sorted(ROOT.glob("*.yaml")):
    with yaml_path.open(encoding="utf-8") as stream:
        inspect(yaml.safe_load(stream), [yaml_path.name])

if failures:
    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    raise SystemExit(1)

print(f"OK: parsed {template_count} embedded Jinja templates")
