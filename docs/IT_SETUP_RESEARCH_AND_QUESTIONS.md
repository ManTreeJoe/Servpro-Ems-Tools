# Linguar Hub — IT setup decisions and questions

Prepared September 1, 2026. This is the working technical brief to send to the IT provider before a setup meeting.

## The short recommendation

Use one system for each kind of information:

| Responsibility | Recommended owner | Why |
| --- | --- | --- |
| Clients, claims, divisions, stages, requirements, comments, KPIs, permissions, audit history | Linguar Hub in Supabase | This is the operational source of truth and remains searchable without Trello. |
| Photos, field evidence, photo reports, CompanyCam project links | CompanyCam | It is already designed for field capture, tagging, reports, and project photos. |
| Signed forms, contracts, estimates, invoices, and final PDFs | SharePoint Online document library | It provides version history, retention controls, recoverability, and Microsoft 365 permissions. |
| Email, calendars, and Teams notifications | Microsoft 365 through Microsoft Graph | One supported Microsoft integration surface with tenant-controlled permissions. |
| AI summaries and drafting | OpenAI Responses API through a private backend | The secret stays off user computers and the app can require human approval before writing anything. |
| Existing Trello cards | Read-only migration/reference connector | Keep evidence and links available while Linguar Hub takes over stages, requirements, and comments. |

Do not store the only copy of signed contracts in CompanyCam. CompanyCam is a strong photo and field-document system, but SharePoint is the safer long-term records system. CompanyCam currently offers a SharePoint integration that copies new projects, photos, videos, and files, but it does not backfill projects created before the integration is connected.

## Recommended architecture

1. The desktop app and web app use the same Linguar Hub API and the same Supabase project for production.
2. Microsoft Entra ID is the company identity provider. Users sign in with their SERVPRO Microsoft account.
3. Supabase Auth federates sign-in to Entra ID and issues the session used by Supabase Row Level Security. Avoid a second, independent website login.
4. Supabase stores structured text and metadata. It stores file IDs, URLs, hashes, document type, version, and retention state—not duplicate photo/PDF blobs unless a feature specifically requires it.
5. CompanyCam stores field photos and reports. A CompanyCam Application Key owned by the integration—not Nathan's personal token—handles the shared connection.
6. SharePoint stores durable documents. CompanyCam's SharePoint sync can copy new CompanyCam content to a controlled library; older projects need a one-time export/backfill process.
7. Microsoft Graph sends email, creates calendar events, and posts selected Teams notifications.
8. OpenAI calls run only from a protected backend. No OpenAI secret belongs in browser JavaScript, the desktop installer, or a user's settings file.
9. Heavy photo/report sync jobs run in an Azure Container Apps job or equivalent worker. Small webhooks and ordinary database actions can run in Supabase Edge Functions.
10. Keep separate development/trial and production Supabase projects, storage locations, API keys, and Microsoft app registrations.

## Decisions IT should confirm

These are the exact questions to ask during the meeting.

### Microsoft tenant and identity

- What is the exact Microsoft Entra tenant ID and primary verified domain for the SERVPRO users?
- Can IT create a single-tenant Entra app registration named Linguar Hub Production and a separate Linguar Hub Trial registration?
- Can sign-in be limited to active users in assigned Entra groups rather than every account in the tenant?
- Which Entra groups should map to Super Admin, Franchise Admin, Front Office, Field Technician, Estimator, and Read Only?
- Can IT provide the redirect URLs for the production website, trial website, desktop callback, and local developer callback?
- Will Conditional Access require MFA, compliant devices, a specific location, or an approved client app?
- Who owns removal of access when an employee leaves or changes franchises?
- Can Nathan remain the initial company Super Admin while franchise access is assigned through groups?

Recommended answer: one Microsoft login, single tenant, group-based access, MFA enabled, and no shared accounts.

### Supabase and the database

- Who owns the production Supabase organization, billing, and recovery contacts?
- Can IT create separate Trial and Production projects and prohibit production secrets from being used in Trial?
- Which region meets the company's data-location requirements?
- Can IT enable Row Level Security on every exposed table and review both allowed and denied test cases?
- Can the app use the current publishable key on clients while all secret/service keys stay only in backend secret storage?
- What backup target is required: daily backup only, Point-in-Time Recovery, and/or a separate scheduled database export?
- Who receives alerts for failed backups, failed webhooks, unusual sign-ins, and growing storage?
- How long must client, claim, job-log, audit, and deleted-user history be retained?
- Does the company require a legal hold or a documented deletion/disposition process?

Recommended answer: keep Supabase as the structured source of truth, use RLS, enable Point-in-Time Recovery if the plan permits, and keep an independent scheduled export. Supabase database backups do not back up external storage objects, so files need their own protection.

### SharePoint and document retention

- Which SharePoint site and document library will be the official job-document archive?
- Should every job use a fixed path such as Client / Claim / Division / Document Type?
- Can IT enable and verify version history for that library?
- What retention period applies to signed contracts, work authorizations, estimates, invoices, and final reports?
- Should signed documents receive a Purview retention label, a record label, or a normal retention policy?
- Who may edit, replace, delete, or restore signed documents?
- Should CompanyCam sync into the same official library or into an intake library that Linguar Hub later files?
- How will existing X-drive and OneDrive job folders be migrated, deduplicated, and reconciled?
- Can IT test recovery of one file, one deleted folder, and the full library before production launch?

