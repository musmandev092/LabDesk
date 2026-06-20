"""Entry point for a Nuitka standalone/onefile build of LabDesk.

Nuitka compiles from a real entry script (not `-m package`), so this thin wrapper
just calls the app's CLI entry. The whole `labdesk` package is pulled in via
--include-package=labdesk in the build invocation (see scripts/build_app.sh and
scripts/build_release.sh).
"""

from __future__ import annotations

from labdesk.app import run_cli

if __name__ == "__main__":
    raise SystemExit(run_cli())
