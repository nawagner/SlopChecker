"""The `slopcheck` command: `run` (#6), `render` (#19), `config`."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from slopchecker import __version__, config
from slopchecker.ingest import LOADERS, ingest
from slopchecker.models import EvidenceReport

app = typer.Typer(
    help=("Automating slop checks for funding proposals. Start with: slopcheck run proposal.md"),
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _result_text(row) -> str:
    if row.status != "ok":
        return (
            f"[yellow]{row.status}[/yellow]"
            if row.status == "skipped"
            else f"[red]{row.status}[/red]"
        )
    if isinstance(row.result, bool):
        return "[green]yes[/green]" if row.result else "[red]no[/red]"
    return f"[cyan]{row.result:g}[/cyan]"  # a score: its own lane, not pass/fail


def _print_summary(report: EvidenceReport, written: list[Path]) -> None:
    table = Table(title=f"Checks — {report.document.file}", title_justify="left")
    table.add_column("Check")
    table.add_column("Result")
    table.add_column("Detail")
    for row in report.ledger:
        table.add_row(row.label or row.check, _result_text(row), row.detail or row.reason or "")
    console.print(table)

    c = report.counts()
    console.print(
        f"passed [green]{c['passed']}[/green] · failed [red]{c['failed']}[/red] · "
        f"scores {c['scores']} · skipped [yellow]{c['skipped']}[/yellow] · "
        f"errored [red]{c['errored']}[/red] · findings {len(report.findings)}"
    )
    console.print(
        f"Recommendation: [bold]{report.summary.recommendation}[/bold] "
        "(signals for a human reviewer — never an auto-reject)"
    )
    for path in written:
        console.print(f"Wrote [green]{path}[/green]")


def _dry_run(checks, n_docs: int) -> None:
    table = Table(title=f"Dry run — would run {len(checks)} check(s) on {n_docs} document(s)")
    # fold, don't ellipsize: ids are the --only/--skip vocabulary, and rich's
    # default drops end chars on narrow consoles (legacy Windows is ~1 char
    # narrower than CI, which is how this only ever broke locally).
    table.add_column("Check id", overflow="fold")
    table.add_column("Name")
    table.add_column("Tier")
    table.add_column("Est. cost/doc", justify="right")
    table.add_column("Network")
    for rc in checks:
        table.add_row(
            rc.meta.id,
            rc.meta.name,
            rc.meta.tier,
            f"${rc.meta.est_cost_usd:.4f}",
            "yes" if rc.meta.needs_network else "no",
        )
    console.print(table)
    total = sum(rc.meta.est_cost_usd for rc in checks) * n_docs
    console.print(f"Estimated total API spend: [bold]${total:.4f}[/bold]. No checks were run.")


@app.command()
def run(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            help="A proposal file (.pdf/.docx/.md/.html/.txt) or a folder of them",
        ),
    ],
    tier: Annotated[
        str,
        typer.Option("--tier", help="Which cost tier to run: deterministic, api, llm, or all"),
    ] = "all",
    only: Annotated[
        list[str] | None,
        typer.Option("--only", help="Run only this check id (repeatable)"),
    ] = None,
    skip: Annotated[
        list[str] | None,
        typer.Option("--skip", help="Skip this check id (repeatable)"),
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Folder for reports (default: ./slopcheck-reports)"),
    ] = None,
    formats: Annotated[
        str,
        typer.Option("--format", help="Report formats, comma-separated: json,html"),
    ] = "json",
    solicitation: Annotated[
        str | None,
        typer.Option("--solicitation", help="Solicitation the proposal responds to (id or path)"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="List what would run and the estimated cost; run nothing"),
    ] = False,
    batch: Annotated[
        bool,
        typer.Option("--batch", help="Treat PATH as a folder (implied when PATH is a folder)"),
    ] = False,
    no_cache: Annotated[
        bool,
        typer.Option("--no-cache", help="Re-fetch every DOI/URL instead of using the disk cache"),
    ] = False,
    cache_dir: Annotated[
        Path | None,
        typer.Option("--cache-dir", help="Where to cache lookups (default: ~/.cache/slopchecker)"),
    ] = None,
) -> None:
    """Check one proposal (or a folder of them) and write an evidence report.

    The report lists what each check found, what was skipped and why. It
    recommends human review where warranted; it never rejects anything on
    its own. Exit code is nonzero only if the tool itself fails — findings
    are evidence, not errors.
    """
    from slopchecker.pipeline import CheckContext, all_checks, discover, run_checks, select_checks
    from slopchecker.report import render_report

    config.load()
    discover()

    fmt_list = [f.strip() for f in formats.split(",") if f.strip()]
    bad = set(fmt_list) - {"json", "html"}
    if bad or not fmt_list:
        console.print(f"[red]--format must be json, html, or both; got '{formats}'[/red]")
        raise typer.Exit(2)

    try:
        checks = select_checks(all_checks(), tier=tier, only=only or [], skip=skip or [])
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        console.print("Known checks: " + ", ".join(rc.meta.id for rc in all_checks()))
        raise typer.Exit(2) from exc

    if batch and not path.is_dir():
        console.print("[red]--batch expects PATH to be a folder[/red]")
        raise typer.Exit(2)

    if path.is_dir():
        targets = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in LOADERS)
        if not targets:
            exts = ", ".join(sorted(LOADERS))
            console.print(f"[red]no readable proposals ({exts}) found in {path}[/red]")
            raise typer.Exit(1)
    else:
        targets = [path]

    if dry_run:
        _dry_run(checks, n_docs=len(targets))
        return

    out_dir = out or Path("slopcheck-reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx = CheckContext(solicitation=solicitation, no_cache=no_cache, cache_dir=cache_dir)

    rows: list[dict] = []
    for target in targets:
        result = ingest(target)
        if result.status != "ok" or result.document is None:
            # ingest() is total: errored results always carry an actionable reason.
            reason = result.reason or "unknown ingestion error"
            if len(targets) == 1:
                console.print(f"[red]{reason}[/red]")
                raise typer.Exit(1)
            # batch: a bad file is a gap, not a crash — record it and move on
            console.print(f"[yellow]skipping {target.name}: {reason}[/yellow]")
            rows.append({"file": target.name, "error": reason})
            continue
        doc = result.document

        report = run_checks(doc, checks, context=ctx)
        report.solicitation = solicitation

        written: list[Path] = []
        if "json" in fmt_list:
            json_path = out_dir / f"{target.stem}.report.json"
            # utf-8 explicitly: on Windows write_text defaults to cp1252, which
            # render_file's utf-8 read then rejects on any non-ASCII detail.
            json_path.write_text(report.model_dump_json(exclude_none=True, indent=2), "utf-8")
            written.append(json_path)
        if "html" in fmt_list:
            html_path = out_dir / f"{target.stem}.report.html"
            html_path.write_text(render_report(report.to_report_dict()), "utf-8")
            written.append(html_path)

        counts = report.counts()
        rows.append(
            {
                "file": target.name,
                "concerns": counts["failed"] + counts["errored"],
                **counts,
                "findings": len(report.findings),
                "report": str(written[0]) if written else "",
            }
        )
        if len(targets) == 1:
            _print_summary(report, written)

    if len(targets) > 1:
        _print_batch_summary(rows, out_dir)


def _print_batch_summary(rows: list[dict], out_dir: Path) -> None:
    """Ranked table + summary.csv: most concerning (failed + errored) first."""
    rows.sort(key=lambda r: r.get("concerns", -1), reverse=True)

    table = Table(title=f"Batch summary — {len(rows)} document(s), most concerns first")
    for col in ("File", "Concerns", "Passed", "Failed", "Scores", "Skipped", "Errored", "Findings"):
        table.add_column(col, justify="right" if col != "File" else "left")
    for r in rows:
        if "error" in r:
            table.add_row(r["file"], "[yellow]not read[/yellow]", "", "", "", "", "", "")
        else:
            table.add_row(
                r["file"],
                str(r["concerns"]),
                str(r["passed"]),
                str(r["failed"]),
                str(r["scores"]),
                str(r["skipped"]),
                str(r["errored"]),
                str(r["findings"]),
            )
    console.print(table)

    csv_path = out_dir / "summary.csv"
    fields = [
        "file",
        "concerns",
        "passed",
        "failed",
        "scores",
        "skipped",
        "errored",
        "findings",
        "report",
        "error",
    ]
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    console.print(f"Wrote [green]{csv_path}[/green]")


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
def render(
    report: Annotated[Path, typer.Argument(exists=True, help="Path to a report.json")],
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Output path")] = None,
    pdf: Annotated[bool, typer.Option("--pdf", help="Print to PDF via headless Chromium")] = False,
) -> None:
    """Render a report.json into the evidence report: HTML, or PDF with --pdf (#19)."""
    from slopchecker.report import render_file, render_pdf

    if pdf or (out is not None and out.suffix.lower() == ".pdf"):
        written = render_pdf(report, out)
    else:
        written = render_file(report, out)
    console.print(f"Wrote [green]{written}[/green]")


@app.command()
def version() -> None:
    """Print the version."""
    console.print(__version__)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
