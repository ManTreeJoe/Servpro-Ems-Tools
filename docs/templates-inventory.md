# Template and form storage inventory

Inspected 2026-11-19. This is a **code-only inventory**, not a database export or a migration. No application modules were imported or executed, no database connections were opened, and neither `api.oneloss.work` nor the demo database was contacted. SQL below was read, never executed.

## Source and interpretation

The inspected source is the existing `main-stability-hotfix` working tree, branch `handoff/paperclip-source-20261003`, HEAD `bb92f21`, **including its uncommitted and untracked application files**. References are workspace-relative `file:line` locations in that inspected tree. They are not assertions about the deployed release. This documentation-only branch is based on `origin/main` (`93f0835`); some referenced local features are not present on that base. No application changes have been copied into this PR.

“Franchise” is represented by `department` in these modules. `division` means EMS / Contents / Recon, a different dimension. `Any` division is not a global-franchise flag. Database row counts are **unknown** unless explicitly stated otherwise; built-in definition counts and query limits are not database counts. Access observations describe the checked-in/local SQL and callers, not independently verified server policies.

## Database-backed reusable content

| Content | Table / field | Scope | Count visible in code |
| --- | --- | --- | --- |
| Initial / post-inspection / contents note templates | `public.job_note_templates` | Franchise (`department`), then division | Unknown DB count; 3 code fallback definitions; no seed INSERT in its migration |
| Job paperwork / requirement profiles | `public.job_profiles` | Franchise (`department`), payer, carrier/client, loss type, division | Unknown DB count; 29 separate JSON starter definitions, not automatically 29 DB rows |
| Property-manager template references and naming defaults | `public.jobs.metadata_json.property_manager_profile` | Stored on account/job rows with department; not a global template table | Unknown DB count; 22 code seed records |

### Initial note templates — `public.job_note_templates`

Schema: `supabase/migrations/20260921183000_job_note_templates.sql:3`.

- Read: `initial_note_templates.py:63` (`list_templates`), REST GET at `initial_note_templates.py:72`. Selects `*`, orders `sort_order,name`, optionally filters uppercase `department`, filters `active=true` by default, then accepts the requested division or `Any` in Python.
- Fields consumed/returned: `template_id`, `department`, `name`, `division`, `body`, `active`, `sort_order`. Because the request selects `*`, schema audit fields also travel in returned records: `created_by`, `updated_by`, `created_at`, `updated_at`.
- Write: `initial_note_templates.py:87` (`save`). Existing non-builtin IDs PATCH at `initial_note_templates.py:105`; new/builtin IDs POST at `initial_note_templates.py:112`. Body includes `department,name,division,body,active,sort_order,updated_by`; inserts add a new UUID `template_id` and `created_by`. Timestamps default in SQL. No application DELETE call or external caller of this save function was found; SQL grants admin DELETE, which does not establish a wired UI.
- Web reader: `pipeline_web.py:2063` exposes `initial_note_templates`; it calls the module at `pipeline_web.py:2068` using the active department. Composer request: `pipeline_web_assets/app.js:4586`. No corresponding initial-note administration writer was found in `settings_web.py`.
- Fallback: `initial_note_templates.py:13` defines 3 builtins. Missing-schema errors and an empty result after filtering fall back to code definitions (`initial_note_templates.py:57`, `initial_note_templates.py:79`). Other read errors propagate. These definitions are not seeded database rows.
- Boundary: RLS read is admin or department membership; writes require admin (`supabase/migrations/20260921183000_job_note_templates.sql:24`). Omitting a department filter can expose multiple authorized departments, not a separate global template namespace.

### Job profiles — `public.job_profiles`

Schema: `supabase/migrations/20260921174341_job_profiles.sql:6`.

