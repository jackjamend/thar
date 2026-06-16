from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable


def enrich_facility_locations(records: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    """Add district provenance fields to facility records.

    Facility rows in the source data generally have blank district values, while
    pincode rows include district and state. This helper keeps the original rows
    intact except for enriched facility copies.
    """
    rows = list(records)
    pincode_locations = _pincode_location_index(rows)
    return [_with_facility_location(row, pincode_locations) for row in rows]


def _pincode_location_index(records: list[dict[str, str]]) -> dict[str, tuple[str, str]]:
    location_counts: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)
    for row in records:
        if row.get("record_type") != "pincode":
            continue

        pincode = _clean(row.get("pincode"))
        district = _clean(row.get("district"))
        state = _clean(row.get("state"))
        if pincode and district:
            location_counts[pincode][(state, district)] += 1

    return {
        pincode: counts.most_common(1)[0][0]
        for pincode, counts in location_counts.items()
        if counts
    }


def _with_facility_location(row: dict[str, str], pincode_locations: dict[str, tuple[str, str]]) -> dict[str, str]:
    if row.get("record_type") != "facility":
        return row

    enriched = dict(row)
    source_district = _clean(row.get("district"))
    city = _clean(row.get("city"))
    pincode = _clean(row.get("pincode"))

    inferred = pincode_locations.get(pincode)
    if inferred:
        inferred_state, inferred_district = inferred
        enriched["district"] = inferred_district.title()
        enriched["district_source"] = "pincode_inferred"
        if inferred_state:
            enriched["state"] = inferred_state.title()
        return enriched

    if source_district:
        enriched["district"] = source_district
        enriched["district_source"] = _clean(row.get("district_source")) or "source_district"
        return enriched

    if city:
        enriched["district_source"] = "city_fallback"
        return enriched

    enriched["district_source"] = "missing_location"
    return enriched


def _clean(value: str | None) -> str:
    return " ".join((value or "").strip().split())
