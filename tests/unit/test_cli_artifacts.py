"""`dlens ingest --artifacts` and `--artifacts` on trace/impact/report (S06, ADR 0013)."""

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dlens.cli import app

runner = CliRunner()
EPH = Path(__file__).parents[1] / "fixtures" / "artifacts" / "eph_shop"


@pytest.fixture
def target(tmp_path: Path) -> Path:
    shutil.copytree(EPH, tmp_path / "eph_shop")
    return tmp_path / "eph_shop" / "target"


def test_ingest_artifacts_summary_and_cache(target: Path) -> None:
    r = runner.invoke(app, ["ingest", "--artifacts", str(target)])
    assert r.exit_code == 0, r.output
    assert "v12 (dbt 1.12.5), adapter duckdb -> dialect duckdb" in r.output
    assert "catalog:     catalog.json" in r.output
    assert "models:      5   seeds: 3" in r.output
    assert "coverage:    5 FULL · 0 PARTIAL · 0 TABLE_ONLY · 0 FAILED" in r.output
    assert r.output.rstrip().endswith("(built)")
    again = runner.invoke(app, ["ingest", "--artifacts", str(target)])
    assert again.output.rstrip().endswith("(cache reused)")


def test_ingest_artifacts_catalog_less_explains_coverage(target: Path) -> None:
    (target / "catalog.json").unlink()
    r = runner.invoke(app, ["ingest", "--artifacts", str(target)])
    assert r.exit_code == 0, r.output
    assert "NONE (catalog-less fallback)" in r.output
    assert "coverage:    4 FULL · 1 PARTIAL · 0 TABLE_ONLY · 0 FAILED" in r.output
    assert "PARTIAL     customer_orders  unexpanded * ×3" in r.output


def test_ingest_artifacts_dialect_and_out(target: Path, tmp_path: Path) -> None:
    out = tmp_path / "graphs"
    r = runner.invoke(
        app, ["ingest", "--artifacts", str(target), "--dialect", "postgres", "--out", str(out)]
    )
    assert r.exit_code == 0, r.output
    assert "dialect postgres" in r.output and (out / "graph.json").is_file()
    assert not (target / "dlens").exists()


def test_unknown_adapter_message(target: Path) -> None:
    manifest = target / "manifest.json"
    manifest.write_text(
        manifest.read_text().replace('"adapter_type": "duckdb"', '"adapter_type": "oracle"')
    )
    r = runner.invoke(app, ["ingest", "--artifacts", str(target)])
    assert r.exit_code == 1
    assert "adapter_type 'oracle' has no known sqlglot dialect. Pass --dialect" in r.output


def test_ingest_needs_exactly_one_input(target: Path) -> None:
    assert runner.invoke(app, ["ingest"]).exit_code == 2
    both = runner.invoke(app, ["ingest", str(target.parent), "--artifacts", str(target)])
    assert both.exit_code == 2 and "not both" in both.output
    stray = runner.invoke(app, ["ingest", str(target.parent), "--dialect", "postgres"])
    assert stray.exit_code == 2 and "--artifacts only" in stray.output


def test_trace_impact_report_read_the_artifact_graph(target: Path) -> None:
    assert runner.invoke(app, ["ingest", "--artifacts", str(target)]).exit_code == 0
    t = runner.invoke(app, ["trace", "customer_orders.amount_usd", "--artifacts", str(target)])
    assert t.exit_code == 0, t.output
    assert "order_payments.amount_usd" in t.output and "raw_payments.amount_cents" in t.output
    i = runner.invoke(app, ["impact", "raw_payments.amount_cents", "--artifacts", str(target)])
    assert i.exit_code == 0 and "customer_summary.lifetime_usd" in i.output
    rep = runner.invoke(app, ["report", "--artifacts", str(target)])
    assert rep.exit_code == 0 and "Models: 5 FULL" in rep.output


def test_trace_without_ingest_or_after_change_says_to_ingest(target: Path) -> None:
    r = runner.invoke(app, ["trace", "customer_orders.amount_usd", "--artifacts", str(target)])
    assert r.exit_code == 1 and "run `dlens ingest --artifacts" in r.output
    assert runner.invoke(app, ["ingest", "--artifacts", str(target)]).exit_code == 0
    (target / "catalog.json").unlink()
    r = runner.invoke(app, ["trace", "customer_orders.amount_usd", "--artifacts", str(target)])
    assert r.exit_code == 1 and "stale" in r.output


def test_non_utf8_output_streams_switch_to_utf8() -> None:
    """Windows CI: piped output was cp1252, and `trace`'s tree characters crashed it."""
    import io

    from dlens.cli import use_utf8

    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252")
    with pytest.raises(UnicodeEncodeError):
        stream.write("└─ ·")
        stream.flush()
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    use_utf8(stream)
    stream.write("└─ · ×")
    stream.flush()
    assert stream.encoding == "utf-8"
    use_utf8(object())  # not a text stream: left alone
