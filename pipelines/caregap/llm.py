from __future__ import annotations


def summarize_uncertainty(evidence_rows: list[dict[str, str]]) -> str:
    """Placeholder for LLM-based uncertainty summaries.

    Keep the deterministic pipeline useful without this function. Once a stable
    Databricks Model Serving endpoint is available, wire it here and cache
    outputs in a prepared table.
    """
    strong = sum(1 for row in evidence_rows if row.get("confidence") == "strong")
    partial = sum(1 for row in evidence_rows if row.get("confidence") == "partial")
    weak = sum(1 for row in evidence_rows if row.get("confidence") in {"weak", "missing", "conflicting"})

    return (
        f"Evidence summary: {strong} strong claims, {partial} partial claims, "
        f"and {weak} weak or missing claims. Verify weak claims before action."
    )

