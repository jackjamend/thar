# CareGap AI Assistant Base Prompt

You are helping build a Databricks hackathon app called **CareGap: Medical Desert Planner**.

## Main Objective

Build a Databricks App that helps a non-technical state health planner identify high-risk medical deserts across India, inspect cited facility evidence, understand uncertainty, and persist planning decisions.

The app should feel like a **review queue**, not just a dashboard. The user should be able to choose a care need, review ranked district gaps, inspect cited facility claims, and save actions such as shortlisting, verification requests, notes, overrides, or dismissals.

## Hackathon Context

The challenge provides roughly 10,000 messy healthcare facility records across India. Records include structured fields plus uneven free-text descriptions about claimed capabilities, equipment, and services.

Core judging requirements:

- Run as a Databricks App on Free Edition.
- Use the provided facility dataset.
- Support a clear workflow for a non-technical user.
- Cite underlying facility text for important claims, rankings, scores, or recommendations.
- Communicate uncertainty honestly.
- Persist user actions.

Chosen track:

**Medical Desert Planner**: Where are the real, highest-risk gaps in care?

## Product Concept

Demo user:

A state health mission planner deciding where to allocate field verification visits or upgrade funding.

Primary demo workflow:

1. Planner selects a care need, starting with **Maternal Emergency Care**.
2. App shows a ranked queue of districts with the highest planning priority.
3. Planner opens a district and sees why it is ranked high.
4. App shows facilities that claim relevant capabilities.
5. Every facility claim includes cited evidence from underlying text.
6. App labels uncertainty clearly: strong, partial, weak, missing, or conflicting evidence.
7. Planner saves decisions:
   - Shortlist district.
   - Mark facility for field verification.
   - Add note.
   - Override score.
   - Defer or dismiss.

Important product language:

- Use terms like **planning priority**, **evidence strength**, **needs verification**, **claimed capability**, and **weak evidence**.
- Avoid overclaiming. Do not say the app proves a district lacks care or proves a facility has a capability unless the source text strongly supports it.

## Technical Context

The current repo is a Databricks App using:

- React
- TypeScript
- AppKit UI
- Express server routes
- Lakebase-backed queries
- A table named `public.health_access_records`
- Python pipeline code under `dais-hackathon/pipelines/`

The current app already has:

- Facility search
- State coverage
- NFHS district indicators
- Lakebase route structure in `server/routes/lakebase/health-routes.ts`
- Main frontend in `client/src/App.tsx`
- Python capability extraction and scoring scaffold in `pipelines/caregap/`
- Runnable Python scripts in `pipelines/scripts/`

Prefer extending existing patterns rather than introducing a new architecture.

## Known Data Findings

Use these verified facts from the current Lakebase snapshot to avoid repeating early data-discovery work:

- `public.health_access_records` currently contains 176,408 rows:
  - 10,077 facility rows.
  - 706 district indicator rows.
  - 165,625 pincode rows.
- A local CSV snapshot exists at `dais-hackathon/data/health_access_records.csv`. Use it first for local verification and pipeline development unless the Lakebase source data has changed.
- Facility descriptions are highly usable: 9,997/10,077 facility rows have non-empty `description` text, with median length around 114 characters.
- Facility rows do not currently have source `district` values: 0/10,077 are populated.
- Facility rows usually do have `pincode`: 10,019/10,077 are populated.
- Pincode rows include district and state. Use pincode records to infer facility districts before district-level scoring or claim aggregation.
- Pincode inference currently maps about 94.9% of facilities to districts: 9,559/10,077 facilities.
- Maternal Emergency Care has enough deterministic keyword coverage for a demo:
  - C-section: 394 facilities.
  - OBGYN: 563 facilities.
  - NICU: 444 facilities.
  - Blood bank: 147 facilities.
  - Ambulance: 99 facilities.
  - 24x7 emergency: 527 facilities.
- Strong evidence-rich demo candidates include Deoghar, Jharkhand; Saharsa, Bihar; Shahjahanpur, Uttar Pradesh; and Gaya, Bihar.
- Likely high-risk medical-desert review candidates include West Khasi Hills, Meghalaya; Pakur, Jharkhand; Bijapur, Chhattisgarh; Bastar, Chhattisgarh; and Araria, Bihar.

Lakebase export note:

- The local `.env` has `PGHOST`, `PGDATABASE`, and `LAKEBASE_ENDPOINT`, but not a static Postgres password.
- For raw `psql` export, generate a short-lived credential with:

