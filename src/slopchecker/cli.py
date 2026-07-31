"""The `slopcheck` command. `run` lands in #6; `config` exists now so you can
verify your keys are wired up before any checks are written."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from slopchecker import __version__, config

app = typer.Typer(
    help="Automating slop checks for funding proposals.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


# Named explicitly: the function can't be `config` (that's the imported module),
# and typer would otherwise derive the command name "config-cmd" from it.
@app.command(name="config")
def config_cmd() -> None:
    """Show which API keys are set, without printing them."""
    config.load()

    table = Table(title="Credentials", title_justify="left")
    table.add_column("Variable")
    table.add_column("Status")
    table.add_column("Used for")

    for cred, display in config.status():
        if display is None:
            status = "[yellow]not set[/yellow]"
        else:
            status = f"[green]set[/green] {display}"
        table.add_row(cred.env_var, status, cred.purpose)

    console.print(table)
    console.print(f"\nLLM model: [cyan]{config.llm_model()}[/cyan]")
    console.print("Unset keys aren't fatal — those checks report as skipped.")


@app.command()
def version() -> None:
    """Print the version."""
    console.print(__version__)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
