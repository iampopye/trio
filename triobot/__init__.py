"""trio - the open agent framework for every platform."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

try:
    from importlib.metadata import version as _pkg_version, PackageNotFoundError
    try:
        __version__ = _pkg_version("triobot")
    except PackageNotFoundError:
        __version__ = "0.2.3"
    del _pkg_version, PackageNotFoundError
except ImportError:
    __version__ = "0.2.3"

__app_name__ = "trio"
