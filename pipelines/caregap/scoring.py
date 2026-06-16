from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Iterable

from .capabilities import CARE_NEEDS
from .records import canonical_district, canonical_state


CONFIDENCE_WEIGHT = {
    "strong": 1.0,
    "partial": 0.45,
    "weak": 0.2,
    "missing": 0.0,
    "conflicting": 0.1,
}

DISTRICT_SOURCE_WEIGHT = {
    "source_district": 1.0,
    "pincode_inferred": 0.85,
    "city_fallback": 0.45,
    "missing_location": 0.0,
    "": 0.3,
}


@dataclass
class ClaimSignal:
    weighted_supply: float = 0.0
    relevant_claims: int = 0
    strong_claims: int = 0
    partial_claims: int = 0
    weak_claims: int = 0
    conflicting_claims: int = 0
    pincode_inferred_claims: int = 0
    city_fallback_claims: int = 0
    missing_location_claims: int = 0

    def add(self, claim: dict[str, str]) -> None:
        confidence = claim.get("confidence", "missing")
        district_source = claim.get("district_source", "")
        confidence_weight = CONFIDENCE_WEIGHT.get(confidence, 0.0)
        location_weight = DISTRICT_SOURCE_WEIGHT.get(district_source, DISTRICT_SOURCE_WEIGHT[""])

        self.weighted_supply += confidence_weight * location_weight
        self.relevant_claims += 1
        if confidence == "strong":
            self.strong_claims += 1
        elif confidence == "partial":
            self.partial_claims += 1
        elif confidence == "weak":
            self.weak_claims += 1
        elif confidence == "conflicting":
            self.conflicting_claims += 1

        if district_source == "pincode_inferred":
            self.pincode_inferred_claims += 1
        elif district_source == "city_fallback":
            self.city_fallback_claims += 1
        elif district_source == "missing_location":
            self.missing_location_claims += 1


def score_district_gaps(
    records: Iterable[dict[str, str]],
    claims: Iterable[dict[str, str]],
    care_need: str = "maternal_emergency",
) -> list[dict[str, str]]:
    """Create district-level planning priority scores.

    Scores are intentionally simple for the hackathon scaffold. They should be
    treated as planning-priority signals, not as ground truth.
    """
    capability_keys = set(CARE_NEEDS[care_need])
    updated_at = datetime.now(timezone.utc).isoformat()

    districts = [record for record in records if record.get("record_type") == "district"]
    claim_signals_by_district: dict[tuple[str, str], ClaimSignal] = defaultdict(ClaimSignal)

    for claim in claims:
        if claim.get("capability") not in capability_keys:
            continue

        state = canonical_state(claim.get("state")) or claim.get("state", "")
        location_key = (
            _norm(state),
            _norm(canonical_district(state, claim.get("district_or_city", ""))),
        )
        claim_signals_by_district[location_key].add(claim)

    scored: list[dict[str, str]] = []
    for district in districts:
        state = canonical_state(district.get("state")) or district.get("state", "")
        district_name = district.get("entity_name", "")
        location_key = (_norm(state), _norm(canonical_district(state, district_name)))
        claim_signal = claim_signals_by_district[location_key]

        risk_score = _risk_score(district)
        supply_score = _supply_score(claim_signal)
        evidence_score = _evidence_score(claim_signal)
        data_quality_score = _data_quality_score(district, claim_signal)
        uncertainty_label = _uncertainty_label(claim_signal, data_quality_score)

        planning_priority_score = _clamp(
            (risk_score * 0.55)
            + ((100.0 - supply_score) * 0.25)
            + ((100.0 - evidence_score) * 0.15)
            + ((100.0 - data_quality_score) * 0.05),
        )

        scored.append(
            {
                "district_id": district.get("record_id", ""),
                "district_name": district_name,
                "state": state,
                "care_need": care_need,
                "planning_priority_score": f"{planning_priority_score:.1f}",
                "risk_score": f"{risk_score:.1f}",
                "supply_score": f"{supply_score:.1f}",
                "evidence_score": f"{evidence_score:.1f}",
                "data_quality_score": f"{data_quality_score:.1f}",
                "relevant_claims": str(claim_signal.relevant_claims),
                "strong_claims": str(claim_signal.strong_claims),
                "partial_claims": str(claim_signal.partial_claims),
                "pincode_inferred_claims": str(claim_signal.pincode_inferred_claims),
                "city_fallback_claims": str(claim_signal.city_fallback_claims),
                "uncertainty_label": uncertainty_label,
                "explanation": _explanation(
                    planning_priority_score,
                    risk_score,
                    supply_score,
                    evidence_score,
                    claim_signal,
                    uncertainty_label,
                ),
                "updated_at": updated_at,
            },
        )

    return sorted(scored, key=lambda row: float(row["planning_priority_score"]), reverse=True)


