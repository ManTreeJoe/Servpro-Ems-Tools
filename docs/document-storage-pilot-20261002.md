# Document storage pilot — foundation

## Actual status

The additive migration `20261002185042_document_storage_pilot.sql` was applied
to OneLoss/Linguar Hub (`oqwwapqnzzhefqxobadl`) on October 2, 2026. The local
migration was created with Supabase CLI and its filename aligned with the
applied MCP migration version. L OPS was not changed.

Live verification: private `job-documents` bucket, 50 MiB maximum, RLS enabled
on all five new tables, zero pilot users, zero pilot jobs, zero documents.
An authenticated Nathan-context query sees no enabled jobs or objects.
No source files were uploaded, modified, moved, or deleted. No desktop release
was published. This foundation is **not yet connected to the Files UI**.

## Decisions implemented

- Independent user and job allowlists; neither is writable by app accounts.
  Pilot membership never bypasses existing `jobs` RLS/office permissions.
- Permanent file UUID per job and case-insensitive relative document path.
- Append-only version UUIDs, SHA-256, size, MIME, source modification time,
  creator, storage provider/bucket/object key. Filenames are not object keys.
- Unchanged latest verified content is skipped; A → B → A is three versions.
- One-hour pending reservations allow same-user retry without overwriting.
  Changed content or another uploader waits until completion/expiry.
- Read-back SHA-256/size verification before an immutable completion receipt.
  Database RLS verifies object existence and size, **not server-side SHA-256**.
  This is not malware scanning or adversarial integrity attestation.
- No app UPDATE/DELETE permissions or object overwrite policies.
- Source disappearance never deletes cloud history.
- Documents only; no photo bulk import. Private downloads require user JWTs.
- `document_import.py` is independent of provider/network implementation.
  `document_store.py` uses the existing user's JWT, pins account/project for a
  transfer, refuses redirects, and has no offline write fallback/service key.

## Pilot limits and known gaps

The preview processes at most 10,000 entries / 250 MiB of documents, with a
50 MiB limit per nonempty document. It preserves subfolders and filenames.
Offline files and all reparse points/junctions are skipped conservatively;
this can exclude hydrated OneDrive files too. The preview must clearly show
these exclusions before user confirmation. No automatic hydration occurs.
Changed/deleted files after preview stop execution; files added afterward are
not silently included. Partial successful uploads remain versioned; retry
resumes pending objects or skips verified content.

This is a backend foundation, not a finished import flow. Still needed:

1. Confirm Sam's exact account and identify 2–3 pilot job UUIDs from user choices.
2. Provision those exact pilot users/jobs through trusted administration.
3. Connect preview → explicit confirmation → background progress to Files,
   with skip/error details, history, open/download, cancellation between files,
   and account-switch cleanup. Use exact job IDs, never fuzzy title matching.
4. Exercise real upload/read-back/retry with an approved pilot document and
   verify Sam's permitted access plus a nonpilot user's denial through Storage.
5. Add portable manifest export and a separately tested object backup/restore.
   Supabase database backups do not include the stored object bytes.
6. Test those flows on both computers before considering desktop publication.

Future office-server migration must preserve job/file/version IDs, checksums,
relative paths, creator/history and access rules. Copy objects plus metadata,
verify hashes/counts, then change the provider adapter. No migration or restore
has been performed or claimed as tested here.

## Verification

- 34 passing Python tests: importer, transport and existing local file browser.
- Isolated PostgreSQL/WASM (PGlite 0.5.8) test executes the actual migration and
  verifies office isolation, pilot gates, invalid paths, reservation retry,
  A/B/A versions, premature receipt denial, immutable objects/rows and anon denial.
- Live schema and authenticated empty-gate read checks passed.
- Security advisor before/after found no additional findings. Preexisting
  notices remain: seven RLS/no-policy internal tables, two callable admin
  definer functions, and disabled leaked-password protection. No unrelated
  security settings were changed.

Run Python tests with an isolated pytest basetemp:
`python -m pytest tests/test_document_import.py tests/test_document_store.py tests/test_job_file_browser.py -q`

Run `node tests/document_storage_sql.cjs` with `NODE_PATH` pointing to an
external installation of `@electric-sql/pglite@0.5.8`. It uses an in-memory
database, synthetic users/jobs, and no live credentials.

Security references:
- https://supabase.com/docs/guides/storage/security/access-control
- https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection
- https://supabase.com/docs/guides/database/database-linter?lint=0029_authenticated_security_definer_function_executable
