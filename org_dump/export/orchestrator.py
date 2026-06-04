import os
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.console import Console
from rich.table import Table
from org_dump.planning.models import ExportPlan
from org_dump.export.csv_writer import write_table_csv
from org_dump.export.manifest import write_manifest
from org_dump.db import get_connection

console = Console()

WORKERS = 8


def run_export(cfg, plan: ExportPlan, output_dir: str) -> dict[str, int]:
    """Export all tables in parallel. Opens WORKERS connections, one per thread."""
    os.makedirs(output_dir, exist_ok=True)
    actual_rows: dict[str, int] = {}
    errors: dict[str, str] = {}
    lock = threading.Lock()

    n_workers = min(WORKERS, len(plan.tables))
    # Distribute tables round-robin so each worker gets a balanced mix of
    # large and small tables (they're sorted alphabetically, not by size).
    chunks = [plan.tables[i::n_workers] for i in range(n_workers)]

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        TextColumn("{task.fields[status]}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        overall = progress.add_task(
            "[bold cyan]Overall",
            total=len(plan.tables),
            status=f"[green]0/{len(plan.tables)} done",
        )
        worker_tasks = [
            progress.add_task(
                f"[dim]Worker {i + 1}",
                total=len(chunks[i]),
                status="[dim]waiting...",
            )
            for i in range(n_workers)
        ]

        def worker(worker_id, chunk):
            conn = get_connection(cfg)
            try:
                for tp in chunk:
                    progress.update(worker_tasks[worker_id], status=f"[yellow]{tp.table}")
                    try:
                        count = write_table_csv(conn, tp.export_query, plan.org_id, tp.output_file)
                        with lock:
                            actual_rows[tp.table] = count
                            done = len(actual_rows) + len(errors)
                        progress.update(worker_tasks[worker_id], advance=1, status=f"[green]{tp.table} ({count} rows)")
                        progress.update(overall, advance=1, status=f"[green]{done}/{len(plan.tables)} done")
                    except Exception as exc:
                        with lock:
                            errors[tp.table] = str(exc)
                            actual_rows[tp.table] = -1
                            done = len(actual_rows) + len(errors)
                        progress.update(worker_tasks[worker_id], advance=1, status=f"[red]{tp.table} ERROR")
                        progress.update(overall, advance=1, status=f"[green]{done}/{len(plan.tables)} done")
                        progress.console.print(f"[red]  ERROR exporting {tp.table}: {exc}")
                progress.update(worker_tasks[worker_id], status="[dim]done")
            finally:
                conn.close()

        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futures = [executor.submit(worker, i, chunks[i]) for i in range(n_workers)]
            for f in as_completed(futures):
                f.result()  # re-raise any unexpected worker-level exception

    manifest_path = write_manifest(plan, actual_rows, output_dir)

    plan_path = os.path.join(output_dir, "plan.json")
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(_plan_to_dict(plan), f, indent=2, default=str)

    _print_export_summary(plan, actual_rows, errors, output_dir)
    return actual_rows


def _plan_to_dict(plan: ExportPlan) -> dict:
    return {
        "org_id": plan.org_id,
        "schema": plan.schema,
        "tables": [
            {
                "table": tp.table,
                "strategy": tp.strategy,
                "estimated_rows": tp.estimated_rows,
                "output_file": tp.output_file,
                "query": tp.export_query,
            }
            for tp in plan.tables
        ],
        "skipped_tables": plan.skipped_tables,
    }


def _print_export_summary(plan: ExportPlan, actual_rows: dict, errors: dict, output_dir: str):
    table = Table(title="Export Summary", show_lines=True)
    table.add_column("Table", style="cyan")
    table.add_column("Strategy", style="yellow")
    table.add_column("Est. Rows", justify="right")
    table.add_column("Actual Rows", justify="right")
    table.add_column("Status", justify="center")

    for tp in plan.tables:
        actual = actual_rows.get(tp.table, 0)
        status = "[red]ERROR" if tp.table in errors else (
            "[yellow]MISMATCH" if actual != tp.estimated_rows and tp.estimated_rows >= 0
            else "[green]OK"
        )
        table.add_row(
            tp.table,
            tp.strategy,
            str(tp.estimated_rows),
            str(actual),
            status,
        )

    console.print(table)
    console.print(f"\n[bold]Output directory:[/bold] {output_dir}")
    console.print(f"[bold]Tables exported:[/bold] {len(plan.tables)}")
    console.print(f"[bold]Tables skipped (Type C):[/bold] {len(plan.skipped_tables)}")
    if errors:
        console.print(f"[bold red]Tables with errors:[/bold red] {list(errors.keys())}")
