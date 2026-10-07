# Shared job movement timing — integration proposal

Status: required next backend work; NOT implemented or deployed by the timing UI change.
Owner: OneLoss/shared backend. Branch: handoff/paperclip-source-20261003.

## Required outcome

Every job needs retained movement history across boards, including every arrival
at Logs. Entering Logs stops the estimator cycle; Billed is a separate milestone.
Include completed/archived jobs in historical reporting, not only active queues.
Preserve returns, estimator transfers, and reopened estimating cycles.

## Proposed contract for L OPS coordination before migration

- Append-only organization-scoped movement events tied to stable job identity,
  division, and provider card ID. Never merge different cards by customer name.
- Retain source/destination board and lane IDs plus names at event time, actor,
  occurrence timestamp, observation timestamp, source, and idempotency identity.
- Record confirmed OneLoss moves durably through the shared backend. Failed or
  pending move requests are not completed movements; reconcile provider outcomes.
- Ingest Trello lane and cross-board events, with webhook retries and scheduled
  reconciliation/backfill. Deduplicate provider echoes and out-of-order deliveries.
- A changed placement without a source event establishes an observation, NOT an
  exact move time. Preserve last-known/first-seen bounds and mark timing unknown.
- Logs-entry reporting must include arrivals without a known estimator start;
  do not silently omit those jobs or manufacture an estimating duration.
- Retain history through archive, board transfer and explicitly linked temporary
  WIP-card retirement. Keep source provenance; do not sum overlapping copies.
- Enforce organization/franchise access at ingestion and read boundaries.

L OPS must use the shared confirmed-movement pathway when it gains movement
controls; it must not create a competing local clock. Final table/RPC names and
identity mappings still require inspection/coordination before implementation.

## Acceptance tests before claiming all-job tracking

Cross-board move, Trello-originated move, OneLoss-originated move, duplicate echo,
missed webhook, offline client, multiple moves between polls, out-of-order events,
archive/reopen, explicit temporary-card linking, unknown start, and organization
isolation. Restart both clients and verify historical timings remain available.

## Current UI scope

The timing dialog now has a current-lane duration, estimator cycle summaries,
chronological movement timeline, collapsible lane totals and explicit coverage.
It still reads available exact-card Trello events on demand. No persistent ledger,
all-job backfill, schema deployment or production release is included here.