Recommended answer: use a SharePoint team site/document library rather than one employee's OneDrive. Turn on versioning, set retention with IT/legal, and keep a claim ID in document metadata so moving a folder never breaks the job link.

### CompanyCam

- Which CompanyCam plan is active, and does it include Project Files, report templates, the API, and the Microsoft SharePoint integration?
- Can an Admin register a private Linguar Hub application and issue an Application Key with only the required permissions?
- What is the key expiration period, and who owns rotation before expiry?
- Which events/webhooks are available for projects, photos, photo tags, files, reports, pages, and checklists?
- Can the new API create and retrieve reports and documents, or must report creation remain in an embedded CompanyCam window?
- What rate limits, retry rules, payload limits, and webhook replay behavior apply?
- How are deleted projects, files, reports, and photos restored, and what are their retention periods?
- Can CompanyCam provide an account-wide export or only per-project photo downloads and project/checklist CSV exports?
- Does the SharePoint integration sync originals, edits/markups, videos, files, descriptions, tags, and timestamps?
- How should the existing CompanyCam projects be backfilled, since the built-in SharePoint sync only covers projects created after connection?
- Can the CompanyCam project ID and the Linguar Hub claim ID be stored on both sides to prevent duplicate matches?

Recommended answer: use an Application Key instead of a personal token; keep automatic SharePoint copies; use project/claim IDs rather than names as the permanent match. The legacy CompanyCam API ends September 1, 2027, so all new work must use the current Developer Portal API.

### Outlook, calendars, and Teams

- Which actions should be user-delegated and which must run unattended as the company?
- May Linguar Hub send from a shared mailbox such as operations@... rather than from Nathan's mailbox?
- Which shared calendars or dispatch calendars may the app read and update?
- Which Teams/team/channel should receive overdue, blocked, assignment, and closeout alerts?
- Does IT permit a Teams app installation, or should notifications start with email only?
- For application permissions, can IT scope mailbox access and Teams access to only the approved mailboxes/teams?
- What is the approval process for Microsoft Graph permissions and future permission changes?
- Who owns subscription renewal and failure monitoring for Graph webhooks?

Recommended answer: start with delegated permissions for actions a signed-in user triggers. Add narrowly scoped application permissions only for approved background automation. Choose either a Teams activity notification or a bot/channel message for each event so users do not get duplicates.

### Website and hosting

- What production hostname should be used, for example hub.companydomain.com?
- Who controls DNS and can add the verification and certificate records?
- Is Azure the required hosting provider, or may the static frontend use another approved host?
- Can IT create separate production and trial environments, secret stores, budgets, and alerting?
- Can Azure Static Web Apps host the frontend while Supabase remains the app authentication and data authority?
- Can Azure Container Apps Jobs run scheduled/event-driven CompanyCam sync, exports, and large report processing?
- What monitoring platform is approved for errors, performance, and uptime?
- What are the required recovery-time and recovery-point targets?

Recommended answer: Azure Static Web Apps for the light web frontend, Supabase for database/auth/API, and Azure Container Apps Jobs for heavier background work. Do not place large photo processing in a short-lived edge function.

### OpenAI / AI assistant

- May client names, claim data, photos, contracts, insurance details, and adjuster communications be sent to an external AI API?
- Which categories must be redacted before an AI request?
- Does the company require Zero Data Retention or Modified Abuse Monitoring eligibility?
- Can the company create and own a dedicated OpenAI API organization/project, service account, spend limit, and alert recipients?
- Which model/tool uses are approved: summarization, drafting, OCR/extraction, photo analysis, or action recommendations?
- Which actions must always require a human confirmation before the app changes a job, sends a message, or generates a final document?
- How long may Linguar Hub keep AI prompts, responses, citations, and reviewer decisions in its own audit log?
- Who reviews incorrect or unsafe AI output and disables the feature during an incident?

Recommended answer: use the OpenAI Responses API only through the backend, with a company-owned project/service account. Set store=false unless a feature genuinely needs OpenAI-hosted state. API data is not used for model training unless the organization explicitly opts in, but standard abuse-monitoring logs can be retained up to 30 days; confirm whether that is acceptable before any production client data is sent.

### Trello transition

- How long must Trello remain readable after Linguar Hub becomes the status owner?
- Should the integration be read-only immediately, or are any temporary writebacks still required?
- Which Trello data must be imported: boards, cards, list history, comments, attachments, checklists, members, labels, automation rules, and archived cards?
- What is the authoritative claim ID when card names differ or duplicates exist?
- What is the date for stopping new Trello automations and the date for final export?
- Who signs off that a board is fully reconciled before access becomes archive-only?

Recommended answer: read-only reference during transition, scheduled imports with conflict reporting, then a final immutable export. Linguar Hub owns new status, requirements, comments, and audit history.

