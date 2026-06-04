from dataclasses import dataclass


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    is_nullable: bool


@dataclass
class ForeignKey:
    from_table: str
    from_col: str
    to_table: str
    to_col: str


class SchemaInspector:
    def __init__(self, conn, schema: str):
        self.conn = conn
        self.schema = schema

    def get_tables(self) -> list[str]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = %s AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """,
                (self.schema,),
            )
            return [row[0] for row in cur.fetchall()]

    def get_columns(self) -> dict[str, list[ColumnInfo]]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name, column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = %s
                ORDER BY table_name, ordinal_position
                """,
                (self.schema,),
            )
            result: dict[str, list[ColumnInfo]] = {}
            for table, col, dtype, nullable in cur.fetchall():
                result.setdefault(table, []).append(
                    ColumnInfo(name=col, data_type=dtype, is_nullable=(nullable == "YES"))
                )
            return result

    def get_primary_keys(self) -> dict[str, list[str]]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.relname, a.attname
                FROM pg_index i
                JOIN pg_class c ON c.oid = i.indrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
                WHERE n.nspname = %s AND i.indisprimary
                ORDER BY c.relname, a.attnum
                """,
                (self.schema,),
            )
            result: dict[str, list[str]] = {}
            for table, col in cur.fetchall():
                result.setdefault(table, []).append(col)
            return result

    def get_foreign_keys(self) -> list[ForeignKey]:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    c_from.relname  AS from_table,
                    a_from.attname  AS from_col,
                    c_to.relname    AS to_table,
                    a_to.attname    AS to_col
                FROM pg_constraint con
                JOIN pg_class c_from ON c_from.oid = con.conrelid
                JOIN pg_class c_to   ON c_to.oid   = con.confrelid
                JOIN pg_namespace n  ON n.oid = c_from.relnamespace
                JOIN pg_attribute a_from ON a_from.attrelid = con.conrelid
                  AND a_from.attnum = ANY(con.conkey)
                JOIN pg_attribute a_to ON a_to.attrelid = con.confrelid
                  AND a_to.attnum = ANY(con.confkey)
                WHERE n.nspname = %s AND con.contype = 'f'
                """,
                (self.schema,),
            )
            return [ForeignKey(*row) for row in cur.fetchall()]

    def get_org_row_counts(
        self,
        classifications: dict,
        org_id: str,
    ) -> dict[str, int]:
        """Run COUNT(*) with org filter for all Type A tables in a single UNION ALL query.
        Returns -1 for Type B (indirect) tables — count requires the full join query.
        """
        # Cast to int so psycopg2 binds as integer, not text.
        # Passing str '2088' against a bigint partition key causes PostgreSQL
        # constraint exclusion to discard all partitions and return 0.
        try:
            org_id_param: int | str = int(org_id)
        except ValueError:
            org_id_param = org_id

        counts: dict[str, int] = {}

        for table, cl in classifications.items():
            if cl.table_class == "B":
                counts[table] = -1  # requires full join query; skipped in analyze phase

        for table, cl in classifications.items():
            if cl.table_class == "A" and cl.org_col:
                try:
                    with self.conn.cursor() as cur:
                        cur.execute(
                            f'SELECT COUNT(*) FROM {self.schema}."{table}" WHERE "{cl.org_col}" = %s',
                            (org_id_param,),
                        )
                        counts[table] = cur.fetchone()[0]
                except Exception as exc:
                    counts[table] = -1

        return counts
