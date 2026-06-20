#!/usr/bin/env python3
"""Bump the LabDesk version in BOTH places at once — the two that
scripts/check_version.py guards — so you can never bump one and forget the other:

  * pyproject.toml          [project].version  (the canonical version)
  * src/labdesk/__init__.py the fallback ``__version__ = "..."`` literal
                            (NOT the ``_v("labdesk")`` metadata line)

Usage:
    python scripts/bump_version.py 1.0.1

Stdlib only (no pytest), to match check_version.py / the lean shipped runtime.
After bumping, run `uv sync` (refreshes the editable install's metadata) and then
`python scripts/check_version.py` should print OK. Then commit and merge to main —
the build workflow cuts a `v<version>` release automatically.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# accept X.Y.Z, optionally with a -pre / +build suffix (e.g. 1.0.1, 1.1.0-rc1)
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?$")


def _replace_once(path: Path, pattern: str, repl: str) -> None:
    """Apply exactly one substitution; abort if the file doesn't have exactly one
    match (so a future refactor that moves the line can't silently no-op)."""
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(pattern, repl, text, count=1)
    if n != 1:
        raise SystemExit(
            f"!! expected exactly 1 match for {pattern!r} in "
            f"{path.relative_to(ROOT)}, found {n} — aborting (nothing written)."
        )
    path.write_text(new, encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != 2:  # noqa: PLR2004 (prog name + the version arg)
        print(__doc__)
        print("usage: python scripts/bump_version.py <new_version>   (e.g. 1.0.1)")
        return 2

    new = argv[1].strip().lstrip("v")
    if not _VERSION_RE.match(new):
        print(f"!! '{new}' is not a valid version — expected X.Y.Z (e.g. 1.0.1).")
        return 2

    pyproject = ROOT / "pyproject.toml"
    init = ROOT / "src" / "labdesk" / "__init__.py"
    old = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    if old == new:
        print(f"version is already {new} — nothing to do.")
        return 0

    # pyproject [project].version: the only line that starts (column 0) with `version`
    _replace_once(pyproject, r'(?m)^version = "[^"]+"', f'version = "{new}"')
    # __init__.py fallback literal (the `_v("labdesk")` line has no `"` after `= `)
    _replace_once(init, r'__version__ = "[^"]+"', f'__version__ = "{new}"')

    print(f"bumped {old} -> {new} in:")
    print(f"  - {pyproject.relative_to(ROOT)}")
    print(f"  - {init.relative_to(ROOT)}")
    print()
    print("next:")
    print("  uv sync                          # refresh the editable install metadata")
    print(
        f"  python scripts/check_version.py  # expect: OK — version is {new} everywhere"
    )
    print(f'  git commit -am "chore: release v{new}"   # then merge dev -> main')
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