- Read: `job_profiles.py:73` (`list_profiles`), GET at `job_profiles.py:81`, selecting `*`, optionally filtering department and active, ordered by department/name.
- Fields used by normalization, matching and application: `profile_id,department,name,payer_type,carrier_or_client,loss_type,division,required_items,active` (`job_profiles.py:41`, `job_profiles.py:150`, `job_profiles.py:181`). `required_items` is a JSON array of labels, **not PDF/form bytes or a storage object reference**. Schema also returns `source_profile_id,created_by,updated_by,created_at,updated_at`; `source_profile_id` is declared in SQL but not written by the inspected Python CRUD functions.
- Create/update: `job_profiles.py:85`; PATCH at `job_profiles.py:92`, POST at `job_profiles.py:97`. Writes normalized fields and `updated_by`; insert adds `created_by`; SQL supplies the ID and timestamp defaults.
- Activate/deactivate: `job_profiles.py:104`, PATCH at `job_profiles.py:107`, writing `active,updated_by` by `profile_id`.
- Delete: `job_profiles.py:116`, DELETE at `job_profiles.py:128`, filtered by both `profile_id` and `active=false`. It removes the library record, not an already-applied job snapshot.
- Admin web callers: `settings_web.py:424` lists profiles and JSON starters; `settings_web.py:439` saves; `settings_web.py:448` changes active status; `settings_web.py:458` deletes.
- Job-facing readers: `job_profiles.py:198` (`suggestions`), `job_profiles.py:233` (`available`); `audit_web.py:1802` obtains available profiles; `audit_web.py:1911` reloads active profiles before application. `section_profile_review.py:62` and `section_profile_review.py:150` load active department profiles for section review. `pipeline_web.py:2549` delegates profile application to the audit API.
- Application writer: `audit_web.py:1921` copies the profile through `apply_to_job`, then `ems_db.update_job`; section-specific application writes through `section_profile_review.py:69`. See the job metadata section below.
- Starter source: `job_profile_starters.py:6` reads `job_profile_sources.json` at line 7. Static JSON parsing found **29 source definitions**. It constructs inactive starter suggestions; displaying them does not itself POST database profiles. SQL contains no seed rows for this table.
- Boundary: RLS read is admin or department membership; writes require admin (`supabase/migrations/20260921174341_job_profiles.sql:34`). Empty department filters do not create global definitions.

### Property-manager naming/templates — `public.jobs.metadata_json`

This is reusable template-related configuration embedded in account records, not a dedicated forms table.

- Read: `property_managers.py:49` loops `ems_db.iter_jobs()` and extracts `property_manager_profile`. Supabase implementation: `ems_db_supabase.py:704`, GET via `_rows("jobs", select="*")` at line 710; `_job` decodes `metadata_json` at `ems_db_supabase.py:132`.
- Columns: `canon_key,display_name,department,metadata_json`. Nested profile keys: `company_name,template_card_id,template_card_name,naming_format,contact_name,contact_role,phone,email,notes,active,updated_at`; returned profile `id` is the job's canonical key (`property_managers.py:40`, `property_managers.py:82`). The reference does not contain the Trello template's full description/checklists/PDF.
- Write: `property_managers.py:73` (`save_record`), reading existing records through `ems_db.get_job`, preserving other metadata, and calling `ems_db.upsert_job` at `property_managers.py:98`. Supabase implementation starts at `ems_db_supabase.py:143`. Renames can also merge account/job records at `property_managers.py:103`.
- **Read-side write:** `property_managers.list_records` seeds missing records at `property_managers.py:61` by calling `save_record`, then reads again. `_SEEDS` contains **22** static records. Do not run this function merely to count templates during a read-only audit.
- Web: `settings_web.py:479` lists; `settings_web.py:487` saves and can optionally rename the corresponding **Trello** card at `settings_web.py:499`.
- Scope: save uses the active department (`property_managers.py:95`); listing uses all rows returned by the backend's authorized job iterator. Seed definitions are bundled code; persisted entries are not demonstrated to be globally shared.

## Database-backed job records that are not reusable templates

These belong in the inventory because Snapshot/forms workflows read and write them. Moving library definitions to files must not accidentally move or discard these records.

### Snapshot revisions — `public.job_events`

- Readers: `snapshot_revisions.py:20` (`list_revisions`), `snapshot_revisions.py:35` (`queue_status`); web history at `snapshot_web.py:1920`, queue status at `snapshot_web.py:1097`.
- Writer: `snapshot_web.py:1882` calls `snapshot_revisions.save_revision` (`snapshot_revisions.py:46`), which appends an event at `snapshot_revisions.py:69`.
- Supabase transport: `ems_db_supabase.py:1417` (`log_event`, POST at line 1431); `ems_db_supabase.py:1434` (`list_events`, GET via `_rows` at line 1447).
- Columns: `id,canon_key,event_type,event_at,payload_json,actor`. Event type is `snapshot_revision` (`ems_db_common.py:158`). JSON includes `snapshot_id,revision,status,created_at,job,data,rendered_text,pdf_path,card_id,source_refs` (`snapshot_revisions.py:56`). `pdf_path` is a reference to the generated file, not embedded PDF bytes or a blank template.
- Scope/count: per linked job, inheriting job authorization; no global template library. Unknown rows. Default history request is 100, backend clamp is 1–1000; those are read limits, not totals.

