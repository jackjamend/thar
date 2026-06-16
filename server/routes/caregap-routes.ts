import { promises as fs } from 'node:fs';
import path from 'node:path';
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

type CsvRow = Record<string, string>;

const QueueQuery = z.object({
  careNeed: z.string().optional().default('maternal_emergency'),
  state: z.string().optional().default('all'),
  evidence: z.string().optional().default('all'),
  mode: z.enum(['decision', 'missing_info']).optional().default('decision'),
  limit: z.coerce.number().int().min(1).max(200).optional().default(60),
});

const ClaimsQuery = z.object({
  careNeed: z.string().optional().default('maternal_emergency'),
  state: z.string().min(1),
  district: z.string().min(1),
});

const ActionsQuery = z.object({
  careNeed: z.string().optional().default('maternal_emergency'),
});

const DistrictActionsBody = z.object({
  careNeed: z.string().min(1),
  districtId: z.string().min(1),
  districtName: z.string().min(1),
  state: z.string().min(1),
  shortlisted: z.boolean(),
  dismissed: z.boolean(),
  verificationRequested: z.boolean(),
});

const PlannerNoteBody = z.object({
  careNeed: z.string().min(1),
  districtId: z.string().min(1),
  districtName: z.string().min(1),
  state: z.string().min(1),
  noteText: z.string().trim().max(4000),
});

const FacilityVerificationBody = z.object({
  careNeed: z.string().min(1),
  facilityId: z.string().min(1),
  facilityName: z.string().optional().default(''),
  capability: z.string().min(1),
  state: z.string().optional().default(''),
  districtOrCity: z.string().optional().default(''),
  requested: z.boolean(),
  reason: z.string().trim().max(2000).optional().default(''),
});

const ScoreOverrideBody = z.object({
  careNeed: z.string().min(1),
  districtId: z.string().min(1),
  districtName: z.string().min(1),
  state: z.string().min(1),
  overrideScore: z.number().min(0).max(100).nullable(),
  overrideReason: z.string().trim().max(2000).optional().default(''),
});

const CARE_NEED_CAPABILITIES: Record<string, Set<string>> = {
  maternal_emergency: new Set(['c_section', 'obgyn', 'nicu', 'blood_bank', 'ambulance', 'emergency_24x7']),
  critical_care: new Set(['icu', 'ventilator', 'emergency_24x7', 'ambulance']),
  dialysis_access: new Set(['dialysis', 'icu', 'emergency_24x7']),
};

const DATA_DIR = path.join(process.cwd(), 'data');
const GAPS_CSV = path.join(DATA_DIR, 'caregap_district_gaps.csv');
const CLAIMS_CSV = path.join(DATA_DIR, 'caregap_facility_claims.csv');
const HEALTH_ENRICHED_TABLE = 'public.health_access_facility_enriched';

const SETUP_SQL = [
  'CREATE SCHEMA IF NOT EXISTS app',
  `
    CREATE TABLE IF NOT EXISTS app.caregap_review_decisions (
      care_need TEXT NOT NULL,
      district_id TEXT NOT NULL,
      district_name TEXT NOT NULL,
      state TEXT NOT NULL,
      shortlisted BOOLEAN NOT NULL DEFAULT false,
      dismissed BOOLEAN NOT NULL DEFAULT false,
      verification_requested BOOLEAN NOT NULL DEFAULT false,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      PRIMARY KEY (care_need, state, district_name)
    )
  `,
  `
    CREATE TABLE IF NOT EXISTS app.caregap_planner_notes (
      id BIGSERIAL PRIMARY KEY,
      care_need TEXT NOT NULL,
      district_id TEXT NOT NULL,
      district_name TEXT NOT NULL,
      state TEXT NOT NULL,
      note_text TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
  `,
  `
    CREATE TABLE IF NOT EXISTS app.caregap_facility_verifications (
      care_need TEXT NOT NULL,
      facility_id TEXT NOT NULL,
      facility_name TEXT NOT NULL DEFAULT '',
      capability TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT '',
      district_or_city TEXT NOT NULL DEFAULT '',
      requested BOOLEAN NOT NULL DEFAULT false,
      reason TEXT NOT NULL DEFAULT '',
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      PRIMARY KEY (care_need, facility_id, capability)
    )
  `,
  `
    CREATE TABLE IF NOT EXISTS app.caregap_score_overrides (
      care_need TEXT NOT NULL,
      district_id TEXT NOT NULL,
      district_name TEXT NOT NULL,
      state TEXT NOT NULL,
      override_score NUMERIC(5, 2),
      override_reason TEXT NOT NULL DEFAULT '',
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      PRIMARY KEY (care_need, state, district_name)
    )
  `,
  'CREATE INDEX IF NOT EXISTS idx_caregap_notes_lookup ON app.caregap_planner_notes (care_need, state, district_name, created_at DESC)',
  'CREATE INDEX IF NOT EXISTS idx_caregap_facility_verifications_lookup ON app.caregap_facility_verifications (care_need, facility_id, capability)',
];

