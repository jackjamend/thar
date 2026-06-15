# CareGap Python Pipelines

This folder contains the Python-side analytical pipeline for **CareGap: Medical Desert Planner**.

The Databricks App should stay focused on the review workflow:

- Render the district review queue.
- Show facility evidence and uncertainty.
- Persist planner actions in Lakebase.

The Python pipeline owns the analytical preparation:

- Verify whether facility descriptions contain useful capability evidence.
- Extract cited facility capability claims.
- Score district care gaps.
- Optionally enrich explanations with an LLM.
- Write prepared outputs for the app to read.

## Folder Structure

```text
pipelines/
  requirements.txt
  caregap/
    capabilities.py     # capability taxonomy and deterministic extraction
    scoring.py          # district gap scoring
    lakebase_io.py      # future Lakebase read/write helpers
    llm.py              # future LLM enrichment helpers
  scripts/
    verify_data.py      # inspect descriptions and capability coverage
    extract_claims.py   # create facility capability claim rows
    score_gaps.py       # create district gap score rows
    run_all.py          # run extraction + scoring together
  notebooks/
    exploration.py      # Databricks notebook-style scratchpad
```

## Recommended Hackathon Flow

1. Export or query facility records into a CSV with fields like:
   - `record_id`
   - `record_type`
   - `entity_name`
   - `state`
   - `city`
   - `pincode`
   - `facility_type`
   - `description`
   - NFHS district indicator columns, where available

2. Run data verification:

   ```bash
   python pipelines/scripts/verify_data.py --input data/health_access_records.csv
   ```

3. Extract capability claims:

   ```bash
   python pipelines/scripts/extract_claims.py \
     --input data/health_access_records.csv \
     --output data/caregap_facility_claims.csv
   ```

4. Score district gaps:

   ```bash
   python pipelines/scripts/score_gaps.py \
     --input data/health_access_records.csv \
     --claims data/caregap_facility_claims.csv \
     --output data/caregap_district_gaps.csv
   ```

5. Load the generated tables into Lakebase or a synced table for the app to read.

## Target Output Tables

Python pipeline outputs:

```text
caregap_facility_claims
- facility_id
- facility_name
- state
- district_or_city
- capability
- claim_status
- confidence
- evidence_text
- uncertainty_reason
- extraction_method
- updated_at

caregap_district_gaps
- district_id
- district_name
- state
- care_need
- planning_priority_score
- risk_score
- supply_score
- evidence_score
- data_quality_score
- explanation
- updated_at
```

App writes:

```text
caregap_review_decisions
caregap_planner_notes
caregap_shortlists
caregap_facility_verifications
caregap_score_overrides
```

## Design Notes

- Keep deterministic extraction working even if LLM endpoints are unavailable.
- Treat uncertainty as product behavior, not an error.
- Cite exact evidence snippets for every important facility capability claim.
- Use cautious language: "claimed capability", "planning priority", and "needs verification".
- Avoid presenting scores as ground truth.

