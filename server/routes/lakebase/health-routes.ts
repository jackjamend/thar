import { Application } from 'express';
import { z } from 'zod';

interface AppKitWithLakebase {
  lakebase: {
    query(text: string, params?: unknown[]): Promise<{ rows: Record<string, unknown>[] }>;
  };
  server: {
    extend(fn: (app: Application) => void): void;
  };
}

const SearchQuery = z.object({
  q: z.string().optional().default(''),
  state: z.string().optional().default('all'),
  type: z.string().optional().default('all'),
  limit: z.coerce.number().int().min(1).max(100).optional().default(25),
});

const DistrictQuery = z.object({
  state: z.string().optional().default('all'),
  limit: z.coerce.number().int().min(1).max(200).optional().default(50),
});

const ENRICHED_TABLE = 'public.health_access_facility_enriched';
const LEGACY_TABLE = 'public.health_access_records';

async function safeRows(appkit: AppKitWithLakebase, label: string, sql: string, params: unknown[] = []) {
  try {
    const result = await appkit.lakebase.query(sql, params);
    return { ok: true, rows: result.rows, error: null };
  } catch (err) {
    const message = err instanceof Error ? err.message : `Failed to query ${label}`;
    console.warn(`[health] ${label}: ${message}`);
    return { ok: false, rows: [], error: message };
  }
}

function firstNumber(rows: Record<string, unknown>[], key: string) {
  const value = rows[0]?.[key];
  return Number(value ?? 0);
}

function stringField(value: unknown, fallback = '') {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return fallback;
}

