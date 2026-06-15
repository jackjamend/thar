from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def lakebase_connection() -> Iterator[object]:
    """Open a Lakebase/Postgres connection using environment variables.

    This helper is intentionally small until the team decides the exact local
    and deployed credentials flow. It expects psycopg to be installed from
    `pipelines/requirements.txt`.
    """
    import psycopg
    from dotenv import load_dotenv

    load_dotenv()

    conn = psycopg.connect(
        host=_env("DATABRICKS_POSTGRES_HOST", "PGHOST"),
        port=os.environ.get("DATABRICKS_POSTGRES_PORT", os.environ.get("PGPORT", "5432")),
        dbname=_env("DATABRICKS_POSTGRES_DATABASE", "PGDATABASE"),
        user=_env("DATABRICKS_POSTGRES_USER", "PGUSER", "USER"),
        password=_env("DATABRICKS_POSTGRES_PASSWORD", "PGPASSWORD"),
        sslmode=os.environ.get("DATABRICKS_POSTGRES_SSLMODE", os.environ.get("PGSSLMODE", "require")),
    )
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    raise KeyError(f"Missing environment variable; tried {', '.join(names)}")
