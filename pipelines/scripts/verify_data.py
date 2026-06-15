from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

sys.path.append(str(Path(__file__).resolve().parents[1]))

from caregap.capabilities import CARE_NEEDS, extract_facility_claims, summarize_capability_coverage
from caregap.health_access_validation import print_validation_report, validate_health_access_records
from caregap.locations import enrich_facility_locations

MATERNAL_NEED = "maternal_emergency"


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect CareGap source data coverage.")
    parser.add_argument("--input", required=True, help="CSV export of health_access_records.")
    parser.add_argument("--samples", type=int, default=3, help="Evidence snippets to show per maternal capability.")
    args = parser.parse_args()

    records = _read_csv(args.input)
    source_report = validate_health_access_records(records)
    print_validation_report(source_report, max_examples=8)
    print()
    verified_records = enrich_facility_locations(records)
    facilities = [row for row in verified_records if row.get("record_type") == "facility"]
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
        description_lengths = [len(text.strip()) for text in descriptions]
        print(f"Median facility description length: {median(description_lengths):.0f} chars")
        print(f"Short facility descriptions (<40 chars): {_count_short_descriptions(descriptions):,}")

    print("\nLocation quality")
    for field in ("state", "city", "pincode"):
        present = _count_present(facilities, field)
        pct = (present / len(facilities)) * 100 if facilities else 0
        print(f"- Facilities with {field}: {present:,}/{len(facilities):,} ({pct:.1f}%)")
    direct_districts = _count_present([row for row in records if row.get("record_type") == "facility"], "district")
    inferred_districts = _count_present(facilities, "district")
    inferred_pct = (inferred_districts / len(facilities)) * 100 if facilities else 0
    print(f"- Facilities with source district: {direct_districts:,}/{len(facilities):,}")
    print(f"- Facilities with district after pincode inference: {inferred_districts:,}/{len(facilities):,} ({inferred_pct:.1f}%)")

    print("\nCapability coverage")
    for capability, count in summarize_capability_coverage(verified_records).items():
        print(f"- {capability}: {count:,} facilities")

    claims = extract_facility_claims(verified_records)
    maternal_capabilities = set(CARE_NEEDS[MATERNAL_NEED])
    maternal_claims = [claim for claim in claims if claim["capability"] in maternal_capabilities]

    print("\nMaternal emergency coverage by state")
    for state, count in _top_counts(maternal_claims, "state", limit=12):
        print(f"- {state}: {count:,} facility claims")

    print("\nTop maternal emergency districts/cities by claimed supply")
    for location, count in _top_location_counts(maternal_claims, limit=12):
        print(f"- {location}: {count:,} facility claims")

    print("\nMaternal evidence samples")
    _print_evidence_samples(maternal_claims, args.samples)

    print("\nCandidate demo districts needing review")
    for candidate in _candidate_demo_districts(districts, maternal_claims, max_claims=0):
        print(
            "- "
            f"{candidate['district']}, {candidate['state']}: "
            f"risk={candidate['risk_score']:.1f}, "
            f"maternal_claims={candidate['maternal_claims']}, "
            f"strong_claims={candidate['strong_claims']}, "
            f"anaemia={candidate['anaemia_pct']}, "
            f"stunting={candidate['stunting_pct']}, "
            f"institutional_birth={candidate['institutional_birth_pct']}"
        )

    print("\nCandidate demo districts with reviewable facility evidence")
    for candidate in _candidate_demo_districts(districts, maternal_claims, min_claims=1):
        print(
            "- "
            f"{candidate['district']}, {candidate['state']}: "
            f"risk={candidate['risk_score']:.1f}, "
            f"maternal_claims={candidate['maternal_claims']}, "
            f"strong_claims={candidate['strong_claims']}, "
            f"anaemia={candidate['anaemia_pct']}, "
            f"stunting={candidate['stunting_pct']}, "
            f"institutional_birth={candidate['institutional_birth_pct']}"
        )


def _read_csv(path: str) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _count_present(rows: list[dict[str, str]], field: str) -> int:
    return sum(1 for row in rows if (row.get(field) or "").strip())


