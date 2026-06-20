#!/usr/bin/env python3
"""Bake schema.sql + seed.sqlite + assets/ INTO the app as a Python module.

Nuitka's accelerated mode compiles Python modules into the binary but has no place
for loose data files. So instead of shipping schema.sql / seed.sqlite / assets next
to the installed binary (readable), the build runs this to emit
`src/labdesk/_embedded_data.py` (base64 of each), which Nuitka then compiles in.
At runtime `labdesk._resources` materialises them to a private temp dir (because
SQLite and Qt open by path); nothing data-like is left lying in the install folder.

  * Run by build_app.sh / build_release.sh right before Nuitka, removed afterwards.
  * The generated file is git-ignored. Dev/source runs don't have it and read the
    real schema.sql / seed.sqlite / assets directly — so this is build-only.
"""

from __future__ import annotations

import base64
import pathlib

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "labdesk"


def main() -> int:
    schema_b64 = base64.b64encode((PKG / "schema.sql").read_bytes()).decode()
    seed_b64 = base64.b64encode((PKG / "seed.sqlite").read_bytes()).decode()

    # Every file under assets/, keyed by its path relative to assets/ (posix form).
    assets: dict[str, str] = {}
    adir = PKG / "assets"
    for f in sorted(adir.rglob("*")):
        if f.is_file():
            rel = f.relative_to(adir).as_posix()
            assets[rel] = base64.b64encode(f.read_bytes()).decode()

    out = PKG / "_embedded_data.py"
    lines = [
        '"""GENERATED AT BUILD TIME — schema.sql + seed.sqlite + assets baked in.',
        'Do not edit or commit; build scripts create and then delete this."""',
        "",
        f'SCHEMA_B64 = "{schema_b64}"',
        f'SEED_B64 = "{seed_b64}"',
        "ASSETS = {",
    ]
    lines += [f'    "{rel}": "{b64}",' for rel, b64 in assets.items()]
    lines += ["}", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(
        f"✓ wrote {out} (schema {len(schema_b64)}B + seed {len(seed_b64)}B + "
        f"{len(assets)} assets, base64)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
