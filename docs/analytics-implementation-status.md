# Windows Analytics — implementation status

Target: Linguar Hub Windows desktop. L OPS is a visual reference only.

## Implemented locally

- Separate Analytics entry; APA Monitor remains accessible from its toolbar.
- Seven views: Overview, Weekly Review, Jobs to Review, Corrections and Follow-ups,
  Billing and AR, Trends, Data Quality.
- Existing OperationsData adapter reads the real workspace job graph. No sample figures.
- Explicit Loss IDs are grouped; legacy job identities remain separate and disclosed.
- Shared filter state and clickable metric-to-record lists.
- Review notes, owner, due date, outcome and revision history; local snapshots preserve filters.
- CSV export through the Windows save dialog, including applied filters.

## Not production-complete

- Weekly Review now includes **Logs audit · To Be Preserved** (IE only): exact-card
  queue, complete comment/checklist reads, structured weekly spreadsheet fields,
  department confirmations, dated Trello note preview, and confirmed month/Questions
  moves. Billed month is user-verified; invoice creation and payment alone do not
  determine it. Drafts remain local. Individual and selected-batch approval are
  supported. Not-billed cards get a dated audit comment without moving. Missing
  paperwork is recorded but does not independently block an explicitly billed card.
- New periods carry forward findings and clear confirmations; full-history reads
  highlight new/edited comments. Combined cards require both billed dates and use
  the last division's month. Missing month lanes have a separate approval action.
- Evidence gathering suggests explicitly labeled fields and quotes relevant notes
  with source references. Conflicting values are not auto-filled, and saved edits
  are preserved. AR candidate search and confirmed-link history comparison are
  available in Billing & finish. No automatic pass or ambiguous date inference is
  performed. Reviewers must verify candidates and resolve historical conflicts.
  Initial-note timing uses explicit completion/sent timestamps and a 60-minute limit.
  Separate Contents queue support and shared drafts remain future work.
- Interrupted publications reconcile the exact audit marker before retrying.
  Changed evidence or an unresolved comment result stops the move for manual review;
  only an unstarted preview can be discarded. No production cards were moved during tests.

- Reviews and snapshots are currently local to this PC, not a shared management workflow.
- The current IE graph has 444 legacy records with no explicit Loss IDs. Confirm identities
  through a reviewed migration; never merge names or claim numbers automatically.
- 245 are legacy-unclassified. They are excluded from the active total and shown in Data Quality.
- Activity dates, next actions, requirements, estimator status, role assignments and Job Profiles
  need adapters to their authoritative records. Unknown coverage is not a successful score.
- Invoice balances, payment aging and recurring-problem classification are not integrated.
- Department clocks, official scorecard thresholds and weight rules remain to implement.
- Active backlog is point-in-time. Date range controls event counts and billed/paid cohorts;
  eight-week trends describe the selected population, not necessarily all historical jobs.
- Existing graph-derived billing readiness is not verified against complete billing requirements.
- Native UI/interaction verification remains required; browser-control startup failed in this environment.

## Validation

- Model tests cover explicit identity grouping, location isolation, division filtering,
  billing dates, inspectable IDs and unclassified stages.
- API tests cover review validation, scope, revision history and immutable saved snapshots.
- Read-only live load verified Supabase connectivity and population counts; no live job writes.
- Local changes only: not packaged, published or released.

Close Out remains: Jobs → open a job → Finish → Close Out Job.
