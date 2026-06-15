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
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@databricks/appkit-ui/react';
import {
  Activity,
  Building2,
  DatabaseZap,
  Hospital,
  MapPin,
  RefreshCw,
  Search,
  ShieldCheck,
} from 'lucide-react';

type StateSummary = {
  state: string;
  districts: number;
  institutional_birth_pct: number | null;
  stunting_pct: number | null;
  anaemia_pct: number | null;
  facilities: number;
};

type FacilityType = {
  facility_type: string;
  count: number;
};

type Overview = {
  counts: {
    facilities: number;
    pincodes: number;
    districts: number;
    states: number;
  };
  states: StateSummary[];
  facilityTypes: FacilityType[];
  availability: {
    facilities: boolean;
    pincodeDirectory: boolean;
    nfhsIndicators: boolean;
  };
  errors: string[];
};

type Facility = {
  facility_id: string;
  name: string | null;
  facility_type: string | null;
  operator_type: string | null;
  city: string | null;
  state: string | null;
  pincode: string | null;
  phone: string | null;
  website: string | null;
  latitude: number | null;
  longitude: number | null;
  description: string | null;
};

type District = {
  district_id: string;
  district_name: string;
  state_ut: string;
  households_surveyed: number;
  institutional_birth_5y_pct: number;
  stunting_pct: number;
  anaemia_pct: number;
  hh_improved_water_pct: number;
  hh_use_improved_sanitation_pct: number;
  hh_member_covered_health_insurance_pct: number;
};

function formatNumber(value: number | null | undefined) {
  return Number(value ?? 0).toLocaleString();
}

function formatPct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'n/a';
  return `${Number(value).toFixed(1)}%`;
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  const payload = (await response.json()) as T & { error?: string };
  if (!response.ok) throw new Error(payload.error ?? response.statusText);
  return payload;
}

function MetricCard({
  title,
  value,
  note,
  icon: Icon,
}: {
  title: string;
  value: string;
  note: string;
  icon: typeof Activity;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-semibold tracking-normal text-foreground">{value}</div>
        <p className="mt-1 text-xs text-muted-foreground">{note}</p>
      </CardContent>
    </Card>
  );
}

