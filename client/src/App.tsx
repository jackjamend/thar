import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  AlertDescription,
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
  Textarea,
} from '@databricks/appkit-ui/react';
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  FileText,
  Flag,
  MapPin,
  RefreshCw,
  Save,
  ShieldQuestion,
  Star,
} from 'lucide-react';

type CareNeed = 'maternal_emergency' | 'critical_care' | 'dialysis_access';
type QueueMode = 'decision' | 'missing_info';
type SourceLabel = 'lakebase' | 'csv-fallback';
type EvidenceLabel = 'strong' | 'partial' | 'weak' | 'missing' | 'conflicting';

type ReviewQueueResponse = {
  careNeed: string;
  mode: QueueMode;
  source: SourceLabel;
  states: string[];
  queue: DistrictGap[];
};

type DistrictGap = {
  district_id: string;
  district_name: string;
  state: string;
  care_need: string;
  planning_priority_score: number;
  risk_score: number;
  supply_score: number;
  evidence_score: number;
  data_quality_score: number;
  relevant_claims: number;
  strong_claims: number;
  partial_claims: number;
  pincode_inferred_claims: number;
  city_fallback_claims: number;
  uncertainty_label: EvidenceLabel;
  explanation: string;
  updated_at: string;
};

type FacilityClaim = {
  facility_id: string;
  facility_name: string;
  state: string;
  district_or_city: string;
  district_source: string;
  capability: string;
  claim_status: string;
  confidence: EvidenceLabel;
  evidence_text: string;
  uncertainty_reason: string;
  extraction_method: string;
  updated_at: string;
};

type PlannerActions = {
  shortlisted: boolean;
  verificationRequested: boolean;
  dismissed: boolean;
  noteLatest: string;
  overrideScore: number | null;
  overrideReason: string;
};

type FacilityVerification = {
  requested: boolean;
  reason: string;
};

type ActionsResponse = {
  districtActions: Array<{
    districtName: string;
    state: string;
    shortlisted: boolean;
    dismissed: boolean;
    verificationRequested: boolean;
  }>;
  latestNotes: Array<{
    districtName: string;
    state: string;
    noteLatest: string;
  }>;
  scoreOverrides: Array<{
    districtName: string;
    state: string;
    overrideScore: number | null;
    overrideReason: string;
  }>;
  facilityVerifications: Array<{
    facilityId: string;
    capability: string;
    requested: boolean;
    reason: string;
  }>;
};

const CARE_NEEDS: { value: CareNeed; label: string }[] = [
  { value: 'maternal_emergency', label: 'Maternal Emergency Care' },
  { value: 'critical_care', label: 'Critical Care' },
  { value: 'dialysis_access', label: 'Dialysis Access' },
];

const EVIDENCE_FILTERS = [
  { value: 'all', label: 'All evidence' },
  { value: 'missing', label: 'Missing' },
  { value: 'weak', label: 'Weak' },
  { value: 'partial', label: 'Partial' },
  { value: 'strong', label: 'Strong' },
];

const QUEUE_MODES: { value: QueueMode; label: string }[] = [
  { value: 'decision', label: 'Decision' },
  { value: 'missing_info', label: 'Missing info' },
];

const CAPABILITY_LABELS: Record<string, string> = {
  c_section: 'C-section',
  obgyn: 'OBGYN',
  nicu: 'NICU',
  blood_bank: 'Blood bank',
  ambulance: 'Ambulance',
  emergency_24x7: '24x7 emergency',
  icu: 'ICU',
  ventilator: 'Ventilator',
  dialysis: 'Dialysis',
};

const EMPTY_ACTIONS: PlannerActions = {
  shortlisted: false,
  verificationRequested: false,
  dismissed: false,
  noteLatest: '',
  overrideScore: null,
  overrideReason: '',
};

function formatScore(value: number) {
  return Number(value ?? 0).toFixed(1);
}

function formatNumber(value: number) {
  return Number(value ?? 0).toLocaleString();
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const payload = (await response.json()) as T & { error?: string };
  if (!response.ok) throw new Error(payload.error ?? response.statusText);
  return payload;
}

function evidenceVariant(label: EvidenceLabel): 'default' | 'secondary' | 'outline' | 'destructive' {
  if (label === 'strong') return 'default';
  if (label === 'missing' || label === 'conflicting') return 'destructive';
  if (label === 'partial') return 'secondary';
  return 'outline';
}