## Information to bring to the meeting

- Microsoft tenant ID, verified domains, and intended production hostname.
- Names of every franchise and which staff need each franchise.
- Current Microsoft 365 license types and Purview/retention licensing.
- Supabase organization/project names, plan, region, and named owners. Do not email secret keys.
- CompanyCam plan, account owner, API access, current project count, and current SharePoint availability.
- Shared mailbox, dispatch calendar, and Teams destination names.
- Existing X-drive/OneDrive/SharePoint roots and approximate storage size/file count.
- Required document retention periods from management/legal/accounting.
- Recovery expectations: how much data loss is acceptable and how quickly service must return.
- A list of five real jobs that cover EMS only, Contents, Recon, combined divisions, commercial/self-pay, and property management.

## Proposed rollout

### Phase 1 — foundation

- Entra single sign-on through Supabase Auth.
- Production/trial separation.
- RLS and role/franchise permissions.
- Supabase backups and error monitoring.
- SharePoint document library, metadata, versioning, and retention decision.

### Phase 2 — operational connectors

- CompanyCam Application Key and project/claim ID mapping.
- CompanyCam to SharePoint sync for new projects.
- One-time historical CompanyCam and X-drive reconciliation.
- Microsoft Graph delegated Outlook/calendar actions.
- Trello read-only import and conflict report.

### Phase 3 — controlled automation

- Teams notifications and unattended Graph jobs where approved.
- Scheduled CompanyCam sync/report jobs.
- OpenAI assistant for summaries and drafts with human confirmation and audit history.
- Trello shutdown readiness report and final export.

## Acceptance tests IT should witness

1. A new user signs in with Microsoft and sees only the assigned franchises.
2. A disabled user loses access without an app reinstall.
3. The same claim opens correctly from a card name, client name, claim number, and CompanyCam project.
4. A requirement can be completed, blocked, marked not needed with a reason, and audited with the user's identity.
5. A photo added in CompanyCam connects to the correct claim and reaches the intended SharePoint location.
6. A signed form can be restored to a previous version and cannot be silently destroyed contrary to retention rules.
7. A failed webhook retries without creating duplicate updates.
8. Trial data cannot read or write production data.
9. A backup restore is demonstrated, not merely configured.
10. An AI-generated summary cites its source data and cannot send or change anything without the required approval.

## Research sources

- [CompanyCam custom integrations and current API](https://help.companycam.com/en/articles/15949273-building-custom-integrations-with-companycam-s-api)
- [CompanyCam to Microsoft SharePoint integration](https://help.companycam.com/en/articles/11385193-integrating-companycam-with-microsoft-sharepoint)
- [CompanyCam photo download/export](https://help.companycam.com/en/articles/6828429-how-to-download-save-photos-from-companycam)
- [CompanyCam project and checklist data export](https://help.companycam.com/en/articles/7047268-how-to-export-project-and-checklist-data)
- [CompanyCam photo trash recovery](https://help.companycam.com/en/articles/6971309-restore-items-from-project-trash)
- [CompanyCam Project Files](https://help.companycam.com/en/articles/8345636-uploading-and-managing-project-files)
- [CompanyCam reports](https://help.companycam.com/en/articles/7048115-creating-a-report)
- [Supabase Microsoft/Azure sign-in](https://supabase.com/docs/guides/auth/social-login/auth-azure)
- [Supabase database security and Row Level Security](https://supabase.com/docs/guides/database/secure-data)
- [Supabase API keys](https://supabase.com/docs/guides/getting-started/api-keys)
- [Supabase database backups](https://supabase.com/docs/guides/platform/backups)
- [Supabase Edge Function limits](https://supabase.com/docs/guides/functions/limits)
- [Microsoft Entra app registration](https://learn.microsoft.com/en-us/graph/auth-register-app-v2)
- [Microsoft Graph send mail](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0)
- [Microsoft Graph create calendar event](https://learn.microsoft.com/en-us/graph/api/calendar-post-events?view=graph-rest-1.0)
- [Microsoft Graph Teams activity notifications](https://learn.microsoft.com/en-us/graph/teams-send-activityfeednotifications)
- [Microsoft Graph webhook delivery](https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks)
- [Azure Static Web Apps authentication](https://learn.microsoft.com/en-us/azure/static-web-apps/authentication-authorization)
- [Azure Container Apps Jobs](https://learn.microsoft.com/en-us/azure/container-apps/jobs)
- [SharePoint and OneDrive retention](https://learn.microsoft.com/en-us/purview/retention-policies-sharepoint)
- [Microsoft 365 records management](https://learn.microsoft.com/en-us/purview/records-management)
- [SharePoint version history and restore](https://support.microsoft.com/en-us/sharepoint/documents-and-library/restore-a-previous-version-of-an-item-or-file-in-sharepoint)
- [OpenAI API data controls](https://developers.openai.com/api/docs/guides/your-data)
- [OpenAI project service accounts](https://developers.openai.com/api/reference/typescript/resources/admin/subresources/organization/subresources/projects/subresources/service_accounts/subresources/api_keys/methods/create)
