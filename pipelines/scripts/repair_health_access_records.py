from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from caregap.health_access_validation import HEALTH_ACCESS_FIELDS
from caregap.lakebase_io import lakebase_connection


FACILITY_ERROR_SQL = """
record_type = 'facility'
AND (
  record_id !~ '^facility:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
  OR NULLIF(BTRIM(COALESCE(entity_name, '')), '') IS NULL
  OR BTRIM(COALESCE(entity_name, '')) ~ '^[\\[\\{]'
  OR BTRIM(COALESCE(entity_name, '')) ~ '^(\\*|__|\\*\\*|>|#)'
  OR LOWER(BTRIM(COALESCE(facility_type, ''))) NOT IN ('', 'hospital', 'clinic', 'dentist', 'doctor', 'pharmacy', 'farmacy', 'null')
  OR BTRIM(COALESCE(facility_type, '')) ~ '^[\\[\\{]'
  OR LOWER(BTRIM(COALESCE(operator_type, ''))) NOT IN ('', 'private', 'public', 'government', 'null')
  OR BTRIM(COALESCE(operator_type, '')) ~ '^[\\[\\{]'
  OR BTRIM(COALESCE(phone, '')) LIKE '{"coordinates":%'
  OR (
    BTRIM(COALESCE(website, '')) <> ''
    AND BTRIM(COALESCE(website, '')) !~* '^https?://'
    AND BTRIM(COALESCE(website, '')) ~ '(^[\\[\\{]|^[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,36}$|^\\d{4}-\\d{2}-\\d{2}$)'
  )
  OR BTRIM(COALESCE(description, '')) ~ '^(true|false|null)$'
  OR BTRIM(COALESCE(description, '')) ~ '^[\\[\\{]'
  OR BTRIM(COALESCE(description, '')) ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,36}$'
  OR BTRIM(COALESCE(description, '')) ~ '^\\d{4}-\\d{2}-\\d{2}$'
  OR BTRIM(COALESCE(description, '')) ~ '^-?\\d+(\\.\\d+)?$'
)
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create validated public.health_access_records candidate tables and optionally replace the source table."
    )
    parser.add_argument("--source-table", default="public.health_access_records", help="Current source table.")
    parser.add_argument("--candidate-table", default="public.health_access_records_candidate", help="Validated candidate table.")
    parser.add_argument("--quarantine-table", default="public.health_access_records_quarantine", help="Rejected rows table.")
    parser.add_argument("--backup-table", help="Backup table name. Defaults to timestamped public.health_access_records_backup_*.")
    parser.add_argument("--apply", action="store_true", help="Replace --source-table with --candidate-table after building it.")
    args = parser.parse_args()

    backup_table = args.backup_table or f"public.health_access_records_backup_{_timestamp()}"
    fields = ", ".join(HEALTH_ACCESS_FIELDS)

    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            _execute(cur, f"DROP TABLE IF EXISTS {args.candidate_table}")
            _execute(cur, f"DROP TABLE IF EXISTS {args.quarantine_table}")
            _execute(cur, f"CREATE TABLE {args.candidate_table} AS SELECT {fields} FROM {args.source_table} WHERE NOT ({FACILITY_ERROR_SQL})")
            _execute(cur, f"CREATE TABLE {args.quarantine_table} AS SELECT {fields} FROM {args.source_table} WHERE {FACILITY_ERROR_SQL}")

            counts = {
                "source": _count(cur, args.source_table),
                "candidate": _count(cur, args.candidate_table),
                "quarantine": _count(cur, args.quarantine_table),
            }
            print("Lakebase health_access_records repair candidate")
            for name, count in counts.items():
                print(f"- {name}: {count:,}")

            if counts["candidate"] + counts["quarantine"] != counts["source"]:
                raise RuntimeError("Candidate and quarantine counts do not add up to source count.")

            if not args.apply:
                print("\nDry run only. Re-run with --apply to replace the source table.")
                return

            _execute(cur, f"DROP TABLE IF EXISTS {backup_table}")
            _execute(cur, f"CREATE TABLE {backup_table} AS SELECT {fields} FROM {args.source_table}")
            _execute(cur, f"DROP TABLE {args.source_table}")
            _execute(cur, f"ALTER TABLE {args.candidate_table} RENAME TO {_unqualified_table_name(args.source_table)}")
            print(f"\nReplaced {args.source_table}. Backup table: {backup_table}")


def _execute(cur, sql: str) -> None:
    cur.execute(sql)


def _count(cur, table_name: str) -> int:
    cur.execute(f"SELECT COUNT(*) FROM {table_name}")
    row = cur.fetchone()
    return int(row[0])


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _unqualified_table_name(table_name: str) -> str:
    return table_name.split(".")[-1]


if __name__ == "__main__":
    main()