function priorityLabel(score: number) {
  if (score >= 70) return 'High';
  if (score >= 45) return 'Medium';
  return 'Watch';
}

function scoreWidth(value: number) {
  return `${Math.max(3, Math.min(100, value))}%`;
}

function districtKeyFromParts(state: string, districtName: string) {
  return `${state.trim()}:${districtName.trim()}`;
}

function districtKey(district: DistrictGap) {
  return districtKeyFromParts(district.state, district.district_name);
}

function facilityKeyFromParts(facilityId: string, capability: string) {
  return `${facilityId}:${capability}`;
}

function facilityKey(claim: FacilityClaim) {
  return facilityKeyFromParts(claim.facility_id, claim.capability);
}

function mergeActions(base: PlannerActions, patch: Partial<PlannerActions>): PlannerActions {
  return { ...base, ...patch };
}

export default function App() {
  const [careNeed, setCareNeed] = useState<CareNeed>('maternal_emergency');
  const [queueMode, setQueueMode] = useState<QueueMode>('decision');
  const [stateFilter, setStateFilter] = useState('all');
  const [evidenceFilter, setEvidenceFilter] = useState('all');
  const [queueResponse, setQueueResponse] = useState<ReviewQueueResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [claims, setClaims] = useState<FacilityClaim[]>([]);
  const [actions, setActions] = useState<Record<string, PlannerActions>>({});
  const [facilityVerifications, setFacilityVerifications] = useState<Record<string, FacilityVerification>>({});
  const [queueLoading, setQueueLoading] = useState(true);
  const [claimsLoading, setClaimsLoading] = useState(false);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const queue = useMemo(() => queueResponse?.queue ?? [], [queueResponse]);
  const selectedDistrict = useMemo(
    () => queue.find((district) => district.district_id === selectedId) ?? queue[0] ?? null,
    [queue, selectedId],
  );
  const selectedActions = selectedDistrict ? actions[districtKey(selectedDistrict)] ?? EMPTY_ACTIONS : null;

  const queueStats = useMemo(
    () =>
      queueMode === 'missing_info'
        ? {
            high: queue.length,
            missing: queue.filter((district) => {
              const districtActions = actions[districtKey(district)] ?? EMPTY_ACTIONS;
              return districtActions.verificationRequested;
            }).length,
            reviewable: queue.filter((district) => district.relevant_claims === 0).length,
          }
        : {
            high: queue.filter((district) => district.planning_priority_score >= 70).length,
            missing: queue.filter((district) => district.uncertainty_label === 'missing').length,
            reviewable: queue.filter((district) => district.relevant_claims > 0).length,
          },
    [actions, queue, queueMode],
  );

  const refreshQueue = useCallback(async () => {
    setQueueLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        careNeed,
        state: stateFilter,
        evidence: evidenceFilter,
        mode: queueMode,
        limit: '80',
      });
      const payload = await fetchJson<ReviewQueueResponse>(`/api/caregap/review-queue?${params.toString()}`);
      setQueueResponse(payload);
      setSelectedId((current) =>
        current && payload.queue.some((district) => district.district_id === current)
          ? current
          : payload.queue[0]?.district_id ?? null,
      );
    } catch (err) {
      setQueueResponse(null);
      setSelectedId(null);
      setError(err instanceof Error ? err.message : 'Failed to load review queue');
    } finally {
      setQueueLoading(false);
    }
  }, [careNeed, evidenceFilter, queueMode, stateFilter]);

  const refreshActions = useCallback(async () => {
    try {
      const payload = await fetchJson<ActionsResponse>(`/api/caregap/actions?careNeed=${encodeURIComponent(careNeed)}`);
      const nextActions: Record<string, PlannerActions> = {};
      const nextFacilityVerifications: Record<string, FacilityVerification> = {};

      for (const action of payload.districtActions) {
        const key = districtKeyFromParts(action.state, action.districtName);
        nextActions[key] = mergeActions(nextActions[key] ?? EMPTY_ACTIONS, {
          shortlisted: action.shortlisted,
          verificationRequested: action.verificationRequested,
          dismissed: action.dismissed,
        });
      }

      for (const note of payload.latestNotes) {
        const key = districtKeyFromParts(note.state, note.districtName);
        nextActions[key] = mergeActions(nextActions[key] ?? EMPTY_ACTIONS, { noteLatest: note.noteLatest });
      }

      for (const override of payload.scoreOverrides) {
        const key = districtKeyFromParts(override.state, override.districtName);
        nextActions[key] = mergeActions(nextActions[key] ?? EMPTY_ACTIONS, {
          overrideScore: override.overrideScore,
          overrideReason: override.overrideReason,
        });
      }

      for (const verification of payload.facilityVerifications) {
        nextFacilityVerifications[facilityKeyFromParts(verification.facilityId, verification.capability)] = {
          requested: verification.requested,
          reason: verification.reason,
        };
      }

      setActions(nextActions);
      setFacilityVerifications(nextFacilityVerifications);
    } catch (err) {
      setActions({});
      setFacilityVerifications({});
      setError(err instanceof Error ? err.message : 'Planner actions are unavailable');
    }
  }, [careNeed]);

  useEffect(() => {
    void refreshQueue();
    void refreshActions();
  }, [refreshActions, refreshQueue]);

  useEffect(() => {
    if (stateFilter !== 'all' && queueResponse && !queueResponse.states.includes(stateFilter)) {
      setStateFilter('all');
    }
  }, [queueResponse, stateFilter]);

  useEffect(() => {
    if (!selectedDistrict) {
      setClaims([]);
      return;
    }

    const controller = new AbortController();
    setClaimsLoading(true);
    const params = new URLSearchParams({
      careNeed,
      state: selectedDistrict.state,
      district: selectedDistrict.district_name,
    });
    fetch(`/api/caregap/facility-claims?${params.toString()}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) {
          return response
            .json()
            .then((body: { error?: string }) => Promise.reject(new Error(body.error ?? response.statusText)));
        }
        return response.json() as Promise<FacilityClaim[]>;
      })
      .then(setClaims)
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setClaims([]);
      })
      .finally(() => setClaimsLoading(false));

    return () => controller.abort();
  }, [careNeed, selectedDistrict]);

  const setDistrictActions = (district: DistrictGap, patch: Partial<PlannerActions>) => {
    setActions((current) => {
      const key = districtKey(district);
      return { ...current, [key]: mergeActions(current[key] ?? EMPTY_ACTIONS, patch) };
    });
  };

  const saveDistrictAction = async (district: DistrictGap, patch: Partial<PlannerActions>) => {
    const key = districtKey(district);
    const previous = actions[key] ?? EMPTY_ACTIONS;
    const next = mergeActions(previous, patch);
    setDistrictActions(district, patch);
    setSavingKey(key);
    setError(null);

    try {
      await fetchJson('/api/caregap/district-actions', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          careNeed,
          districtId: district.district_id,
          districtName: district.district_name,
          state: district.state,
          shortlisted: next.shortlisted,
          dismissed: next.dismissed,
          verificationRequested: next.verificationRequested,
        }),
      });
    } catch (err) {
      setActions((current) => ({ ...current, [key]: previous }));
      setError(err instanceof Error ? err.message : 'Failed to save planner action');
    } finally {
      setSavingKey(null);
    }
  };

  const savePlannerNote = async (district: DistrictGap) => {
    const key = districtKey(district);
    const noteText = (actions[key] ?? EMPTY_ACTIONS).noteLatest.trim();
    if (!noteText) return;

    setSavingKey(`${key}:note`);
    setError(null);
    try {
      await fetchJson('/api/caregap/planner-notes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          careNeed,
          districtId: district.district_id,
          districtName: district.district_name,
          state: district.state,
          noteText,
        }),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save planner note');
    } finally {
      setSavingKey(null);
    }
  };

  const saveScoreOverride = async (district: DistrictGap) => {
    const key = districtKey(district);
    const action = actions[key] ?? EMPTY_ACTIONS;
    setSavingKey(`${key}:override`);
    setError(null);

    try {
      await fetchJson('/api/caregap/score-overrides', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          careNeed,
          districtId: district.district_id,
          districtName: district.district_name,
          state: district.state,
          overrideScore: action.overrideScore,
          overrideReason: action.overrideReason,
        }),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save score override');
    } finally {
      setSavingKey(null);
    }
  };

  const saveFacilityVerification = async (claim: FacilityClaim, patch: Partial<FacilityVerification>) => {
    const key = facilityKey(claim);
    const previous = facilityVerifications[key] ?? { requested: false, reason: '' };
    const next = { ...previous, ...patch };
    setFacilityVerifications((current) => ({ ...current, [key]: next }));
    setSavingKey(key);
    setError(null);

    try {
      await fetchJson('/api/caregap/facility-verifications', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          careNeed,
          facilityId: claim.facility_id,
          facilityName: claim.facility_name,
          capability: claim.capability,
          state: claim.state,
          districtOrCity: claim.district_or_city,
          requested: next.requested,
          reason: next.reason,
        }),
      });
    } catch (err) {
      setFacilityVerifications((current) => ({ ...current, [key]: previous }));
      setError(err instanceof Error ? err.message : 'Failed to save facility verification');
    } finally {
      setSavingKey(null);
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-4 md:flex-row md:items-center md:justify-between md:px-6">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">CareGap</Badge>
              <Badge variant="outline">Review queue</Badge>
              {queueResponse?.source && <Badge variant="outline">{queueResponse.source}</Badge>}
            </div>
            <h1 className="mt-2 text-2xl font-semibold tracking-normal text-foreground md:text-3xl">
              Medical Desert Planner
            </h1>
          </div>
          <Button
            variant="outline"
            onClick={() => {
              void refreshQueue();
              void refreshActions();
            }}
            disabled={queueLoading}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-4 px-4 py-5 md:px-6">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <section className="grid gap-3 md:grid-cols-[260px_220px_200px_260px_minmax(0,1fr)]">
          <Select value={careNeed} onValueChange={(value) => setCareNeed(value as CareNeed)}>
            <SelectTrigger aria-label="Care need">
              <SelectValue placeholder="Care need" />
            </SelectTrigger>
            <SelectContent>
              {CARE_NEEDS.map((need) => (
                <SelectItem key={need.value} value={need.value}>
                  {need.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={stateFilter} onValueChange={setStateFilter}>
            <SelectTrigger aria-label="State">
              <SelectValue placeholder="State" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All states</SelectItem>
              {(queueResponse?.states ?? []).map((state) => (
                <SelectItem key={state} value={state}>
                  {state}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={evidenceFilter} onValueChange={setEvidenceFilter}>
            <SelectTrigger aria-label="Evidence">
              <SelectValue placeholder="Evidence" />
            </SelectTrigger>
            <SelectContent>
              {EVIDENCE_FILTERS.map((filter) => (
                <SelectItem key={filter.value} value={filter.value}>
                  {filter.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="grid grid-cols-2 gap-2">
            {QUEUE_MODES.map((mode) => (
              <Button
                key={mode.value}
                variant={queueMode === mode.value ? 'default' : 'outline'}
                onClick={() => setQueueMode(mode.value)}
                type="button"
              >
                {mode.value === 'decision' ? (
                  <ClipboardCheck className="mr-2 h-4 w-4" />
                ) : (
                  <ShieldQuestion className="mr-2 h-4 w-4" />
                )}
                {mode.label}
              </Button>
            ))}
          </div>
          <div className="grid grid-cols-3 gap-2">
            {queueMode === 'missing_info' ? (
              <>
                <QueueStat label="Need info" value={queueStats.high} />
                <QueueStat label="Requested" value={queueStats.missing} />
                <QueueStat label="No claims" value={queueStats.reviewable} />
              </>
            ) : (
              <>
                <QueueStat label="High" value={queueStats.high} />
                <QueueStat label="Missing" value={queueStats.missing} />
                <QueueStat label="Reviewable" value={queueStats.reviewable} />
              </>
            )}
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-[410px_minmax(0,1fr)]">
          <div className="space-y-3" aria-label="District review queue">
            {queueLoading ? (
              Array.from({ length: 8 }, (_, index) => <Skeleton key={index} className="h-28 w-full" />)
            ) : queue.length === 0 ? (
              <Card>
                <CardContent className="py-8">
                  <Empty>
                    <EmptyHeader>
                      <EmptyTitle>No districts match</EmptyTitle>
                      <EmptyDescription>Try a broader state or evidence filter.</EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                </CardContent>
              </Card>
            ) : (
              queue.map((district) => {
                const districtActions = actions[districtKey(district)] ?? EMPTY_ACTIONS;
                const displayScore = districtActions.overrideScore ?? district.planning_priority_score;
                return (
                  <button
                    key={district.district_id}
                    className={`w-full rounded-md border bg-card p-3 text-left transition hover:border-primary ${
                      selectedDistrict?.district_id === district.district_id ? 'border-primary ring-1 ring-primary' : ''
                    } ${districtActions.dismissed ? 'opacity-55' : ''}`}
                    onClick={() => setSelectedId(district.district_id)}
                    type="button"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate font-medium text-foreground">{district.district_name}</div>
                        <div className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
                          <MapPin className="h-3.5 w-3.5" />
                          {district.state}
                        </div>
                      </div>
                      {district.supply_score === 0 ? (
                        <Badge variant="destructive">Info needed</Badge>
                      ) : (
                        <Badge variant={displayScore >= 70 ? 'destructive' : 'secondary'}>{priorityLabel(displayScore)}</Badge>
                      )}
                    </div>
                    <div className="mt-3 grid grid-cols-[70px_minmax(0,1fr)_54px] items-center gap-2 text-xs">
                      <span className="text-muted-foreground">Priority</span>
                      <ScoreBar value={displayScore} />
                      <span className="text-right font-medium">{formatScore(displayScore)}</span>
                      <span className="text-muted-foreground">Supply</span>
                      <ScoreBar value={district.supply_score} muted />
                      <span className="text-right font-medium">{formatScore(district.supply_score)}</span>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <Badge variant={evidenceVariant(district.uncertainty_label)}>{district.uncertainty_label}</Badge>
                      <Badge variant="outline">{formatNumber(district.relevant_claims)} claims</Badge>
                      {districtActions.shortlisted && <Badge variant="secondary">shortlisted</Badge>}
                      {districtActions.verificationRequested && (
                        <Badge variant="outline">{district.supply_score === 0 ? 'info requested' : 'verify'}</Badge>
                      )}
                      {districtActions.overrideScore !== null && <Badge variant="secondary">override</Badge>}
                    </div>
                  </button>
                );
              })
            )}
          </div>

          <DistrictDetail
            actions={selectedActions}
            claims={claims}
            claimsLoading={claimsLoading}
            district={selectedDistrict}
            facilityVerifications={facilityVerifications}
            queueMode={queueMode}
            onSaveDistrictAction={saveDistrictAction}
            onSaveFacilityVerification={saveFacilityVerification}
            onSaveNote={savePlannerNote}
            onSaveOverride={saveScoreOverride}
            onUpdateAction={setDistrictActions}
            onUpdateFacilityVerification={(claim, patch) => {
              const key = facilityKey(claim);
              setFacilityVerifications((current) => ({
                ...current,
                [key]: { ...(current[key] ?? { requested: false, reason: '' }), ...patch },
              }));
            }}
            savingKey={savingKey}
          />
        </section>
      </main>
    </div>
  );
}

function QueueStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border bg-card px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold leading-tight">{formatNumber(value)}</div>
    </div>
  );
}

function ScoreBar({ value, muted = false }: { value: number; muted?: boolean }) {
  return (
    <div className="h-2 overflow-hidden rounded-full bg-muted">
      <div
        className={`h-full rounded-full ${muted ? 'bg-muted-foreground' : 'bg-primary'}`}
        style={{ width: scoreWidth(value) }}
      />
    </div>
  );
}

function DistrictDetail({
  actions,
  claims,
  claimsLoading,
  district,
  facilityVerifications,
  queueMode,
  onSaveDistrictAction,
  onSaveFacilityVerification,
  onSaveNote,
  onSaveOverride,
  onUpdateAction,
  onUpdateFacilityVerification,
  savingKey,
}: {
  actions: PlannerActions | null;
  claims: FacilityClaim[];
  claimsLoading: boolean;
  district: DistrictGap | null;
  facilityVerifications: Record<string, FacilityVerification>;
  queueMode: QueueMode;
  onSaveDistrictAction: (district: DistrictGap, patch: Partial<PlannerActions>) => Promise<void>;
  onSaveFacilityVerification: (claim: FacilityClaim, patch: Partial<FacilityVerification>) => Promise<void>;
  onSaveNote: (district: DistrictGap) => Promise<void>;
  onSaveOverride: (district: DistrictGap) => Promise<void>;
  onUpdateAction: (district: DistrictGap, patch: Partial<PlannerActions>) => void;
  onUpdateFacilityVerification: (claim: FacilityClaim, patch: Partial<FacilityVerification>) => void;
  savingKey: string | null;
}) {
  if (!district || !actions) {
    return (
      <Card>
        <CardContent className="py-10">
          <Empty>
            <EmptyHeader>
              <EmptyTitle>No district selected</EmptyTitle>
              <EmptyDescription>Select a district from the review queue.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        </CardContent>
      </Card>
    );
  }

  const scoreForDisplay = actions.overrideScore ?? district.planning_priority_score;
  const isMissingInfoWorkflow = queueMode === 'missing_info' || district.supply_score === 0;
  const districtSaving = savingKey === districtKey(district);
  const noteSaving = savingKey === `${districtKey(district)}:note`;
  const overrideSaving = savingKey === `${districtKey(district)}:override`;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="space-y-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>{district.district_name}</CardTitle>
              <div className="mt-1 text-sm text-muted-foreground">{district.state}</div>
            </div>
            <Badge variant={evidenceVariant(district.uncertainty_label)}>{district.uncertainty_label}</Badge>
          </div>
          <div className="grid gap-3 md:grid-cols-4">
            <ScoreMetric label="Priority" value={scoreForDisplay} icon={Flag} />
            <ScoreMetric label="Health risk" value={district.risk_score} icon={AlertTriangle} />
            <ScoreMetric label="Claimed supply" value={district.supply_score} icon={ClipboardCheck} />
            <ScoreMetric label="Evidence" value={district.evidence_score} icon={ShieldQuestion} />
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {isMissingInfoWorkflow && (
            <Alert>
              <ShieldQuestion className="h-4 w-4" />
              <AlertDescription>
                This district has no usable supply evidence for the selected care need. Collect missing facility or source
                information before making a planning decision.
              </AlertDescription>
            </Alert>
          )}
          {actions.overrideScore !== null && (
            <Alert>
              <AlertDescription>
                Override priority {formatScore(actions.overrideScore)}. {actions.overrideReason || 'No override reason saved.'}
              </AlertDescription>
            </Alert>
          )}
          <p className="text-sm leading-6 text-muted-foreground">{district.explanation}</p>
          <div className="grid gap-2 text-sm md:grid-cols-4">
            <DetailPill label="Relevant claims" value={district.relevant_claims} />
            <DetailPill label="Strong" value={district.strong_claims} />
            <DetailPill label="Partial" value={district.partial_claims} />
            <DetailPill label="Pincode linked" value={district.pincode_inferred_claims} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{isMissingInfoWorkflow ? 'Information Collection' : 'Planner Actions'}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {!isMissingInfoWorkflow && (
              <Button
                variant={actions.shortlisted ? 'default' : 'outline'}
                onClick={() => void onSaveDistrictAction(district, { shortlisted: !actions.shortlisted })}
                disabled={districtSaving}
              >
                <Star className="mr-2 h-4 w-4" />
                Shortlist
              </Button>
            )}
            <Button
              variant={actions.verificationRequested ? 'default' : 'outline'}
              onClick={() =>
                void onSaveDistrictAction(district, { verificationRequested: !actions.verificationRequested })
              }
              disabled={districtSaving}
            >
              {isMissingInfoWorkflow ? (
                <ShieldQuestion className="mr-2 h-4 w-4" />
              ) : (
                <CheckCircle2 className="mr-2 h-4 w-4" />
              )}
              {isMissingInfoWorkflow ? 'Request information' : 'Field verification'}
            </Button>
            <Button
              variant={actions.dismissed ? 'destructive' : 'outline'}
              onClick={() => void onSaveDistrictAction(district, { dismissed: !actions.dismissed })}
              disabled={districtSaving}
            >
              Dismiss
            </Button>
          </div>
          <Textarea
            className="min-h-24"
            placeholder="Planner note"
            value={actions.noteLatest}
            onChange={(event) => onUpdateAction(district, { noteLatest: event.target.value })}
          />
          <div className="flex justify-end">
            <Button
              variant="outline"
              onClick={() => void onSaveNote(district)}
              disabled={noteSaving || actions.noteLatest.trim().length === 0}
            >
              <Save className="mr-2 h-4 w-4" />
              Save note
            </Button>
          </div>
        </CardContent>
      </Card>

      {!isMissingInfoWorkflow && (
        <Card>
          <CardHeader>
            <CardTitle>Score Override</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-3 md:grid-cols-[170px_minmax(0,1fr)]">
              <input
                aria-label="Override score"
                className="h-10 rounded-md border bg-background px-3 text-sm"
                max={100}
                min={0}
                placeholder="Override score"
                type="number"
                value={actions.overrideScore ?? ''}
                onChange={(event) =>
                  onUpdateAction(district, {
                    overrideScore: event.target.value === '' ? null : Number(event.target.value),
                  })
                }
              />
              <input
                aria-label="Override reason"
                className="h-10 rounded-md border bg-background px-3 text-sm"
                placeholder="Override reason"
                value={actions.overrideReason}
                onChange={(event) => onUpdateAction(district, { overrideReason: event.target.value })}
              />
            </div>
            <div className="flex justify-end">
              <Button variant="outline" onClick={() => void onSaveOverride(district)} disabled={overrideSaving}>
                <Save className="mr-2 h-4 w-4" />
                Save override
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Facility Evidence</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {claimsLoading ? (
            Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-24 w-full" />)
          ) : claims.length === 0 ? (
            <Empty>
              <EmptyHeader>
                <EmptyTitle>No facility claims found</EmptyTitle>
                <EmptyDescription>
                  {isMissingInfoWorkflow
                    ? 'Add facility capability or source data, then regenerate the CareGap claims and district gaps.'
                    : 'Evidence is missing for this care need in the prepared claims table.'}
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            claims.map((claim) => (
              <ClaimRow
                claim={claim}
                key={`${claim.facility_id}:${claim.capability}`}
                onSaveVerification={onSaveFacilityVerification}
                onUpdateVerification={onUpdateFacilityVerification}
                saving={savingKey === facilityKey(claim)}
                verification={facilityVerifications[facilityKey(claim)] ?? { requested: false, reason: '' }}
              />
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function ScoreMetric({ icon: Icon, label, value }: { icon: typeof Flag; label: string; value: number }) {
  return (
    <div className="rounded-md border p-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className="mt-2 text-xl font-semibold">{formatScore(value)}</div>
      <div className="mt-2">
        <ScoreBar value={value} muted={label !== 'Priority'} />
      </div>
    </div>
  );
}

function DetailPill({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-muted px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-medium">{formatNumber(value)}</div>
    </div>
  );
}

function ClaimRow({
  claim,
  onSaveVerification,
  onUpdateVerification,
  saving,
  verification,
}: {
  claim: FacilityClaim;
  onSaveVerification: (claim: FacilityClaim, patch: Partial<FacilityVerification>) => Promise<void>;
  onUpdateVerification: (claim: FacilityClaim, patch: Partial<FacilityVerification>) => void;
  saving: boolean;
  verification: FacilityVerification;
}) {
  return (
    <div className="rounded-md border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-medium text-foreground">{claim.facility_name}</div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>{CAPABILITY_LABELS[claim.capability] ?? claim.capability}</span>
            <span>{claim.district_source.replaceAll('_', ' ')}</span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {verification.requested && <Badge variant="outline">needs verification</Badge>}
          <Badge variant={evidenceVariant(claim.confidence)}>{claim.confidence}</Badge>
        </div>
      </div>
      <div className="mt-3 flex gap-2 text-sm leading-6">
        <FileText className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <p className="text-muted-foreground">{claim.evidence_text}</p>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{claim.uncertainty_reason}</p>
      <div className="mt-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
        <input
          aria-label={`Verification reason for ${claim.facility_name}`}
          className="h-10 rounded-md border bg-background px-3 text-sm"
          placeholder="Verification reason"
          value={verification.reason}
          onChange={(event) => onUpdateVerification(claim, { reason: event.target.value })}
        />
        <Button
          variant={verification.requested ? 'default' : 'outline'}
          onClick={() => void onSaveVerification(claim, { requested: !verification.requested })}
          disabled={saving}
        >
          <CheckCircle2 className="mr-2 h-4 w-4" />
          Needs verification
        </Button>
      </div>
    </div>
  );
}
