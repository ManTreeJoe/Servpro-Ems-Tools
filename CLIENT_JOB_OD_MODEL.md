# OD-Backed Client and Job Model

Status: Trial-first architecture rule.

## Canonical hierarchy

```text
Client
└── Job / claim / property unit
    ├── EMS
    ├── Contents
    └── Recon
```

Each division has its own stage, requirements, assigned users, comments, Job Log view, checklist, Trello card, photo-report context, and closeout state. Contacts, claim identity, address, customer history, and explicitly shared documents belong above the division.

## Source responsibilities

| Source | Owns |
|---|---|
| OD job folders | Client/job hierarchy and durable job documents |
| Linguar Hub database | Stable IDs, aliases, relationships, workflow state, requirements, contacts, activity history, and sync state |
| Trello | Temporary board/card adapter and external evidence while migration continues |
| CompanyCam | Photo/project adapter |
| DocuSign | Signature adapter; signed files return to OD |

OD identifies where work belongs. The database indexes that structure and adds workflow metadata; it must not invent a competing folder hierarchy. Trello never owns the client/job relationship.

## Folder interpretations

### Simple client with one job

```text
Rose, Jasmin/
└── EMS/
    ├── DOCS/
    └── PICS/
```

The client root is also an implicit first job. No artificial `1st Claim` folder is required unless a later claim makes separation necessary.

### One job with multiple divisions

```text
Acosta, Oscar & Kathleen/
├── EMS/
├── CONTENTS/
└── RECON/
```

This is one client and one job with 3 division workspaces—not 3 clients and not 3 unrelated jobs.

### Umbrella client with child jobs

```text
Aperto Property Management/
├── Tres Lagos - Unit 3208 - 8.13.26/
│   └── EMS/
└── Tres Lagos - Unit 6204 - 8.17.26/
    └── EMS/
```

The property-management company is the client. Each unit/work order is a job. A job may then contain EMS, Contents, and Recon.

### Additional claims

An existing root-level job remains the implicit first claim. Later `2nd Claim`, dated claim, unit, site, or work-order folders become child jobs. If the first job is deliberately promoted into `1st Claim`, all saved folder pins must be repointed atomically.

## Recognition rules

Division aliases normalize as follows:

- `EMS`, `Mitigation`, and the legacy water/fire job shell → `EMS`
- `CONTENTS` and `Contents` → `CONTENTS`
- `RECON` and `RECONSTRUCTION` → `RECON`

Folders such as `DOCS`, `PICS`, `Photos`, `Receipts`, `Field Docs`, and generated reports are containers or evidence, not jobs.

An immediate child beneath a client is a job when it represents a claim, property/site, unit, tenant, or work order. The existing `job_folders` module remains the recognition seam; callers should not reimplement these rules.

## Clients screen

Clients is the durable directory across years and active/closed work. One client row opens:

- Contacts and contact roles
- All jobs/claims/units
- Active and archived divisions
- Addresses and aliases
- Claim history
- Shared documents

Division filters answer “which clients have this kind of work?” They do not change the selected division inside a job.

## Jobs screen

Jobs is active operational work. Each board card represents one job/claim and summarizes which divisions are involved. Opening a card exposes a permanent division switch:

```text
💧 EMS   📦 Contents   🔨 Recon   ＋ Add Division
```

Switching divisions changes division-owned data without closing the card. Shared client/job facts remain stable.

## Identity and conflict handling

- Use stable database IDs for Client, Job, and Division records.
- Store OD paths as locators, not primary IDs; paths can move or vary by Windows user.
- Match known folders by normalized relative path beneath the configured franchise root.
- Claim number is a strong job link but not the sole identity because self-pay and commercial work may not have one.
- A Trello card with an existing claim number should propose the matching job; ambiguous matches require review.
- Preserve both conflicting changes and require resolution rather than silently overwriting.
- Renames update aliases and relative paths while retaining history.

## Migration order

1. Keep the Job Workspace mounted and patch sections in place.
2. Index OD into stable Client, Job, and Division records without moving folders.
3. Show reviewable matches and conflicts.
4. Activate the new Clients directory per franchise.
5. Make Jobs read active work from the shared index, using Trello as an adapter.
6. Move requirements, comments, checklists, and stages fully into Linguar Hub.

No automatic folder moves or bulk renames occur during indexing. Those require a reviewed migration action.
