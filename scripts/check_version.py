#!/usr/bin/env python3
"""Guard: the app version must be defined in exactly one place.

uv_build has no dynamic-version support, so the canonical version is hard-coded in
pyproject.toml's [project].version. The package's __version__ reads it from installed
metadata with a hard-coded fallback (for the dist-info-less AppImage layout). This
check asserts all three agree, so the UI footer and the "Updated to vX" notice can
never disagree again. Run manually or in CI:  python scripts/check_version.py

Stdlib only (no pytest) so it works against the same lean runtime the app ships.
"""

from __future__ import annotations

import sys
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = pyproject["project"]["version"]

    # Import the package version (this also exercises the metadata/fallback path).
    sys.path.insert(0, str(ROOT / "src"))
    import labdesk  # noqa: E402

    pkg = labdesk.__version__

    problems = []
    if pkg != declared:
        problems.append(
            f"labdesk.__version__ ({pkg}) != pyproject version ({declared})"
        )

    # When installed (dev/editable/wheel), the metadata must match too. In a bare
    # source/vendored layout there's no dist-info, so a miss here is expected, not a
    # failure — the fallback in __init__.py governs there.
    try:
        meta = version("labdesk")
        if meta != declared:
            problems.append(
                f"importlib.metadata version ({meta}) != pyproject version ({declared})"
            )
    except PackageNotFoundError:
        print("note: labdesk not installed (no dist-info) — metadata check skipped")

    if problems:
        print("VERSION MISMATCH:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK — version is {declared} everywhere")
    return 0


if __name__ == "__main__":
    sys.exit(main())
