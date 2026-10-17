"""Shared fixtures for retrieval tests: synthetic_shop and eph_shop graphs built from committed
artifacts (no dbt), with their project source files from the repo."""

from pathlib import Path

import pytest

from dlens.graph import LineageGraph, build_graph_from_artifacts
from dlens.retrieval.chunks import ChunkSet, build_chunks

ROOT = Path(__file__).parents[3]
SS_TARGET = ROOT / "tests" / "fixtures" / "artifacts" / "synthetic_shop"
SS_PROJECT = ROOT / "corpora" / "synthetic_shop"
EPH_PROJECT = ROOT / "tests" / "fixtures" / "artifacts" / "eph_shop"
EPH_TARGET = EPH_PROJECT / "target"


@pytest.fixture(scope="session")
def ss_graph() -> LineageGraph:
    return build_graph_from_artifacts(SS_TARGET)[0]


@pytest.fixture(scope="session")
def ss_chunks(ss_graph: LineageGraph) -> ChunkSet:
    return build_chunks(ss_graph, SS_TARGET, SS_PROJECT)


@pytest.fixture(scope="session")
def eph_graph() -> LineageGraph:
    return build_graph_from_artifacts(EPH_TARGET)[0]


@pytest.fixture(scope="session")
def eph_chunks(eph_graph: LineageGraph) -> ChunkSet:
    return build_chunks(eph_graph, EPH_TARGET, EPH_PROJECT)