export function setupCareGapRoutes(appkit: AppKitWithLakebase) {
  const schemaReady = setupCareGapSchema(appkit);

  appkit.server.extend((app) => {
    app.get('/api/caregap/review-queue', async (req, res) => {
      const parsed = QueueQuery.safeParse(req.query);
      if (!parsed.success) {
        res.status(400).json({ error: 'Invalid review queue parameters' });
        return;
      }

      try {
        const payload = await loadReviewQueue(appkit, parsed.data);
        res.json(payload);
      } catch (err) {
        res.status(500).json({ error: messageFromError(err, 'Failed to load review queue') });
      }
    });

    app.get('/api/caregap/facility-claims', async (req, res) => {
      const parsed = ClaimsQuery.safeParse(req.query);
      if (!parsed.success) {
        res.status(400).json({ error: 'Invalid facility claim parameters' });
        return;
      }

      try {
        const payload = await loadFacilityClaims(appkit, parsed.data);
        res.json(payload);
      } catch (err) {
        res.status(500).json({ error: messageFromError(err, 'Failed to load facility claims') });
      }
    });

    app.get('/api/caregap/actions', async (req, res) => {
      const parsed = ActionsQuery.safeParse(req.query);
      if (!parsed.success) {
        res.status(400).json({ error: 'Invalid actions parameters' });
        return;
      }

      try {
        await schemaReady;
        res.json(await loadActions(appkit, parsed.data.careNeed));
      } catch (err) {
        res.status(503).json({ error: messageFromError(err, 'Failed to load planner actions') });
      }
    });

    app.put('/api/caregap/district-actions', async (req, res) => {
      const parsed = DistrictActionsBody.safeParse(req.body);
      if (!parsed.success) {
        res.status(400).json({ error: 'Invalid district action payload' });
        return;
      }

      try {
        await schemaReady;
        const result = await appkit.lakebase.query(
          `
            INSERT INTO app.caregap_review_decisions (
              care_need,
              district_id,
              district_name,
              state,
              shortlisted,
              dismissed,
              verification_requested
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (care_need, state, district_name)
            DO UPDATE SET
              district_id = EXCLUDED.district_id,
              shortlisted = EXCLUDED.shortlisted,
              dismissed = EXCLUDED.dismissed,
              verification_requested = EXCLUDED.verification_requested,
              updated_at = NOW()
            RETURNING
              care_need,
              district_id,
              district_name,
              state,
              shortlisted,
              dismissed,
              verification_requested,
              updated_at
          `,
          [
            parsed.data.careNeed,
            parsed.data.districtId,
            parsed.data.districtName,
            parsed.data.state,
            parsed.data.shortlisted,
            parsed.data.dismissed,
            parsed.data.verificationRequested,
          ],
        );
        res.json(mapDistrictAction(result.rows[0]));
      } catch (err) {
        res.status(503).json({ error: messageFromError(err, 'Failed to save district action') });
      }
    });

    app.post('/api/caregap/planner-notes', async (req, res) => {
      const parsed = PlannerNoteBody.safeParse(req.body);
      if (!parsed.success) {
        res.status(400).json({ error: 'Invalid note payload' });
        return;
      }

      try {
        await schemaReady;
        const result = await appkit.lakebase.query(
          `
            INSERT INTO app.caregap_planner_notes (
              care_need,
              district_id,
              district_name,
              state,
              note_text
            )
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, care_need, district_id, district_name, state, note_text, created_at
          `,
          [
            parsed.data.careNeed,
            parsed.data.districtId,
            parsed.data.districtName,
            parsed.data.state,
            parsed.data.noteText,
          ],
        );
        res.status(201).json(mapNote(result.rows[0]));
      } catch (err) {
        res.status(503).json({ error: messageFromError(err, 'Failed to save planner note') });
      }
    });

    app.put('/api/caregap/facility-verifications', async (req, res) => {
      const parsed = FacilityVerificationBody.safeParse(req.body);
      if (!parsed.success) {
        res.status(400).json({ error: 'Invalid facility verification payload' });
        return;
      }

      try {
        await schemaReady;
        const result = await appkit.lakebase.query(
          `
            INSERT INTO app.caregap_facility_verifications (
              care_need,
              facility_id,
              facility_name,
              capability,
              state,
              district_or_city,
              requested,
              reason
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (care_need, facility_id, capability)
            DO UPDATE SET
              facility_name = EXCLUDED.facility_name,
              state = EXCLUDED.state,
              district_or_city = EXCLUDED.district_or_city,
              requested = EXCLUDED.requested,
              reason = EXCLUDED.reason,
              updated_at = NOW()
            RETURNING
              care_need,
              facility_id,
              facility_name,
              capability,
              state,
              district_or_city,
              requested,
              reason,
              updated_at
          `,
          [
            parsed.data.careNeed,
            parsed.data.facilityId,
            parsed.data.facilityName,
            parsed.data.capability,
            parsed.data.state,
            parsed.data.districtOrCity,
            parsed.data.requested,
            parsed.data.reason,
          ],
        );
        res.json(mapFacilityVerification(result.rows[0]));
      } catch (err) {
        res.status(503).json({ error: messageFromError(err, 'Failed to save facility verification') });
      }
    });

    app.put('/api/caregap/score-overrides', async (req, res) => {
      const parsed = ScoreOverrideBody.safeParse(req.body);
      if (!parsed.success) {
        res.status(400).json({ error: 'Invalid score override payload' });
        return;
      }

      try {
        await schemaReady;
        const result = await appkit.lakebase.query(
          `
            INSERT INTO app.caregap_score_overrides (
              care_need,
              district_id,
              district_name,
              state,
              override_score,
              override_reason
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (care_need, state, district_name)
            DO UPDATE SET
              district_id = EXCLUDED.district_id,
              override_score = EXCLUDED.override_score,
              override_reason = EXCLUDED.override_reason,
              updated_at = NOW()
            RETURNING
              care_need,
              district_id,
              district_name,
              state,
              override_score,
              override_reason,
              updated_at
          `,
          [
            parsed.data.careNeed,
            parsed.data.districtId,
            parsed.data.districtName,
            parsed.data.state,
            parsed.data.overrideScore,
            parsed.data.overrideReason,
          ],
        );
        res.json(mapScoreOverride(result.rows[0]));
      } catch (err) {
        res.status(503).json({ error: messageFromError(err, 'Failed to save score override') });
      }
    });
  });
}

