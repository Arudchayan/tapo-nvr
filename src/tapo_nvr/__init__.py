"""Private, camera-only RTSP relay for a self-hosted Frigate NVR."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("tapo-nvr")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0"

__all__ = ["__version__"]
