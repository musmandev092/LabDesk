"""LabDesk — laboratory management system."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _v

try:
    __version__ = _v("labdesk")
except PackageNotFoundError:
    # The AppImage/vendored layout copies this package into site-packages without
    # its .dist-info, so importlib.metadata can't find it and this fallback is the
    # authoritative version at runtime. Keep it == pyproject.toml [project].version.
    __version__ = "1.2.0"