async function setupCareGapSchema(appkit: AppKitWithLakebase) {
  try {
    for (const sql of SETUP_SQL) {
      await appkit.lakebase.query(sql);
    }
    console.log('[caregap] Planner action tables are ready');
  } catch (err) {
    console.warn('[caregap] Planner action schema setup failed:', messageFromError(err, 'unknown error'));
  }
}

async function loadReviewQueue(appkit: AppKitWithLakebase, query: z.infer<typeof QueueQuery>) {
  try {
    const rows = await queryLakebaseGaps(appkit, query);
    const states = await queryLakebaseStates(appkit, query);
    return { careNeed: query.careNeed, mode: query.mode, source: 'lakebase', states, queue: rows.map(mapDistrictGap) };
  } catch (err) {
    console.warn('[caregap] Falling back to CSV review queue:', messageFromError(err, 'unknown error'));
    const rows = await readCsv(GAPS_CSV);
    const queue = rows
      .filter((row) => row.care_need === query.careNeed)
      .filter((row) => matchesQueueMode(numberField(row.supply_score), query.mode))
      .filter((row) => query.state === 'all' || row.state === query.state)
      .filter((row) => query.evidence === 'all' || row.uncertainty_label === query.evidence)
      .sort((a, b) => numberField(b.planning_priority_score) - numberField(a.planning_priority_score))
      .slice(0, query.limit)
      .map(mapCsvDistrictGap);

    return {
      careNeed: query.careNeed,
      mode: query.mode,
      source: 'csv-fallback',
      states: [
        ...new Set(
          rows
            .filter((row) => row.care_need === query.careNeed)
            .filter((row) => matchesQueueMode(numberField(row.supply_score), query.mode))
            .map((row) => row.state),
        ),
      ].sort(),
      queue,
    };
  }
}

