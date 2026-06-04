import json
import os
from datetime import datetime, timezone
from org_dump.planning.models import ExportPlan, TablePlan


def write_manifest(plan: ExportPlan, actual_rows: dict[str, int], output_dir: str) -> str:
    tables_info = []
    for tp in plan.tables:
        tables_info.append({
            "table": tp.table,
            "file": os.path.basename(tp.output_file),
            "table_class": tp.table_class,
            "strategy": tp.strategy,
            "anchor_table": tp.anchor_table,
            "estimated_rows": tp.estimated_rows,
            "actual_rows": actual_rows.get(tp.table, 0),
            "columns": tp.columns,
            "query": tp.export_query,
        })

    manifest = {
        "org_id": plan.org_id,
        "schema": plan.schema,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "total_tables_exported": len(plan.tables),
        "total_tables_skipped": len(plan.skipped_tables),
        "skipped_tables": plan.skipped_tables,
        "custom_strategy_tables": plan.custom_tables,
        "tables": tables_info,
    }

    path = os.path.join(output_dir, "manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=str)
    return path