def _risk_score(district: dict[str, str]) -> float:
    anaemia = _float(district.get("anaemia_pct"))
    stunting = _float(district.get("stunting_pct"))
    institutional_birth = _float(district.get("institutional_birth_pct"))
    institutional_birth_gap = 100.0 - institutional_birth if institutional_birth else 50.0
    values = [value for value in (anaemia, stunting, institutional_birth_gap) if value is not None]
    if not values:
        return 50.0
    return _clamp(sum(values) / len(values))


def _supply_score(signal: ClaimSignal) -> float:
    if signal.relevant_claims == 0:
        return 0.0
    # Six strong, well-located claims is enough to count as a strong district-level supply signal.
    return min(100.0, signal.weighted_supply * (100.0 / 6.0))


def _evidence_score(signal: ClaimSignal) -> float:
    if signal.relevant_claims == 0:
        return 0.0

    confidence_score = min(100.0, signal.weighted_supply * (100.0 / 5.0))
    strong_share = signal.strong_claims / signal.relevant_claims
    location_penalty = 0.0
    if signal.city_fallback_claims:
        location_penalty += min(20.0, signal.city_fallback_claims * 5.0)
    if signal.missing_location_claims:
        location_penalty += min(35.0, signal.missing_location_claims * 10.0)

    return _clamp((confidence_score * 0.7) + (strong_share * 100.0 * 0.3) - location_penalty)


def _data_quality_score(district: dict[str, str], signal: ClaimSignal) -> float:
    score = 100.0
    if not district.get("state"):
        score -= 25.0
    if not district.get("entity_name"):
        score -= 25.0
    if signal.relevant_claims == 0:
        score -= 20.0
    if signal.city_fallback_claims:
        score -= min(25.0, signal.city_fallback_claims * 5.0)
    if signal.missing_location_claims:
        score -= min(40.0, signal.missing_location_claims * 10.0)
    return _clamp(score)


def _uncertainty_label(signal: ClaimSignal, data_quality_score: float) -> str:
    if signal.relevant_claims == 0:
        return "missing"
    if signal.conflicting_claims:
        return "conflicting"
    if data_quality_score < 65 or signal.city_fallback_claims or signal.missing_location_claims:
        return "weak"
    if signal.strong_claims >= 2 and signal.strong_claims >= signal.partial_claims:
        return "strong"
    if signal.strong_claims or signal.partial_claims:
        return "partial"
    return "weak"


def _explanation(
    priority: float,
    risk: float,
    supply: float,
    evidence: float,
    signal: ClaimSignal,
    uncertainty_label: str,
) -> str:
    if priority >= 70:
        level = "High planning priority"
    elif priority >= 45:
        level = "Medium planning priority"
    else:
        level = "Watch"

    if signal.relevant_claims == 0:
        evidence_note = "No relevant facility claims were found for this care need."
    else:
        evidence_note = (
            f"Found {signal.relevant_claims} relevant claimed capabilities "
            f"({signal.strong_claims} strong, {signal.partial_claims} partial)."
        )

    return (
        f"{level}: health-risk signal is {risk:.1f}/100, claimed supply signal is "
        f"{supply:.1f}/100, and evidence strength is {evidence:.1f}/100. "
        f"{evidence_note} Overall evidence label is {uncertainty_label}; review cited "
        "facility text before making an intervention decision."
    )


def _float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").strip().lower()).strip()


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))
