from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from caregap.capabilities import CARE_NEEDS
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
    "explanation",
    "updated_at",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Score CareGap district medical desert gaps.")
    parser.add_argument("--input", required=True, help="CSV export of health_access_records.")
    parser.add_argument("--claims", required=True, help="CSV of caregap_facility_claims.")
    parser.add_argument("--output", required=True, help="Output CSV path for caregap_district_gaps.")
    parser.add_argument("--care-need", choices=CARE_NEEDS.keys(), default="maternal_emergency")
    args = parser.parse_args()

    records = _read_csv(args.input)
    claims = _read_csv(args.claims)
    gaps = score_district_gaps(records, claims, care_need=args.care_need)
    _write_csv(args.output, gaps)
    print(f"Wrote {len(gaps):,} district gap scores to {args.output}")


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

