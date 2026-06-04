import os
from rich.progress import Progress, SpinnerColumn, TextColumn, MofNCompleteColumn, TimeElapsedColumn
from rich.console import Console
from org_dump.config import Config
from org_dump.discovery.schema_inspector import SchemaInspector, ColumnInfo
from org_dump.discovery.fk_graph import FKGraph
from org_dump.planning.query_builder import build_query, estimate_rows
from org_dump.planning.models import ExportPlan, TablePlan

_console = Console()


def build_export_plan(
    conn,
    cfg: Config,
    tables: list[str],
    columns: dict[str, list[ColumnInfo]],
    primary_keys: dict[str, list[str]],
    fk_graph: FKGraph,
    classifications: dict,
    precomputed_counts: dict[str, int],
) -> ExportPlan:
    """Build the export plan using pre-fetched Phase 1 artifacts — no redundant DB queries."""
    org_col_map = {
        t: c.org_col
        for t, c in classifications.items()
        if c.table_class == "A" and c.org_col
    }

    exportable = [
        t for t in tables
        if classifications[t].table_class != "C" and classifications[t].strategy != "SKIP"
    ]

    table_plans: list[TablePlan] = []
    skipped: list[str] = []
    custom: list[str] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=_console,
    ) as progress:
        task = progress.add_task("Building plan...", total=len(exportable))

        for table in tables:
            cl = classifications[table]

            if cl.table_class == "C" or cl.strategy == "SKIP":
                skipped.append(table)
                continue

            col_names = [c.name for c in columns.get(table, [])]
            query = build_query(cl, cfg.db_schema, columns.get(table, []), primary_keys, org_col_map)

            # Reuse Phase 1 counts for Type A — avoids 188 extra COUNT queries
            if table in precomputed_counts:
                est = precomputed_counts[table]
            else:
                est = estimate_rows(conn, query, cfg.org_id)

            output_file = os.path.join(cfg.output_dir, f"{table}.csv")

            table_plans.append(TablePlan(
                table=table,
                table_class=cl.table_class,
                strategy=cl.strategy,
                org_col=cl.org_col,
                join_path=cl.join_path,
                estimated_rows=est,
                output_file=output_file,
                export_query=query,
                columns=col_names,
                anchor_table=cl.anchor_table,
            ))

            if cl.strategy == "CUSTOM":
                custom.append(table)

            progress.update(task, advance=1, description=f"[bold blue]{table}")

    sorted_names = fk_graph.topological_sort([p.table for p in table_plans])
    name_order = {name: i for i, name in enumerate(sorted_names)}
    table_plans.sort(key=lambda p: name_order.get(p.table, 9999))

    return ExportPlan(
        org_id=cfg.org_id,
        schema=cfg.db_schema,
        tables=table_plans,
        skipped_tables=skipped,
        custom_tables=custom,
    )
