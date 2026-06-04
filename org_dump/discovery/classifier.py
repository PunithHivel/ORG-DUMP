import re
from dataclasses import dataclass, field
from org_dump.discovery.schema_inspector import ColumnInfo
from org_dump.discovery.fk_graph import FKGraph, JoinStep

ORG_COLUMN_PATTERNS = {"organizationid", "organization_id", "orgid", "org_id"}

# Matches tables like ai_insights_org_1750, ai_insights_partitioned_org_2088
_ORG_PARTITION_RE = re.compile(r'_org_(\d+)$')

STRATEGY_ANCHOR_PATTERNS = [
    ({"team", "teams"}, "TEAM_BASED"),
    ({"author", "authors", "user", "users", "member", "members"}, "AUTHOR_BASED"),
    ({"repo", "repos", "repository", "repositories"}, "REPOSITORY_BASED"),
    ({"project", "projects"}, "PROJECT_BASED"),
    ({"workspace", "workspaces"}, "WORKSPACE_BASED"),
]


@dataclass
class TableClassification:
    table: str
    table_class: str          # "A", "B", "C"
    org_col: str | None       # for Type A
    join_path: list[JoinStep] = field(default_factory=list)  # for Type B
    strategy: str = "SKIP"   # DIRECT_ORG / TEAM_BASED / AUTHOR_BASED / ... / CUSTOM / SKIP
    anchor_table: str | None = None


def _strategy_for_path(path: list[JoinStep]) -> tuple[str, str | None]:
    """Derive export strategy from the anchor table name in the path."""
    if not path:
        return "DIRECT_ORG", None
    anchor = path[-1].to_table.lower()
    for name_set, strategy in STRATEGY_ANCHOR_PATTERNS:
        if anchor in name_set or any(anchor.startswith(n) for n in name_set):
            return strategy, path[-1].to_table
    return "CUSTOM", path[-1].to_table


def classify_tables(
    tables: list[str],
    columns: dict[str, list[ColumnInfo]],
    fk_graph: FKGraph,
    org_id: str = "",
) -> dict[str, TableClassification]:
    result: dict[str, TableClassification] = {}

    # Pre-pass: skip per-org partition tables that belong to a different org.
    # e.g. ai_insights_org_1750 should be skipped when ORG_ID=2088.
    if org_id:
        for table in tables:
            m = _ORG_PARTITION_RE.search(table)
            if m and m.group(1) != org_id:
                result[table] = TableClassification(
                    table=table,
                    table_class="C",
                    org_col=None,
                    strategy="SKIP",
                )

    # Pass 1: identify Type A tables (skip any already classified by pre-pass)
    type_a: set[str] = set()
    for table in tables:
        if table in result:
            continue
        for col in columns.get(table, []):
            if col.name.lower() in ORG_COLUMN_PATTERNS:
                type_a.add(table)
                result[table] = TableClassification(
                    table=table,
                    table_class="A",
                    org_col=col.name,
                    strategy="DIRECT_ORG",
                )
                break

    # Pass 2: BFS for Type B vs Type C
    for table in tables:
        if table in result:
            continue

        paths = fk_graph.all_paths_to_targets(table, type_a)
        if not paths:
            result[table] = TableClassification(
                table=table,
                table_class="C",
                org_col=None,
                strategy="SKIP",
            )
            continue

        # Pick shortest path; on tie prefer the one whose anchor has a known strategy
        paths.sort(key=lambda p: len(p))
        best_path = paths[0]
        strategy, anchor = _strategy_for_path(best_path)

        # If multiple equal-length paths exist, prefer one with a known strategy
        if len(paths) > 1:
            for p in paths:
                s, a = _strategy_for_path(p)
                if s != "CUSTOM":
                    best_path, strategy, anchor = p, s, a
                    break

        result[table] = TableClassification(
            table=table,
            table_class="B",
            org_col=None,
            join_path=best_path,
            strategy=strategy,
            anchor_table=anchor,
        )

    return result
