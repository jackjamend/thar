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
    health_access_validation.py # source health_access_records validation
    scoring.py          # district gap scoring
    lakebase_io.py      # future Lakebase read/write helpers
    llm.py              # future LLM enrichment helpers
  scripts/
    export_health_access_records.py # export source Lakebase table to CSV
    rebuild_health_access_records_from_uc.py # rebuild source snapshot from UC tables
    build_health_access_facility_enriched.py # create facility-grain joined UC table
    load_health_access_records.py # load rebuilt snapshot into Lakebase
    repair_health_access_records.py # quarantine structurally invalid source rows
    validate_health_access_records.py # validate source CSV before extraction
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

   To export from Lakebase using the explicit supported schema:

   ```bash
   python pipelines/scripts/export_health_access_records.py \
     --output data/health_access_records.csv
   ```

2. Validate the source snapshot before extraction:

   ```bash
   python pipelines/scripts/validate_health_access_records.py \
     --input data/health_access_records.csv \
     --quarantine-output data/health_access_records_quarantine.csv
   ```

   Source validation fails on structural problems such as malformed facility IDs, shifted JSON/coordinates in scalar columns, blank facility names, and description-column drift. It warns on softer description quality issues.

3. Run data verification:

   ```bash
   python pipelines/scripts/verify_data.py --input data/health_access_records.csv
   ```

4. Extract capability claims:

   ```bash
   python pipelines/scripts/extract_claims.py \
     --input data/health_access_records.csv \
     --output data/caregap_facility_claims.csv
   ```

5. Score district gaps:

   ```bash
   python pipelines/scripts/score_gaps.py \
     --input data/health_access_records.csv \
     --claims data/caregap_facility_claims.csv \
     --output data/caregap_district_gaps.csv
   ```

6. Or run extraction and all care-need scoring together:

   ```bash
   python pipelines/scripts/run_all.py \
     --input data/health_access_records.csv \
     --out-dir data
   ```

7. Load the generated tables into Lakebase for the app to read:

   ```bash
   python pipelines/scripts/load_prepared_tables.py \
     --claims data/caregap_facility_claims.csv \
     --gaps data/caregap_district_gaps.csv
   ```

## Repairing `public.health_access_records`

If source validation fails against the Lakebase table, prefer starting fresh from the three source datasets in Unity Catalog.

The default source schema is:

```text
databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset
```

Run the rebuild script on Databricks/Spark, either as a notebook/job task or with `spark-submit` in the workspace. It auto-discovers facility, pincode/post-office, and district indicator tables by their columns; pass explicit table names if discovery picks the wrong table.

```bash
python pipelines/scripts/rebuild_health_access_records_from_uc.py \
  --output-path /Volumes/<catalog>/<schema>/<volume>/health_access_records_csv
```

For explicit table selection:

```bash
python pipelines/scripts/rebuild_health_access_records_from_uc.py \
  --facility-table <facility_source_table> \
  --pincode-table <pincode_source_table> \
  --district-table <district_source_table> \
  --output-path /Volumes/<catalog>/<schema>/<volume>/health_access_records_csv
```

Copy the generated CSV part file to `data/health_access_records.csv`, validate it, then load it into Lakebase:

```bash
python pipelines/scripts/validate_health_access_records.py \
  --input data/health_access_records.csv

python pipelines/scripts/load_health_access_records.py \
  --input data/health_access_records.csv

python pipelines/scripts/load_health_access_records.py \
  --input data/health_access_records.csv \
  --apply
```

The first load command creates `public.health_access_records_candidate` and does not replace the live table. The `--apply` command backs up the live table and swaps in the candidate.

## Building the Joined Analysis Table

For analysis and inference, prefer a facility-grain enriched table over the mixed `record_type` snapshot. The enriched table keeps one row per valid facility, rolls pincode/post-office rows up to one row per pincode, and left joins NFHS district indicators through the best available district signal.

Run the builder on Databricks/Spark:

```bash
python pipelines/scripts/build_health_access_facility_enriched.py \
  --validate-only
```

When validation passes, write the Unity Catalog table:

```bash
python pipelines/scripts/build_health_access_facility_enriched.py
```

The default output table is:

```text
workspace.default.health_access_facility_enriched
```

The source dataset catalog is a Delta Sharing catalog, so it is read-only. Use `--output-table` if you want to write to a different managed catalog/schema.

To write elsewhere or export a CSV snapshot:

```bash
python pipelines/scripts/build_health_access_facility_enriched.py \
  --output-table <catalog>.<schema>.health_access_facility_enriched \
  --output-path /Volumes/<catalog>/<schema>/<volume>/health_access_facility_enriched_csv
```

The builder fails if the final row count changes from the valid facility count or if duplicate `facility_id` rows appear, which catches accidental one-to-many joins from the pincode table.

If you only need a guarded Lakebase-side cleanup for obvious structural failures in the existing table, run:

```bash
python pipelines/scripts/repair_health_access_records.py
```

That dry run creates:

- `public.health_access_records_candidate`
- `public.health_access_records_quarantine`

It does not replace the source table unless you explicitly pass `--apply`. This repair only quarantines malformed rows; it cannot recover descriptions that were already joined to the wrong facility without the original source keys.

## Target Output Tables

Python pipeline outputs:

```text
caregap_facility_claims
- facility_id
- facility_name
- state
- district_or_city
- district_source
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
- relevant_claims
- strong_claims
- partial_claims
- pincode_inferred_claims
- city_fallback_claims
- uncertainty_label
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
