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

The current app already has:

- Facility search
- State coverage
- NFHS district indicators
- Lakebase route structure in `server/routes/lakebase/health-routes.ts`
- Main frontend in `client/src/App.tsx`

Prefer extending existing patterns rather than introducing a new architecture.

## Priority Features

### 1. Data Verification

Before major implementation, verify:

- Facility `description` text has usable care capability evidence.
- Facility records have enough location info to connect to districts, states, or pincodes.
- Capability terms appear often enough for demo use.
- There are 2-3 strong demo districts or facilities.

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

### 2. Capability Extraction

Build structured facility claims from messy text.

Each claim should include:

- `facility_id`
- `facility_name`
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

### 3. Gap Scoring

Create a district-level planning priority score.

Score should consider:

- Health risk indicators from NFHS.
- Supply signal from relevant facility claims.
- Evidence strength.
- Data quality issues.
- Missing or vague facility descriptions.

The score should support ranking, but must include explanation and uncertainty.

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

- `review_decisions`
- `planner_notes`
- `shortlists`
- `facility_verifications`
- optional `score_overrides`

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
