# Demo file library and job paperwork — backend contract

Prepared November 23, 2026. Scope: demo only. The read-only server preflight confirmed
`platform_losses.id` as the job/loss identity and `foundation_franchises` /
`foundation_memberships` / `platform_admins` as demo's existing access model.
This is distinct from production Main's `public.jobs` and approval tables.
Do not apply this SQL to Main or deploy it through the Windows updater.

## Storage and user experience

PostgreSQL stores relationships, statuses, permissions, revisions and small field maps.
PDFs, documents, photos and videos use private Supabase Storage with the existing
file backend at `/opt/oneloss/demo/volumes/storage`, mounted as `/var/lib/storage`.
Do not put file contents, base64 media or expiring download URLs into database rows.
The VM currently has about 117 GB allocated, not the physical host's full 4 TB.
Storage growth still requires the VM disk/filesystem to be expanded by IT.

Each job has Paperwork (required slots and optional slots), Documents (drop-in files),
Photos and Videos. Uploading a general file never requires picking a paperwork slot.
An uploaded file can subsequently be linked to one or more slots on that same job.
Keep the shared blank form library separate from completed job documents.
Original names are display metadata; object paths use UUIDs, preventing collisions
and avoiding customer names in storage paths. Originals are never overwritten.

## Starter profiles

| Profile | Required slots | Optional slots |
| --- | --- | --- |
| Normal EMS | ATP, CER, CIF, COS | None |
| State Farm EMS | ATP, CER, CIF, COS, SF ATR, SF ATP | None |
| Commercial — base | ATP, CER, CIF, COS | None |
| Self-pay | Long form contract, COS | Credit card authorization |

Four independent profiles are seeded per existing demo franchise. These are labels,
not fabricated blank PDFs. Blank PDFs and custom mappings will be supplied/imported
later. The library supports any number of additional profiles, including commercial
property-specific profiles (`property_label`). Contents and Recon are supported
division values, but no default paperwork is invented for them.
Credit card authorization is an optional document slot, not a payment processor;
there are no card number, CVV or payment credential fields in this schema.

## Tables

All tables are in `public` for the existing REST API, with RLS enabled. All direct
client writes are revoked; use the checked RPCs below. No existing tables are altered.

| Table | Purpose |
| --- | --- |
| `demo_form_templates` | Franchise shared blank-form identities/titles |
| `demo_file_profiles` | Editable profile identity, division, property label, revision |
| `demo_profile_slots` | Profile requirement labels, ordering, required flag, optional template |
| `demo_job_profiles` | Applied job/division profile identity and source revision snapshot |
| `demo_job_form_slots` | Job-specific snapshot of required/optional slots and selected blank revision |
| `demo_job_files` | Job file identity, kind, category, tags, capture time and metadata revision |
| `demo_file_uploads` | Immutable file or blank-template revisions, field maps and upload lifecycle |
| `demo_slot_files` | Same-job links from completed uploads to requirement slots |
| `demo_file_events` | Server-authored actor/entity/event audit trail |

Every file/template/profile is scoped to a franchise. Template links cannot cross
franchises; slot-file links cannot cross jobs. Existing job IDs and memberships are
reused rather than creating another user directory or copy of the jobs.

## Permissions

Members can read their franchise's files and blanks. Editors can add job files,
apply profiles, organize attachments and update slot statuses. Company administrators
can also manage their company franchises' shared forms and profile library.
Viewers cannot upload, apply profiles, change metadata or mark documents accepted.
Removing membership removes subsequent file access; no email/user-metadata fallback.
Admin authorization comes from the existing server-owned `platform_admins` table.

Storage object policies require a matching reserved upload record. Restrictive
boundaries cover these two buckets even if a later unrelated permissive policy is
added. Clients cannot overwrite or delete object revisions. Future retention/purge
must be a separate reviewed server operation; never delete Storage metadata with SQL.
Use authenticated downloads initially. Short-lived signed URLs, if added later,
remain bearer links until expiry; do not store them as permanent file references.

## Upload protocol for prod's demo site

1. For a new job attachment call `demo_create_job_file(p_loss,p_kind,p_title,p_division)`.
   `p_kind` is `document`, `photo` or `video`. For a reusable blank, an admin calls
   `demo_create_template(p_franchise,p_title)` instead.
2. Call `demo_reserve_file_upload(p_target,p_template,p_expected_revision,p_name,p_type,
   p_bytes,p_sha256,p_mapping)`. The expected upload revision is zero for the first
   revision; after that use the maximum existing revision, including unfinished ones.
   `p_template` selects a blank template versus a job file. This returns the full
   upload row including `id`, `bucket_id`, `object_key` and `state=reserved`.
   Supply the existing Form Builder fields array only for blank templates, and keep
   mapping schema `form-builder-v1`. The existing PDF/field geometry validation must
   be reused in the application before rendering. SQL bounds the array but is not
   a PDF parser or a complete field-map validator.
