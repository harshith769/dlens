import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _source_version(pyproject: Path) -> str:
    """Version from the source tree's pyproject.toml (the public demo runs src/ uninstalled)."""
    try:
        return str(tomllib.loads(pyproject.read_text())["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "0+unknown"


try:
    __version__ = version("dlens-lineage")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = _source_version(Path(__file__).resolve().parents[2] / "pyproject.toml")
