from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from caregap.lakebase_io import lakebase_connection


WAREHOUSE_ID = "eed4a162ca1cfc3d"
SOURCE_TABLE = "workspace.default.health_access_facility_enriched"
TARGET_TABLE = "public.health_access_facility_enriched"

FIELDS = [
    "facility_id",
    "facility_name",
    "facility_type",
    "operator_type",
    "source_city",
    "analysis_state",
    "analysis_district",
    "source_pincode",
    "phone",
    "website",
    "latitude",
    "longitude",
    "description",
    "pincode_match_status",
    "district_match_status",
    "district_source",
    "location_confidence",
    "source_quality_flags",
    "analysis_location_key",
    "households_surveyed",
    "institutional_birth_pct",
    "stunting_pct",
    "anaemia_pct",
    "improved_water_pct",
    "improved_sanitation_pct",
    "health_insurance_pct",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Mirror the UC enriched health access table into Lakebase for the app.")
    parser.add_argument("--profile", default="dais-2026", help="Databricks CLI profile.")
    parser.add_argument("--warehouse-id", default=WAREHOUSE_ID, help="Databricks SQL warehouse ID.")
    parser.add_argument("--source-table", default=SOURCE_TABLE, help="Unity Catalog source table.")
    parser.add_argument("--target-table", default=TARGET_TABLE, help="Lakebase target table.")
    parser.add_argument("--output", help="Optional CSV path to keep the exported data.")
    parser.add_argument("--wait-timeout", default="50s", help="SQL statement API wait timeout.")
    args = parser.parse_args()

    output_path = Path(args.output) if args.output else Path(tempfile.mkstemp(suffix=".csv")[1])
    try:
        _export_uc_table(args.profile, args.warehouse_id, args.source_table, args.wait_timeout, output_path)
        _load_lakebase(args.target_table, output_path)
    finally:
        if not args.output:
            output_path.unlink(missing_ok=True)


def _export_uc_table(profile: str, warehouse_id: str, source_table: str, wait_timeout: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    sql = _build_sql(source_table)
    response = _api_post(
        profile,
        "/api/2.0/sql/statements",
        {
            "warehouse_id": warehouse_id,
            "statement": sql,
            "wait_timeout": wait_timeout,
            "on_wait_timeout": "CONTINUE",
            "disposition": "EXTERNAL_LINKS",
            "format": "JSON_ARRAY",
        },
    )
    statement_id = response["statement_id"]
    response = _wait_for_statement(profile, statement_id, response)
    _write_statement_csv(profile, statement_id, response, output)
    print(f"Exported {source_table} to {output}")


def _load_lakebase(target_table: str, csv_path: Path) -> None:
    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL.format(table_name=target_table))
            cur.execute(f"TRUNCATE TABLE {target_table}")
            _copy_csv(cur, target_table, csv_path)
            for sql in INDEX_SQL:
                cur.execute(sql.format(table_name=target_table))
            cur.execute(f"SELECT COUNT(*) FROM {target_table}")
            count = cur.fetchone()[0]
    print(f"Loaded {count:,} rows into {target_table}")


def _wait_for_statement(profile: str, statement_id: str, response: dict) -> dict:
    while response.get("status", {}).get("state") in {"PENDING", "RUNNING"}:
        time.sleep(5)
        response = _api_get(profile, f"/api/2.0/sql/statements/{statement_id}")

    state = response.get("status", {}).get("state")
    if state != "SUCCEEDED":
        raise RuntimeError(f"Statement {statement_id} ended with state {state}: {response}")
    return response


def _write_statement_csv(profile: str, statement_id: str, response: dict, output: Path) -> None:
    manifest = response["manifest"]
    columns = [column["name"] for column in manifest["schema"]["columns"]]
    total_chunks = int(manifest["total_chunk_count"])

    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        first_chunk = response.get("result")
        for chunk_index in range(total_chunks):
            if chunk_index == 0 and first_chunk and int(first_chunk.get("chunk_index", -1)) == 0:
                chunk = first_chunk
            else:
                chunk = _api_get(profile, f"/api/2.0/sql/statements/{statement_id}/result/chunks/{chunk_index}")
            writer.writerows(_sanitize_row(row) for row in _chunk_rows(chunk))


def _chunk_rows(chunk: dict) -> list[list[str]]:
    if "external_links" not in chunk:
        return chunk.get("data_array", [])

    rows: list[list[str]] = []
    for link in chunk["external_links"]:
        with urllib.request.urlopen(link["external_link"]) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, list):
            rows.extend(payload)
        else:
            rows.extend(payload.get("data_array", []))
    return rows


def _sanitize_row(row: list[str]) -> list[str]:
    return [value.replace("\x00", "") if isinstance(value, str) else value for value in row]


def _copy_csv(cur, table_name: str, path: Path) -> None:
    columns = ", ".join(FIELDS)
    with path.open("r", encoding="utf-8", newline="") as handle:
        with cur.copy(f"COPY {table_name} ({columns}) FROM STDIN WITH CSV HEADER NULL ''") as copy:
            while chunk := handle.read(1024 * 1024):
                copy.write(chunk)


def _api_post(profile: str, path: str, payload: dict) -> dict:
    return _run_databricks(profile, ["api", "post", path, "--json", json.dumps(payload), "-o", "json"])


def _api_get(profile: str, path: str) -> dict:
    return _run_databricks(profile, ["api", "get", path, "-o", "json"])


def _run_databricks(profile: str, args: list[str]) -> dict:
    command = ["databricks", *args, "--profile", profile]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def _build_sql(source_table: str) -> str:
    columns = ",\n    ".join(FIELDS)
    return f"""
SELECT
    {columns}
FROM {source_table}
ORDER BY facility_name, facility_id
"""


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} (
  facility_id TEXT PRIMARY KEY,
  facility_name TEXT,
  facility_type TEXT,
  operator_type TEXT,
  source_city TEXT,
  analysis_state TEXT,
  analysis_district TEXT,
  source_pincode TEXT,
  phone TEXT,
  website TEXT,
  latitude DOUBLE PRECISION,
  longitude DOUBLE PRECISION,
  description TEXT,
  pincode_match_status TEXT,
  district_match_status TEXT,
  district_source TEXT,
  location_confidence DOUBLE PRECISION,
  source_quality_flags TEXT,
  analysis_location_key TEXT,
  households_surveyed DOUBLE PRECISION,
  institutional_birth_pct DOUBLE PRECISION,
  stunting_pct DOUBLE PRECISION,
  anaemia_pct DOUBLE PRECISION,
  improved_water_pct DOUBLE PRECISION,
  improved_sanitation_pct DOUBLE PRECISION,
  health_insurance_pct DOUBLE PRECISION
)
"""

INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_health_enriched_state ON {table_name} (analysis_state)",
    "CREATE INDEX IF NOT EXISTS idx_health_enriched_district ON {table_name} (analysis_state, analysis_district)",
    "CREATE INDEX IF NOT EXISTS idx_health_enriched_type ON {table_name} (facility_type)",
    "CREATE INDEX IF NOT EXISTS idx_health_enriched_pincode_status ON {table_name} (pincode_match_status)",
    "CREATE INDEX IF NOT EXISTS idx_health_enriched_district_status ON {table_name} (district_match_status)",
]


if __name__ == "__main__":
    main()
