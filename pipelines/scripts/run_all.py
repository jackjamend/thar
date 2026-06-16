from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from caregap.capabilities import CARE_NEEDS, extract_facility_claims
from caregap.health_access_validation import print_validation_report, validate_health_access_records
from caregap.locations import enrich_facility_locations
from caregap.records import read_health_access_input
from caregap.scoring import score_district_gaps


CLAIM_FIELDS = [
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

GAP_FIELDS = [
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
    parser = argparse.ArgumentParser(description="Run the CareGap pipeline locally.")
    parser.add_argument("--input", required=True, help="CSV export of health_access_records or health_access_facility_enriched.")
    parser.add_argument("--out-dir", required=True, help="Directory for generated CSV outputs.")
    parser.add_argument(
        "--district-input",
        default="data/health_access_records.csv",
        help="Optional health_access_records CSV used as the full NFHS district universe when --input is enriched.",
    )
    parser.add_argument("--care-need", choices=[*CARE_NEEDS.keys(), "all"], default="all")
    parser.add_argument("--skip-source-validation", action="store_true", help="Allow extraction from structurally invalid source data.")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    records = read_health_access_input(args.input, district_input=args.district_input)
    if not args.skip_source_validation:
        _validate_source(records)
    enriched_records = enrich_facility_locations(records)
    claims = extract_facility_claims(enriched_records)
    care_needs = CARE_NEEDS.keys() if args.care_need == "all" else [args.care_need]
    gaps = [
        gap
        for care_need in care_needs
        for gap in score_district_gaps(enriched_records, claims, care_need=care_need)
    ]

    _write_csv(out_dir / "caregap_facility_claims.csv", claims, CLAIM_FIELDS)
    _write_csv(out_dir / "caregap_district_gaps.csv", gaps, GAP_FIELDS)

    print(f"Wrote {len(claims):,} facility claims")
    print(f"Wrote {len(gaps):,} district gap scores")


def _validate_source(records: list[dict[str, str]]) -> None:
    report = validate_health_access_records(records)
    if report.error_count:
        print_validation_report(report)
        raise SystemExit("Source validation failed. Fix health_access_records.csv or pass --skip-source-validation.")


def _write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
