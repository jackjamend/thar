# Plan: Rebuild `public.health_access_records`

## Goal

Regenerate `public.health_access_records` so each facility row has a stable facility identity, correctly aligned structured fields, and a description that belongs to the listed facility. Then re-export `data/health_access_records.csv` from the corrected table.

## Problem Summary

The current snapshot contains two classes of upstream data issues:

- Some `facility` rows are not real facility records. Their `record_id` values contain markdown/prose fragments such as `facility:  *  __Genomics`, and scalar fields contain JSON arrays, coordinates, dates, or booleans.
- Some real facility rows appear to have descriptions or websites joined from a different facility.

The local CareGap scripts consume `health_access_records.csv`; they do not create the source table. The fix belongs in the upstream table build/export process.

## Rebuild Strategy

1. Locate the upstream source builder.
   - Use the three source datasets in `databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset`.
   - Run `pipelines/scripts/rebuild_health_access_records_from_uc.py` to auto-discover the raw facility, pincode, and district source tables, or pass explicit table names.
   - Record the exact source table names and join keys before making changes.

2. Rebuild facility rows from canonical source records.
   - Use only rows with a stable facility identifier.
   - Generate `record_id` as `facility:<uuid>` or preserve the canonical source UUID if already available.
   - Map fields by explicit column name, never by positional array index.
   - Keep raw scraped prose/markdown as description text only after it has been attached to a valid facility row.

3. Fix description alignment.
   - Join descriptions to facilities by a stable key such as source facility ID, source URL, provider-specific place ID, or canonical record UUID.
   - Do not join by row number, dataframe index, sort order, or fuzzy name alone.
   - If only fuzzy matching is available, write unmatched or low-confidence rows to a quarantine table instead of loading them into `public.health_access_records`.

4. Normalize source values before loading.
   - Convert `null`, empty strings, and missing values consistently.
   - Store one website value in `website`; if source has multiple URLs, choose the canonical facility/homepage URL or add a separate JSON/source column outside this table.
   - Ensure latitude and longitude are numeric and mapped only to `latitude` and `longitude`.
   - Ensure `facility_type` is limited to known values such as `hospital`, `clinic`, `dentist`, `doctor`, or `pharmacy`.

5. Add validation gates.
   - Fail the build if any `facility` row has a `record_id` that does not match `^facility:[0-9a-fA-F-]{36}$`.
   - Fail or quarantine rows where `entity_name`, `facility_type`, `operator_type`, `website`, or `description` contains obvious column drift.
   - Flag descriptions that mention a different named hospital or clinic than `entity_name`.
   - Report counts for valid, quarantined, and rejected rows.

6. Recreate `public.health_access_records`.
   - Build corrected facility rows from Unity Catalog.
   - Union with pincode and district rows using an explicit shared schema.
   - Export the rebuilt CSV.
   - Use `pipelines/scripts/load_health_access_records.py` to create a candidate Lakebase table.
   - Replace the live table only after validation passes.
   - Keep the automatic backup table created by `load_health_access_records.py --apply`.

7. Re-export the local snapshot.
   - Export with an explicit column list matching `data/health_access_records.csv`.
   - Sort deterministically by `record_type, record_id`.
   - Replace `data/health_access_records.csv` only after local validation passes.
   - Use:

     ```bash
     python pipelines/scripts/export_health_access_records.py \
       --output data/health_access_records.csv
     ```

8. Regenerate derived CareGap tables.
   - Run `python pipelines/scripts/validate_health_access_records.py --input data/health_access_records.csv`.
   - Run `python pipelines/scripts/verify_data.py --input data/health_access_records.csv`.
   - Run `python pipelines/scripts/run_all.py --input data/health_access_records.csv --out-dir data`.
   - Load regenerated `caregap_facility_claims.csv` and `caregap_district_gaps.csv` back into Lakebase if needed.

## Validation Checks

Run these checks before accepting the rebuilt table:

- Total rows by `record_type`.
- Facility rows with invalid `record_id`.
- Facility rows with blank `entity_name`.
- Facility rows with JSON, coordinate objects, dates, booleans, or UUIDs in the wrong scalar columns.
- Facility descriptions that are blank, equal to only the name, or shorter than 40 characters.
- Facility descriptions likely naming another facility.
- Facility rows with missing or non-numeric coordinates.
- Facility rows with `district` missing before and after pincode inference.

## Acceptance Criteria

- Zero facility rows have malformed `record_id` values.
- Zero facility rows have prose fragments as IDs or names.
- Zero facility rows have coordinates, JSON arrays, or booleans shifted into scalar fields.
- All non-empty facility descriptions are attached by a stable source key or marked with a documented confidence/provenance field.
- Suspicious description matches are quarantined rather than loaded as trusted facility descriptions.
- The local CSV and derived CareGap CSVs are regenerated from the corrected table.

## Recommended Follow-Up Work

- Keep `export_health_access_records.py` as the only supported local snapshot exporter.
- Keep `validate_health_access_records.py` in the extraction path before claim generation.
- Add provenance columns or a companion audit table for facility description source, match key, and match confidence.