def _count_short_descriptions(descriptions: list[str]) -> int:
    return sum(1 for text in descriptions if 0 < len(text.strip()) < 40)


def _top_counts(rows: list[dict[str, str]], field: str, limit: int) -> list[tuple[str, int]]:
    counts = Counter((row.get(field) or "Unknown").strip() or "Unknown" for row in rows)
    return counts.most_common(limit)


def _top_location_counts(rows: list[dict[str, str]], limit: int) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for row in rows:
        state = (row.get("state") or "Unknown").strip() or "Unknown"
        location = (row.get("district_or_city") or "Unknown").strip() or "Unknown"
        counts[f"{location}, {state}"] += 1
    return counts.most_common(limit)


def _print_evidence_samples(claims: list[dict[str, str]], samples_per_capability: int) -> None:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for claim in claims:
        grouped[claim["capability"]].append(claim)

    for capability in CARE_NEEDS[MATERNAL_NEED]:
        print(f"- {capability}")
        for claim in grouped.get(capability, [])[:samples_per_capability]:
            facility = claim["facility_name"] or "Unknown facility"
            location = claim["district_or_city"] or claim["state"] or "Unknown location"
            confidence = claim["confidence"]
            evidence = claim["evidence_text"]
            print(f"  [{confidence}] {facility} ({location}): {evidence}")
        if not grouped.get(capability):
            print("  No evidence samples found.")


def _candidate_demo_districts(
    districts: list[dict[str, str]],
    maternal_claims: list[dict[str, str]],
    limit: int = 10,
    min_claims: int = 0,
    max_claims: int | None = None,
) -> list[dict[str, object]]:
    supply_by_location: Counter[tuple[str, str]] = Counter()
    strong_by_location: Counter[tuple[str, str]] = Counter()

    for claim in maternal_claims:
        key = (_normalized(claim.get("state")), _normalized(claim.get("district_or_city")))
        supply_by_location[key] += 1
        if claim.get("confidence") == "strong":
            strong_by_location[key] += 1

    candidates: list[dict[str, object]] = []
    for district in districts:
        state = district.get("state", "")
        name = district.get("entity_name", "")
        key = (_normalized(state), _normalized(name))
        risk_score = _risk_score(district)
        maternal_claims_count = supply_by_location[key]
        strong_claims_count = strong_by_location[key]
        if risk_score <= 0:
            continue
        if maternal_claims_count < min_claims:
            continue
        if max_claims is not None and maternal_claims_count > max_claims:
            continue

        candidates.append(
            {
                "state": state or "Unknown",
                "district": name or "Unknown",
                "risk_score": risk_score,
                "maternal_claims": maternal_claims_count,
                "strong_claims": strong_claims_count,
                "anaemia_pct": _display_pct(district.get("anaemia_pct")),
                "stunting_pct": _display_pct(district.get("stunting_pct")),
                "institutional_birth_pct": _display_pct(district.get("institutional_birth_pct")),
            },
        )

    return sorted(
        candidates,
        key=lambda row: (-float(row["risk_score"]), int(row["strong_claims"]), int(row["maternal_claims"])),
    )[:limit]


def _risk_score(row: dict[str, str]) -> float:
    anaemia = _float(row.get("anaemia_pct"))
    stunting = _float(row.get("stunting_pct"))
    institutional_birth = _float(row.get("institutional_birth_pct"))
    if anaemia is None and stunting is None and institutional_birth is None:
        return 0

    score = 0.0
    if anaemia is not None:
        score += anaemia
    if stunting is not None:
        score += stunting
    if institutional_birth is not None:
        score += max(0, 100 - institutional_birth)
    return score


def _float(value: str | None) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except ValueError:
        return None


def _display_pct(value: str | None) -> str:
    number = _float(value)
    if number is None:
        return "missing"
    return f"{number:.1f}%"


def _normalized(value: str | None) -> str:
    return " ".join((value or "").lower().split())


if __name__ == "__main__":
    main()
