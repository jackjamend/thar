# Health Access Facility Enriched Runbook

## Output Table

The enriched analysis table is:

```text
workspace.default.health_access_facility_enriched
```

It was created from the three DAIS 2026 Unity Catalog source tables:

```text
databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities
databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.india_post_pincode_directory
databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.nfhs_5_district_health_indicators
```

The source catalog is a Delta Sharing catalog, so it is read-only. The enriched table must be written to a managed writable catalog such as `workspace.default`.

## Authentication Note

The Codex sandbox cannot read the Databricks OAuth credential cache in the user home directory. To make Databricks CLI commands work, the user needed to authenticate the Codex session from a web browser using OAuth:

```bash
databricks auth login \
  --host https://dbc-e3cabb27-f036.cloud.databricks.com \
  --profile dais-2026
```

After browser login, Databricks commands that access the OAuth cache may still need to run outside the Codex sandbox with elevated execution. Verify auth with:

```bash
databricks auth profiles
databricks current-user me --profile dais-2026
```

## How The Data Was Created

The build script is:

```text
pipelines/scripts/build_health_access_facility_enriched.py
```

The script builds a facility-grain table:

1. Cleans facility rows from `facilities`.
   - Keeps rows with valid UUID-style `unique_id` values.
   - Normalizes facility names, facility type, operator type, phone, website, pincode, latitude, and longitude.
   - Builds a fallback facility description when no usable source description exists.
   - Drops exact duplicate source rows.
   - Preserves duplicate provenance fields:
     - `source_duplicate_count`
     - `source_duplicate_rank`
     - `source_row_signature`

2. Rolls pincode rows up before joining.
   - Groups `india_post_pincode_directory` to one row per normalized pincode.
   - Chooses the canonical `(state, district)` by most frequent pair.
   - Preserves post-office context as arrays, including office names, office types, delivery values, circles, regions, and divisions.
   - This prevents one facility from becoming many rows when a pincode has multiple post offices.

3. Cleans district indicators.
   - Normalizes district and state join keys.
   - Safely parses NFHS numeric fields.
   - Handles malformed numeric strings, including values such as `(18.0)`.

4. Left joins from facilities outward.
   - Facility rows are never dropped because of missing pincode or missing NFHS data.
   - `pincode_match_status`, `district_match_status`, `district_source`, and `location_confidence` document how each row was enriched.

## Recreate The Table

Upload the script to Databricks as a raw workspace file:

```bash
databricks workspace mkdirs \
  /Workspace/Users/jamend@humana.com/db_hackathon26/pipelines/scripts \
  --profile dais-2026

databricks workspace import \
  /Workspace/Users/jamend@humana.com/db_hackathon26/pipelines/scripts/build_health_access_facility_enriched_file.py \
  --file pipelines/scripts/build_health_access_facility_enriched.py \
  --format RAW \
  --overwrite \
  --profile dais-2026
```

Run validation first:

```bash
databricks jobs submit \
  --json @.databricks-health-enriched-validate-run.json \
  --profile dais-2026 \
  --timeout 30m
```

Run the build:

```bash
databricks jobs submit \
  --json @.databricks-health-enriched-build-run.json \
  --profile dais-2026 \
  --timeout 30m
```

The build JSON writes to:

```text
workspace.default.health_access_facility_enriched
```

You can also run the Python script directly on Databricks/Spark:

```bash
python pipelines/scripts/build_health_access_facility_enriched.py --validate-only
python pipelines/scripts/build_health_access_facility_enriched.py
```

Use `--output-table` to choose another writable destination:

```bash
python pipelines/scripts/build_health_access_facility_enriched.py \
  --output-table workspace.default.health_access_facility_enriched
```

## Validation Results From Successful Build

Successful build run:

```text
workspace.default.health_access_facility_enriched
```

Observed counts:

```text
input valid facility rows: 9,989
enriched facility rows: 9,989
duplicate facility_id rows: 0
```

Match summary:

```text
pincode matched: 9,707
pincode missing: 282
NFHS district matched: 6,199
NFHS missing: 3,790
```

Final SQL verification:

```sql
SELECT
  COUNT(*) AS rows,
  COUNT(DISTINCT facility_id) AS distinct_facilities
FROM workspace.default.health_access_facility_enriched;
```

Expected result:

```text
rows: 9,989
distinct_facilities: 9,989
```

## Tips And Gotchas

- Do not write to `databricks_virtue_foundation_dataset_dais_2026`; it is Delta Sharing and read-only.
- Do not directly join raw pincode rows to facilities. Roll up to one row per pincode first.
- Run `--validate-only` before writing. The script fails if joins duplicate/drop facility rows.
- Use the `dais-2026` profile explicitly on every CLI command.
- If CLI auth looks valid outside Codex but fails inside Codex, rerun the Databricks command with elevated execution so it can read the OAuth cache.
- If a job fails, inspect task output, not only the parent run:

  ```bash
  databricks jobs get-run <parent-run-id> --profile dais-2026 -o json
  databricks jobs get-run-output <task-run-id> --profile dais-2026 -o json
  ```
