# Department timing and ownership

Status: implemented as a machine-readable tracking foundation for Trial/dev.
This is an **internal operational diagnostic**, separate from the official
SERVPRO franchise scorecard.

## What is tracked

Every claim/division can accumulate multiple work periods under three groups:

| Group | Current Pipeline ownership | Operational responsibility |
|---|---|---|
| Front Operations | New, Closeout, Approved, AR | Intake, customer contact, scheduling handoffs, closeout, and receivables follow-through |
| Field | Initial, Mitigation | Initial inspection, active production, monitoring, and field completion evidence |
| Estimating | Estimating, Submitted | Estimate preparation, submission, revision, and file completion |

The underlying hierarchy remains **Client → Job/claim → Division → Work
period**. EMS, Contents, and Recon retain separate detailed stages and can
close independently before the overall job closes.

## Clock rules

- Total elapsed time never stops.
- Controllable time excludes only approved pauses.
- Approved default pause categories: customer, carrier, weather, access,
  material, and subcontractor.
- Custom pause reasons require review and do not hide controllable delay until
  approved.
- A handoff uses one timestamp: it ends the source clock and begins the
  destination clock.
- Reopening a completed group creates a new work period; it does not overwrite
  history.
- The most-specific deadline wins: stage/client-program, then group/franchise.
- Every event retains its owner, source, source ID/evidence, and timestamp.

## Current target source

Until the earlier audit-log photos are reattached, the system uses the Pipeline
targets already configured in the app so the Jobs board and KPI report agree:

| Stage | Default target |
|---|---:|
| New | 2 days |
| Initial | 3 days |
| Mitigation | 14 days |
| Closeout | 5 days |
| Estimating | 7 days |
| Submitted | 14 days |
| Approved | 5 days |
| AR | 30 days |

These defaults are configurable and are **not** presented as carrier/client
SLAs. Any stricter Front Operations, Field, or Estimating deadlines visible in
the unavailable photos must be entered as explicit overrides after the source
is recovered; the tracker does not invent them.

## Data quality

Existing Pipeline transition history can already be rolled up by group. It has
stage elapsed time but no historical pause detail, so the result is labeled
`estimated_from_stage_history`. New native events support exact total and
controllable time.

## Module interface

`operational_tracking.py` is the single timing module used by job views and KPI
reporting:

- `project(events, now, targets)` projects native start/pause/resume/handoff/
  complete/reopen events for one job.
- `project_stage_history(transitions, current, now, thresholds)` adapts the
  existing Pipeline history.
- `rollup(jobs)` aggregates independently projected jobs for department
  reporting.
- `specification()` supplies labels and rules to browser/desktop interfaces.

The KPI bridge now exposes both `operational_tracking_spec()` and
`operational_group_stats()`.
