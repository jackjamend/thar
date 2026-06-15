import { useEffect, useMemo, useState } from 'react';
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
  ShieldQuestion,
  Star,
} from 'lucide-react';

type CareNeed = 'maternal_emergency' | 'critical_care' | 'dialysis_access';

type ReviewQueueResponse = {
  careNeed: string;
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

type EvidenceLabel = 'strong' | 'partial' | 'weak' | 'missing' | 'conflicting';

type PlannerActions = {
  shortlisted: boolean;
  verification: boolean;
  dismissed: boolean;
  note: string;
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

function formatScore(value: number) {
  return Number(value ?? 0).toFixed(1);
}

function formatNumber(value: number) {
  return Number(value ?? 0).toLocaleString();
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
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

function actionKey(district: DistrictGap) {
  return `${district.state}:${district.district_name}`;
}

export default function App() {
  const [careNeed, setCareNeed] = useState<CareNeed>('maternal_emergency');
  const [stateFilter, setStateFilter] = useState('all');
  const [evidenceFilter, setEvidenceFilter] = useState('all');
  const [queueResponse, setQueueResponse] = useState<ReviewQueueResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [claims, setClaims] = useState<FacilityClaim[]>([]);
  const [actions, setActions] = useState<Record<string, PlannerActions>>({});
  const [queueLoading, setQueueLoading] = useState(true);
  const [claimsLoading, setClaimsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const queue = queueResponse?.queue ?? [];
  const selectedDistrict = queue.find((district) => district.district_id === selectedId) ?? queue[0] ?? null;
  const selectedActions = selectedDistrict
    ? actions[actionKey(selectedDistrict)] ?? { shortlisted: false, verification: false, dismissed: false, note: '' }
    : null;

  const queueStats = useMemo(
    () => ({
      high: queue.filter((district) => district.planning_priority_score >= 70).length,
      missing: queue.filter((district) => district.uncertainty_label === 'missing').length,
      reviewable: queue.filter((district) => district.relevant_claims > 0).length,
    }),
    [queue],
  );

  const refreshQueue = async () => {
    setQueueLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        careNeed,
        state: stateFilter,
        evidence: evidenceFilter,
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
  };

  useEffect(() => {
    void refreshQueue();
  }, [careNeed, stateFilter, evidenceFilter]);

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
  }, [careNeed, selectedDistrict?.district_id]);

  const updateAction = (district: DistrictGap, patch: Partial<PlannerActions>) => {
    setActions((current) => {
      const key = actionKey(district);
      const existing = current[key] ?? { shortlisted: false, verification: false, dismissed: false, note: '' };
      return { ...current, [key]: { ...existing, ...patch } };
    });
  };

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-4 md:flex-row md:items-center md:justify-between md:px-6">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">CareGap</Badge>
              <Badge variant="outline">Review queue</Badge>
            </div>
            <h1 className="mt-2 text-2xl font-semibold tracking-normal text-foreground md:text-3xl">
              Medical Desert Planner
            </h1>
          </div>
          <Button variant="outline" onClick={() => void refreshQueue()} disabled={queueLoading}>
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

        <section className="grid gap-3 md:grid-cols-[260px_220px_200px_minmax(0,1fr)]">
          <Select value={careNeed} onValueChange={(value) => setCareNeed(value as CareNeed)}>
            <SelectTrigger>
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
            <SelectTrigger>
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
            <SelectTrigger>
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
          <div className="grid grid-cols-3 gap-2">
            <QueueStat label="High" value={queueStats.high} />
            <QueueStat label="Missing" value={queueStats.missing} />
            <QueueStat label="Reviewable" value={queueStats.reviewable} />
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-[410px_minmax(0,1fr)]">
          <div className="space-y-3">
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
              queue.map((district) => (
                <button
                  key={district.district_id}
                  className={`w-full rounded-md border bg-card p-3 text-left transition hover:border-primary ${
                    selectedDistrict?.district_id === district.district_id ? 'border-primary ring-1 ring-primary' : ''
                  } ${actions[actionKey(district)]?.dismissed ? 'opacity-55' : ''}`}
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
                    <Badge variant={district.planning_priority_score >= 70 ? 'destructive' : 'secondary'}>
                      {priorityLabel(district.planning_priority_score)}
                    </Badge>
                  </div>
                  <div className="mt-3 grid grid-cols-[70px_minmax(0,1fr)_54px] items-center gap-2 text-xs">
                    <span className="text-muted-foreground">Priority</span>
                    <ScoreBar value={district.planning_priority_score} />
                    <span className="text-right font-medium">{formatScore(district.planning_priority_score)}</span>
                    <span className="text-muted-foreground">Supply</span>
                    <ScoreBar value={district.supply_score} muted />
                    <span className="text-right font-medium">{formatScore(district.supply_score)}</span>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Badge variant={evidenceVariant(district.uncertainty_label)}>{district.uncertainty_label}</Badge>
                    <Badge variant="outline">{formatNumber(district.relevant_claims)} claims</Badge>
                    {actions[actionKey(district)]?.shortlisted && <Badge variant="secondary">shortlisted</Badge>}
                    {actions[actionKey(district)]?.verification && <Badge variant="outline">verify</Badge>}
                  </div>
                </button>
              ))
            )}
          </div>

          <DistrictDetail
            actions={selectedActions}
            claims={claims}
            claimsLoading={claimsLoading}
            district={selectedDistrict}
            onUpdateAction={updateAction}
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
      <div className={`h-full rounded-full ${muted ? 'bg-muted-foreground' : 'bg-primary'}`} style={{ width: scoreWidth(value) }} />
    </div>
  );
}

