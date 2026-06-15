from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from caregap.capabilities import CARE_NEEDS, extract_facility_claims
from caregap.locations import enrich_facility_locations
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
    parser.add_argument("--input", required=True, help="CSV export of health_access_records.")
    parser.add_argument("--out-dir", required=True, help="Directory for generated CSV outputs.")
    parser.add_argument("--care-need", choices=[*CARE_NEEDS.keys(), "all"], default="all")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    records = _read_csv(args.input)
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


def _read_csv(path: str) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
