"""The public-demo bundle and demo mode (DLENS_DEMO=1): no dbt, no target/, no Ollama."""

import getpass
import json
import os
import re
import shutil
from pathlib import Path

import pytest

from dlens.ui import demo, view

BUNDLE = demo.ROOT / "demo"
ABS_JSON_STRING = re.compile(r'"(?:/[A-Za-z]|[A-Za-z]:[\\/])')


def _bundle_text_files() -> list[Path]:
    return [p for p in BUNDLE.rglob("*") if p.is_file() and p.suffix in {".json", ".sql", ".csv"}]


def test_demo_mode_is_opt_in(monkeypatch):
    monkeypatch.delenv("DLENS_DEMO", raising=False)
    assert not demo.enabled() and view.projects() is view.PROJECTS
    monkeypatch.setenv("DLENS_DEMO", "1")
    monkeypatch.setenv("DLENS_DEMO_DIR", "/x")
    assert demo.enabled() and view.projects() == {"synthetic_shop": Path("/x/synthetic_shop")}


def test_bundle_loads_and_holds_exactly_the_cited_files():
    project = demo.projects({})[demo.PROJECT]
    graph = demo.load_graph(project)  # also fails if the graph was built by another dlens version
    cited = demo.bundle_files(graph)
    assert cited and all((project / f).is_file() for f in cited)
    present = sorted(
        p.relative_to(project).as_posix()
        for p in project.rglob("*")
        if p.is_file() and p.name != demo.GRAPH_FILE
    )
    assert present == cited


def test_bundle_has_no_absolute_paths_or_usernames():
    files = _bundle_text_files()
    assert files
    user = getpass.getuser()
    for p in files:
        text = p.read_text(errors="replace")
        for needle in ("/home/", "/Users/", str(Path.home())):
            assert needle not in text, f"{p}: contains {needle}"
        if len(user) >= 4:
            assert user.lower() not in text.lower(), f"{p}: contains the username"
        if p.suffix == ".json":
            assert not ABS_JSON_STRING.search(text), f"{p}: absolute path in a JSON string"


def test_graph_json_paths_are_relative():
    raw = json.loads((BUNDLE / demo.PROJECT / demo.GRAPH_FILE).read_text())
    files = [m["file"] for m in raw["models"]] + [e["file"] for e in raw["derives"]]
    assert files and not any(Path(f).is_absolute() or ".." in Path(f).parts for f in files)


pytest.importorskip("streamlit", reason="needs the ui extra: uv sync --extra ui")


@pytest.fixture
def demo_app(monkeypatch, tmp_path):
    """The real app on a temp copy of the bundle; any dbt build or graph cache use raises."""
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    import dlens.graph as dg
    import dlens.graph.graph as dgg

    def boom(*a, **k):
        raise AssertionError("demo mode must not run dbt or read target/")

    st.cache_resource.clear()
    copy = tmp_path / "bundle"
    shutil.copytree(BUNDLE, copy)
    assert not (copy / demo.PROJECT / "target").exists()
    monkeypatch.setenv("DLENS_DEMO", "1")
    monkeypatch.setenv("DLENS_DEMO_DIR", str(copy))
    monkeypatch.setenv("DLENS_RUN_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(dg, "load_or_build", boom)
    monkeypatch.setattr(dg, "build_graph", boom)
    monkeypatch.setattr(dgg, "build_graph", boom)
    at = AppTest.from_file(str(view.ROOT / "src/dlens/ui/app.py"), default_timeout=30)
    at.run()
    return at


def test_app_boots_from_the_bundle_without_target(demo_app):
    at = demo_app
    assert not at.exception, at.exception
    assert not at.error, [e.value for e in at.error]
    assert any("15 models" in m.value for m in at.markdown)
    assert os.environ.get("DLENS_DEMO") == "1"  # forced on by the entrypoint
    at.selectbox(key="explore_col").set_value("fct_orders.order_total").run()
    assert not at.exception, at.exception
    htmls = [h.proto.body for h in at.get("html")]
    assert any("dl-src" in h for h in htmls)  # model SQL read from the bundle copy


# -- Cloud install -------------------------------------------------------------------------------

HEAVY = ("torch", "sentence-transformers", "lancedb", "bm25s", "dbt-core", "dbt-duckdb")


def _pins() -> dict[str, str]:
    lines = (BUNDLE / "requirements.txt").read_text().splitlines()
    reqs = [ln.split(";")[0].strip() for ln in lines if ln.strip() and not ln.startswith("#")]
    return dict(r.split("==") for r in reqs)


def test_cloud_requirements_are_light_and_fully_pinned():
    pins = _pins()
    assert not [p for p in pins if p in HEAVY or p.startswith("nvidia-")]
    for needed in ("streamlit", "google-genai", "ollama", "sqlglot", "networkx", "pydantic"):
        assert needed in pins, needed
    assert all(v for v in pins.values())


def test_source_version_reads_pyproject(tmp_path):
    from dlens import _source_version

    py = tmp_path / "pyproject.toml"
    py.write_text('[project]\nname = "x"\nversion = "9.8.7"\n')
    assert _source_version(py) == "9.8.7"
    assert _source_version(tmp_path / "missing.toml") == "0+unknown"


def test_cloud_entrypoint_boots_in_demo_mode(monkeypatch, tmp_path):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    st.cache_resource.clear()
    monkeypatch.setenv("DLENS_DEMO", "")  # registers the key: teardown removes what the app sets
    monkeypatch.delenv("DLENS_DEMO")
    monkeypatch.delenv("DLENS_DEMO_DIR", raising=False)
    monkeypatch.setenv("DLENS_RUN_DIR", str(tmp_path / "runs"))
    at = AppTest.from_file(str(BUNDLE / "streamlit_app.py"), default_timeout=30)
    at.run()
    assert not at.exception and not at.error
    assert any("15 models" in m.value for m in at.markdown)
    assert os.environ.get("DLENS_DEMO") == "1"  # forced on by the entrypoint


def test_demo_folder_is_excluded_from_the_package():
    import tomllib

    hatch = tomllib.loads((demo.ROOT / "pyproject.toml").read_text())["tool"]["hatch"]["build"]
    assert "demo" in hatch["targets"]["sdist"]["exclude"]
    assert hatch["targets"]["wheel"]["packages"] == ["src/dlens"]
