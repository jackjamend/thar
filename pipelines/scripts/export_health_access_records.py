from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from caregap.health_access_validation import (
    HEALTH_ACCESS_FIELDS,
    print_validation_report,
    read_health_access_csv,
    validate_health_access_records,
)
from caregap.lakebase_io import lakebase_connection


def main() -> None:
    parser = argparse.ArgumentParser(description="Export public.health_access_records from Lakebase to a local CSV.")
    parser.add_argument("--output", default="data/health_access_records.csv", help="Output CSV path.")
    parser.add_argument("--table", default="public.health_access_records", help="Source table to export.")
    parser.add_argument("--skip-validation", action="store_true", help="Do not validate the exported CSV.")
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    _export_table(args.table, output)
    print(f"Exported {args.table} to {output}")

    if not args.skip_validation:
        records = read_health_access_csv(output)
        report = validate_health_access_records(records)
        print()
        print_validation_report(report)
        if report.error_count:
            raise SystemExit(1)


def _export_table(table_name: str, output: Path) -> None:
    columns = ", ".join(HEALTH_ACCESS_FIELDS)
    sql = f"""
COPY (
  SELECT {columns}
  FROM {table_name}
  ORDER BY record_type, record_id
) TO STDOUT WITH CSV HEADER
"""
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            with output.open("wb") as handle:
                with cur.copy(sql) as copy:
                    while chunk := copy.read():
                        handle.write(chunk)


if __name__ == "__main__":
    main()
