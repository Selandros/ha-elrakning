"""Validate that a custom_components root contains only importable domains."""

from __future__ import annotations

import keyword
import re
import sys
from pathlib import Path


DOMAIN_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


def invalid_custom_component_entries(root: Path) -> list[Path]:
    """Return root entries that must not be exposed to Home Assistant's importer."""
    if not root.is_dir():
        return [root]
    invalid = []
    for entry in sorted(root.iterdir(), key=lambda path: path.name):
        if entry.is_dir() and (not DOMAIN_NAME.fullmatch(entry.name) or keyword.iskeyword(entry.name)):
            invalid.append(entry)
        elif entry.is_file() and entry.suffix == ".py":
            invalid.append(entry)
    return invalid


def main() -> int:
    """Validate the path supplied on the command line."""
    root = Path(sys.argv[1]) if len(sys.argv) == 2 else Path("custom_components")
    invalid = invalid_custom_component_entries(root)
    if invalid:
        for entry in invalid:
            print(entry)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
