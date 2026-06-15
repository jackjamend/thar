from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable

from .capabilities import CARE_NEEDS


CONFIDENCE_WEIGHT = {
    "strong": 1.0,
    "partial": 0.45,
    "weak": 0.2,
    "missing": 0.0,
    "conflicting": 0.1,
}


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
    claim_scores_by_state_city: dict[tuple[str, str], float] = defaultdict(float)
    claim_counts_by_state_city: dict[tuple[str, str], int] = defaultdict(int)

    for claim in claims:
        if claim.get("capability") not in capability_keys:
            continue

        location_key = (
            _norm(claim.get("state", "")),
            _norm(claim.get("district_or_city", "")),
        )
        claim_scores_by_state_city[location_key] += CONFIDENCE_WEIGHT.get(claim.get("confidence", "missing"), 0.0)
        claim_counts_by_state_city[location_key] += 1

    scored: list[dict[str, str]] = []
    for district in districts:
        state = district.get("state", "")
        district_name = district.get("entity_name", "")
        location_key = (_norm(state), _norm(district_name))

        risk_score = _risk_score(district)
        supply_score = min(100.0, claim_scores_by_state_city.get(location_key, 0.0) * 16.0)
        evidence_score = min(100.0, claim_scores_by_state_city.get(location_key, 0.0) * 20.0)
        data_quality_score = _data_quality_score(district, claim_counts_by_state_city.get(location_key, 0))

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
                "explanation": _explanation(planning_priority_score, risk_score, supply_score, evidence_score),
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


def _data_quality_score(district: dict[str, str], relevant_claim_count: int) -> float:
    score = 100.0
    if not district.get("state"):
        score -= 25.0
    if not district.get("entity_name"):
        score -= 25.0
    if relevant_claim_count == 0:
        score -= 20.0
    return _clamp(score)


def _explanation(priority: float, risk: float, supply: float, evidence: float) -> str:
    if priority >= 70:
        level = "High planning priority"
    elif priority >= 45:
        level = "Medium planning priority"
    else:
        level = "Watch"

    return (
        f"{level}: health-risk signal is {risk:.1f}/100, claimed supply signal is "
        f"{supply:.1f}/100, and evidence strength is {evidence:.1f}/100. Review cited "
        "facility claims before making an intervention decision."
    )


def _float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))

