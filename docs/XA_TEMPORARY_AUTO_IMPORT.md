# XA temporary assignment intake backlog

**Status:** queued after the shared Client → Claim → Division migration  
**Target:** internal Windows Linguar Hub  
**Replacement:** official Verisk XactAnalysis events when access is provisioned

## Non-negotiable safety contract

- An imported message creates an **Import Draft**, never a live Job.
- An authorized Front Ops user must approve every new, related, or merged Job.
- Linguar Hub never stores Microsoft, Xactimate, or XactAnalysis passwords and
  never bypasses MFA, CAPTCHA, access controls, or rate limits.
- Email HTML is parsed as inert content. Remote content is not loaded and
  executable, script, or macro attachments are blocked or quarantined.
- Production messages, extracted customer data, attachments, and credentials
  stay out of Git and ordinary application logs.
- CompanyCam projects and downstream tasks are not created before approval.

## Module seam

All sources satisfy one small interface:

```text
AssignmentImportSource.read() -> SourceAssignment
                         ↓
             parse -> match -> Import Draft
                         ↓
                authorized approval
                         ↓
          Client / Claim / XA assignment records
                         ↓
               post-commit outbox work
```

Initial adapters:

1. Local `.eml` file selection, drag/drop, and an optional approved watch
   folder.
2. Microsoft Graph reading from an authorized Outlook `XA Intake` folder.
3. Official Verisk events later, using trace and assignment identifiers for
   idempotency.

Attended capture is not part of the initial build. It may be considered only
if email/export coverage is inadequate and Verisk confirms it is allowed.

## Required records

### Import Draft

Store company/franchise, source type, source identifiers and hashes, received
time, sender/subject, raw-source storage reference, XA and claim identifiers,
carrier/profile/type, insured and property facts, contact fields, instructions,
loss details, warnings, candidates, review status, reviewer, decision, and the
target Job. Preserve raw and normalized values separately.

### Import Attachment

Store draft ID, original name, content type, size, SHA-256, protected-storage
reference, malware scan status, and review status. Never use the filename as
the identifier.

### Candidate Match

Store the candidate Job, match type, score, and human-readable reasons. Match
types are exact assignment, same claim/property, same claim, same
property/date, and possible contact.

## Matching order

1. Same source SHA-256 or Internet Message ID: already ingested.
2. Same normalized XA/assignment ID: exact assignment candidate.
3. Same claim and property with different XA ID: related assignment candidate.
4. Same claim with a different property/unit: warning, never auto-merge.
5. Same property and loss date with a different claim: event candidate.
6. Similar name, email, or phone only: contact candidate, never auto-merge.

The temporary importer never automatically merges a candidate.

## Front Ops review

Show the source and received time; sender and subject; insured/customer;
property; claim and XA IDs; carrier and representative; loss date/type/cause;
contacts; instructions; safe attachment state; warnings; candidate Jobs and
match reasons; and a safe original-source reference.

Actions:

- Approve as new Job
- Add as related assignment
- Merge duplicate/update assignment
- Edit extracted fields
- Reject/ignore

Every decision creates an audit entry. A merge into a live Job requires a
second confirmation.

## Approval transaction

Inside one database transaction:

1. Recheck idempotency.
2. Create or select the master Job.
3. Create the claim/XA assignment association without overwriting siblings.
4. Connect the Client/contact and property records.
5. Save the imported communication and approved attachment records.
6. Apply the reviewed Job Profile and workstreams.
7. Create initial Front Ops tasks and the audit entry.
8. Mark the draft approved with reviewer and decision.
9. Write outbox records for CompanyCam and other external setup.

No external request runs inside the transaction.

## Delivery gates

### Phase 1 — parser and persistence

- Add draft, attachment, candidate, decision, and outbox persistence.
- Port the proven `.eml` parser behind the source interface.
- Fingerprint complete sources and preserve Internet Message IDs.
- Preserve unknown labels and multiline content.
- Use synthetic, non-customer fixtures in Git.

### Phase 2 — pure matching

- Implement the ordered matching rules against the shared workspace contract.
- Distinguish duplicate assignments from related assignments under one Job.
- Keep reasons visible and make every result advisory.

### Phase 3 — review and approval

- Add the Front Ops queue and detail view.
- Add authorization, confirmations, atomic approval, audit history, retries,
  and an exception queue.

### Phase 4 — local acceptance

- Run the approved local sample collection without committing it.
- Verify core-field extraction, multiline content, address cleanup, malformed
  character handling, idempotency, authorization, rejection, double-click
  safety, and outbox failure recovery.

### Phase 5 — Microsoft Graph source

- Use delegated OAuth for the first pilot unless IT approves narrowly scoped
  application access.
- Read only the selected mailbox/folder with the minimum permission.
- Track Graph and Internet Message IDs without moving, deleting, replying to,
  or changing read state.
- Reconcile periodically and display last-success and integration health.

### Phase 6 — official Verisk source

- Consume supported assignment and lifecycle events.
- Use event trace IDs for idempotency and official assignment IDs for matching.
- Download authorized expiring attachments promptly into protected storage.
- Retain the temporary importer as reconciliation until official delivery is
  proven reliable.

## Definition of done

- The approved sample set imports without parser crashes.
- Core fields are extracted while missing optional fields remain warnings.
- Exact duplicates and related assignments are visibly different.
- No unapproved or rejected draft creates a Job, CompanyCam project, profile,
  requirement, or task.
- Approval is authorized, atomic, idempotent, audited, and retry-safe.
- Sensitive production data is absent from Git and normal logs.
- The UI clearly labels this as temporary pending official Verisk access.
