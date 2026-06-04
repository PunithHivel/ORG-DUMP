import os


class _CountingWriter:
    """Bytes file wrapper that counts newlines as data passes through."""
    def __init__(self, f):
        self._f = f
        self.newlines = 0

    def write(self, data: bytes) -> int:
        self.newlines += data.count(b"\n")
        return self._f.write(data)


def write_table_csv(conn, query: str, org_id: str, output_file: str) -> int:
    """Stream query results to a CSV file using COPY. Returns actual row count written."""
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    with conn.cursor() as cur:
        final_query = cur.mogrify(query, {"org_id": org_id}).decode()
        copy_sql = f"COPY ({final_query}) TO STDOUT WITH CSV HEADER"

        with open(output_file, "wb") as f:
            writer = _CountingWriter(f)
            cur.copy_expert(copy_sql, writer)

    return writer.newlines - 1  # subtract header line
