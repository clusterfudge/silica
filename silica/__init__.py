"""silica - A command line tool for creating workspaces for agents on top of piku."""

try:
    from silica._version import __version__
except ImportError:
    # Fallback version if setuptools_scm hasn't generated the version file
    __version__ = "0.1.0"
