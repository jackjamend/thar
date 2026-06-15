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

    conn = psycopg.connect(
        host=os.environ["DATABRICKS_POSTGRES_HOST"],
        port=os.environ.get("DATABRICKS_POSTGRES_PORT", "5432"),
        dbname=os.environ["DATABRICKS_POSTGRES_DATABASE"],
        user=os.environ["DATABRICKS_POSTGRES_USER"],
        password=os.environ["DATABRICKS_POSTGRES_PASSWORD"],
        sslmode=os.environ.get("DATABRICKS_POSTGRES_SSLMODE", "require"),
    )
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

