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
A dated structured record of scheduled or completed work, findings, crew, equipment, and next steps for a Job or Division.
_Avoid_: Snapshot, comment

**Snapshot**:
A point-in-time report generated from selected Job Log Entries. It is an output, not a separate history.
_Avoid_: Job Log

**Requirement**:
A stage-aware obligation that controls readiness and retains its status, evidence, ownership, and history.
_Avoid_: Checklist item

**Checklist Item**:
A task grouped by responsibility that can provide evidence for a Requirement but does not replace it.
_Avoid_: Requirement

## External systems

**Division Card**:
The temporary Trello representation of one Division. Linguar Hub owns the Job relationship and operational state.
_Avoid_: Job, source of truth

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
