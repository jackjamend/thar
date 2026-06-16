from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable


@dataclass(frozen=True)
class Capability:
    key: str
    label: str
    strong_patterns: tuple[str, ...]
    partial_patterns: tuple[str, ...] = ()


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        key="c_section",
        label="C-section",
        strong_patterns=(r"\bc[- ]?section\b", r"\bcaesarean\b", r"\bcesarean\b", r"\blscs\b", r"\blower segment caesarean\b"),
        partial_patterns=(r"\bobstetric", r"\bobgyn\b", r"\bgynaec", r"\blabou?r room\b", r"\bdelivery room\b"),
    ),
    Capability(
        key="obgyn",
        label="OBGYN",
        strong_patterns=(r"\bobgyn\b", r"\bobstetric", r"\bgynaec", r"\bgynec", r"\bgynae\b", r"\bmaternity\b"),
        partial_patterns=(r"\bwomen'?s health\b", r"\bantenatal\b", r"\bdelivery\b", r"\bmother and child\b", r"\breproductive"),
    ),
    Capability(
        key="nicu",
        label="NICU",
        strong_patterns=(r"\bnicu\b", r"\bneonatal intensive care\b", r"\bsncu\b", r"\bspecial newborn care\b"),
        partial_patterns=(r"\bneonatal\b", r"\bnewborn\b", r"\bpaediatric intensive\b", r"\bpediatric intensive\b", r"\bpaediatric\b", r"\bpediatric\b"),
    ),
    Capability(
        key="blood_bank",
        label="Blood bank",
        strong_patterns=(r"\bblood bank\b", r"\bblood storage\b", r"\bblood transfusion\b", r"\bblood storage unit\b"),
        partial_patterns=(r"\bblood component\b", r"\bblood centre\b", r"\bblood center\b"),
    ),
    Capability(
        key="ambulance",
        label="Ambulance",
        strong_patterns=(r"\bambulance\b", r"\bemergency transport\b", r"\bpatient transport\b", r"\b108 ambulance\b"),
    ),
    Capability(
        key="emergency_24x7",
        label="24x7 emergency",
        strong_patterns=(
            r"\b24\s*[x/]\s*7\b.*\bemergency\b",
            r"\bemergency\b.*\b24\s*[x/]\s*7\b",
            r"\b24\s*hour\b.*\bemergency\b",
            r"\bemergency\b.*\b24\s*hour\b",
        ),
        partial_patterns=(r"\bemergency\b", r"\btrauma\b", r"\bcasualty\b", r"\baccident\b", r"\bemergency department\b"),
    ),
    Capability(
        key="icu",
        label="ICU",
        strong_patterns=(r"\bicu\b", r"\bintensive care\b", r"\bintensive care unit\b", r"\bccu\b"),
        partial_patterns=(r"\bcritical care\b", r"\bhigh dependency\b", r"\bhdu\b", r"\bcardiac care\b"),
    ),
    Capability(
        key="ventilator",
        label="Ventilator",
        strong_patterns=(r"\bventilator", r"\bventilation support\b", r"\bmechanical ventilation\b"),
        partial_patterns=(r"\boxygen\b", r"\blife support\b", r"\brespiratory support\b"),
    ),
    Capability(
        key="dialysis",
        label="Dialysis",
        strong_patterns=(r"\bdialysis\b", r"\bhemodialysis\b", r"\bhaemodialysis\b", r"\bdialysis unit\b"),
        partial_patterns=(r"\bnephrology\b", r"\brenal\b", r"\bkidney\b"),
    ),
)


CARE_NEEDS: dict[str, tuple[str, ...]] = {
    "maternal_emergency": (
        "c_section",
        "obgyn",
        "nicu",
        "blood_bank",
        "ambulance",
        "emergency_24x7",
    ),
    "critical_care": (
        "icu",
        "ventilator",
        "emergency_24x7",
        "ambulance",
    ),
    "dialysis_access": (
        "dialysis",
        "icu",
        "emergency_24x7",
    ),
}

FACILITY_TYPE_CAPABILITY_HINTS: dict[str, tuple[str, ...]] = {
    "hospital": ("emergency_24x7",),
    "nursing_home": ("obgyn",),
}


def extract_facility_claims(records: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    """Extract deterministic capability claims with evidence snippets."""
    updated_at = datetime.now(timezone.utc).isoformat()
    claims: list[dict[str, str]] = []

    for record in records:
        if record.get("record_type") != "facility":
            continue

        description = record.get("description") or ""
        state = record.get("state", "")
        district_or_city = record.get("district", "") or record.get("city", "")
        if not state or not district_or_city:
            continue

        claimed_capabilities: set[str] = set()
        for capability in CAPABILITIES:
            match = _first_match(description, capability.strong_patterns)
            confidence = "strong"
            uncertainty_reason = "Explicit capability term found in facility description."

            if match is None:
                match = _first_match(description, capability.partial_patterns)
                confidence = "partial"
                uncertainty_reason = "Related term found, but capability is not stated explicitly."

            if match is None:
                continue

            claimed_capabilities.add(capability.key)
            claims.append(
                {
                    "facility_id": record.get("record_id", ""),
                    "facility_name": record.get("entity_name", ""),
                    "state": state,
                    "district_or_city": district_or_city,
                    "district_source": record.get("district_source", "") or _district_source(record),
                    "capability": capability.key,
                    "claim_status": "claimed",
                    "confidence": confidence,
                    "evidence_text": _snippet(description, match.start(), match.end()),
                    "uncertainty_reason": uncertainty_reason,
                    "extraction_method": "deterministic_regex_v1",
                    "updated_at": updated_at,
                },
            )

        facility_type = (record.get("facility_type") or "").strip().lower()
        for capability_key in FACILITY_TYPE_CAPABILITY_HINTS.get(facility_type, ()):
            if capability_key in claimed_capabilities:
                continue
            claims.append(
                {
                    "facility_id": record.get("record_id", ""),
                    "facility_name": record.get("entity_name", ""),
                    "state": state,
                    "district_or_city": district_or_city,
                    "district_source": record.get("district_source", "") or _district_source(record),
                    "capability": capability_key,
                    "claim_status": "claimed",
                    "confidence": "weak",
                    "evidence_text": f"Facility type is {facility_type.replace('_', ' ')}; capability requires verification.",
                    "uncertainty_reason": "Weak facility-type hint only; capability is not stated in the source description.",
                    "extraction_method": "facility_type_hint_v1",
                    "updated_at": updated_at,
                },
            )

    return claims


def _district_source(record: dict[str, str]) -> str:
    if record.get("district"):
        return "source_district"
    if record.get("city"):
        return "city_fallback"
    return "missing_location"


def summarize_capability_coverage(records: Iterable[dict[str, str]]) -> dict[str, int]:
    """Count facilities with at least one claim for each capability."""
    counts = {capability.key: 0 for capability in CAPABILITIES}
    seen_pairs: set[tuple[str, str]] = set()

    for claim in extract_facility_claims(records):
        pair = (claim["facility_id"], claim["capability"])
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        counts[claim["capability"]] += 1

    return counts


def _first_match(text: str, patterns: tuple[str, ...]) -> re.Match[str] | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match
    return None


def _snippet(text: str, start: int, end: int, window: int = 90) -> str:
    left = max(0, start - window)
    right = min(len(text), end + window)
    snippet = text[left:right].strip()
    snippet = re.sub(r"\s+", " ", snippet)
    if left > 0:
        snippet = f"...{snippet}"
    if right < len(text):
        snippet = f"{snippet}..."
    return snippet