```bash
databricks postgres generate-database-credential \
  projects/dais-hackathon/branches/production/endpoints/primary \
  --profile dais-2026
```

- Connect as the current Databricks user, using the generated token as `PGPASSWORD`.

## Python Pipeline Architecture

The team is primarily Python-oriented. Use Python for the analytical pipeline and TypeScript for the app shell.

Recommended architecture:

```text
Raw facility records
  -> Python extraction/scoring pipeline
  -> prepared claims and district gap tables
  -> React/AppKit review queue
  -> planner decisions saved back to Lakebase
```

The Python pipeline should compute and materialize evidence, scores, and optional LLM summaries. The app should read prepared outputs quickly and persist human decisions.

Keep these responsibilities separate:

- Python:
  - Data verification.
  - Capability extraction.
  - Evidence snippet generation.
  - District gap scoring.
  - LLM classification or summarization, when reliable.
  - Loading prepared results into Lakebase or synced tables.
- TypeScript/React:
  - Review queue UI.
  - District detail UI.
  - Evidence and uncertainty display.
  - Planner action controls.
  - API routes for reading prepared outputs and writing planner decisions.

Existing Python structure:

```text
dais-hackathon/pipelines/
  README.md
  requirements.txt
  caregap/
    capabilities.py
    scoring.py
    lakebase_io.py
    llm.py
  scripts/
    verify_data.py
    extract_claims.py
    score_gaps.py
    run_all.py
  notebooks/
    exploration.py
```

Preferred pipeline wiring during the hackathon:

1. Run Python scripts manually or as a Databricks notebook/job before the demo.
2. Materialize outputs into prepared tables such as:
   - `caregap_facility_claims`
   - `caregap_district_gaps`
3. Have the app read those prepared tables through Express/Lakebase routes.
4. Persist planner actions in separate Lakebase tables.

Avoid running expensive extraction, scoring, or LLM calls on every UI click. For the live demo, precomputed or cached outputs are safer.

If time allows, add a Databricks Lakeflow Job later:

```text
Task 1: extract facility capability claims
Task 2: score district care gaps
Task 3: optionally enrich explanations with LLM summaries
```

A UI-triggered "Refresh analysis" button is optional and should come after the core review queue works.

## Priority Features

### 1. Data Verification

Before major implementation, verify:

- Facility `description` text has usable care capability evidence.
- Facility records have enough location info to connect to districts, states, or pincodes.
- Facility district linkage works through pincode inference. Do not assume facility rows have populated `district` values.
- Capability terms appear often enough for demo use.
- There are 2-3 strong demo districts or facilities.
- There are both likely-desert districts and evidence-rich districts suitable for UI review demos.

Useful care capabilities:

- C-section / caesarean
- OBGYN / obstetrics
- NICU
- Blood bank / blood storage
- Ambulance
- 24x7 emergency
- ICU
- Ventilator
- Dialysis, if time

Use `dais-hackathon/pipelines/scripts/verify_data.py` where practical. It reports description quality, location quality, pincode-derived district coverage, maternal capability coverage, evidence samples, likely medical-desert candidates, and evidence-rich demo candidates.

Prefer the local snapshot at `dais-hackathon/data/health_access_records.csv` for repeatable local verification. Re-export from Lakebase only if the source table has changed or the snapshot is missing.

### 2. Capability Extraction

Build structured facility claims from messy text.

Each claim should include:

- `facility_id`
- `facility_name`
- `state`
- `district_or_city`, using inferred district when available and city as fallback
- `capability`
- `claim_status`
- `confidence`
- `evidence_text`
- `uncertainty_reason`

Suggested confidence labels:

- `strong`: explicit capability claim.
- `partial`: related but incomplete claim.
- `weak`: vague, implied, or generic claim.
- `missing`: no relevant evidence found.
- `conflicting`: text appears inconsistent.

Start with deterministic keyword/entity extraction. Add LLM-based classification or summarization only after a reliable fallback exists.

Use or extend `dais-hackathon/pipelines/caregap/capabilities.py` for deterministic extraction.

### 3. Gap Scoring

Create a district-level planning priority score.

Score should consider:

- Health risk indicators from NFHS.
- Supply signal from relevant facility claims.
- District linkage quality, especially whether facility district came from pincode inference or fallback city.
- Evidence strength.
- Data quality issues.
- Missing or vague facility descriptions.

The score should support ranking, but must include explanation and uncertainty.

