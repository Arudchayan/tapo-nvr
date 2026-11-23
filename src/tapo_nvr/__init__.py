"""Private RTSP relay and recording tools for Tapo cameras."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("tapo-nvr")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0"

__all__ = ["__version__"]
