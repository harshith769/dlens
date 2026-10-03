from importlib.metadata import version

import dlens


def test_version_comes_from_package_metadata() -> None:
    assert dlens.__version__ == version("dlens-lineage")
