from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from caregap.capabilities import extract_facility_claims
from caregap.locations import enrich_facility_locations


FIELDS = [
    "facility_id",
    "facility_name",
    "state",
    "district_or_city",
    "district_source",
    "capability",
    "claim_status",
    "confidence",
    "evidence_text",
    "uncertainty_reason",
    "extraction_method",
    "updated_at",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract CareGap facility capability claims.")
    parser.add_argument("--input", required=True, help="CSV export of health_access_records.")
    parser.add_argument("--output", required=True, help="Output CSV path for caregap_facility_claims.")
    args = parser.parse_args()

    records = _read_csv(args.input)
    enriched_records = enrich_facility_locations(records)
    claims = extract_facility_claims(enriched_records)
    _write_csv(args.output, claims)
    print(f"Wrote {len(claims):,} facility capability claims to {args.output}")


def _read_csv(path: str) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: str, rows: list[dict[str, str]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
