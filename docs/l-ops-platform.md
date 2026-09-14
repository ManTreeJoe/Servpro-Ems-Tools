# L OPS platform / EMS Tools coordination

Status: September 14, 2026.

Read the [full L OPS agent guide](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/README.md) before transferring features. It covers web CRM, Expo phone/iPad app, architecture, shared data, roles, run/visit crew assignments, media, documents, forms/signing, build commands, tests and remaining work.

- [Product decisions](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/product.md)
- [Architecture](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/architecture.md)
- [Builds and validation](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/builds.md)
- [Data and permissions](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/data-and-access.md)
- [Current status](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/status.md)
- [Transfer protocol](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/cross-repo.md)
- [Local intake mapping](intake-parity.md)

## EMS Tools remains a business-workflow reference
`new_loss_intake.py` has mature carrier intake parsing and template/folder/CompanyCam workflows. The new web intake now has corresponding contact, loss, claim/policy, adjuster and property/notes fields. Its parser fills explicit recognized labels for review; external provisioning and fallback parsing are not fully ported.

The user wants useful features to move in both directions. Shared domain contracts and fixtures should stay compatible, while Python desktop and TypeScript web/native rendering remain platform-specific. Tech assignments belong to dated runs/visits; permanent job contacts and Lead Tech staff designation are separate.

## No automatic DB merger
The legacy DB and new platform DB are not yet one database. Do read-only comparisons, agree stable IDs and source-of-truth/conflict rules, and build a reversible migration before shared writes. Avoid destructive changes to the working legacy app.

## Publication caveat
This is a documentation snapshot. Some new-platform code is still local/uncommitted; the mobile repo has no remote yet. Verify the actual source revision and migration state before assuming a described feature is available from GitHub or deployed. No production release is implied by these notes.