async function queryLakebaseGaps(appkit: AppKitWithLakebase, query: z.infer<typeof QueueQuery>) {
  const result = await appkit.lakebase.query(
    `
      SELECT
        district_id,
        TRIM(district_name) AS district_name,
        state,
        care_need,
        planning_priority_score,
        risk_score,
        supply_score,
        evidence_score,
        data_quality_score,
        relevant_claims,
        strong_claims,
        partial_claims,
        pincode_inferred_claims,
        city_fallback_claims,
        uncertainty_label,
        explanation,
        updated_at
      FROM public.caregap_district_gaps
      WHERE
        care_need = $1
        AND ($2 = 'all' OR state = $2)
        AND ($3 = 'all' OR uncertainty_label = $3)
        AND (($5 = 'missing_info' AND supply_score::numeric = 0) OR ($5 = 'decision' AND supply_score::numeric > 0))
      ORDER BY planning_priority_score::numeric DESC
      LIMIT $4
    `,
    [query.careNeed, query.state, query.evidence, query.limit, query.mode],
  );
  return result.rows;
}

async function queryLakebaseStates(appkit: AppKitWithLakebase, query: z.infer<typeof QueueQuery>) {
  const result = await appkit.lakebase.query(
    `
      SELECT DISTINCT state
      FROM public.caregap_district_gaps
      WHERE
        care_need = $1
        AND state IS NOT NULL
        AND state <> ''
        AND (($2 = 'missing_info' AND supply_score::numeric = 0) OR ($2 = 'decision' AND supply_score::numeric > 0))
      ORDER BY state
    `,
    [query.careNeed, query.mode],
  );
  return result.rows.map((row) => stringField(row.state)).filter(Boolean);
}

async function loadFacilityClaims(appkit: AppKitWithLakebase, query: z.infer<typeof ClaimsQuery>) {
  const capabilities = [...(CARE_NEED_CAPABILITIES[query.careNeed] ?? CARE_NEED_CAPABILITIES.maternal_emergency)];
  try {
    const result = await appkit.lakebase.query(
      `
        SELECT
          claims.facility_id,
          COALESCE(NULLIF(TRIM(enriched.facility_name), ''), claims.facility_name) AS facility_name,
          COALESCE(NULLIF(TRIM(enriched.analysis_state), ''), claims.state) AS state,
          COALESCE(NULLIF(TRIM(enriched.analysis_district), ''), claims.district_or_city) AS district_or_city,
          COALESCE(NULLIF(TRIM(enriched.district_source), ''), claims.district_source) AS district_source,
          claims.capability,
          claims.claim_status,
          claims.confidence,
          claims.evidence_text,
          claims.uncertainty_reason,
          claims.extraction_method,
          claims.updated_at
        FROM public.caregap_facility_claims claims
        LEFT JOIN ${HEALTH_ENRICHED_TABLE} enriched
          ON enriched.facility_id = claims.facility_id
        WHERE
          COALESCE(NULLIF(TRIM(enriched.analysis_state), ''), claims.state) = $1
          AND LOWER(TRIM(COALESCE(NULLIF(TRIM(enriched.analysis_district), ''), claims.district_or_city))) = LOWER(TRIM($2))
          AND claims.capability = ANY($3::text[])
        ORDER BY
          CASE claims.confidence
            WHEN 'strong' THEN 3
            WHEN 'partial' THEN 2
            WHEN 'weak' THEN 1
            ELSE 0
          END DESC,
          COALESCE(NULLIF(TRIM(enriched.facility_name), ''), claims.facility_name),
          claims.capability
      `,
      [query.state, query.district, capabilities],
    );
    return result.rows.map(mapFacilityClaim);
  } catch (err) {
    console.warn('[caregap] Falling back to CSV facility claims:', messageFromError(err, 'unknown error'));
    return (await readCsv(CLAIMS_CSV))
      .filter((row) => row.state === query.state)
      .filter((row) => normalized(row.district_or_city) === normalized(query.district))
      .filter((row) => capabilities.includes(row.capability))
      .sort(
        (a, b) =>
          confidenceRank(b.confidence) - confidenceRank(a.confidence) ||
          a.facility_name.localeCompare(b.facility_name) ||
          a.capability.localeCompare(b.capability),
      )
      .map(mapCsvFacilityClaim);
  }
}