export function setupHealthExplorerRoutes(appkit: AppKitWithLakebase) {
  appkit.server.extend((app) => {
    app.get('/api/health/overview', async (_req, res) => {
      const enriched = await enrichedOverview(appkit);
      if (enriched.ok) {
        res.json(enriched.payload);
        return;
      }

      const [facilityCount, pincodeCount, districtCount, stateHealthRows, facilityStateRows, typeRows] = await Promise.all([
        safeRows(appkit, 'facility count', `SELECT COUNT(*)::int AS count FROM ${LEGACY_TABLE} WHERE record_type = 'facility'`),
        safeRows(appkit, 'pincode count', `SELECT COUNT(*)::int AS count FROM ${LEGACY_TABLE} WHERE record_type = 'pincode'`),
        safeRows(appkit, 'district count', `SELECT COUNT(*)::int AS count FROM ${LEGACY_TABLE} WHERE record_type = 'district'`),
        safeRows(
          appkit,
          'state health summary',
          `
            SELECT
              state,
              COUNT(*)::int AS districts,
              ROUND(AVG(institutional_birth_pct::numeric), 1)::float AS institutional_birth_pct,
              ROUND(AVG(stunting_pct::numeric), 1)::float AS stunting_pct,
              ROUND(AVG(anaemia_pct::numeric), 1)::float AS anaemia_pct
            FROM ${LEGACY_TABLE}
            WHERE record_type = 'district'
            GROUP BY state
            ORDER BY state
          `,
        ),
        safeRows(
          appkit,
          'facility state summary',
          `
            SELECT UPPER(state) AS state, COUNT(*)::int AS facilities
            FROM ${LEGACY_TABLE}
            WHERE record_type = 'facility' AND state IS NOT NULL
            GROUP BY UPPER(state)
          `,
        ),
        safeRows(
          appkit,
          'facility type summary',
          `
            SELECT COALESCE(facility_type, 'unknown') AS facility_type, COUNT(*)::int AS count
            FROM ${LEGACY_TABLE}
            WHERE record_type = 'facility'
            GROUP BY COALESCE(facility_type, 'unknown')
            ORDER BY count DESC, facility_type
            LIMIT 8
          `,
        ),
      ]);

      const facilityCountsByState = new Map(
        facilityStateRows.rows.map((row) => [stringField(row.state), Number(row.facilities ?? 0)]),
      );
      const states = stateHealthRows.rows
        .map((row): Record<string, unknown> & { state: string; facilities: number } => {
          const state = stringField(row.state, 'Unknown');
          return {
            ...row,
            state,
            facilities: facilityCountsByState.get(state.toUpperCase()) ?? 0,
          };
        })
        .sort((a, b) => Number(b.facilities) - Number(a.facilities) || String(a.state).localeCompare(String(b.state)))
        .slice(0, 12);

      res.json({
        counts: {
          facilities: firstNumber(facilityCount.rows, 'count'),
          pincodes: firstNumber(pincodeCount.rows, 'count'),
          districts: firstNumber(districtCount.rows, 'count'),
          states: stateHealthRows.rows.length,
        },
        states,
        facilityTypes: typeRows.rows,
        source: 'legacy-health-access-records',
        availability: {
          facilities: facilityCount.ok && typeRows.ok,
          pincodeDirectory: pincodeCount.ok,
          nfhsIndicators: districtCount.ok,
        },
        errors: [
          facilityCount.error,
          pincodeCount.error,
          districtCount.error,
          stateHealthRows.error,
          facilityStateRows.error,
          typeRows.error,
        ].filter(Boolean),
      });
    });

    app.get('/api/health/facilities', async (req, res) => {
      const parsed = SearchQuery.safeParse(req.query);
      if (!parsed.success) {
        res.status(400).json({ error: 'Invalid search parameters' });
        return;
      }

      const enriched = await enrichedFacilities(appkit, parsed.data);
      if (enriched.ok) {
        res.json(enriched.rows);
        return;
      }

      const { q, state, type, limit } = parsed.data;
      const result = await safeRows(
        appkit,
        'facility search',
        `
          SELECT
            record_id AS facility_id,
            entity_name AS name,
            facility_type,
            operator_type,
            city,
            state,
            pincode,
            phone,
            website,
            latitude,
            longitude,
            description
          FROM ${LEGACY_TABLE}
          WHERE
            record_type = 'facility'
            AND ($1 = '' OR lower(COALESCE(entity_name, '')) LIKE '%' || $1 || '%'
              OR lower(COALESCE(city, '')) LIKE '%' || $1 || '%'
              OR lower(COALESCE(state, '')) LIKE '%' || $1 || '%'
              OR COALESCE(pincode, '') LIKE '%' || $1 || '%')
            AND ($2 = 'all' OR state = $2)
            AND ($3 = 'all' OR facility_type = $3)
          ORDER BY entity_name NULLS LAST
          LIMIT $4
        `,
        [q.trim().toLowerCase(), state, type, limit],
      );

      res.json(result.ok ? result.rows : []);
    });

    app.get('/api/health/districts', async (req, res) => {
      const parsed = DistrictQuery.safeParse(req.query);
      if (!parsed.success) {
        res.status(400).json({ error: 'Invalid district parameters' });
        return;
      }

      const enriched = await enrichedDistricts(appkit, parsed.data);
      if (enriched.ok) {
        res.json(enriched.rows);
        return;
      }

      const { state, limit } = parsed.data;
      const result = await safeRows(
        appkit,
        'district indicators',
        `
          SELECT
            record_id AS district_id,
            entity_name AS district_name,
            state AS state_ut,
            households_surveyed,
            institutional_birth_pct AS institutional_birth_5y_pct,
            stunting_pct,
            anaemia_pct,
            improved_water_pct AS hh_improved_water_pct,
            improved_sanitation_pct AS hh_use_improved_sanitation_pct,
            health_insurance_pct AS hh_member_covered_health_insurance_pct
          FROM ${LEGACY_TABLE}
          WHERE record_type = 'district' AND ($1 = 'all' OR state = $1)
          ORDER BY state, entity_name
          LIMIT $2
        `,
        [state, limit],
      );

      res.json(result.ok ? result.rows : []);
    });
  });
}