### Applied form profiles and confirmations — `public.jobs.metadata_json`

- Profile definitions are copied to `applied_job_profiles` by `job_profiles.py:181` / `job_profiles.py:220`; copied fields include `profile_id,profile_name,applied_at,selectors,requirements`. Each requirement has `key,label,division,introduced_stage,owner,importance`.
- Readers: `job_profiles.py:198`, `job_profiles.py:233`, `section_profile_review.py:87`, `job_progress.py:179`. Job decoding: `ems_db_supabase.py:132`.
- Writers: `audit_web.py:1921` / `audit_web.py:1922` use `ems_db.update_job` (`ems_db_supabase.py:247`); `section_profile_review.py:23` prepares section metadata and line 69 PATCHes the exact job. It also saves `section_profile_facts`.
- Form confirmation writer: `pipeline_web.py:2306` delegates to `form_confirmation.py:51`; PATCH at `form_confirmation.py:68`. It writes `form_confirmations.EMS` and `form_confirmation_history`, including file fingerprint/version and actor/time, not blank form definitions. `form_confirmation.py:31` reads the context and existing job metadata.
- Columns used for these writes/guards: `job_id,canon_key,department,metadata_json`; confirmations select back `job_id`. Scope is the linked job/franchise; DB count unknown. Arrays/history lengths vary by job.

### Run-document history — saved instances, not DOCX templates

- Tables: `public.run_history_documents`, `public.run_history_rows`, plus audit table `public.run_history_link_changes`. Schema: `supabase/migrations/20261005171816_run_document_history.sql:3`, line 11 and line 20.
- Document fields: `id,department,run_date,source_digest,filename,snapshot,imported_by,imported_at`. JSON snapshot preserves `paragraphs,tables,blockers,section_labels` (`run_history_store.py:37`). Row fields: `id,document_id,source_index,raw_text,section,struck,job_id,revision`. Joined reads also request `jobs(display_name)`.
- Readers: `run_history_store.py:60` GETs documents at line 64; `run_history_store.py:74` GETs rows at line 77. Web callers: `run_doc_editor_web.py:31`, line 40.
- Import writer: `tools/import_run_history.py:34` calls `import_run_history`; SQL inserts document/rows at migration lines 44 and 54. Link writer: `run_history_store.py:86` calls `link_run_history` at line 98 or `link_schedule_card_history` for card-only jobs. Web delegation: `run_doc_editor_web.py:49`. `link_run_history` updates `job_id,revision` and records `id,row_id,old_job_id,new_job_id,actor,occurred_at,revision` in the audit table (migration lines 20, 69).
- Scope/count: department-filtered document history with dependent row access; unknown persisted counts. 1000-document and 500-row page limits with a 2500-row display bound are request safeguards, not inventory counts. Schedule visit records are operational scheduling data, not reusable form definitions.

### Imported job documents — Supabase Storage pilot

- Tables: `public.job_documents` (`file_id,job_id,relative_path,created_by,created_at`); `public.job_document_versions` (`version_id,file_id,version_order,sha256,byte_size,content_type,source_modified_at,provider,bucket,object_key,created_by,created_at`); `public.job_document_receipts` (`version_id,verified_by,verified_at`). Schema: `supabase/migrations/20261002185042_document_storage_pilot.sql:1`.
- Writer call chain: `document_import.py:168` prepares, uploads and confirms at line 177 through `document_store.py:70`, line 85 and line 104. RPCs are `prepare_job_document` and `confirm_job_document`; prepare receives job ID, relative path, hash, size, type and modification time.
- Binary reader: `document_store.py:100`; GET `/storage/v1/object/authenticated/job-documents/<file_id>/<version_id>`. Binary writer at `document_store.py:85`. Those bytes live in bucket `job-documents`, not relational template rows. `document_store.py:64` reads enabled `document_pilot_jobs.job_id` for authorization; pilot-user/job tables are allowlists, not forms.
- Scope/count: per authorized job/pilot user, not a reusable blank-template catalog. Unknown rows/objects. This is evidence of a code path, not evidence that the pilot is enabled or populated on the current server.

## Sources already outside Supabase

