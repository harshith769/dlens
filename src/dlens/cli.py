"""DLens command-line entry point."""

import typer

from dlens import __version__

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
