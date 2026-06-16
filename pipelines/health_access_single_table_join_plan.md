# Plan: Build One Analysis-Ready Health Access Table

## Goal

Create one table for analysis and inference from the three Unity Catalog source tables:

- `databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.facilities`
- `databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.india_post_pincode_directory`
- `databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset.nfhs_5_district_health_indicators`

The table should keep every usable facility row, enrich each facility with best-known location context from pincode data, and attach district-level NFHS indicators where a district match is available.

## Current Findings

Local snapshot `data/health_access_records.csv` validates cleanly with:

- `10,000` facility rows
- `165,627` pincode/post-office rows
- `706` district indicator rows
- `0` validation errors

The previous snapshot shows why the current scripts are fragile:

- malformed facility IDs such as markdown fragments
- shifted scalar fields containing JSON, coordinates, dates, or booleans
- descriptions and websites that may not belong to the listed facility

The existing rebuild scripts primarily `UNION ALL` the three sources into a shared schema. Downstream code then infers facility districts from pincode rows. For analysis and inference, a facility-grain joined table will be easier to use and less lossy than a mixed `record_type` table.

## Recommended Target Table

Create a new facility-grain Delta table, for example:

```text
<catalog>.<schema>.health_access_facility_enriched
```

Each row is one valid facility. Keep source identifiers and add provenance so derived columns can be trusted or filtered.

Core facility fields:

- `facility_id`
- `facility_name`
- `facility_type`
- `operator_type`
- `phone`
- `website`
- `description`
- `source_city`
- `source_state`
- `source_pincode`
- `latitude`
- `longitude`

Pincode enrichment fields:

- `pincode_state`
- `pincode_district`
- `pincode_match_status`
- `pincode_office_count`
- `pincode_office_names`
- `pincode_office_types`
- `pincode_delivery_values`
- `pincode_latitude`
- `pincode_longitude`

District indicator fields:

- `district_state`
- `district_name`
- `district_match_status`
- `households_surveyed`
- `institutional_birth_pct`
- `stunting_pct`
- `anaemia_pct`
- `improved_water_pct`
- `improved_sanitation_pct`
- `health_insurance_pct`

Useful inference fields:

- `analysis_location_key`
- `location_confidence`
- `facility_profile_text`
- `source_quality_flags`
- `created_at`

## Join Strategy

1. Clean facilities first.
   - Keep only rows with valid `unique_id` UUIDs.
   - Normalize names from JSON/string variants.
   - Normalize `facilityTypeId` and `operatorTypeId`.
   - Cast coordinates with `try_cast`.
   - Keep a generated fallback description only when no trustworthy source description exists.

2. Roll up pincode rows before joining.
   - Do not directly join facilities to raw pincode rows because one pincode can have many post offices and would duplicate facility rows.
   - Build one row per normalized pincode.
   - Choose canonical `(state, district)` using the most frequent non-empty pair.
   - Preserve post-office detail as arrays or delimited strings: office names, office types, delivery values, divisions, regions, and circles.
   - Keep `office_count` and coordinate coverage so users know how broad the pincode evidence is.

3. Normalize district indicators.
   - Build one row per normalized `(state, district)`.
   - Preserve original state and district display names.
   - Cast all NFHS indicators to numeric columns.
   - Add a normalized join key, not just display text.

4. Left join from facilities outward.
   - `facilities LEFT JOIN pincode_rollup ON normalized facility pincode`
   - `LEFT JOIN district_indicators ON normalized state + normalized district`
   - Prefer source district if present, otherwise pincode district, otherwise city fallback.
   - Mark the match path in `district_match_status`.

5. Do not discard unmatched rows.
   - Facilities without a pincode match stay in the table with `pincode_match_status = 'missing'`.
   - Facilities with pincode but no district indicator stay in the table with `district_match_status = 'missing_nfhs'`.
   - Suspicious rows stay available only if structurally valid; add flags rather than silently dropping them.

## SQL Shape

```sql
CREATE OR REPLACE TABLE <catalog>.<schema>.health_access_facility_enriched AS
WITH facility_clean AS (...),
pincode_normalized AS (...),
pincode_rollup AS (
  SELECT
    pincode_key,
    max_by(state, state_district_count) AS pincode_state,
    max_by(district, state_district_count) AS pincode_district,
    count(*) AS pincode_office_count,
    array_sort(collect_set(officename)) AS pincode_office_names,
    array_sort(collect_set(officetype)) AS pincode_office_types,
    array_sort(collect_set(delivery)) AS pincode_delivery_values,
    avg(try_cast(latitude AS DOUBLE)) AS pincode_latitude,
    avg(try_cast(longitude AS DOUBLE)) AS pincode_longitude
  FROM pincode_normalized
  GROUP BY pincode_key
),
district_clean AS (...),
joined AS (
  SELECT
    f.*,
    p.*,
    d.*,
    CASE
      WHEN p.pincode_key IS NOT NULL THEN 'matched'
      ELSE 'missing'
    END AS pincode_match_status,
    CASE
      WHEN d.district_key IS NOT NULL THEN 'matched'
      WHEN p.pincode_district IS NOT NULL THEN 'pincode_no_nfhs'
      ELSE 'missing_location'
    END AS district_match_status
  FROM facility_clean f
  LEFT JOIN pincode_rollup p
    ON f.pincode_key = p.pincode_key
  LEFT JOIN district_clean d
    ON normalize(coalesce(f.source_state, p.pincode_state)) = d.state_key
   AND normalize(coalesce(f.source_district, p.pincode_district, f.source_city)) = d.district_key
)
SELECT * FROM joined;
```

## Validation Checks

Run these before using the table:

- Facility row count before and after joins must match.
- No duplicate `facility_id` rows.
- Count facilities by `pincode_match_status` and `district_match_status`.
- Count facilities with NFHS indicators attached.
- Sample unmatched pincodes and unmatched districts.
- Validate that direct pincode joins would have duplicated rows, and confirm rollup prevented that.
- Confirm no malformed IDs, shifted JSON/coordinate/date values, or blank facility names.
- Compare capability extraction coverage before and after the enriched build.

## Implementation Steps

1. Re-authenticate Databricks CLI and inspect live source schemas/counts.
2. Add a Spark/SQL builder script for `health_access_facility_enriched`.
3. Keep the existing mixed `health_access_records` export for current app compatibility until the app is migrated.
4. Update extraction/scoring to prefer the enriched table fields:
   - use attached district indicators directly
   - use `location_confidence`
   - include pincode and district match provenance in claims
5. Export a local CSV snapshot of the enriched table for development.
6. Regenerate `caregap_facility_claims.csv` and `caregap_district_gaps.csv`.
7. Only replace app-facing tables after the enriched table validates and derived outputs look sane.

## Authentication Blocker

Live Unity Catalog review could not be completed locally because both configured Databricks CLI profiles are currently invalid:

- `DEFAULT`
- `dais-2026`

After re-authentication, use `databricks experimental aitools tools discover-schema` and targeted row-count/match-rate queries to confirm the exact source schemas before implementation.
