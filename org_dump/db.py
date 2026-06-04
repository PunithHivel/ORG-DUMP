from contextlib import contextmanager
import psycopg2
import psycopg2.extras
from org_dump.config import Config


def get_connection(cfg: Config):
    conn = psycopg2.connect(
        host=cfg.db_host,
        port=cfg.db_port,
        dbname=cfg.db_name,
        user=cfg.db_user,
        password=cfg.db_password,
        options=f"-c search_path={cfg.db_schema}",
    )
    conn.set_session(readonly=True)
    return conn


@contextmanager
def open_connection(cfg: Config):
    conn = get_connection(cfg)
    try:
        yield conn
    finally:
        conn.close()
