"""Verify DB row counts against analysis_report.txt for org_id from config."""
import sys
from org_dump.config import load_config
from org_dump.db import open_connection

REPORT_PATH = "/Users/punith/Desktop/DUMP/analysis_report.txt"


def parse_report(path: str) -> list[tuple[str, str, int]]:
    """Return list of (table, org_col, expected_count)."""
    rows = []
    with open(path) as f:
        for line in f:
            if "DIRECT_ORG" not in line and "INDIRECT" not in line:
                continue
            parts = [p.strip() for p in line.split("│")]
            if len(parts) < 6:
                continue
            table, org_col, count_str = parts[1], parts[4], parts[5]
            if not table or not count_str.lstrip("-").isdigit():
                continue
            rows.append((table, org_col, int(count_str)))
    return rows


def main():
    cfg = load_config()
    entries = parse_report(REPORT_PATH)
    print(f"Verifying {len(entries)} tables for org_id={cfg.org_id}\n")

    match = mismatch = error = 0
    mismatches = []

    with open_connection(cfg) as conn:
        for table, org_col, expected in entries:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        f'SELECT COUNT(*) FROM "{table}" WHERE "{org_col}" = %s',
                        (int(cfg.org_id),),
                    )
                    actual = cur.fetchone()[0]
                conn.rollback()
            except Exception as exc:
                print(f"  ERROR {table}: {exc}")
                conn.rollback()
                error += 1
                continue

            if actual == expected:
                match += 1
            else:
                mismatch += 1
                mismatches.append((table, expected, actual))

    print(f"Results: {match} match  |  {mismatch} mismatch  |  {error} error\n")

    if mismatches:
        print(f"{'Table':<45} {'Report':>10} {'DB':>10} {'Diff':>10}")
        print("-" * 78)
        for table, exp, act in mismatches:
            print(f"{table:<45} {exp:>10} {act:>10} {act - exp:>+10}")

    return 1 if (mismatch or error) else 0


if __name__ == "__main__":
    sys.exit(main())
