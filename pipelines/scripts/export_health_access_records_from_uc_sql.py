from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from caregap.health_access_validation import print_validation_report, read_health_access_csv, validate_health_access_records


WAREHOUSE_ID = "eed4a162ca1cfc3d"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export rebuilt health_access_records from DAIS Unity Catalog source tables via SQL.")
    parser.add_argument("--profile", default="dais-2026", help="Databricks CLI profile.")
    parser.add_argument("--warehouse-id", default=WAREHOUSE_ID, help="Databricks SQL warehouse ID.")
    parser.add_argument("--output", default="data/health_access_records.csv", help="Output CSV path.")
    parser.add_argument("--wait-timeout", default="50s", help="SQL statement API wait timeout.")
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    sql = _build_sql()
    response = _api_post(
        args.profile,
        "/api/2.0/sql/statements",
        {
            "warehouse_id": args.warehouse_id,
            "statement": sql,
            "wait_timeout": args.wait_timeout,
            "on_wait_timeout": "CONTINUE",
            "disposition": "EXTERNAL_LINKS",
            "format": "JSON_ARRAY",
        },
    )
    statement_id = response["statement_id"]
    response = _wait_for_statement(args.profile, statement_id, response)
    _write_statement_csv(args.profile, statement_id, response, output)
    print(f"Wrote rebuilt health_access_records CSV to {output}")

    records = read_health_access_csv(output)
    report = validate_health_access_records(records)
    print()
    print_validation_report(report)
    if report.error_count:
        raise SystemExit(1)


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


def _api_post(profile: str, path: str, payload: dict) -> dict:
    return _run_databricks(profile, ["api", "post", path, "--json", json.dumps(payload), "-o", "json"])


def _api_get(profile: str, path: str) -> dict:
    return _run_databricks(profile, ["api", "get", path, "-o", "json"])


