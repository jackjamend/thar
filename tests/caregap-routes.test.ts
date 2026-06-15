import { beforeEach, describe, expect, test } from 'vitest';
import { setupCareGapRoutes } from '../server/routes/caregap-routes';

type StoredDecision = {
  care_need: string;
  district_id: string;
  district_name: string;
  state: string;
  shortlisted: boolean;
  dismissed: boolean;
  verification_requested: boolean;
  updated_at: string;
};

type StoredNote = {
  care_need: string;
  district_id: string;
  district_name: string;
  state: string;
  note_text: string;
  created_at: string;
};

type StoredVerification = {
  care_need: string;
  facility_id: string;
  facility_name: string;
  capability: string;
  state: string;
  district_or_city: string;
  requested: boolean;
  reason: string;
  updated_at: string;
};

type Handler = (req: { body?: unknown; query?: Record<string, string> }, res: MockResponse) => unknown;

class MockResponse {
  statusCode = 200;
  payload: unknown;

  status(code: number) {
    this.statusCode = code;
    return this;
  }

  json(payload: unknown) {
    this.payload = payload;
    return this;
  }
}

const decisions: StoredDecision[] = [];
const notes: StoredNote[] = [];
const verifications: StoredVerification[] = [];
const routes = new Map<string, Handler>();

beforeEach(() => {
  decisions.length = 0;
  notes.length = 0;
  verifications.length = 0;
  routes.clear();

  setupCareGapRoutes({
    lakebase: { query: mockLakebaseQuery },
    server: {
      extend(fn) {
        fn({
          get: (path: string, handler: Handler) => routes.set(`GET ${path}`, handler),
          post: (path: string, handler: Handler) => routes.set(`POST ${path}`, handler),
          put: (path: string, handler: Handler) => routes.set(`PUT ${path}`, handler),
        } as never);
      },
    },
  });
});

describe('CareGap planner persistence routes', () => {
  test('saves district actions, notes, and facility verification requests', async () => {
    const actionResponse = await callRoute('PUT', '/api/caregap/district-actions', {
      careNeed: 'maternal_emergency',
      districtId: 'district:pakur',
      districtName: 'Pakur',
      state: 'Jharkhand',
      shortlisted: true,
      dismissed: false,
      verificationRequested: true,
    });
    expect(actionResponse.statusCode).toBe(200);

    const noteResponse = await callRoute('POST', '/api/caregap/planner-notes', {
      careNeed: 'maternal_emergency',
      districtId: 'district:pakur',
      districtName: 'Pakur',
      state: 'Jharkhand',
      noteText: 'Prioritize field team follow-up.',
    });
    expect(noteResponse.statusCode).toBe(201);

    const verificationResponse = await callRoute('PUT', '/api/caregap/facility-verifications', {
      careNeed: 'maternal_emergency',
      facilityId: 'facility:1',
      facilityName: 'Demo Clinic',
      capability: 'obgyn',
      state: 'Jharkhand',
      districtOrCity: 'Pakur',
      requested: true,
      reason: 'Evidence is partial.',
    });
    expect(verificationResponse.statusCode).toBe(200);

    const actionsResponse = await callRoute('GET', '/api/caregap/actions', undefined, {
      careNeed: 'maternal_emergency',
    });
    expect(actionsResponse.statusCode).toBe(200);
    const actions = actionsResponse.payload as {
      districtActions: unknown[];
      latestNotes: Array<{ noteLatest: string }>;
      facilityVerifications: Array<{ requested: boolean; reason: string }>;
    };

    expect(actions.districtActions).toHaveLength(1);
    expect(actions.latestNotes[0]?.noteLatest).toBe('Prioritize field team follow-up.');
    expect(actions.facilityVerifications[0]).toMatchObject({ requested: true, reason: 'Evidence is partial.' });
  });
});

async function callRoute(method: string, path: string, body?: unknown, query: Record<string, string> = {}) {
  const handler = routes.get(`${method} ${path}`);
  if (!handler) throw new Error(`Missing route ${method} ${path}`);

  const response = new MockResponse();
  await handler({ body, query }, response);
  return response;
}

async function mockLakebaseQuery(text: string, params: unknown[] = []) {
  if (text.includes('INSERT INTO app.caregap_review_decisions')) {
    const row: StoredDecision = {
      care_need: String(params[0]),
      district_id: String(params[1]),
      district_name: String(params[2]),
      state: String(params[3]),
      shortlisted: Boolean(params[4]),
      dismissed: Boolean(params[5]),
      verification_requested: Boolean(params[6]),
      updated_at: new Date().toISOString(),
    };
    decisions.splice(0, decisions.length, row);
    return { rows: [row] };
  }

  if (text.includes('INSERT INTO app.caregap_planner_notes')) {
    const row: StoredNote = {
      care_need: String(params[0]),
      district_id: String(params[1]),
      district_name: String(params[2]),
      state: String(params[3]),
      note_text: String(params[4]),
      created_at: new Date().toISOString(),
    };
    notes.push(row);
    return { rows: [{ id: 1, ...row }] };
  }

  if (text.includes('INSERT INTO app.caregap_facility_verifications')) {
    const row: StoredVerification = {
      care_need: String(params[0]),
      facility_id: String(params[1]),
      facility_name: String(params[2]),
      capability: String(params[3]),
      state: String(params[4]),
      district_or_city: String(params[5]),
      requested: Boolean(params[6]),
      reason: String(params[7]),
      updated_at: new Date().toISOString(),
    };
    verifications.splice(0, verifications.length, row);
    return { rows: [row] };
  }

  if (text.includes('FROM app.caregap_review_decisions')) return { rows: decisions };
  if (text.includes('FROM app.caregap_planner_notes')) return { rows: notes.slice(-1) };
  if (text.includes('FROM app.caregap_score_overrides')) return { rows: [] };
  if (text.includes('FROM app.caregap_facility_verifications')) return { rows: verifications };

  return { rows: [] };
}
