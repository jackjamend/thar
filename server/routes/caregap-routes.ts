import { promises as fs } from 'node:fs';
import path from 'node:path';
import { Application } from 'express';
import { z } from 'zod';

interface AppKitServerOnly {
  server: {
    extend(fn: (app: Application) => void): void;
  };
}

type CsvRow = Record<string, string>;

const QueueQuery = z.object({
  careNeed: z.string().optional().default('maternal_emergency'),
  state: z.string().optional().default('all'),
  evidence: z.string().optional().default('all'),
  limit: z.coerce.number().int().min(1).max(200).optional().default(60),
});

const ClaimsQuery = z.object({
  careNeed: z.string().optional().default('maternal_emergency'),
  state: z.string().min(1),
  district: z.string().min(1),
});

const CARE_NEED_CAPABILITIES: Record<string, Set<string>> = {
  maternal_emergency: new Set(['c_section', 'obgyn', 'nicu', 'blood_bank', 'ambulance', 'emergency_24x7']),
  critical_care: new Set(['icu', 'ventilator', 'emergency_24x7', 'ambulance']),
  dialysis_access: new Set(['dialysis', 'icu', 'emergency_24x7']),
};

const DATA_DIR = path.join(process.cwd(), 'data');
const GAPS_CSV = path.join(DATA_DIR, 'caregap_district_gaps.csv');
const CLAIMS_CSV = path.join(DATA_DIR, 'caregap_facility_claims.csv');

export function setupCareGapRoutes(appkit: AppKitServerOnly) {
  appkit.server.extend((app) => {
    app.get('/api/caregap/review-queue', async (req, res) => {
      const parsed = QueueQuery.safeParse(req.query);
      if (!parsed.success) {
        res.status(400).json({ error: 'Invalid review queue parameters' });
        return;
      }

      try {
        const { careNeed, state, evidence, limit } = parsed.data;
        const rows = await readCsv(GAPS_CSV);
        const queue = rows
          .filter((row) => row.care_need === careNeed)
          .filter((row) => state === 'all' || row.state === state)
          .filter((row) => evidence === 'all' || row.uncertainty_label === evidence)
          .sort((a, b) => numberField(b.planning_priority_score) - numberField(a.planning_priority_score))
          .slice(0, limit)
          .map((row) => ({
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
          }));

        res.json({
          careNeed,
          states: [...new Set(rows.filter((row) => row.care_need === careNeed).map((row) => row.state))].sort(),
          queue,
        });
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
        const { careNeed, state, district } = parsed.data;
        const capabilities = CARE_NEED_CAPABILITIES[careNeed] ?? CARE_NEED_CAPABILITIES.maternal_emergency;
        const claims = (await readCsv(CLAIMS_CSV))
          .filter((row) => row.state === state)
          .filter((row) => normalized(row.district_or_city) === normalized(district))
          .filter((row) => capabilities.has(row.capability))
          .sort(
            (a, b) =>
              confidenceRank(b.confidence) - confidenceRank(a.confidence) ||
              a.facility_name.localeCompare(b.facility_name) ||
              a.capability.localeCompare(b.capability),
          )
          .map((row) => ({
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
          }));

        res.json(claims);
      } catch (err) {
        res.status(500).json({ error: messageFromError(err, 'Failed to load facility claims') });
      }
    });
  });
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

function numberField(value: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function integerField(value: string) {
  return Math.trunc(numberField(value));
}

function confidenceRank(value: string) {
  if (value === 'strong') return 3;
  if (value === 'partial') return 2;
  if (value === 'weak') return 1;
  return 0;
}

function normalized(value: string) {
  return value.trim().toLowerCase();
}

function messageFromError(err: unknown, fallback: string) {
  return err instanceof Error ? err.message : fallback;
}
