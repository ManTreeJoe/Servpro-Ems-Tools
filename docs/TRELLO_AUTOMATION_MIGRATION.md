# Trello automation migration

## Direction

Linguar Hub owns job status, requirements, comments, deadlines, and automation.
Trello remains a temporary reference and sync destination. No Linguar rule should
require a Trello board, list, card, label, checklist, or member ID to function.

## What exists on the live boards

The read-only board history shows that the current process relies most heavily
on these outcomes:

- moving cards between lanes and boards;
- posting operational comments;
- checking checklist items;
- adding or removing members;
- copying cards and adding checklists;
- scheduled or deadline-driven follow-up.

The inspected boards were Contents, Estimating, Recon Closeout/Collections,
The Logs - EMS, WIP, EMS Billing Disputes, Disaster Response, and Commercial.
Trello's action history confirms the outcomes, but it does not provide a clean
export of the original Butler trigger, conditions, and action definition. Exact
rules therefore require a one-time visual comparison in Trello Automation.

## Simplified Linguar model

Every automation is one sentence:

> When **trigger**, if **conditions**, then **actions**.

The UI keeps only five groups familiar to current Trello users:

1. **Rules** — react to a job, stage, division, requirement, comment, or sync event.
2. **Schedule** — daily, weekday, weekly, or configured-time review.
3. **Deadlines** — due soon, overdue, follow-up due, or inactive too long.
4. **Job buttons** — a deliberate action on one job, such as Request closeout.
5. **Board buttons** — a deliberate action on the current filtered group.

Conditions may use franchise, division, job type, stage, carrier, tag, assignee,
priority, requirement state, inactivity, and deadline. Actions may move a stage,
assign work, add a tag or log entry, create requirements, set a due date, notify,
complete a division, archive a job, or mirror an approved change to Trello.

## Safe rollout

- **Review:** Rule is visible but disabled. Compare it with the Trello behavior.
- **Shadow:** Evaluate real events and log the proposed result without changing jobs.
- **Own:** Linguar performs the action. Trello mirrors it only while the adapter is on.

Rules use an event key so a retry cannot run the same rule twice. Activation is
admin-only. Closeout and Closed remain admin-controlled. Every run is logged.

## First drafts

- Prepare next-stage requirements and carry unfinished requirements forward.
- Flag overdue assigned work and escalate after a delay.
- Let a user request division closeout; require admin confirmation.
- Produce one weekday stalled-job review instead of many noisy alerts.
- Mirror reviewed Linguar changes to Trello during the transition.

## One-time Trello review checklist

For each current Butler item, record:

- board and automation name;
- type: rule, schedule, deadline, card button, or board button;
- exact trigger and all conditions;
- exact actions in order;
- whether it changes another board or card;
- who receives a notification;
- whether Linguar already owns the same result;
- Keep, Combine, Replace, or Retire decision.

Duplicate notification-only rules should normally be combined. Rules that only
compensate for a Trello limitation should be retired once Linguar owns that data.