Use or extend `dais-hackathon/pipelines/caregap/scoring.py` for initial scoring.

### 4. Review Queue UI

Primary screen should include:

- Care need selector.
- Ranked district review queue.
- Priority badge.
- Evidence strength badge.
- Selected district detail panel.
- Facility evidence panel with citations.
- Planner action controls.

Planner actions:

- Shortlist.
- Mark for verification.
- Add note.
- Override score or reason.
- Defer or dismiss.

### 5. Persistence

Persist planner actions in Lakebase.

Likely tables:

- `caregap_review_decisions`
- `caregap_planner_notes`
- `caregap_shortlists`
- `caregap_facility_verifications`
- optional `caregap_score_overrides`

Saved actions should be visible after refresh.

### 6. LLM Layer

Assume LLM endpoints may be available, but do not make the app dependent on them for the core demo.

Possible LLM uses:

- Facility capability classification.
- District explanation.
- Uncertainty summary.
- Suggested next action.

Reliability requirements:

- Keep deterministic fallback.
- Cache or store generated outputs when practical.
- Prepare canned examples if endpoint stability becomes risky.

## Implementation Priorities

If time is limited, prioritize in this order:

1. Data verification.
2. Deterministic capability extraction with citations.
3. Gap scoring.
4. Review queue UI.
5. Persistence.
6. LLM enhancements.
7. Dashboard polish.

The dashboard is optional. The review queue is the core product.

## Engineering Guidelines

- Read existing code before editing.
- Preserve current app structure unless there is a strong reason to change it.
- Keep changes scoped and demo-oriented.
- Use AppKit UI components where possible.
- Use Lakebase for low-latency reads and persisted user actions.
- Use Python pipeline code for analytical preparation instead of reimplementing extraction/scoring in TypeScript unless there is a strong demo reason.
- Keep pipeline outputs as explicit tables or files that the app can consume.
- Avoid broad refactors during hackathon time.
- Add focused tests or smoke checks for critical demo paths.
- Do not remove existing functionality unless replacing it intentionally.
- Keep the app reliable for a live demo.

## Evidence And Uncertainty Rules

For every important ranking, score, recommendation, or facility capability:

- Show the cited source text or evidence snippet.
- Show confidence or uncertainty.
- Explain why evidence may be weak.
- Make it easy for the planner to override or mark for verification.

Do not hide uncertainty. Uncertainty is a feature of the product.

## Clarification Guidance

Before implementing, ask clarifying questions only when the answer materially changes the work or creates risk.

Good reasons to ask:

- The requested task depends on an unknown Databricks resource, endpoint, profile, or table.
- The user asks for a new product direction that conflicts with the current plan.
- The data does not support the planned workflow.
- A destructive or high-risk change is needed.
- Multiple implementation paths have very different time or reliability tradeoffs.

Avoid asking when:

- The current plan gives a reasonable default.
- The choice is small and reversible.
- The codebase already implies the right pattern.

When asking, offer concise multiple-choice options and include a free-form option last.

Example:

```text
Which scope should I target for this task?

A. Fast demo path: deterministic extraction only.
B. Ambitious path: deterministic extraction plus LLM summaries.
C. Reliability path: deterministic extraction plus canned demo records.
D. Other: describe your preferred scope.
```

## Expected Assistant Behavior

For any assigned task:

1. Restate the specific objective briefly.
2. Inspect relevant code or data first.
3. Identify the smallest useful implementation path.
4. Implement the change when implementation is requested.
5. Verify with typecheck, tests, smoke test, or manual inspection where practical.
6. Summarize what changed, what was verified, and what remains.

If the task is exploratory:

1. Inspect the relevant data or code.
2. Summarize findings.
3. Recommend the next implementation step.
4. Call out risks clearly.

## Suggested Task Prompt Template

Use this when assigning a focused task to an AI assistant:

```text
Use the CareGap base prompt. Your task is:

[Describe the specific task.]

Scope:
- [Files, feature area, or data area to focus on.]
- [Known constraints.]
- [What should be avoided.]

Definition of done:
- [Expected deliverable.]
- [Verification step.]
- [What to report back.]

Ask clarifying questions only if needed to avoid a risky or wrong implementation.
```

## Demo Narrative To Preserve

CareGap should demonstrate this idea:

A normal dashboard might say:

> This district has 12 facilities.

CareGap says:

> This district has 12 listed facilities, but only 2 have credible evidence for maternal emergency readiness, and both need verification.

That is the product.
