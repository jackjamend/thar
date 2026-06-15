from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from caregap.capabilities import summarize_capability_coverage


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect CareGap source data coverage.")
    parser.add_argument("--input", required=True, help="CSV export of health_access_records.")
    args = parser.parse_args()

    records = _read_csv(args.input)
    facilities = [row for row in records if row.get("record_type") == "facility"]
    districts = [row for row in records if row.get("record_type") == "district"]
    descriptions = [row.get("description", "") for row in facilities]
    non_empty_descriptions = [text for text in descriptions if text.strip()]

    print("CareGap data verification")
    print(f"Total rows: {len(records):,}")
    print(f"Facility rows: {len(facilities):,}")
    print(f"District rows: {len(districts):,}")
    print(f"Facility descriptions present: {len(non_empty_descriptions):,}/{len(facilities):,}")
    if facilities:
        pct = (len(non_empty_descriptions) / len(facilities)) * 100
        print(f"Facility description coverage: {pct:.1f}%")

    print("\nCapability coverage")
    for capability, count in summarize_capability_coverage(records).items():
        print(f"- {capability}: {count:,} facilities")


def _read_csv(path: str) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    main()

