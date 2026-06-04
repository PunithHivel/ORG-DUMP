import json
import os
import sys
import click
from rich.console import Console

console = Console()


@click.group()
def cli():
    """Org Data Dump Utility — export all data for a specific org from PostgreSQL."""


@cli.command()
@click.option(
    "--output", "-o",
    default=None,
    help="Write report to this file instead of the terminal (e.g. analysis_report.txt).",
)
def analyze(output):
    """Phase 1 only: discover schema and write classification report to a file."""
    from rich.console import Console as RichConsole
    from org_dump.config import load_config
    from org_dump.db import open_connection
    from org_dump.discovery.schema_inspector import SchemaInspector
    from org_dump.discovery.fk_graph import FKGraph
    from org_dump.discovery.classifier import classify_tables
    from org_dump.report.reporter import print_discovery_report

    cfg = load_config()

    # Default output path: OUTPUT_DIR/analysis_report.txt
    report_path = output or os.path.join(cfg.output_dir, "analysis_report.txt")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)

    with open_connection(cfg) as conn:
        inspector = SchemaInspector(conn, cfg.db_schema)
        tables = inspector.get_tables()
        columns = inspector.get_columns()
        foreign_keys = inspector.get_foreign_keys()

        fk_graph = FKGraph(foreign_keys)
        classifications = classify_tables(tables, columns, fk_graph, org_id=cfg.org_id)

        # Run actual COUNT(*) per org for Type A tables — stats estimates are unreliable
        row_counts = inspector.get_org_row_counts(classifications, cfg.org_id)

    with open(report_path, "w", encoding="utf-8") as f:
        file_console = RichConsole(file=f, highlight=False, markup=True, width=120)
        print_discovery_report(classifications, row_counts, out=file_console)

    console.print(f"[green]Analysis report written to:[/green] [bold]{report_path}[/bold]")


@cli.command()
def dump():
    """Full pipeline: discover → plan → export → validate."""
    from org_dump.config import load_config
    from org_dump.db import open_connection, get_connection
    from org_dump.discovery.schema_inspector import SchemaInspector
    from org_dump.discovery.fk_graph import FKGraph
    from org_dump.discovery.classifier import classify_tables
    from org_dump.planning.export_planner import build_export_plan
    from org_dump.export.orchestrator import run_export
    from org_dump.validation.validator import run_validation
    from org_dump.report.reporter import print_discovery_report, print_validation_report

    cfg = load_config()
    os.makedirs(cfg.output_dir, exist_ok=True)

    console.print(f"\n[bold]Org Dump[/bold] — org_id=[cyan]{cfg.org_id}[/cyan] "
                  f"schema=[cyan]{cfg.db_schema}[/cyan] "
                  f"output=[cyan]{cfg.output_dir}[/cyan]\n")

    with open_connection(cfg) as conn:
        # Phase 1: Discovery
        console.rule("[bold blue]Phase 1: Schema Discovery")
        inspector = SchemaInspector(conn, cfg.db_schema)
        tables = inspector.get_tables()
        columns = inspector.get_columns()
        foreign_keys = inspector.get_foreign_keys()
        fk_graph = FKGraph(foreign_keys)
        classifications = classify_tables(tables, columns, fk_graph, org_id=cfg.org_id)
        row_counts = inspector.get_org_row_counts(classifications, cfg.org_id)
        print_discovery_report(classifications, row_counts)

        # Phase 2: Planning
        console.rule("[bold blue]Phase 2: Building Export Plan")
        primary_keys = inspector.get_primary_keys()
        plan = build_export_plan(
            conn, cfg,
            tables=tables,
            columns=columns,
            primary_keys=primary_keys,
            fk_graph=fk_graph,
            classifications=classifications,
            precomputed_counts=row_counts,
        )
        console.print(f"[green]Plan built:[/green] {len(plan.tables)} tables to export, "
                      f"{len(plan.skipped_tables)} skipped")
        if plan.custom_tables:
            console.print(f"[yellow]Tables with CUSTOM strategy (review manually):[/yellow] "
                          f"{plan.custom_tables}")

        # Phase 3: Export
        console.rule("[bold blue]Phase 3: Exporting Data")
        actual_rows = run_export(cfg, plan, cfg.output_dir)

        # Phase 4: Validation
        console.rule("[bold blue]Phase 4: Validation")
        report = run_validation(conn, plan, actual_rows, cfg.output_dir, foreign_keys)
        print_validation_report(report)

    status = "SUCCESS" if report.passed else "COMPLETED WITH WARNINGS"
    color = "green" if report.passed else "yellow"
    console.print(f"\n[bold {color}]{status}[/bold {color}]")
    console.print(f"Output: [bold]{cfg.output_dir}[/bold]")

    if not report.passed:
        sys.exit(1)


@cli.command()
@click.option("--output-dir", required=True, help="Directory containing the exported CSVs and manifest.json")
def validate(output_dir):
    """Re-validate an existing export directory against its manifest."""
    import json
    from org_dump.config import load_config
    from org_dump.db import open_connection
    from org_dump.discovery.schema_inspector import SchemaInspector
    from org_dump.discovery.fk_graph import FKGraph
    from org_dump.validation.validator import (
        ValidationReport, ValidationResult,
        check_row_counts, check_fk_integrity, check_exclusivity,
    )
    from org_dump.planning.models import ExportPlan, TablePlan
    from org_dump.report.reporter import print_validation_report

    manifest_path = os.path.join(output_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        console.print(f"[red]manifest.json not found in {output_dir}[/red]")
        sys.exit(1)

    with open(manifest_path) as f:
        manifest = json.load(f)

    cfg = load_config()

    # Reconstruct a minimal ExportPlan from the manifest
    table_plans = []
    actual_rows = {}
    for t in manifest["tables"]:
        tp = TablePlan(
            table=t["table"],
            table_class=t["table_class"],
            strategy=t["strategy"],
            org_col=None,
            join_path=[],
            estimated_rows=t["estimated_rows"],
            output_file=os.path.join(output_dir, t["file"]),
            export_query=t["query"],
            columns=t["columns"],
            anchor_table=t.get("anchor_table"),
        )
        # Find org_col for Type A
        if t["table_class"] == "A":
            for col in t["columns"]:
                from org_dump.discovery.classifier import ORG_COLUMN_PATTERNS
                if col.lower() in ORG_COLUMN_PATTERNS:
                    tp.org_col = col
                    break
        table_plans.append(tp)
        actual_rows[t["table"]] = t["actual_rows"]

    plan = ExportPlan(
        org_id=manifest["org_id"],
        schema=manifest["schema"],
        tables=table_plans,
        skipped_tables=manifest.get("skipped_tables", []),
        custom_tables=manifest.get("custom_strategy_tables", []),
    )

    with open_connection(cfg) as conn:
        inspector = SchemaInspector(conn, cfg.db_schema)
        foreign_keys = inspector.get_foreign_keys()

        report = ValidationReport()
        report.results.extend(check_row_counts(plan, actual_rows))
        report.results.extend(check_fk_integrity(plan, output_dir, foreign_keys))
        report.results.extend(check_exclusivity(conn, plan, output_dir, plan.org_id))

    print_validation_report(report)

    report_path = os.path.join(output_dir, "validation_report.json")
    with open(report_path, "w") as f:
        json.dump(report.to_dict(), f, indent=2)
    console.print(f"Report saved to [bold]{report_path}[/bold]")

    if not report.passed:
        sys.exit(1)


if __name__ == "__main__":
    cli()