function DistrictDetail({
  actions,
  claims,
  claimsLoading,
  district,
  onUpdateAction,
}: {
  actions: PlannerActions | null;
  claims: FacilityClaim[];
  claimsLoading: boolean;
  district: DistrictGap | null;
  onUpdateAction: (district: DistrictGap, patch: Partial<PlannerActions>) => void;
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
            <ScoreMetric label="Priority" value={district.planning_priority_score} icon={Flag} />
            <ScoreMetric label="Health risk" value={district.risk_score} icon={AlertTriangle} />
            <ScoreMetric label="Claimed supply" value={district.supply_score} icon={ClipboardCheck} />
            <ScoreMetric label="Evidence" value={district.evidence_score} icon={ShieldQuestion} />
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
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
          <CardTitle>Planner Actions</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button
              variant={actions.shortlisted ? 'default' : 'outline'}
              onClick={() => onUpdateAction(district, { shortlisted: !actions.shortlisted })}
            >
              <Star className="mr-2 h-4 w-4" />
              Shortlist
            </Button>
            <Button
              variant={actions.verification ? 'default' : 'outline'}
              onClick={() => onUpdateAction(district, { verification: !actions.verification })}
            >
              <CheckCircle2 className="mr-2 h-4 w-4" />
              Field verification
            </Button>
            <Button
              variant={actions.dismissed ? 'destructive' : 'outline'}
              onClick={() => onUpdateAction(district, { dismissed: !actions.dismissed })}
            >
              Dismiss
            </Button>
          </div>
          <Textarea
            className="min-h-24"
            placeholder="Planner note"
            value={actions.note}
            onChange={(event) => onUpdateAction(district, { note: event.target.value })}
          />
        </CardContent>
      </Card>

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
                <EmptyDescription>Evidence is missing for this care need in the prepared claims table.</EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            claims.map((claim) => <ClaimRow claim={claim} key={`${claim.facility_id}:${claim.capability}`} />)
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

function ClaimRow({ claim }: { claim: FacilityClaim }) {
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
        <Badge variant={evidenceVariant(claim.confidence)}>{claim.confidence}</Badge>
      </div>
      <div className="mt-3 flex gap-2 text-sm leading-6">
        <FileText className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <p className="text-muted-foreground">{claim.evidence_text}</p>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{claim.uncertainty_reason}</p>
    </div>
  );
}
