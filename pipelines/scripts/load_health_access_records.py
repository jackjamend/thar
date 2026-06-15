from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from caregap.health_access_validation import (
    HEALTH_ACCESS_FIELDS,
    print_validation_report,
    read_health_access_csv,
    validate_health_access_records,
)
from caregap.lakebase_io import lakebase_connection


CREATE_TABLE_TEMPLATE = """
CREATE TABLE {table_name} (
  record_id TEXT NOT NULL,
  record_type TEXT NOT NULL,
  entity_name TEXT,
  state TEXT,
  district TEXT,
  city TEXT,
  pincode TEXT,
  latitude DOUBLE PRECISION,
  longitude DOUBLE PRECISION,
  facility_type TEXT,
  operator_type TEXT,
  phone TEXT,
  website TEXT,
  description TEXT,
  office_type TEXT,
  delivery TEXT,
  households_surveyed DOUBLE PRECISION,
  institutional_birth_pct DOUBLE PRECISION,
  stunting_pct DOUBLE PRECISION,
  anaemia_pct DOUBLE PRECISION,
  improved_water_pct DOUBLE PRECISION,
  improved_sanitation_pct DOUBLE PRECISION,
  health_insurance_pct DOUBLE PRECISION
)
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Load a regenerated health_access_records CSV into Lakebase.")
    parser.add_argument("--input", required=True, help="Regenerated health_access_records CSV.")
    parser.add_argument("--table", default="public.health_access_records", help="Live Lakebase table to replace.")
    parser.add_argument("--candidate-table", help="Candidate table name. Defaults to <table>_candidate.")
    parser.add_argument("--backup-table", help="Backup table name. Defaults to timestamped <table>_backup_*.")
    parser.add_argument("--apply", action="store_true", help="Replace --table with the loaded candidate table.")
    parser.add_argument("--warnings-fail", action="store_true", help="Fail when source validation warnings are present.")
    args = parser.parse_args()

    input_path = Path(args.input)
    records = read_health_access_csv(input_path)
    report = validate_health_access_records(records)
    print_validation_report(report)
    if report.error_count or (args.warnings_fail and report.warning_count):
        raise SystemExit("Input validation failed; not loading Lakebase.")

    candidate_table = args.candidate_table or f"{args.table}_candidate"
    backup_table = args.backup_table or f"{args.table}_backup_{_timestamp()}"
    columns = ", ".join(HEALTH_ACCESS_FIELDS)

    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {candidate_table}")
            cur.execute(CREATE_TABLE_TEMPLATE.format(table_name=candidate_table))
            _copy_csv(cur, candidate_table, columns, input_path)
            print(f"Loaded candidate table {candidate_table}: {_count(cur, candidate_table):,} rows")

            if not args.apply:
                print("Dry run only. Re-run with --apply to replace the live table.")
                return

            cur.execute(f"DROP TABLE IF EXISTS {backup_table}")
            cur.execute(f"CREATE TABLE {backup_table} AS SELECT * FROM {args.table}")
            cur.execute(f"DROP TABLE IF EXISTS {args.table}")
            cur.execute(f"ALTER TABLE {candidate_table} RENAME TO {_unqualified_table_name(args.table)}")
            print(f"Replaced {args.table}. Backup table: {backup_table}")


def _copy_csv(cur, table_name: str, columns: str, path: Path) -> None:
    with path.open("r", encoding="utf-8", newline="") as handle:
        with cur.copy(f"COPY {table_name} ({columns}) FROM STDIN WITH CSV HEADER NULL ''") as copy:
            while chunk := handle.read(1024 * 1024):
                copy.write(chunk)


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
