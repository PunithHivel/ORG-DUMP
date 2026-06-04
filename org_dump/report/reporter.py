from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from org_dump.discovery.classifier import TableClassification
from org_dump.planning.models import ExportPlan
from org_dump.validation.validator import ValidationReport

console = Console()


def print_discovery_report(
    classifications: dict[str, TableClassification],
    row_counts: dict[str, int],
    out: Console | None = None,
):
    out = out or console
    type_counts = {"A": 0, "B": 0, "C": 0}
    skipped_names: list[str] = []

    # Only show tables that will actually be exported (Type A and B)
    active_table = Table(title="Tables to Export", show_lines=True)
    active_table.add_column("Table", style="cyan", no_wrap=True)
    active_table.add_column("Class", justify="center")
    active_table.add_column("Strategy", style="yellow")
    active_table.add_column("Org Column / Anchor", style="magenta")
    active_table.add_column("Org Rows", justify="right")

    for name, cl in sorted(classifications.items()):
        type_counts[cl.table_class] += 1
        count = row_counts.get(name, -1)
        count_str = str(count) if count >= 0 else "[dim]?[/dim]"
        if cl.table_class == "A":
            active_table.add_row(
                name,
                "[green]A (Direct)[/green]",
                cl.strategy,
                cl.org_col or "",
                count_str,
            )
        elif cl.table_class == "B":
            path_str = " → ".join(s.to_table for s in cl.join_path) if cl.join_path else ""
            active_table.add_row(
                name,
                "[yellow]B (Indirect)[/yellow]",
                cl.strategy,
                f"{cl.anchor_table} via [{path_str}]",
                count_str,
            )
        else:
            skipped_names.append(name)

    out.print(active_table)

    # Skipped tables: just a compact list, not a full table
    if skipped_names:
        skipped_table = Table(title=f"Skipped Tables ({len(skipped_names)} total)", show_lines=False, box=None)
        skipped_table.add_column("Table", style="dim")
        for name in skipped_names:
            skipped_table.add_row(name)
        out.print(skipped_table)

    out.print(
        f"\n[bold]Summary:[/bold] "
        f"[green]{type_counts['A']} will be exported (Direct)[/green]  "
        f"[yellow]{type_counts['B']} will be exported (Indirect)[/yellow]  "
        f"[dim]{type_counts['C']} skipped[/dim]"
    )


def print_validation_report(report: ValidationReport):
    table = Table(title="Validation Report", show_lines=True)
    table.add_column("Check", style="cyan")
    table.add_column("Table")
    table.add_column("Result", justify="center")
    table.add_column("Detail")

    for r in report.results:
        status = "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]"
        table.add_row(r.check, r.table, status, r.detail)

    console.print(table)

    passed = sum(1 for r in report.results if r.passed)
    failed = sum(1 for r in report.results if not r.passed)
    total = passed + failed

    if failed == 0:
        summary = f"[green]ALL {total} CHECKS PASSED[/green]"
    else:
        summary = (
            f"[green]{passed} passed[/green]  [red]{failed} failed[/red]  "
            f"[dim]({total} total)[/dim]"
        )
    console.print(Panel(summary, expand=False))
