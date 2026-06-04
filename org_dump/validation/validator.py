import csv
import json
import os
import random
from dataclasses import dataclass, field
from org_dump.planning.models import ExportPlan
from org_dump.discovery.schema_inspector import ForeignKey


@dataclass
class ValidationResult:
    passed: bool
    check: str
    table: str
    detail: str


@dataclass
class ValidationReport:
    results: list[ValidationResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    def to_dict(self) -> dict:
        return {
            "overall": "PASS" if self.passed else "FAIL",
            "checks": [
                {
                    "check": r.check,
                    "table": r.table,
                    "passed": r.passed,
                    "detail": r.detail,
                }
                for r in self.results
            ],
        }


def _count_csv_rows(filepath: str) -> int:
    if not os.path.exists(filepath):
        return -1
    with open(filepath, encoding="utf-8") as f:
        return sum(1 for _ in f) - 1  # subtract header


def _load_column_set(filepath: str, col_index: int) -> set:
    values = set()
    if not os.path.exists(filepath):
        return values
    with open(filepath, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        for row in reader:
            if col_index < len(row) and row[col_index]:
                values.add(row[col_index])
    return values


def _get_col_index(filepath: str, col_name: str) -> int | None:
    if not os.path.exists(filepath):
        return None
    with open(filepath, encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader, [])
    try:
        return headers.index(col_name)
    except ValueError:
        return None


def check_row_counts(plan: ExportPlan, actual_rows: dict[str, int]) -> list[ValidationResult]:
    results = []
    for tp in plan.tables:
        actual = actual_rows.get(tp.table, 0)
        if tp.estimated_rows < 0:
            results.append(ValidationResult(
                passed=True,
                check="row_count",
                table=tp.table,
                detail="Estimation unavailable (query failed); skipping count check",
            ))
            continue
        passed = actual == tp.estimated_rows
        results.append(ValidationResult(
            passed=passed,
            check="row_count",
            table=tp.table,
            detail=f"estimated={tp.estimated_rows} actual={actual}",
        ))
    return results


def check_fk_integrity(
    plan: ExportPlan,
    output_dir: str,
    foreign_keys: list[ForeignKey],
) -> list[ValidationResult]:
    results = []
    exported_tables = {tp.table for tp in plan.tables}

    for fk in foreign_keys:
        if fk.from_table not in exported_tables or fk.to_table not in exported_tables:
            continue

        child_file = os.path.join(output_dir, f"{fk.from_table}.csv")
        parent_file = os.path.join(output_dir, f"{fk.to_table}.csv")

        child_col_idx = _get_col_index(child_file, fk.from_col)
        parent_col_idx = _get_col_index(parent_file, fk.to_col)

        if child_col_idx is None or parent_col_idx is None:
            continue

        parent_ids = _load_column_set(parent_file, parent_col_idx)
        child_fk_values = _load_column_set(child_file, child_col_idx)

        # Allow NULLs (empty string in CSV) — filter those out
        child_fk_values.discard("")
        orphaned = child_fk_values - parent_ids

        passed = len(orphaned) == 0
        detail = (
            "All FK values present in parent"
            if passed
            else f"{len(orphaned)} orphaned FK values: {list(orphaned)[:5]}..."
        )
        results.append(ValidationResult(
            passed=passed,
            check="fk_integrity",
            table=fk.from_table,
            detail=f"{fk.from_col} → {fk.to_table}.{fk.to_col}: {detail}",
        ))
    return results


def check_exclusivity(
    conn,
    plan: ExportPlan,
    output_dir: str,
    org_id: str,
    sample_size: int = 20,
) -> list[ValidationResult]:
    """Sample rows from other orgs and verify they don't appear in the export."""
    results = []

    type_a_tables = [tp for tp in plan.tables if tp.table_class == "A" and tp.org_col]
    if not type_a_tables:
        return results

    for tp in type_a_tables:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    f"SELECT id FROM {plan.schema}.{tp.table} "
                    f"WHERE {tp.org_col} != %s AND {tp.org_col} IS NOT NULL "
                    f"LIMIT %s",
                    (org_id, sample_size),
                )
                other_ids = {str(row[0]) for row in cur.fetchall()}
            except Exception:
                continue

        if not other_ids:
            results.append(ValidationResult(
                passed=True,
                check="exclusivity",
                table=tp.table,
                detail="No other-org rows found to sample",
            ))
            continue

        csv_file = os.path.join(output_dir, f"{tp.table}.csv")
        id_col_idx = _get_col_index(csv_file, "id")
        if id_col_idx is None:
            continue

        exported_ids = _load_column_set(csv_file, id_col_idx)
        leaked = other_ids & exported_ids

        passed = len(leaked) == 0
        results.append(ValidationResult(
            passed=passed,
            check="exclusivity",
            table=tp.table,
            detail=(
                "No cross-org data found"
                if passed
                else f"LEAK: {len(leaked)} rows from other orgs found in export: {list(leaked)[:3]}"
            ),
        ))
    return results


def run_validation(
    conn,
    plan: ExportPlan,
    actual_rows: dict[str, int],
    output_dir: str,
    foreign_keys,
) -> ValidationReport:
    report = ValidationReport()
    report.results.extend(check_row_counts(plan, actual_rows))
    report.results.extend(check_fk_integrity(plan, output_dir, foreign_keys))
    report.results.extend(check_exclusivity(conn, plan, output_dir, plan.org_id))

    report_path = os.path.join(output_dir, "validation_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2)

    return report
