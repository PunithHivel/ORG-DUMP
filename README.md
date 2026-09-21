# Org Dump

Exports all records for a specific organization from a PostgreSQL schema into CSV files. Designed for data migrations, org offboarding, or point-in-time snapshots.

## How it works

1. **Phase 1 — Schema Discovery**: Scans the schema, classifies every table as directly or indirectly org-owned, and counts rows for the target org.
2. **Phase 2 — Planning**: Builds an export query per table using pre-fetched schema data (no redundant DB round-trips).
3. **Phase 3 — Export**: Exports all tables in parallel (8 workers) using PostgreSQL `COPY TO STDOUT` — fast, streaming, no row-by-row Python processing.
4. **Phase 4 — Validation**: Verifies row counts and FK integrity on the exported CSVs.

## Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- PostgreSQL database access (read-only is sufficient)

## Setup

```bash
git clone https://github.com/PunithHivel/ORG-DUMP.git
cd ORG-DUMP
uv sync
```

## Configuration

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description | Example |
|----------|-------------|---------|
| `DB_HOST` | PostgreSQL host | `db.example.com` |
| `DB_PORT` | PostgreSQL port (default: 5432) | `5432` |
| `DB_NAME` | Database name | `mydb` |
| `DB_USER` | Database user | `readonly_user` |
| `DB_PASSWORD` | Database password | `secret` |
| `DB_SCHEMA` | Schema to export from | `insightly` |
| `ORG_ID` | Organization ID to export | `2088` |
| `OUTPUT_DIR` | Directory to write CSVs into | `/tmp/org_export` |

## Usage

### Full export (recommended)

Runs all 4 phases and writes CSVs + a manifest to `OUTPUT_DIR`:

```bash
uv run python main.py dump
```

### Analyze only

Prints a report of which tables will be exported and their row counts, without writing any files:

```bash
uv run python main.py analyze
```

### Re-validate an existing export

Re-runs validation against a previously exported directory:

```bash
uv run python main.py validate --output-dir /path/to/export
```

## Output

```
OUTPUT_DIR/
├── <table_name>.csv   # one file per exported table
├── manifest.json      # export metadata (org_id, row counts, timestamps)
├── plan.json          # full export plan with queries used
└── validation_report.json
```

## Notes

- The connection is opened **read-only** — this tool cannot modify the database.
- Tables with no relationship to the target org are automatically skipped.
- The export runs with **8 parallel workers**, each holding one DB connection (9 total including the main connection used for discovery).
- Row count mismatches in validation are expected on a live database (rows can be inserted between Phase 1 and Phase 3).
commit A for test/squash-detect