| Workflow | Actual source and columns/format | Readers / writers | Count and scope |
| --- | --- | --- | --- |
| Blank Snapshot PDF | Config key `snapshot_template`, filesystem PDF | `snapshot_logic.py:31` resolves config; `snapshot_logic.py:1484` / line 1485 reads PDF; `snapshot_gui.py:54` reads config; legacy CLI `fill_snapshot.py:114`. `settings_web.py:22` / line 122 exposes the path, `settings_web.py:513` saves settings. | One configured path per department override (`config.py:110`), not a DB row. Current web generation calls the code-generated renderer `snapshot_logic.render_snapshot` (`snapshot_logic.py:1526`) at `snapshot_web.py:1873`; the method's older docstring is not proof it uses a blank PDF. |
| Built-in job forms | Bundled `form_templates/*.pdf`; field/default maps in Python | `job_forms.py:5`, `job_forms.py:51` (PDF reader), `job_forms.py:62` (catalog), `job_forms.py:80` (render); web API load/export at lines 163 / 230; exposed via `resources_web.py:24` and `job_settings_api.py:40`. | **10** IDs at `job_forms.py:6`: `atp,cif,cos,cer,statefarm_atp,statefarm_atr,statefarm_warranty,selfpay_contract,selfpay_cancel,liability_release`. Shared installed assets; franchise/job facts fill fields. This counts configured IDs, not verified files or DB rows. |
| Custom blank PDF/form mappings | **Local SQLite** `paths.DATA_DIR/form_builder.sqlite3`, table `templates(id,title,pdf BLOB,fields TEXT,revision)`; `fields` is JSON | `form_builder.py:24` creates/opens schema; SELECTs at lines 57 / 69; upload INSERT at line 81; mapping UPDATE at line 114; builtin-copy INSERT at line 241. API methods at lines 231, 246, 254, 266, 275. Catalog also used by `job_forms.py:62` / line 80 and `resources_web.py:49`. | Unknown local rows. No department column: shared across departments using the same local data profile, **not** a globally synchronized server library. Local DB connection can create schema; it was not opened for this inventory. |
| Job profile starter suggestions | Bundled `job_profile_sources.json`, read by `job_profile_starters.py:7` | `settings_web.py:424`; eventual explicit save uses `job_profiles.save` | **29 JSON definitions**, separate from persisted franchise rows. |
| Technician field-note forms | Python `_TEMPLATES` in `field_notes.py`; JSON-like field definitions | `field_notes.py:102` filters/shapes definitions, line 141 builds submitted text; `operations_hub.py:320`, `operations_web.py:57`, `operations_portal.py:143` expose them. | **3 code definitions**, filtered by division; no DB template table. Submitted entries are job activity, not definitions. |
| Initial inspection email | Fixed text composer in Python | `initial_email.py:126` (`compose`); audit API, delegated by `snapshot_web.py:772` | No DB rows; franchise/customer values interpolate into code text. |
| Daily run DOCX / layout | Files under configured `runs_dir`; existing document used to preserve layout | `run_doc.py` locates/parses files; `run_doc_roundtrip.py:108` / line 126 opens optional `template_path`, line 182 writes using the current document as template; `run_doc_editor.py` edits document structure; `run_doc_editor_web.py` exposes editor and DB-backed schedule/history separately. | Unknown files; configured per department/user folder. A document used as a layout template is not a Supabase template row. |
| New-loss Trello templates | Trello board/list/card API, not the inspected Supabase template tables | `new_loss_intake.py:203` lists, lines 214 / 221 GET lists/cards through `trello_client._call`; `new_loss_intake.py:549` creates using the selected card. `audit_web.py:3638`, `pipeline_web.py:1015` expose it. `trello_client.py:39` is direct Trello transport. | Unknown template cards; active franchise WIP board, `isTemplate`, open-card/list checks. **Do not run intake to inventory it.** Other UI reads can use Supabase Trello mirrors (`trello_mirror_reader.py:35`, `mirror_board_transfer.py:29`), but this intake listing explicitly uses direct Trello calls. |
| Isolated WO intake choice | Code-only test choice | `isolated_wo_intake.py:23`, selected through `pipeline_web.py:1015` | One static test template choice. Its create/read RPCs are work records, not a template library. |

No desktop caller of a Supabase `form-templates` bucket was found. Server-created buckets and their current contents cannot be inferred from this source inspection. Authentication invitation/reset email templates are service configuration, separate from these job templates; no app-table template CRUD was found for them in `supabase_client.py`.

## Shared transport and coverage notes