3. Upload the binary using the demo user's JWT to the returned Storage bucket/path
   with `upsert:false`. Never ship service-role credentials in the site. A reservation
   can accept a new upload for 24 hours. If a request is interrupted, inspect the
   reserved row/object before retrying; do not create duplicate job files blindly.
4. Call `demo_finish_file_upload(p_upload)`. It confirms Storage metadata size/MIME
   before exposing the object as available. It is idempotent. This is not malware
   scanning, server-side hash verification or content inspection: `client_sha256`
   is advisory only. Until successful, show Pending/Retry, never Completed.
5. Download by the stored bucket/path under the current user's authentication.
   Read available revisions; keep older revisions for history.

The initial per-file cap is **50 MiB (52,428,800 bytes)**, matching the actual demo
Storage service. PDFs, supported office/text documents, JPEG/PNG/WebP/HEIC photos,
MP4/MOV videos are allowed; executable/HTML/SVG uploads are not allowed. Larger video
support requires a follow-up: resumable upload endpoint, gateway/tunnel limits,
storage setting, bucket cap and UI retries tested together. Do not merely increase
the database limit. HEIC/video browser preview support varies: offer original download.

## Profile and paperwork RPCs

- `demo_save_profile(p_franchise,p_key,p_title,p_division,p_property,p_expected_revision,p_slots)`
  atomically saves the library profile/slot definitions. Use expected revision zero
  to create. Each slot is `{code,label,required,sort_order?,template_id?}`. On stale
  revision (`40001`) reload and let the user reconcile; never overwrite silently.
- `demo_apply_file_profile(p_loss,p_profile,p_expected_revision)` snapshots the
  selected profile and latest available blank revisions. It does not auto-apply to
  existing jobs. A second application for the same job/division is rejected so it
  cannot destroy existing paperwork. Reviewed replace/merge behavior is future work.
- `demo_link_slot_file(p_slot,p_file)` links an available attachment on the same job.
  Attaching a file does not assert signature/completion/acceptance.
- `demo_set_slot_status(p_slot,p_expected_revision,p_status,p_note)` uses
  `missing`, `received`, `accepted`, `not_applicable`. Received/accepted needs an
  attached available file. Not-applicable needs a reason. Existing `platform_requirements`
  remain unchanged; the site must not silently treat two separate completion models
  as synchronized. Define any integration explicitly before changing checklist behavior.
- `demo_set_file_info(p_file,p_expected_revision,p_title,p_category,p_tags,p_captured_at,p_archived)`
  organizes attachments with revision checks; archiving keeps binaries/history intact.

Form mappings and profile edits do not rewrite prior job snapshots/completed files.
Late assignment of a blank to an already-applied slot, profile replacement, template
archive/rename, unlinking and cancellation cleanup need explicit future RPCs; do not
bypass the boundaries with direct table writes to implement them.

## Efficiency and later work

Filter by loss, kind and archived=false; paginate `(created_at,id)`, not all media.
Fetch upload metadata only for visible files. Do not download every original to
paint a gallery. Thumbnails/transcodes need a future background worker/private
derivative store; none is installed by this schema. SHA checks and deduplication
must not reveal another franchise's files. Keep originals during any later copy-only
import from local Form Builder, OneDrive or CompanyCam. No automatic import, source
deletion or provider dependency is introduced here. Note templates remain rows;
their existing behavior is unchanged.

## Deployment and evidence

`deploy/demo-files/preflight.py` collected definitions/settings only from demo.
`node tests/demo_files_sql.mjs` runs the real SQL with synthetic identities in local
PGlite, including role switching, RLS, hostile storage policy, upload status and
franchise/job boundaries. It does not prove the actual Storage HTTP service works.

Package `schema.sql` with `install.py`. Run `install.py rehearse` on Debian, then
`install.py apply --proof <printed-rehearsal-proof>`. Both require the demo Compose
project label plus `/opt/oneloss/demo/` data mount. Rehearsal executes the DDL inside
a rolled-back transaction. Apply requires matching schema checksum, database
container ID and job/access counts. It adds tables, RPCs, policies, starter rows and
private buckets without changing Main, Auth, routes, existing jobs or memberships.
It never restarts containers or performs a full database export. An installed schema
or existing target buckets cause a stop instead of an overwrite. Keep private logs
on the server. Normal users retain no DROP/DELETE privileges.

After apply: actual demo Storage upload/download test with two users, viewer and
cross-franchise denial; interrupted-upload/retry and shared-library revision test;
then prod integrates the demo site. No live rollout until those pass. Deployment
status must be reported separately from local tests: a built package is not an
installed schema or a functioning gallery.
