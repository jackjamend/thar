from __future__ import annotations

import csv
import json
import re
from pathlib import Path


def _state_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean(value).lower()).strip()


def _clean(value: str | None) -> str:
    return " ".join((value or "").strip().split())


CANONICAL_STATES = {
    "Andaman & Nicobar Islands",
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chandigarh",
    "Chhattisgarh",
    "Dadra & Nagar Haveli and Daman & Diu",
    "Delhi",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jammu & Kashmir",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Ladakh",
    "Lakshadweep",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Puducherry",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
}

STATE_ALIASES = {
    _state_key(state): state
    for state in CANONICAL_STATES
}
STATE_ALIASES.update(
    {
        "andaman and nicobar islands": "Andaman & Nicobar Islands",
        "andaman nicobar": "Andaman & Nicobar Islands",
        "andaman nicobar islands": "Andaman & Nicobar Islands",
        "chattisgarh": "Chhattisgarh",
        "chhatisgarh": "Chhattisgarh",
        "daman diu": "Dadra & Nagar Haveli and Daman & Diu",
        "dadra and nagar haveli and daman and diu": "Dadra & Nagar Haveli and Daman & Diu",
        "dadra and nagar haveli daman and diu": "Dadra & Nagar Haveli and Daman & Diu",
        "dadra and nagar haveli": "Dadra & Nagar Haveli and Daman & Diu",
        "dadra nagar haveli": "Dadra & Nagar Haveli and Daman & Diu",
        "dadra nagar haveli daman diu": "Dadra & Nagar Haveli and Daman & Diu",
        "jammu and kashmir": "Jammu & Kashmir",
        "maharastra": "Maharashtra",
        "nct delhi": "Delhi",
        "nct of delhi": "Delhi",
        "new delhi": "Delhi",
        "orissa": "Odisha",
        "pondicherry": "Puducherry",
        "tamilnadu": "Tamil Nadu",
        "u p": "Uttar Pradesh",
        "up": "Uttar Pradesh",
        "uttaranchal": "Uttarakhand",
    }
)


def read_health_access_input(path: str | Path, *, district_input: str | Path | None = None) -> list[dict[str, str]]:
    rows = _read_csv(path)
    return records_from_input(rows, district_input=district_input)


def records_from_input(rows: list[dict[str, str]], *, district_input: str | Path | None = None) -> list[dict[str, str]]:
    if not rows:
        return []

    fieldnames = set(rows[0].keys())
    if {"facility_id", "facility_name", "analysis_state", "analysis_district"}.issubset(fieldnames):
        projected = _project_enriched_rows(rows)
        return _replace_district_universe(projected, district_input)

    return rows


def canonical_state(value: str | None) -> str:
    return STATE_ALIASES.get(_state_key(value), "")


def noncanonical_states(rows: list[dict[str, str]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = _clean(row.get(field))
        if value and not canonical_state(value):
            counts[value] = counts.get(value, 0) + 1
    return counts


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _project_enriched_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    district_rows: dict[tuple[str, str], dict[str, str]] = {}

    for row in rows:
        records.append(_enriched_facility_record(row))

        state = canonical_state(row.get("analysis_state"))
        district = _clean(row.get("analysis_district"))
        if not state or not district:
            continue

        key = (state.lower(), district.lower())
        if key not in district_rows:
            district_rows[key] = _enriched_district_record(row, state, district)
        else:
            _merge_district_metrics(district_rows[key], row)

    return [*district_rows.values(), *records]


def _replace_district_universe(records: list[dict[str, str]], district_input: str | Path | None) -> list[dict[str, str]]:
    if not district_input:
        return records

    path = Path(district_input)
    if not path.exists():
        return records

    districts = [_legacy_district_record(row) for row in _read_csv(path) if row.get("record_type") == "district"]
    if not districts:
        return records

    facilities = [row for row in records if row.get("record_type") == "facility"]
    return [*districts, *facilities]


def _legacy_district_record(row: dict[str, str]) -> dict[str, str]:
    state = canonical_state(row.get("state")) or row.get("state", "")
    return {
        **row,
        "state": state,
        "district": row.get("district") or row.get("entity_name", ""),
    }


def _enriched_facility_record(row: dict[str, str]) -> dict[str, str]:
    return {
        "record_id": row.get("facility_id", ""),
        "record_type": "facility",
        "entity_name": row.get("facility_name", ""),
        "state": canonical_state(row.get("analysis_state")),
        "district": row.get("analysis_district", ""),
        "city": row.get("source_city", ""),
        "pincode": row.get("source_pincode", ""),
        "latitude": row.get("latitude", ""),
        "longitude": row.get("longitude", ""),
        "facility_type": row.get("facility_type", ""),
        "operator_type": row.get("operator_type", ""),
        "phone": row.get("phone", ""),
        "website": _website(row.get("website")),
        "description": row.get("description", ""),
        "office_type": "",
        "delivery": "",
        "households_surveyed": row.get("households_surveyed", ""),
        "institutional_birth_pct": row.get("institutional_birth_pct", ""),
        "stunting_pct": row.get("stunting_pct", ""),
        "anaemia_pct": row.get("anaemia_pct", ""),
        "improved_water_pct": row.get("improved_water_pct", ""),
        "improved_sanitation_pct": row.get("improved_sanitation_pct", ""),
        "health_insurance_pct": row.get("health_insurance_pct", ""),
        "district_source": row.get("district_source", ""),
    }


def _enriched_district_record(row: dict[str, str], state: str, district: str) -> dict[str, str]:
    location_key = row.get("analysis_location_key") or f"{state.lower()}|{district.lower()}"
    return {
        "record_id": f"district:{location_key}",
        "record_type": "district",
        "entity_name": district,
        "state": state,
        "district": district,
        "city": "",
        "pincode": "",
        "latitude": "",
        "longitude": "",
        "facility_type": "",
        "operator_type": "",
        "phone": "",
        "website": "",
        "description": f"NFHS district indicators for {district}, {state}",
        "office_type": "",
        "delivery": "",
        "households_surveyed": row.get("households_surveyed", ""),
        "institutional_birth_pct": row.get("institutional_birth_pct", ""),
        "stunting_pct": row.get("stunting_pct", ""),
        "anaemia_pct": row.get("anaemia_pct", ""),
        "improved_water_pct": row.get("improved_water_pct", ""),
        "improved_sanitation_pct": row.get("improved_sanitation_pct", ""),
        "health_insurance_pct": row.get("health_insurance_pct", ""),
    }


def _merge_district_metrics(target: dict[str, str], source: dict[str, str]) -> None:
    for field in (
        "households_surveyed",
        "institutional_birth_pct",
        "stunting_pct",
        "anaemia_pct",
        "improved_water_pct",
        "improved_sanitation_pct",
        "health_insurance_pct",
    ):
        if not target.get(field) and source.get(field):
            target[field] = source[field]


def _website(value: str | None) -> str:
    text = _clean(value)
    if not text.startswith("["):
        return text

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text

    if isinstance(parsed, list) and parsed:
        return str(parsed[0])
    return ""
