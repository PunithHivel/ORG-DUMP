from dataclasses import dataclass, field
from org_dump.discovery.fk_graph import JoinStep


@dataclass
class TablePlan:
    table: str
    table_class: str           # "A", "B", "C"
    strategy: str              # "DIRECT_ORG", "TEAM_BASED", etc.
    org_col: str | None
    join_path: list[JoinStep]
    estimated_rows: int
    output_file: str           # absolute path to the CSV
    export_query: str          # SQL used for export
    columns: list[str] = field(default_factory=list)
    anchor_table: str | None = None


@dataclass
class ExportPlan:
    org_id: str
    schema: str
    tables: list[TablePlan]    # topologically sorted, Type C excluded
    skipped_tables: list[str]  # Type C tables
    custom_tables: list[str]   # Type B CUSTOM — exported but flagged for review