async function loadActions(appkit: AppKitWithLakebase, careNeed: string) {
  const [decisionRows, noteRows, overrideRows, verificationRows] = await Promise.all([
    appkit.lakebase.query(
      `
        SELECT
          care_need,
          district_id,
          district_name,
          state,
          shortlisted,
          dismissed,
          verification_requested,
          updated_at
        FROM app.caregap_review_decisions
        WHERE care_need = $1
      `,
      [careNeed],
    ),
    appkit.lakebase.query(
      `
        SELECT DISTINCT ON (care_need, state, district_name)
          care_need,
          district_id,
          district_name,
          state,
          note_text,
          created_at
        FROM app.caregap_planner_notes
        WHERE care_need = $1
        ORDER BY care_need, state, district_name, created_at DESC
      `,
      [careNeed],
    ),
    appkit.lakebase.query(
      `
        SELECT
          care_need,
          district_id,
          district_name,
          state,
          override_score,
          override_reason,
          updated_at
        FROM app.caregap_score_overrides
        WHERE care_need = $1
      `,
      [careNeed],
    ),
    appkit.lakebase.query(
      `
        SELECT
          care_need,
          facility_id,
          facility_name,
          capability,
          state,
          district_or_city,
          requested,
          reason,
          updated_at
        FROM app.caregap_facility_verifications
        WHERE care_need = $1
      `,
      [careNeed],
    ),
  ]);

  return {
    districtActions: decisionRows.rows.map(mapDistrictAction),
    latestNotes: noteRows.rows.map(mapLatestNote),
    scoreOverrides: overrideRows.rows.map(mapScoreOverride),
    facilityVerifications: verificationRows.rows.map(mapFacilityVerification),
  };
}

async function readCsv(filePath: string): Promise<CsvRow[]> {
  const text = await fs.readFile(filePath, 'utf8');
  const lines = text.split(/\r?\n/).filter((line) => line.length > 0);
  if (!lines.length) return [];

  const headers = parseCsvLine(lines[0]);
  return lines.slice(1).map((line) => {
    const values = parseCsvLine(line);
    return Object.fromEntries(headers.map((header, index) => [header, values[index] ?? '']));
  });
}

function parseCsvLine(line: string): string[] {
  const values: string[] = [];
  let value = '';
  let inQuotes = false;

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    const next = line[index + 1];

    if (char === '"' && inQuotes && next === '"') {
      value += '"';
      index += 1;
      continue;
    }

    if (char === '"') {
      inQuotes = !inQuotes;
      continue;
    }

    if (char === ',' && !inQuotes) {
      values.push(value);
      value = '';
      continue;
    }

    value += char;
  }

  values.push(value);
  return values;
}

function mapCsvDistrictGap(row: CsvRow) {
  return {
    district_id: row.district_id,
    district_name: row.district_name.trim(),
    state: row.state,
    care_need: row.care_need,
    planning_priority_score: numberField(row.planning_priority_score),
    risk_score: numberField(row.risk_score),
    supply_score: numberField(row.supply_score),
    evidence_score: numberField(row.evidence_score),
    data_quality_score: numberField(row.data_quality_score),
    relevant_claims: integerField(row.relevant_claims),
    strong_claims: integerField(row.strong_claims),
    partial_claims: integerField(row.partial_claims),
    pincode_inferred_claims: integerField(row.pincode_inferred_claims),
    city_fallback_claims: integerField(row.city_fallback_claims),
    uncertainty_label: row.uncertainty_label,
    explanation: row.explanation,
    updated_at: row.updated_at,
  };
}

function mapDistrictGap(row: Record<string, unknown>) {
  return {
    district_id: stringField(row.district_id),
    district_name: stringField(row.district_name).trim(),
    state: stringField(row.state),
    care_need: stringField(row.care_need),
    planning_priority_score: numericField(row.planning_priority_score),
    risk_score: numericField(row.risk_score),
    supply_score: numericField(row.supply_score),
    evidence_score: numericField(row.evidence_score),
    data_quality_score: numericField(row.data_quality_score),
    relevant_claims: integerUnknownField(row.relevant_claims),
    strong_claims: integerUnknownField(row.strong_claims),
    partial_claims: integerUnknownField(row.partial_claims),
    pincode_inferred_claims: integerUnknownField(row.pincode_inferred_claims),
    city_fallback_claims: integerUnknownField(row.city_fallback_claims),
    uncertainty_label: stringField(row.uncertainty_label),
    explanation: stringField(row.explanation),
    updated_at: stringField(row.updated_at),
  };
}

