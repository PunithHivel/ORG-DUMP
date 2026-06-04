from org_dump.discovery.fk_graph import JoinStep
from org_dump.discovery.classifier import TableClassification
from org_dump.discovery.schema_inspector import ColumnInfo


def build_query(
    classification: TableClassification,
    schema: str,
    columns: list[ColumnInfo],
    primary_keys: dict[str, list[str]],
    org_col_map: dict[str, str],  # type_a_table → org_col
) -> str:
    """Generate the export SQL for a table based on its classification."""
    table = classification.table

    if classification.table_class == "A":
        return (
            f"SELECT * FROM {schema}.{table} "
            f"WHERE {classification.org_col} = %(org_id)s"
        )

    if classification.table_class == "B":
        path = classification.join_path
        return _build_indirect_query(table, path, schema, primary_keys, org_col_map)

    return f"SELECT * FROM {schema}.{table}"


def _build_indirect_query(
    leaf_table: str,
    path: list[JoinStep],
    schema: str,
    primary_keys: dict[str, list[str]],
    org_col_map: dict[str, str],
) -> str:
    """Build a CTE chain for multi-hop FK traversal."""
    if not path:
        return f"SELECT * FROM {schema}.{leaf_table}"

    anchor = path[-1].to_table
    anchor_org_col = org_col_map.get(anchor, "org_id")
    anchor_pks = primary_keys.get(anchor, ["id"])

    if len(path) == 1:
        # Single hop: simple JOIN
        step = path[0]
        pk_list = ", ".join(f"a.{pk}" for pk in anchor_pks)
        return (
            f"SELECT t.* FROM {schema}.{leaf_table} t\n"
            f"INNER JOIN {schema}.{anchor} a ON t.{step.from_col} = a.{step.to_col}\n"
            f"WHERE a.{anchor_org_col} = %(org_id)s"
        )

    # Multi-hop: CTE chain
    # path = [leaf → hop1 → hop2 → ... → anchor]
    # We build CTEs from anchor backwards, but path goes forward (leaf → anchor),
    # so we reverse the path to build CTEs from anchor toward leaf.
    reversed_path = list(reversed(path))

    ctes = []
    # CTE 0: anchor filtered by org
    pk_cols = ", ".join(anchor_pks)
    ctes.append(
        f"_step0 AS (\n"
        f"    SELECT {pk_cols} FROM {schema}.{anchor}\n"
        f"    WHERE {anchor_org_col} = %(org_id)s\n"
        f")"
    )

    for i, step in enumerate(reversed_path[:-1]):
        prev_cte = f"_step{i}"
        curr_cte = f"_step{i + 1}"
        mid_table = step.from_table
        mid_pks = primary_keys.get(mid_table, ["id"])
        mid_pk_cols = ", ".join(mid_pks)
        prev_pks = anchor_pks if i == 0 else primary_keys.get(reversed_path[i - 1].from_table, ["id"])
        prev_pk_col = prev_pks[0]
        ctes.append(
            f"{curr_cte} AS (\n"
            f"    SELECT {mid_pk_cols} FROM {schema}.{mid_table}\n"
            f"    WHERE {step.to_col} IN (SELECT {prev_pk_col} FROM {prev_cte})\n"
            f")"
        )

    last_step = reversed_path[-1]
    last_cte = f"_step{len(reversed_path) - 1}"
    last_mid_pks = primary_keys.get(last_step.from_table, ["id"])
    last_pk_col = last_mid_pks[0]

    cte_block = ",\n".join(ctes)
    return (
        f"WITH {cte_block}\n"
        f"SELECT * FROM {schema}.{leaf_table}\n"
        f"WHERE {last_step.from_col} IN (SELECT {last_pk_col} FROM {last_cte})"
    )


def estimate_rows(conn, query: str, org_id: str) -> int:
    """Execute COUNT(*) wrapper around the export query."""
    count_query = f"SELECT COUNT(*) FROM ({query}) _count_wrap"
    with conn.cursor() as cur:
        try:
            cur.execute(count_query, {"org_id": org_id})
            return cur.fetchone()[0]
        except Exception:
            return -1
