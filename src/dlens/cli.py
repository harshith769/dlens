"""DLens command-line entry point."""

from pathlib import Path
from typing import Annotated

import typer

from dlens import __version__
from dlens.ingest import DbtError
from dlens.ingest import ingest as run_ingest

app = typer.Typer(help="DLens: column-level lineage and grounded Q&A for dbt projects.")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show version."
    ),
) -> None:
    """DLens: column-level lineage and grounded Q&A for dbt projects."""


@app.command()
def ingest(project_dir: Annotated[Path, typer.Argument(help="Path to a dbt project.")]) -> None:
    """Run dbt on PROJECT_DIR and summarise what DLens will see."""
    try:
        r = run_ingest(project_dir)
    except DbtError as e:
        typer.echo(f"ingest failed: {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo(f"models:      {len(r.manifest.models)}")
    typer.echo(f"seeds:       {len(r.manifest.seeds)}")
    typer.echo(f"sources:     {len(r.manifest.sources)}")
    typer.echo(f"exposures:   {len(r.manifest.exposures)}")
    typer.echo(f"columns:     {r.catalog.total_columns}")
    typer.echo(f"unmapped relations: {len(r.unmapped)}")
    for rel in r.unmapped:
        typer.echo(f"  - {rel}")
