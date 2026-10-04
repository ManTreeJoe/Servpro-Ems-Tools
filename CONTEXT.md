# Linguar Hub Operations

Linguar Hub organizes restoration work from the lasting customer relationship down to the individual periods of work performed. These terms are the shared language for Main, Trial, L OPS, and future mobile/browser clients.

## Work hierarchy

**Client**:
A person or organization for whom the company performs work across one or more losses, claims, properties, units, or work orders.
_Avoid_: Job, card, claim

**Job**:
One loss, claim, property unit, or work order belonging to a Client. A Job can involve multiple Divisions.
_Avoid_: Client, Trello card

**Division**:
An EMS, Contents, or Recon stream of work within a Job, with its own stage, requirements, checklist, assignments, comments, and closeout.
_Avoid_: Job type, global mode

**Work Period**:
A tracked span of responsibility within a Division, including pauses, handoffs, completion, and reopening.
_Avoid_: Job, stage

## People and records

**Contact**:
A reusable person connected to a Client and selected for a Job by purpose, role, and communication permission.
_Avoid_: User

**User**:
A person authorized to operate Linguar Hub within one or more franchises and roles.
_Avoid_: Client, contact

**Job Log Entry**:
A dated structured record of scheduled or completed work, findings, crew, equipment, and next steps for one Board Placement. Entries written before Board Placement ownership existed remain with the primary Division Card.
_Avoid_: Snapshot, comment

**Job Facts**:
The canonical customer, contact, property, claim, payer, and loss information for one Job. Every Board Placement for that Job displays the same Job Facts.
_Avoid_: Card description, placement activity

**Placement Activity**:
Comments, checklists, and Job Log Entries belonging to one exact Division Card. Placement Activity may differ between WIP, Estimating, Logs, Billing, or other Board Placements for the same Job.
_Avoid_: Job Facts, shared customer record

**Snapshot**:
A point-in-time report generated from selected Job Log Entries. It is an output, not a separate history.
_Avoid_: Job Log

**Requirement**:
A stage-aware obligation that controls readiness and retains its status, evidence, ownership, and history.
_Avoid_: Checklist item

**Checklist Item**:
A task grouped by responsibility that can provide evidence for a Requirement but does not replace it.
_Avoid_: Requirement

## Reusable rules

**Job Profile**:
An admin-managed set of default Requirements selected by payer type, carrier/client, loss type, and Division. Applying a Job Profile copies its Requirements onto the Job so later profile edits do not silently rewrite work already underway.
_Avoid_: live job, Trello template, checklist

**Profile Match**:
A Job Profile whose specified selectors match a Job. An unspecified selector means “Any”; when more than one profile matches, the most-specific match is presented first.
_Avoid_: automatic overwrite

**Applied Profile**:
The immutable snapshot of a Job Profile copied onto one Job, including its name, selectors, Requirements, and application time.
_Avoid_: pointer to the current profile

## External systems

**Division Card**:
One synchronized Trello representation of a Division in a particular work queue. A Division may temporarily have several linked cards with the same shared Job information—for example WIP and Estimating—while each card keeps its own queue-specific placement and work state.
_Avoid_: Job, source of truth

**Board Placement**:
A Division Card's presence in one external board and lane for a particular responsibility or handoff. Moving, completing, or closing one Board Placement does not implicitly remove another placement for the same Division.
_Avoid_: Duplicate job, Division stage

**External Mirror**:
A provider-specific representation of selected Linguar Hub information. It keeps the provider's permanent identifiers and sync state but never becomes the identity or complete record of a Client, Job, or Division.
_Avoid_: Master record, duplicate job

**Sync Operation**:
A durable request to publish one committed Linguar Hub change to an External Mirror. Retrying the same operation must not create a second card, comment, checklist item, or movement.
_Avoid_: Save, direct API call

**Sync Conflict**:
Two different changes to the same mirrored fact after the last shared version. Both values are retained until an authorized user selects the operational value.
_Avoid_: Sync error, latest wins

**Job Folder**:
The durable document location associated with a Job. Its path is a locator and may differ by machine or user.
_Avoid_: Job identity

**Franchise**:
An organization scope that owns Clients, Jobs, users, permissions, and configuration; authorized users may switch between franchises.
_Avoid_: Division