async function enrichedOverview(appkit: AppKitWithLakebase) {
  const [facilityCount, pincodeCount, districtCount, stateRows, typeRows] = await Promise.all([
    safeRows(appkit, 'enriched facility count', `SELECT COUNT(*)::int AS count FROM ${ENRICHED_TABLE}`),
    safeRows(
      appkit,
      'enriched pincode match count',
      `SELECT COUNT(*)::int AS count FROM ${ENRICHED_TABLE} WHERE pincode_match_status = 'matched'`,
    ),
    safeRows(
      appkit,
      'enriched district count',
      `
        SELECT COUNT(DISTINCT analysis_state || '|' || analysis_district)::int AS count
        FROM ${ENRICHED_TABLE}
        WHERE district_match_status = 'matched'
      `,
    ),
    safeRows(
      appkit,
      'enriched state summary',
      `
        SELECT
          analysis_state AS state,
          COUNT(*)::int AS facilities,
          COUNT(DISTINCT analysis_district)::int AS districts,
          ROUND(AVG(institutional_birth_pct::numeric), 1)::float AS institutional_birth_pct,
          ROUND(AVG(stunting_pct::numeric), 1)::float AS stunting_pct,
          ROUND(AVG(anaemia_pct::numeric), 1)::float AS anaemia_pct
        FROM ${ENRICHED_TABLE}
        WHERE analysis_state IS NOT NULL
        GROUP BY analysis_state
        ORDER BY facilities DESC, analysis_state
        LIMIT 12
      `,
    ),
    safeRows(
      appkit,
      'enriched facility type summary',
      `
        SELECT COALESCE(facility_type, 'unknown') AS facility_type, COUNT(*)::int AS count
        FROM ${ENRICHED_TABLE}
        GROUP BY COALESCE(facility_type, 'unknown')
        ORDER BY count DESC, facility_type
        LIMIT 8
      `,
    ),
  ]);

  if (!facilityCount.ok || !stateRows.ok || !typeRows.ok) return { ok: false, payload: null };

  return {
    ok: true,
    payload: {
      counts: {
        facilities: firstNumber(facilityCount.rows, 'count'),
        pincodes: firstNumber(pincodeCount.rows, 'count'),
        districts: firstNumber(districtCount.rows, 'count'),
        states: stateRows.rows.length,
      },
      states: stateRows.rows,
      facilityTypes: typeRows.rows,
      source: 'health-access-facility-enriched',
      availability: {
        facilities: facilityCount.ok && typeRows.ok,
        pincodeDirectory: pincodeCount.ok,
        nfhsIndicators: districtCount.ok,
      },
      errors: [facilityCount.error, pincodeCount.error, districtCount.error, stateRows.error, typeRows.error].filter(Boolean),
    },
  };
}

async function enrichedFacilities(
  appkit: AppKitWithLakebase,
  query: z.infer<typeof SearchQuery>,
) {
  const result = await safeRows(
    appkit,
    'enriched facility search',
    `
      SELECT
        facility_id,
        facility_name AS name,
        facility_type,
        operator_type,
        source_city AS city,
        analysis_state AS state,
        analysis_district AS district,
        source_pincode AS pincode,
        phone,
        website,
        latitude,
        longitude,
        description,
        pincode_match_status,
        district_match_status,
        district_source,
        location_confidence,
        source_quality_flags
      FROM ${ENRICHED_TABLE}
      WHERE
        ($1 = '' OR lower(COALESCE(facility_name, '')) LIKE '%' || $1 || '%'
          OR lower(COALESCE(source_city, '')) LIKE '%' || $1 || '%'
          OR lower(COALESCE(analysis_state, '')) LIKE '%' || $1 || '%'
          OR lower(COALESCE(analysis_district, '')) LIKE '%' || $1 || '%'
          OR COALESCE(source_pincode, '') LIKE '%' || $1 || '%')
        AND ($2 = 'all' OR analysis_state = $2)
        AND ($3 = 'all' OR facility_type = $3)
      ORDER BY facility_name NULLS LAST
      LIMIT $4
    `,
    [query.q.trim().toLowerCase(), query.state, query.type, query.limit],
  );
  return result.ok ? { ok: true, rows: result.rows } : { ok: false, rows: [] };
}

async function enrichedDistricts(appkit: AppKitWithLakebase, query: z.infer<typeof DistrictQuery>) {
  const result = await safeRows(
    appkit,
    'enriched district indicators',
    `
      SELECT
        MIN(analysis_location_key) AS district_id,
        analysis_district AS district_name,
        analysis_state AS state_ut,
        MAX(households_surveyed) AS households_surveyed,
        MAX(institutional_birth_pct) AS institutional_birth_5y_pct,
        MAX(stunting_pct) AS stunting_pct,
        MAX(anaemia_pct) AS anaemia_pct,
        MAX(improved_water_pct) AS hh_improved_water_pct,
        MAX(improved_sanitation_pct) AS hh_use_improved_sanitation_pct,
        MAX(health_insurance_pct) AS hh_member_covered_health_insurance_pct,
        COUNT(*)::int AS facilities,
        SUM(CASE WHEN pincode_match_status = 'matched' THEN 1 ELSE 0 END)::int AS pincode_matched_facilities,
        SUM(CASE WHEN district_match_status = 'matched' THEN 1 ELSE 0 END)::int AS nfhs_matched_facilities
      FROM ${ENRICHED_TABLE}
      WHERE analysis_district IS NOT NULL AND ($1 = 'all' OR analysis_state = $1)
      GROUP BY analysis_state, analysis_district
      ORDER BY analysis_state, analysis_district
      LIMIT $2
    `,
    [query.state, query.limit],
  );
  return result.ok ? { ok: true, rows: result.rows } : { ok: false, rows: [] };
}
