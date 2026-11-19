# Microsoft employee admission rollout

Status: approval permissions are installed on production Main. Recovery password login, Nathan Microsoft sign-in and Pablo pending → Editor/IE approval passed against production on 2026-11-19. Pablo was restored to his original approved role and franchise; jobs were visible and admin API access remained denied. Microsoft-only server enforcement is still off during client rollout. Windows 1.8.49 and live web changes are being prepared; demo remains unchanged.

## Current production contract

The protected permission preflight found eight users, two administrators and existing IE/OC department assignments. All current assigned users are seeded approved with their existing memberships; administrators remain administrators and other assigned users start as editors. No account is deleted. New Microsoft accounts start pending without data access. Role authorization comes from server records, never a matching email in the desktop client.

`oneloss_access` is private. Its account states, recovery allowlist and audit records are not exposed as tables. Public invoker RPCs expose only own access and administrator-checked decisions. Approval decisions are serialized, checked against the expected revision and recorded in an audit log. The recovery administrator and last administrator cannot be removed through approvals.

The table RLS boundaries cover public data, Storage and Realtime. The PostgREST pre-request guard also covers views and privileged RPCs. Viewers can read assigned data but cannot perform database writes or volatile RPCs. Some existing read/write dispatcher RPCs are volatile, so viewer compatibility with those older screens needs application testing; do not loosen the guard to make them work. Trello mutations from the updated desktop also require editor/admin access.

Existing policies still determine which franchise rows an approved user can see. Approval does not grant cross-franchise data access. Client metadata cannot approve a user or assign a role.

## Deployment order

1. Run `deploy/employee-access/server.py rehearse` from the prepared server bundle. Version 3 does not export the database or make another recovery copy. It applies the migration inside one transaction, verifies recovery permissions and existing assignments, then rolls everything back. Session-local lock, statement and transaction limits bound the check; see [PostgreSQL 17 timeout documentation](https://www.postgresql.org/docs/17/runtime-config-client.html). Only a protected diagnostic and count report are saved. IT handles server backups; confirm an appropriate recovery point before any later permanent apply. It does not restart services or change Auth configuration. Keep its diagnostic private.
2. After the real-schema rehearsal passes, run `apply.py --rehearsal REPORT_DIRECTORY` from the matching install bundle. It requires a private root-owned success marker with the same SQL checksum, checks REST compatibility and current access counts, and saves small permission definitions/fingerprints only. It commits the same permission/recovery checks, then verifies assignments, administrators, container IDs and Auth configuration remain unchanged. It does not enable Auth hooks or change the client applications. The SQL defaults `microsoft_only=false` so existing employee clients retain their sessions during rollout. Do not enable signup until the before-user-created hook is configured.
3. Append only `https://app.oneloss.work/auth/microsoft` to production Auth's return allowlist, retaining the existing desktop return and all other entries. Enable the Azure-only creation hook and password-verification hook; keep the email provider enabled for Nathan's recovery account. Restrict Azure to the company tenant and check that other OAuth providers are disabled.
4. Verify Nathan's **actual password recovery login** before enforcement. SQL permission rehearsal is not a password authentication test.
5. Package and test the updated Windows client and publish the live web auth changes. Preserve existing GitHub update compatibility. Do not publish an installer simply by copying this clean feature tree over an unrelated release source tree.
6. Temporarily set **pablo@servpro10100.com** pending for the authorized approval test, saving his exact prior status/role/memberships first. Never delete his Auth account. Test no data access, then approve and restore the saved assignment. This does not verify first-time Microsoft account creation; a new employee is still needed for that test later.
7. Activate `microsoft_only` after client rollout and recovery verification. Confirm Microsoft access, refresh, jobs, admin decisions, viewer denials and editor franchise boundaries. Recheck demo fingerprints. Do not target the older `/opt/oneloss/live` project: production Main is `/opt/oneloss/main-server`.

The live portal now uses Main permissions and the existing Main jobs table. Its older Foundation adapter remains only for non-live/demo builds. Live web provides job browsing/search and access administration; editing, forms and files continue in Windows until the web workspace is expanded.

## Recovery and sessions

Nathan's existing account is selected into the private emergency allowlist by its existing Auth ID and administrator membership at installation. The email/password provider stays enabled; the Auth password hook permits only that recovery ID. Normal employee screens offer Microsoft only; recovery is a separate `"Linguar Hub.exe" --emergency-admin` desktop entry and `/emergency-admin` web route. The desktop keeps the one-Main-window rule and ordinary entry requires Microsoft even if an old password session is saved. There is no public link from normal employee login to recovery.

Approval status is checked live by the database. Desktop admission caching lasts at most five seconds and is keyed to the local user ID; server RLS still applies on every database request. Local sign-out revokes only that session. New Microsoft identities are linked according to Supabase's verified identity policy; no client secret is shipped to Windows or web.

## Local verification

```text
npm ci --prefix .local-test-tools
node tests/employee_access_sql.mjs
python -m pytest tests/test_employee_access.py tests/test_account_access.py tests/test_microsoft_auth.py tests/test_supabase_password_login.py tests/test_employee_setup_guide.py -q
node tests/microsoft_signin.cjs
node tests/employee_access_ui.cjs
```

The browser tests require the repository's Playwright development dependency. SQL tests use pinned PGlite with synthetic records and actual role/RLS switching, not a production connection. They cover pending access, metadata spoofing, definer RPC bypass, franchise boundaries, viewers, admin revision checks, suspension, recovery and hooks. The real server rehearsal remains necessary.


## Rollout configuration and distribution

`auth_rollout.py stage` adds exact Windows/web returns and enables the Azure-only before-user-created hook. The script validates the company tenant, retains recovery password capability and preserves all unrelated container IDs. It saves only a small protected configuration copy, not a database export. New Microsoft accounts enter the existing pending trigger. Current server-wide password access remains unchanged during distribution.

After the Windows release is published and the team has updated, `auth_rollout.py enforce --team-ready` verifies the published installer checksum, enables the recovery-only password hook and activates server-side Microsoft-only access. It restores prior Auth configuration/flag if its rollout verification fails. Re-test Nathan's actual recovery login after enforcement.

The private download policy already lists all eight existing team users. Keep GitHub's existing 1.8.48 transition installer/feed available so older clients can gain private updates. Publish Windows 1.8.49 through the private origin; do not remove the legacy transition release during this rollout.

Live web auth now reads Main's `my_app_access`; the job portal uses the existing Main `jobs` table with RLS. It provides job browsing/search and directs changes to the Windows application. It no longer needs Foundation tables for live login or jobs. The earlier Foundation/demo UI is retained for non-live builds; it is not deployed as part of the live auth rollout.
