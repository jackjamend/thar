from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from caregap.lakebase_io import lakebase_connection


CLAIM_FIELDS = [
    "facility_id",
    "facility_name",
    "state",
    "district_or_city",
    "district_source",
    "capability",
    "claim_status",
    "confidence",
    "evidence_text",
    "uncertainty_reason",
    "extraction_method",
    "updated_at",
]

GAP_FIELDS = [
    "district_id",
    "district_name",
    "state",
    "care_need",
    "planning_priority_score",
    "risk_score",
    "supply_score",
    "evidence_score",
    "data_quality_score",
    "relevant_claims",
    "strong_claims",
    "partial_claims",
    "pincode_inferred_claims",
    "city_fallback_claims",
    "uncertainty_label",
    "explanation",
    "updated_at",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Load CareGap prepared CSVs into Lakebase public tables.")
    parser.add_argument("--claims", required=True, help="CSV path for caregap_facility_claims.")
    parser.add_argument("--gaps", required=True, help="CSV path for caregap_district_gaps.")
    args = parser.parse_args()

    with lakebase_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_CLAIMS_TABLE_SQL)
            cur.execute(CREATE_GAPS_TABLE_SQL)
            cur.execute("TRUNCATE TABLE public.caregap_facility_claims")
            cur.execute("TRUNCATE TABLE public.caregap_district_gaps")
            _copy_csv(cur, "public.caregap_facility_claims", CLAIM_FIELDS, Path(args.claims))
            _copy_csv(cur, "public.caregap_district_gaps", GAP_FIELDS, Path(args.gaps))
            for sql in INDEX_SQL:
                cur.execute(sql)

    print(f"Loaded {args.claims} into public.caregap_facility_claims")
    print(f"Loaded {args.gaps} into public.caregap_district_gaps")


def _copy_csv(cur, table_name: str, fields: list[str], path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)

    columns = ", ".join(fields)
    with path.open("r", encoding="utf-8", newline="") as handle:
        with cur.copy(f"COPY {table_name} ({columns}) FROM STDIN WITH CSV HEADER") as copy:
            while chunk := handle.read(1024 * 1024):
                copy.write(chunk)


CREATE_CLAIMS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS public.caregap_facility_claims (
  facility_id TEXT NOT NULL,
  facility_name TEXT NOT NULL,
  state TEXT NOT NULL,
  district_or_city TEXT NOT NULL,
  district_source TEXT NOT NULL,
  capability TEXT NOT NULL,
  claim_status TEXT NOT NULL,
  confidence TEXT NOT NULL,
  evidence_text TEXT NOT NULL,
  uncertainty_reason TEXT NOT NULL,
  extraction_method TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
)
"""

CREATE_GAPS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS public.caregap_district_gaps (
  district_id TEXT NOT NULL,
  district_name TEXT NOT NULL,
  state TEXT NOT NULL,
  care_need TEXT NOT NULL,
  planning_priority_score NUMERIC(5, 1) NOT NULL,
  risk_score NUMERIC(5, 1) NOT NULL,
  supply_score NUMERIC(5, 1) NOT NULL,
  evidence_score NUMERIC(5, 1) NOT NULL,
  data_quality_score NUMERIC(5, 1) NOT NULL,
  relevant_claims INTEGER NOT NULL,
  strong_claims INTEGER NOT NULL,
  partial_claims INTEGER NOT NULL,
  pincode_inferred_claims INTEGER NOT NULL,
  city_fallback_claims INTEGER NOT NULL,
  uncertainty_label TEXT NOT NULL,
  explanation TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
)
"""

INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_caregap_gaps_need_state ON public.caregap_district_gaps (care_need, state)",
    "CREATE INDEX IF NOT EXISTS idx_caregap_gaps_need_evidence ON public.caregap_district_gaps (care_need, uncertainty_label)",
    "CREATE INDEX IF NOT EXISTS idx_caregap_claims_lookup ON public.caregap_facility_claims (state, district_or_city, capability)",
    "CREATE INDEX IF NOT EXISTS idx_caregap_claims_capability ON public.caregap_facility_claims (capability)",
]


if __name__ == "__main__":
    main()