def _run_databricks(profile: str, args: list[str]) -> dict:
    command = ["databricks", *args, "--profile", profile]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def _build_sql() -> str:
    return r"""
WITH facility_records AS (
  SELECT
    concat('facility:', unique_id) AS record_id,
    'facility' AS record_type,
    nullif(trim(regexp_replace(coalesce(get_json_object(name, '$.name'), name), '\\s+', ' ')), '') AS entity_name,
    nullif(trim(address_stateOrRegion), '') AS state,
    CAST(NULL AS STRING) AS district,
    nullif(trim(address_city), '') AS city,
    nullif(trim(address_zipOrPostcode), '') AS pincode,
    try_cast(latitude AS DOUBLE) AS latitude,
    try_cast(longitude AS DOUBLE) AS longitude,
    CASE lower(nullif(trim(facilityTypeId), ''))
      WHEN 'nursing_home' THEN 'hospital'
      ELSE lower(nullif(trim(facilityTypeId), ''))
    END AS facility_type,
    lower(nullif(trim(operatorTypeId), '')) AS operator_type,
    coalesce(
      nullif(trim(officialPhone), ''),
      nullif(regexp_extract(phone_numbers, '"([^"]+)"', 1), ''),
      nullif(trim(phone_numbers), '')
    ) AS phone,
    coalesce(
      nullif(regexp_extract(officialWebsite, '"([^"]+)"', 1), ''),
      nullif(trim(officialWebsite), ''),
      nullif(regexp_extract(websites, '"([^"]+)"', 1), ''),
      nullif(trim(websites), '')
    ) AS website,
    nullif(trim(regexp_replace(description, '\\s+', ' ')), '') AS description,
    CAST(NULL AS STRING) AS office_type,
    CAST(NULL AS STRING) AS delivery,
    CAST(NULL AS DOUBLE) AS households_surveyed,
    CAST(NULL AS DOUBLE) AS institutional_birth_pct,
    CAST(NULL AS DOUBLE) AS stunting_pct,
    CAST(NULL AS DOUBLE) AS anaemia_pct,
    CAST(NULL AS DOUBLE) AS improved_water_pct,
    CAST(NULL AS DOUBLE) AS improved_sanitation_pct,
    CAST(NULL AS DOUBLE) AS health_insurance_pct
  FROM databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities
  WHERE unique_id RLIKE '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
    AND nullif(trim(name), '') IS NOT NULL
    AND lower(coalesce(facilityTypeId, '')) IN ('', 'hospital', 'clinic', 'dentist', 'doctor', 'pharmacy', 'farmacy', 'null', 'nursing_home')
    AND lower(coalesce(operatorTypeId, '')) IN ('', 'private', 'public', 'government', 'null')
),
pincode_records AS (
  SELECT
    concat('pincode:', sha2(concat_ws('||', coalesce(officename, ''), coalesce(statename, ''), coalesce(district, ''), coalesce(pincode, '')), 256)) AS record_id,
    'pincode' AS record_type,
    nullif(trim(officename), '') AS entity_name,
    nullif(trim(statename), '') AS state,
    nullif(trim(district), '') AS district,
    CAST(NULL AS STRING) AS city,
    nullif(trim(pincode), '') AS pincode,
    try_cast(latitude AS DOUBLE) AS latitude,
    try_cast(longitude AS DOUBLE) AS longitude,
    CAST(NULL AS STRING) AS facility_type,
    CAST(NULL AS STRING) AS operator_type,
    CAST(NULL AS STRING) AS phone,
    CAST(NULL AS STRING) AS website,
    concat_ws(' / ', nullif(trim(circlename), ''), nullif(trim(regionname), ''), nullif(trim(divisionname), '')) AS description,
    nullif(trim(officetype), '') AS office_type,
    nullif(trim(delivery), '') AS delivery,
    CAST(NULL AS DOUBLE) AS households_surveyed,
    CAST(NULL AS DOUBLE) AS institutional_birth_pct,
    CAST(NULL AS DOUBLE) AS stunting_pct,
    CAST(NULL AS DOUBLE) AS anaemia_pct,
    CAST(NULL AS DOUBLE) AS improved_water_pct,
    CAST(NULL AS DOUBLE) AS improved_sanitation_pct,
    CAST(NULL AS DOUBLE) AS health_insurance_pct
  FROM databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.india_post_pincode_directory
),
district_records AS (
  SELECT
    concat('district:', sha2(concat_ws('||', coalesce(state_ut, ''), coalesce(district_name, '')), 256)) AS record_id,
    'district' AS record_type,
    nullif(trim(district_name), '') AS entity_name,
    nullif(trim(state_ut), '') AS state,
    nullif(trim(district_name), '') AS district,
    CAST(NULL AS STRING) AS city,
    CAST(NULL AS STRING) AS pincode,
    CAST(NULL AS DOUBLE) AS latitude,
    CAST(NULL AS DOUBLE) AS longitude,
    CAST(NULL AS STRING) AS facility_type,
    CAST(NULL AS STRING) AS operator_type,
    CAST(NULL AS STRING) AS phone,
    CAST(NULL AS STRING) AS website,
    concat('NFHS district indicators for ', district_name, ', ', state_ut) AS description,
    CAST(NULL AS STRING) AS office_type,
    CAST(NULL AS STRING) AS delivery,
    try_cast(households_surveyed AS DOUBLE) AS households_surveyed,
    try_cast(institutional_birth_5y_pct AS DOUBLE) AS institutional_birth_pct,
    try_cast(child_u5_who_are_stunted_height_for_age_18_pct AS DOUBLE) AS stunting_pct,
    try_cast(all_w15_49_who_are_anaemic_pct AS DOUBLE) AS anaemia_pct,
    try_cast(hh_improved_water_pct AS DOUBLE) AS improved_water_pct,
    try_cast(hh_use_improved_sanitation_pct AS DOUBLE) AS improved_sanitation_pct,
    try_cast(hh_member_covered_health_insurance_pct AS DOUBLE) AS health_insurance_pct
  FROM databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.nfhs_5_district_health_indicators
)
SELECT * FROM pincode_records
UNION ALL
SELECT * FROM facility_records
UNION ALL
SELECT * FROM district_records
ORDER BY record_type, record_id
"""


if __name__ == "__main__":
    main()
