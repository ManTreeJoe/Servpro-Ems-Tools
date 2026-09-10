---
status: proposed
---

# Linguar Hub owns operational records and Trello mirrors them

Linguar Hub will be the canonical record for clients, jobs, divisions, requirements, stages, job logs, and permissions. Trello remains a transitional external mirror: Hub changes commit before a durable, idempotent sync operation is processed, while inbound Trello changes merge only against an unchanged synchronization base and otherwise create a visible conflict. This avoids two competing masters, supports offline/retry behavior, and allows Trello to be removed without changing job identity or history.

## Consequences

- All integration rows, links, queues, and conflicts must be franchise-scoped and protected by database authorization.
- Trello IDs remain useful provider identifiers but never identify a Client, Job, or Division.
- Trello outages cannot block or roll back valid Linguar Hub work.
- A provider write is successful only after an acknowledgement is stored; retries reuse the original operation key.
- Imported activity keeps its origin and author. Hub-owned entries remain editable under Hub permissions and project outward.
