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

DISTRICT_ALIASES = {
    ("Andhra Pradesh", "eluru"): "West Godavari",
    ("Andhra Pradesh", "anakapalli"): "Visakhapatnam",
    ("Andhra Pradesh", "annamayya"): "Y.S.R.",
    ("Andhra Pradesh", "bhimavaram"): "West Godavari",
    ("Andhra Pradesh", "kakinada"): "East Godavari",
    ("Andhra Pradesh", "madanapalle"): "Chittoor",
    ("Andhra Pradesh", "nandyal"): "Kurnool",
    ("Andhra Pradesh", "ntr"): "Krishna",
    ("Andhra Pradesh", "palnadu"): "Guntur",
    ("Andhra Pradesh", "rajamahendravaram"): "East Godavari",
    ("Andhra Pradesh", "spsr nellore"): "Sri Potti Sriramulu Nello",
    ("Andhra Pradesh", "sri sathya sai"): "Anantapur",
    ("Andhra Pradesh", "tirupati"): "Chittoor",
    ("Andhra Pradesh", "vijayawada"): "Krishna",
    ("Andhra Pradesh", "visakhapatanam"): "Visakhapatnam",
    ("Andhra Pradesh", "visakhatapanam"): "Visakhapatnam",
    ("Assam", "kamrup metro"): "Kamrup Metropolitan",
    ("Delhi", "delhi"): "New Delhi",
    ("Gujarat", "ahmedabad"): "Ahmadabad",
    ("Gujarat", "arvalli"): "Aravali",
    ("Gujarat", "kabilpore"): "Navsari",
    ("Haryana", "gurugram"): "Gurgaon",
    ("Jammu & Kashmir", "budgam"): "Badgam",
    ("Jharkhand", "east singhbhum"): "Purbi Singhbhum",
    ("Jharkhand", "east singhbum"): "Purbi Singhbhum",
    ("Jharkhand", "jamshedpur"): "Purbi Singhbhum",
    ("Karnataka", "ballari"): "Bellary",
    ("Karnataka", "belagavi"): "Belgaum",
    ("Karnataka", "bengaluru"): "Bangalore",
    ("Karnataka", "bengaluru rural"): "Bangalore Rural",
    ("Karnataka", "bengaluru urban"): "Bangalore",
    ("Karnataka", "davangere"): "Davanagere",
    ("Karnataka", "kalaburagi"): "Gulbarga",
    ("Karnataka", "mysuru"): "Mysore",
    ("Karnataka", "shivamogga"): "Shimoga",
    ("Karnataka", "tumakuru"): "Tumkur",
    ("Karnataka", "vemagal"): "Kolar",
    ("Karnataka", "vijaynagar"): "Bellary",
    ("Karnataka", "vijayapura"): "Bijapur",
    ("Karnataka", "hubballi"): "Dharwad",
    ("Kerala", "kuttippuram"): "Malappuram",
    ("Kerala", "muvattupuzha"): "Ernakulam",
    ("Madhya Pradesh", "east nimar"): "Khandwa (East Nimar)",
    ("Madhya Pradesh", "khargone"): "Khargone (West Nimar)",
    ("Madhya Pradesh", "narsinghpur"): "Narsimhapur",
    ("Madhya Pradesh", "napier town"): "Jabalpur",
    ("Maharashtra", "ahmednagar"): "Ahmadnagar",
    ("Maharashtra", "beed"): "Bid",
    ("Maharashtra", "buldhana"): "Buldana",
    ("Maharashtra", "gondia"): "Gondiya",
    ("Maharashtra", "kurla"): "Mumbai Suburban",
    ("Maharashtra", "raigad"): "Raigarh",
    ("Maharashtra", "sawangi"): "Wardha",
    ("Maharashtra", "ulhasnagar"): "Thane",
    ("Maharashtra", "goregaon west"): "Mumbai Suburban",
    ("Puducherry", "pondicherry"): "Puducherry",
    ("Punjab", "firozepur"): "Firozpur",
    ("Punjab", "malerkotla"): "Sangrur",
    ("Punjab", "s a s nagar"): "Sahibzada Ajit Singh Nagar",
    ("Punjab", "sas nagar"): "Sahibzada Ajit Singh Nagar",
    ("Punjab", "sri muktsar sahib"): "Muktsar",
    ("Punjab", "urmar tanda"): "Hoshiarpur",
    ("Rajasthan", "jalore"): "Jalor",
    ("Rajasthan", "jhunjhunu"): "Jhunjhunun",
    ("Tamil Nadu", "chengalpattu"): "Kancheepuram",
    ("Tamil Nadu", "aminjikarai chennai"): "Chennai",
    ("Tamil Nadu", "kallakurichi"): "Viluppuram",
    ("Tamil Nadu", "kanchipuram"): "Kancheepuram",
    ("Tamil Nadu", "ranipet"): "Vellore",
    ("Tamil Nadu", "tenkasi"): "Tirunelveli",
    ("Tamil Nadu", "tirupathur"): "Vellore",
    ("Tamil Nadu", "tuticorin"): "Thoothukkudi",
    ("Telangana", "hanumakonda"): "Warangal Urban",
    ("Telangana", "moinabad"): "Ranga Reddy",
    ("Uttar Pradesh", "ayodhya"): "Faizabad",
    ("Uttar Pradesh", "bhadohi"): "Sant Ravidas Nagar (Bhadohi)",
    ("Uttar Pradesh", "greater noida"): "Gautam Buddha Nagar",
    ("Uttar Pradesh", "hathras"): "Mahamaya Nagar",
    ("Uttar Pradesh", "kushi nagar"): "Kushinagar",
    ("Uttar Pradesh", "maharajganj"): "Mahrajganj",
    ("Uttar Pradesh", "amroha"): "Jyotiba Phule Nagar",
    ("Uttar Pradesh", "prayagraj"): "Allahabad",
    ("Uttar Pradesh", "siddhar nagar"): "Siddharthnagar",
    ("Uttar Pradesh", "siddharth nagar"): "Siddharthnagar",
    ("Uttarakhand", "haridwar"): "Hardwar",
    ("Uttarakhand", "udam singh nagar"): "Udham Singh Nagar",
    ("West Bengal", "24 paraganas north"): "North Twenty Four Pargana",
    ("West Bengal", "24 paraganas south"): "South Twenty Four Pargana",
    ("West Bengal", "24 parganas north"): "North Twenty Four Pargana",
    ("West Bengal", "24 parganas south"): "South Twenty Four Pargana",
    ("West Bengal", "coochbehar"): "Koch Bihar",
    ("West Bengal", "barddhaman"): "Paschim Barddhaman",
    ("West Bengal", "darjeeling"): "Darjiling",
    ("West Bengal", "dinajpur uttar"): "Uttar Dinajpur",
    ("West Bengal", "hooghly"): "Hugli",
    ("West Bengal", "howrah"): "Haora",
    ("West Bengal", "medinipur west"): "Paschim Medinipur",
    ("West Bengal", "paschim bardhaman"): "Paschim Barddhaman",
    ("West Bengal", "purba bardhaman"): "Paschim Barddhaman",
    ("West Bengal", "purulia"): "Puruliya",
    ("Bihar", "purbi champaran"): "Purba Champaran",
    ("Assam", "marigaon"): "Morigaon",
    ("Meghalaya", "ri bhoi"): "Ribhoi",
    ("Chhattisgarh", "kabirdham"): "Kabeerdham",
    ("Chhattisgarh", "kawardha"): "Kabeerdham",
    ("Rajasthan", "chittorgarh"): "Chittaurgarh",
}


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


def canonical_district(state: str | None, district: str | None) -> str:
    value = _clean(district)
    canonical = canonical_state(state) or _clean(state)
    return DISTRICT_ALIASES.get((canonical, _state_key(value)), value)


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
        district = canonical_district(state, row.get("analysis_district"))
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
        "district": canonical_district(state, row.get("district") or row.get("entity_name", "")),
    }


def _enriched_facility_record(row: dict[str, str]) -> dict[str, str]:
    return {
        "record_id": row.get("facility_id", ""),
        "record_type": "facility",
        "entity_name": row.get("facility_name", ""),
        "state": canonical_state(row.get("analysis_state")),
        "district": canonical_district(row.get("analysis_state"), row.get("analysis_district")),
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