function LoadingGrid() {
  return (
    <div className="grid gap-4 md:grid-cols-4">
      {Array.from({ length: 4 }, (_, index) => (
        <Card key={index}>
          <CardHeader>
            <Skeleton className="h-4 w-24" />
          </CardHeader>
          <CardContent>
            <Skeleton className="h-8 w-20" />
            <Skeleton className="mt-3 h-3 w-32" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export default function App() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [districts, setDistricts] = useState<District[]>([]);
  const [query, setQuery] = useState('');
  const [state, setState] = useState('all');
  const [facilityType, setFacilityType] = useState('all');
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [facilitiesLoading, setFacilitiesLoading] = useState(true);
  const [districtsLoading, setDistrictsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const states = useMemo(
    () => [...(overview?.states ?? [])].sort((a, b) => a.state.localeCompare(b.state)),
    [overview],
  );

  const refreshOverview = async () => {
    setOverviewLoading(true);
    setError(null);
    try {
      setOverview(await fetchJson<Overview>('/api/health/overview'));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load overview');
    } finally {
      setOverviewLoading(false);
    }
  };

  useEffect(() => {
    void refreshOverview();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      setFacilitiesLoading(true);
      const params = new URLSearchParams({
        q: query,
        state,
        type: facilityType,
        limit: '25',
      });
      fetch(`/api/health/facilities?${params.toString()}`, { signal: controller.signal })
        .then((response) => {
          if (!response.ok) {
            return response
              .json()
              .then((body: { error?: string }) => Promise.reject(new Error(body.error ?? response.statusText)));
          }
          return response.json() as Promise<Facility[]>;
        })
        .then(setFacilities)
        .catch((err) => {
          if (err instanceof DOMException && err.name === 'AbortError') return;
          setFacilities([]);
        })
        .finally(() => setFacilitiesLoading(false));
    }, 250);

    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [query, state, facilityType]);

  useEffect(() => {
    setDistrictsLoading(true);
    const params = new URLSearchParams({ state, limit: '50' });
    fetchJson<District[]>(`/api/health/districts?${params.toString()}`)
      .then(setDistricts)
      .catch(() => setDistricts([]))
      .finally(() => setDistrictsLoading(false));
  }, [state]);

  const maxFacilities = Math.max(...(overview?.states.map((row) => row.facilities) ?? [1]), 1);

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-5 md:flex-row md:items-center md:justify-between md:px-6">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">Lakebase continuous sync</Badge>
              <Badge variant="outline">DAIS 2026</Badge>
            </div>
            <h1 className="mt-3 text-2xl font-semibold tracking-normal text-foreground md:text-3xl">
              India Health Access Explorer
            </h1>
            <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
              Search synced health facilities, compare district NFHS indicators, and inspect coverage
              from Lakebase-backed reads.
            </p>
          </div>
          <Button variant="outline" onClick={() => void refreshOverview()} disabled={overviewLoading}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6 md:px-6">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {overview?.errors.length ? (
          <Alert>
            <AlertDescription>
              Some synced tables are still provisioning. Available views will fill in as Lakebase
              syncs finish.
            </AlertDescription>
          </Alert>
        ) : null}

        {overviewLoading || !overview ? (
          <LoadingGrid />
        ) : (
          <div className="grid gap-4 md:grid-cols-4">
            <MetricCard
              title="Facilities"
              value={formatNumber(overview.counts.facilities)}
              note={overview.availability.facilities ? 'Synced from Lakebase' : 'Sync in progress'}
              icon={Hospital}
            />
            <MetricCard
              title="Pincode offices"
              value={formatNumber(overview.counts.pincodes)}
              note={overview.availability.pincodeDirectory ? 'Directory rows online' : 'Sync in progress'}
              icon={MapPin}
            />
            <MetricCard
              title="NFHS districts"
              value={formatNumber(overview.counts.districts)}
              note="District health indicators"
              icon={ShieldCheck}
            />
            <MetricCard
              title="Source"
              value="3 tables"
              note="Curated CDF Delta to Lakebase"
              icon={DatabaseZap}
            />
          </div>
        )}

        <section className="grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(340px,0.85fr)]">
          <Card>
            <CardHeader>
              <CardTitle>Facility Search</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px_190px]">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                  <Input
                    className="pl-9"
                    placeholder="Search name, city, state, or pincode"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                  />
                </div>
                <Select value={state} onValueChange={setState}>
                  <SelectTrigger>
                    <SelectValue placeholder="State" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All states</SelectItem>
                    {states.map((row) => (
                      <SelectItem key={row.state} value={row.state}>
                        {row.state}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select value={facilityType} onValueChange={setFacilityType}>
                  <SelectTrigger>
                    <SelectValue placeholder="Facility type" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All types</SelectItem>
                    {(overview?.facilityTypes ?? []).map((row) => (
                      <SelectItem key={row.facility_type} value={row.facility_type}>
                        {row.facility_type}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {facilitiesLoading ? (
                <div className="space-y-3">
                  {Array.from({ length: 5 }, (_, index) => (
                    <Skeleton key={index} className="h-16 w-full" />
                  ))}
                </div>
              ) : facilities.length === 0 ? (
                <Empty>
                  <EmptyHeader>
                    <EmptyTitle>No facilities to show</EmptyTitle>
                    <EmptyDescription>
                      Try a broader search, or wait for the facilities sync to finish.
                    </EmptyDescription>
                  </EmptyHeader>
                </Empty>
              ) : (
                <div className="overflow-hidden rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Facility</TableHead>
                        <TableHead>Location</TableHead>
                        <TableHead>Type</TableHead>
                        <TableHead>Contact</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {facilities.map((facility) => (
                        <TableRow key={facility.facility_id}>
                          <TableCell className="max-w-[320px]">
                            <div className="font-medium text-foreground">{facility.name ?? 'Unnamed facility'}</div>
                            <div className="truncate text-xs text-muted-foreground">{facility.description ?? 'No description'}</div>
                          </TableCell>
                          <TableCell>
                            <div>{[facility.city, facility.state].filter(Boolean).join(', ') || 'Unknown'}</div>
                            <div className="text-xs text-muted-foreground">{facility.pincode ?? 'No pincode'}</div>
                          </TableCell>
                          <TableCell>
                            <Badge variant="outline">{facility.facility_type ?? 'unknown'}</Badge>
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {facility.phone ?? facility.website ?? 'No contact'}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>State Coverage</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {(overview?.states ?? []).map((row) => (
                <div key={row.state} className="space-y-2">
                  <div className="flex items-center justify-between gap-3 text-sm">
                    <span className="font-medium text-foreground">{row.state}</span>
                    <span className="text-muted-foreground">{formatNumber(row.facilities)} facilities</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary"
                      style={{ width: `${Math.max(4, (row.facilities / maxFacilities) * 100)}%` }}
                    />
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-xs text-muted-foreground">
                    <span>{row.districts} districts</span>
                    <span>{formatPct(row.institutional_birth_pct)} births</span>
                    <span>{formatPct(row.anaemia_pct)} anaemia</span>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </section>

        <Tabs defaultValue="districts">
          <TabsList>
            <TabsTrigger value="districts">District Indicators</TabsTrigger>
            <TabsTrigger value="types">Facility Mix</TabsTrigger>
          </TabsList>
          <TabsContent value="districts" className="mt-4">
            <Card>
              <CardHeader>
                <CardTitle>NFHS District Indicators</CardTitle>
              </CardHeader>
              <CardContent>
                {districtsLoading ? (
                  <Skeleton className="h-72 w-full" />
                ) : (
                  <div className="overflow-hidden rounded-md border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>District</TableHead>
                          <TableHead>Institutional births</TableHead>
                          <TableHead>Stunting</TableHead>
                          <TableHead>Anaemia</TableHead>
                          <TableHead>Water</TableHead>
                          <TableHead>Insurance</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {districts.map((district) => (
                          <TableRow key={district.district_id}>
                            <TableCell>
                              <div className="font-medium">{district.district_name}</div>
                              <div className="text-xs text-muted-foreground">{district.state_ut}</div>
                            </TableCell>
                            <TableCell>{formatPct(district.institutional_birth_5y_pct)}</TableCell>
                            <TableCell>{formatPct(district.stunting_pct)}</TableCell>
                            <TableCell>{formatPct(district.anaemia_pct)}</TableCell>
                            <TableCell>{formatPct(district.hh_improved_water_pct)}</TableCell>
                            <TableCell>{formatPct(district.hh_member_covered_health_insurance_pct)}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value="types" className="mt-4">
            <Card>
              <CardHeader>
                <CardTitle>Facility Type Mix</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
                {(overview?.facilityTypes ?? []).map((row) => (
                  <div key={row.facility_type} className="rounded-md border p-4">
                    <div className="flex items-center gap-2">
                      <Building2 className="h-4 w-4 text-muted-foreground" />
                      <span className="text-sm font-medium">{row.facility_type}</span>
                    </div>
                    <div className="mt-3 text-2xl font-semibold">{formatNumber(row.count)}</div>
                  </div>
                ))}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
