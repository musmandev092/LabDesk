"""LabDesk — laboratory management system."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _v

try:
    __version__ = _v("labdesk")
except PackageNotFoundError:
    # Vendored layout lacks .dist-info; keep in sync with pyproject.toml version.
    __version__ = "1.2.8"
