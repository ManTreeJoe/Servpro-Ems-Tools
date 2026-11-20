# Remaining 1.8.48 source recovery — release blocked

Do not build a production release from Main until this recovery and updater PR #11
are reviewed and merged. This change publishes no installer, manifest or route,
and runs no migration against an employee profile or server.

## Provenance

Compared the complete tracked 1.8.47 snapshot (`93f0835`) with
`Output/source-main-1.8.48-private-updates`. Only six tracked files differed:
`_packaging/config.json`, `config.py`, `home_web.py`, `trello_client.py`,
`update_check.py`, and `version.txt`. The added root module was
`server_connection_migration.py`. Updater/home changes belong to PR #11.

The retained 63,407,024-byte installer matches the GitHub v1.8.48 asset SHA256:
`5f7c251d891260693885ef4b3f1ba8bb852e5e9ebc27f85784c2b17f267a6084`.
Extracted it without executing setup or the application. Its bundled config and
version files byte-match the recovered files. Recursive code-object comparison
(bytecode, constants, names, arguments, closure variables, flags and exception tables;
excluding filenames/line tables) matches the migration module, config startup hook,
and Trello `_call` method. This is compiled behavior evidence, not source-format proof.

## Recovered behavior

- Main shipping seed targets `https://api.oneloss.work` with its public publishable key.
  No personal provider credentials or server/privileged keys were added.
- Existing Main configs targeting the retired hosted endpoint migrate before defaults
  are loaded. Dev returns before migration; Trial skips it. Custom endpoints stay put;
  a custom franchise endpoint blocks the migration for review.
- A restricted local backup precedes changes. Personal folders and CompanyCam settings
  remain. Old Trello tokens are cleared and Trello writes paused. Moving from the hosted
  endpoint clears the saved Supabase session, requiring a fresh sign-in.
- The shipped `_call` pause is recovered exactly. PR #10 is the stronger default-off
  transport guard covering multipart/direct sinks too; this pause is not its replacement.
- Version metadata is restored to the shipped 1.8.48 contents; no version bump/release.

## Verification and limits

Tests use scratch configs/sessions and fake Windows identity/ACL commands; they check
ordering and refusal, not actual Windows ACL enforcement. No app module startup,
provider request, server SQL or employee-profile migration is exercised.
Existing CI intentionally replaces the shipped seed with an unconfigured seed; preserve
that behavior. The packaging generator now classifies/preserves the recovered pause flag (a
small correction beyond the shipped snapshot). It still derives defaults from operator input;
review regenerated config and its target before any future production build.

The recovered migration is historical behavior: backup ACL failure blocks changes;
replacement failure restores config/session. Crash/concurrent-launch atomicity is not
proven, and an abrupt crash between session removal and config replacement can require
manual restoration from the protected backup. No recovery backup is deleted here.

Dev currently remains pinned to hosted `erenessjerbkmhhrgpvk`; its contents are
unverified with the available account. Selecting the demo backend is a separate decision.
