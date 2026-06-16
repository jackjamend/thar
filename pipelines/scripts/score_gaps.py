from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from caregap.capabilities import CARE_NEEDS
from caregap.health_access_validation import print_validation_report, validate_health_access_records
from caregap.locations import enrich_facility_locations
from caregap.records import read_health_access_input
from caregap.scoring import score_district_gaps


FIELDS = [
    "district_id",
    "district_name",
    "state",
    "care_need",
    "planning_priority_score",
    "risk_score",
    "supply_score",
    "evidence_score",
    "data_quality_score",
    "relevant_claims",
    "strong_claims",
    "partial_claims",
    "pincode_inferred_claims",
    "city_fallback_claims",
    "uncertainty_label",
    "explanation",
    "updated_at",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Score CareGap district medical desert gaps.")
    parser.add_argument("--input", required=True, help="CSV export of health_access_records or health_access_facility_enriched.")
    parser.add_argument("--claims", required=True, help="CSV of caregap_facility_claims.")
    parser.add_argument("--output", required=True, help="Output CSV path for caregap_district_gaps.")
    parser.add_argument(
        "--district-input",
        default="data/health_access_records.csv",
        help="Optional health_access_records CSV used as the full NFHS district universe when --input is enriched.",
    )
    parser.add_argument("--care-need", choices=[*CARE_NEEDS.keys(), "all"], default="all")
    parser.add_argument("--skip-source-validation", action="store_true", help="Allow scoring from structurally invalid source data.")
    args = parser.parse_args()

    records = read_health_access_input(args.input, district_input=args.district_input)
    if not args.skip_source_validation:
        _validate_source(records)
    enriched_records = enrich_facility_locations(records)
    claims = _read_csv(args.claims)
    care_needs = CARE_NEEDS.keys() if args.care_need == "all" else [args.care_need]
    gaps = [gap for care_need in care_needs for gap in score_district_gaps(enriched_records, claims, care_need=care_need)]
    _write_csv(args.output, gaps)
    print(f"Wrote {len(gaps):,} district gap scores to {args.output}")


def _read_csv(path: str) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _validate_source(records: list[dict[str, str]]) -> None:
    report = validate_health_access_records(records)
    if report.error_count:
        print_validation_report(report)
        raise SystemExit("Source validation failed. Fix health_access_records.csv or pass --skip-source-validation.")


def _write_csv(path: str, rows: list[dict[str, str]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