function mapCsvFacilityClaim(row: CsvRow) {
  return {
    facility_id: row.facility_id,
    facility_name: row.facility_name,
    state: row.state,
    district_or_city: row.district_or_city,
    district_source: row.district_source,
    capability: row.capability,
    claim_status: row.claim_status,
    confidence: row.confidence,
    evidence_text: row.evidence_text,
    uncertainty_reason: row.uncertainty_reason,
    extraction_method: row.extraction_method,
    updated_at: row.updated_at,
  };
}

function mapFacilityClaim(row: Record<string, unknown>) {
  return {
    facility_id: stringField(row.facility_id),
    facility_name: stringField(row.facility_name),
    state: stringField(row.state),
    district_or_city: stringField(row.district_or_city),
    district_source: stringField(row.district_source),
    capability: stringField(row.capability),
    claim_status: stringField(row.claim_status),
    confidence: stringField(row.confidence),
    evidence_text: stringField(row.evidence_text),
    uncertainty_reason: stringField(row.uncertainty_reason),
    extraction_method: stringField(row.extraction_method),
    updated_at: stringField(row.updated_at),
  };
}

function mapDistrictAction(row: Record<string, unknown>) {
  return {
    careNeed: stringField(row.care_need),
    districtId: stringField(row.district_id),
    districtName: stringField(row.district_name),
    state: stringField(row.state),
    shortlisted: booleanField(row.shortlisted),
    dismissed: booleanField(row.dismissed),
    verificationRequested: booleanField(row.verification_requested),
    updatedAt: stringField(row.updated_at),
  };
}

function mapNote(row: Record<string, unknown>) {
  return {
    id: row.id,
    careNeed: stringField(row.care_need),
    districtId: stringField(row.district_id),
    districtName: stringField(row.district_name),
    state: stringField(row.state),
    noteText: stringField(row.note_text),
    createdAt: stringField(row.created_at),
  };
}

function mapLatestNote(row: Record<string, unknown>) {
  return {
    careNeed: stringField(row.care_need),
    districtId: stringField(row.district_id),
    districtName: stringField(row.district_name),
    state: stringField(row.state),
    noteLatest: stringField(row.note_text),
    createdAt: stringField(row.created_at),
  };
}

function mapScoreOverride(row: Record<string, unknown>) {
  const overrideScore = row.override_score === null || row.override_score === undefined ? null : numericField(row.override_score);
  return {
    careNeed: stringField(row.care_need),
    districtId: stringField(row.district_id),
    districtName: stringField(row.district_name),
    state: stringField(row.state),
    overrideScore,
    overrideReason: stringField(row.override_reason),
    updatedAt: stringField(row.updated_at),
  };
}

function mapFacilityVerification(row: Record<string, unknown>) {
  return {
    careNeed: stringField(row.care_need),
    facilityId: stringField(row.facility_id),
    facilityName: stringField(row.facility_name),
    capability: stringField(row.capability),
    state: stringField(row.state),
    districtOrCity: stringField(row.district_or_city),
    requested: booleanField(row.requested),
    reason: stringField(row.reason),
    updatedAt: stringField(row.updated_at),
  };
}

function numberField(value: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function numericField(value: unknown) {
  if (typeof value === 'number') return value;
  if (typeof value === 'string') return numberField(value);
  if (value && typeof value === 'object' && 'toString' in value) {
    const text = (value as { toString(): string }).toString();
    return text === '[object Object]' ? 0 : numberField(text);
  }
  return 0;
}

function integerField(value: string) {
  return Math.trunc(numberField(value));
}

function integerUnknownField(value: unknown) {
  return Math.trunc(numericField(value));
}

function confidenceRank(value: string) {
  if (value === 'strong') return 3;
  if (value === 'partial') return 2;
  if (value === 'weak') return 1;
  return 0;
}

function matchesQueueMode(supplyScore: number, mode: z.infer<typeof QueueQuery>['mode']) {
  return mode === 'missing_info' ? supplyScore === 0 : supplyScore > 0;
}

function normalized(value: string) {
  return value.trim().toLowerCase();
}

function stringField(value: unknown, fallback = '') {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (value instanceof Date) return value.toISOString();
  return fallback;
}

function booleanField(value: unknown) {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'string') return value === 'true';
  return Boolean(value);
}

function messageFromError(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback;
}