- `supabase_client.py:510` is generic REST transport, routing to `/rest/v1/<table>` at line 532; RPC transport starts at `supabase_client.py:549`. It does not itself define a hidden Snapshot/form catalog. This inventory follows callers rather than treating transport as a template store.
- `ems_db_supabase.py` stores ordinary jobs and job-event payloads. Its `snapshot` backup/export function (`ems_db_supabase.py:1611`) is unrelated to the user-facing Snapshot PDF. `_SNAPSHOT_TABLES` at line 1604 does **not** include `job_note_templates` or `job_profiles`; it should not be used as evidence that a template-library export is complete.
- Search covered application Python, all `*_web.py` bridges, relevant browser assets, SQL migrations and related import tools. Tests were checked for references, not executed. No runtime behavior, permissions, seed content, migrations, deployment settings or application files were changed.
- Future file extraction needs to distinguish blank definitions, department-specific selectors, audit/identity fields, copied per-job requirements, and local SQLite PDF/mapping revisions. This document authorizes none of those changes. Live counts, actual objects/files, deployed policies, and a final extraction manifest remain unverified by design.

## Search proof

These are the `rg` searches used to discover and trace call sites (run from the inspected source root; forward slashes are accepted by `rg` on Windows). Outputs contain source locations, not database records. Narrow source reads and static AST/JSON parsing supplemented these searches; parsing counted only the builtin arrays/JSON, without importing application modules.

```powershell
rg -n -i 'template|form' initial_note_templates.py ems_db_supabase.py supabase_client.py snapshot_web.py run_doc.py run_doc_editor_web.py resources_web.py job_forms.py job_settings.py job_settings_api.py
rg -l -i '\btemplates?\b|\bforms?\b' -g '*.py' -g '*.sql' -g '!output/**' -g '!build/**' -g '!dist/**' -g '!node_modules/**'
rg -n 'initial_note_templates|job_profiles|form_builder|job_note_templates|template_id|template_body|template_json|form_templates|snapshot_template' -g '*.py' -g '*.sql' -g '!output/**' -g '!build/**' -g '!dist/**' -g '!node_modules/**'
rg -n -i 'create table.*(template|form|resource|document)|\b(template_id|template_body|template_json|pdf_bytes|pdf_data|form_schema)\b' supabase -g '*.sql'
rg -n 'initial_note_templates|job_note_templates|admin_note|note_template' -g '*.py' -g '*.js' -g '*.html' -g '*.sql' -g '!output/**' -g '!build/**' -g '!dist/**' -g '!node_modules/**' -g '!tests/**'
rg -n 'template|form' -g '*_web.py' -g '!output/**' -g '!build/**' -g '!dist/**' -g '!node_modules/**'
rg -n 'list_profiles|apply_to_job|upsert_job|applied_job_profiles' audit_web.py section_profile_review.py job_profiles.py
rg -n 'def |ems_db\.|PROFILE_KEY|metadata|department|template_card' property_managers.py
rg -n 'property_managers' -g '*_web.py' -g '*intake*.py'
rg -n 'render_snapshot|save_revision|write_run_doc|run_history|template' snapshot_web.py run_doc_editor_web.py run_doc_editor.py run_doc_roundtrip.py
rg -n 'snapshot_revisions|list_revisions' snapshot_web.py
rg -n 'def rest|def rpc|rest/v1|def upsert_job|def log_event|def list_events|metadata_json' supabase_client.py ems_db_supabase.py
rg -n 'form_builder.sqlite|CREATE TABLE|SELECT|INSERT|UPDATE' form_builder.py
rg -n 'import_run_history|run_history_documents|run_history_rows' schedule_store.py run_doc_editor_web.py supabase/migrations/20261005171816_run_document_history.sql
rg -n 'import_run_history|document_store|prepare_job_document' -g '*.py' -g '!output/**' -g '!tests/**' -g '!build/**' -g '!dist/**'
rg -n 'document_store|\.prepare\(|\.confirm\(|job_documents|job_document_versions' -g '*document*.py' -g '!output/**' -g '!tests/**' -g '!build/**' -g '!dist/**'
rg -n 'template|rest\(|rpc\(' isolated_wo_intake.py
rg -n 'def |hub_trello_read|mirror|job_documents|job_note_templates|run_history|form_file|rest\(' new_loss_intake.py trello_mirror_reader.py trello_client.py form_confirmation.py run_history_store.py document_store.py initial_note_templates.py job_profiles.py settings_web.py
```
