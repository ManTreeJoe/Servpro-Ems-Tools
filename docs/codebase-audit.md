# Codebase audit — 2026-11-19

**Read-only application audit. No application code, server, database, production route, or release was changed.** This document is the only tracked addition. Main and Dev launchers were not executed. Tests used temporary profiles and explicit network guards; no real provider was called. Git fetch/push and the requested documentation PR are the only remote repository operations.

## Scope and evidence rules

- Audit base: latest fetched `origin/main`, **5cacf1dd903809d2f123bb0206418881cfab25e4** (merge of PR #5). Branch: `codex/codebase-audit` in a separate worktree.
- Findings cite this commit unless explicitly labeled **original working tree**. The original checkout has 257 tracked changes and 726 individually enumerated untracked files; it is not equivalent to Main (command evidence below).
- `file:line` references are source evidence, not proof of deployed behavior. **Unverified** means not established by this audit. Host credentials, database contents, server configuration, release feeds and live permissions were not queried.
- No claim of a comprehensive penetration test or complete secret absence. Test collection failure prevents a passing Python-suite claim. The Node runs below cover 12 selected synthetic scripts, not all 144 top-level scripts.

## 1. Backend targeting

### Actual committed launcher behavior

| Mode / entry | Verified source behavior | Consequence |
|---|---|---|
| Main via `tools/launch_notification_shell.py Main` | Lines 7–12 accept Main but do not set or clear `LINGUAR_CHANNEL`. `paths.py:51` accepts inherited `trial` or `dev`, otherwise defaults to main. | With a clean environment, Main profile. With an inherited channel, targeting can differ. Installed machine's effective URL is **unverified**. |
| Dev via the same launcher | `tools/launch_notification_shell.py:7` sets only `LINGUAR_DEV_MODE=1`; it does not change backend/profile/channel. | In a clean environment, **same profile and connection settings as Main**. “Dev” does not imply test data. |
| IsolatedDev via committed launcher | `tools/launch_notification_shell.py:9` rejects any argument except Main/Dev, with `Launch the installed Trial app instead.` | This mode is not available through the committed entry point. No runtime isolation claim is justified. |
| Source execution with `LINGUAR_CHANNEL=dev` | `paths.py:57`, `paths.py:127` select `OneLoss Identity Dev`; `config.py:21` requires a prepared config and refuses bundled fallback; `supabase_client.py:73` requires the fixed isolated hosted Supabase URL. | Stronger boundaries exist but are not installed by the committed launcher. |
| Frozen executable | `paths.py:40` derives main/trial from executable name/path; other source channel values do not select dev. | Trial is a separate local profile, **not necessarily a separate database** (`paths.py:37`). |

**Original working tree only:** `tools/launch_notification_shell.py:7` has `configure_channel`; lines 12/23 explicitly select main for Dev/Main; lines 15–21 select dev and install `dev_runtime` for IsolatedDev. This is modified, uncommitted source, not the Main implementation above. It explains why a local shortcut can appear to offer stronger isolation than the released source. No shortcut was run.

### Every identified production-source URL/key selector or consumer

Search covered tracked Python, TypeScript, JavaScript/MJS, JSON, TOML and launcher/script text, excluding test fixtures from this table. Evidence search and complete location list are below.

| Location | Selection / storage role |
|---|---|
| `paths.py:96`, `paths.py:125`; `config.py:14`, `config.py:21`, `config.py:38`, `config.py:65` | Source/bundled resource root and profile; seed config; fill blank shared URL/key from bundle on non-dev upgrades. Existing nonblank values survive. |
| `config.py:109`, `config.py:184`, `config.py:248` | Department overlay and effective load. Supabase URL/key are base settings, not department override keys; per-franchise separation depends on backend permissions. |
| `_packaging/config.json:51`, `_packaging/config.json:52` | Committed shared Supabase connection fields. Values are deliberately not reproduced. URL class is hosted Supabase. Packaged public key is not a service-role credential. |
| `_packaging/make_shipped_config.py:38`, `:160`, `:164` | Allows shared public connection fields into the package and checks key prefix. Prefix acceptance is not cryptographic validation of JWT role; do not use this alone as a release secret scanner. |
| `settings_web.py:49`, `:50`, `:103`, `:536` | URL/key settings and admin-scoped save path. Runtime permission configuration is **unverified**. |
| `supabase_client.py:69`, `:71`, `:72`, `:73`, `:272`, `:279` | Central effective credentials, dev URL guard, REST/auth URL construction and request headers. Session token comes from the profile session store (`:39`, `:92`, `:203`). |
| `supabase/functions/_shared/companycam-oauth.ts:14`, `:26`, `:38`, `:46`, `:128` | Server environment publishable-key fallback, callback URL, auth/access calls and service headers. |
| `supabase/functions/companycam-gateway/index.ts:19`, `:22`, `:30`, `:39`, `:59`, `:67` | Server environment URL/legacy anon key or publishable-key map; service credentials via shared helper. |
| `supabase/functions/companycam-oauth-callback/index.ts:72` | Callback uses server Supabase URL for persistence. |
| `supabase/functions/trello-sync/index.ts:4`, `:5`; `core.ts:200`–`:204` | Server environment URL and service-role key; constructs shared DB transport. |
| `supabase/functions/comment-parent/index.ts:3`–`:5`; `core.mjs:16`, `:18`, `:26`, `:56`–`:58` | Passes environment URL/anon/service key to user-authorized reads and thread persistence. |
| `tools/verify_rls_boundary.py:32`, `:33`; `trial_preflight.py:91`, `:92` | Reads current config; the RLS verification tool would contact that backend if run. **Not run.** |
| `employee_setup.py:19`; `job_workspace_cache.py:19` | URL participates in local scope/cache identity; these do not select a new backend. |

**IsolatedDev is not proven completely isolated.** `dev_runtime.py:10` permits the pinned hosted test host plus localhost/loopback. `:14` hooks only `urllib.Request` and `http.client.connect`; it is not an OS firewall and does not intercept arbitrary raw sockets, external processes, browser requests, COM or filesystem access. `trello_client.py:27` and `companycam_api.py:34,75` reject provider calls for `paths.IS_DEV`; `supabase_client.py:564` guards function invocation. These are useful, specific guards, not comprehensive isolation. Whether the pinned project itself contains only test records is **unverified**. The committed launcher does not call `dev_runtime.install()`.

## 2. Secrets and history

A value-suppressing scan inspected all text blobs reachable from **locally fetched refs**, including history. It looked for private-key markers, common provider-secret formats, JWTs (decoding only the role locally), and long literal assignments to credential fields. Output contains locations/categories only. Exact scanner and limitations are in the evidence appendix.

- No matching private credential was found by those rules. This is **not proof that history is secret-free**: opaque/short strings, split/encoded values, binary/PDF/archive contents, LFS payloads, deleted remote refs/reflogs and unfetched branches were not exhaustively inspected.
- Shared public connection material is committed at `_packaging/config.json:51–52` and the Trello application-key location in that file. These are client/public configuration, not automatically private secrets. Values are not printed here. Their deployed scope and authorization strength are **unverified**.
- `_packaging/make_shipped_config.py:149` checks known secret substrings and blank Trello/CompanyCam token fields, but `:164` accepts any `ey` prefix as a publishable-looking JWT. Its comment mentions service-role exclusion; this specific prefix check does not decode/verify role. Recommend a focused negative test for a service-role JWT and scanning at release time.
- `.gitignore:9` ignores local configuration, and `:23` ignores customer document/database extensions. Ignore rules do not remove earlier commits or guarantee files were never force-added.
- Do not rotate public publishable keys solely because they are present. Any future confirmed private credential finding should report only the path/blob/line, then trigger owner-led revocation and history cleanup.

## 3. Tests and CI

### Python

The exact requested command, `python -m pytest tests/ -q`, was run with an external startup guard, temporary APPDATA/LOCALAPPDATA, `LINGUAR_CHANNEL=trial`, plugin autoload disabled and no `LINGUAR_CI` skips. Socket connects, subprocess/UI launches and shared-drive access were blocked before collection. The first attempt stopped because the guard also blocked Windows' NUL device; the guard was corrected to permit that device only. Network restrictions were not relaxed.

Result: **one collection error, 40.79s**. `tests/test_job_log_scope_hotfix.py:7` imports `_job_log_placement_scope`; that name is absent from `pipeline_web.py` at the audited commit. The suite stops before running tests. This is a source/test mismatch, not a database failure. Full output appears below.

`tests/conftest.py:21` redirects profiles before imports; session fixtures later pin SQLite and caches. Those later fixtures do not protect arbitrary collection-time imports. The extra external guard is why this audit can report no live calls. The normal CI workflow does not provide this equivalent all-network block.

### Node: observed results versus declared skip reasons

A fresh worktree has no local node_modules. `node tests/job_conversation.cjs` initially failed with `Cannot find module 'playwright'`. `package.json:5` declares Playwright 1.59.0 and `.github/workflows/windows.yml:36` installs dependencies using npm ci; this is an environment prerequisite, not proof of a broken dependency declaration. No packages were installed. The next runs used existing dependencies via NODE_PATH, a temporary network-blocking preload, fake browser bridges, and a dedicated temp directory. Only a test-created loopback HTTP server was allowed for intake fixtures. No OneLoss process was started.

| Cause | Scripts / observed outcome |
|---|---|
| Missing package | `job_conversation.cjs`: Playwright missing in clean worktree; reproduced before NODE_PATH was supplied. Other package failures **unverified**. |
| Hardcoded developer path | `comment_reactions.cjs:13`, `daily_run_completion.cjs` invoke an absolute developer Python executable. Static portability defect confirmed; not executed because they spawn application imports outside the reviewed browser-only fixture boundary. Current-machine failure **unverified** (path may exist here). |
| Browser timeout | `job_conversation.cjs`: hidden `[data-comment-search]` fill, 30s. `job_workspace_incremental.cjs:31`: missing `#job-tab-files`, 30s. `job_workspace_loading_state.cjs:42`: same missing Files tab, 30s. These are observed selectors/visibility failures; whether obsolete fixture or product regression requires intended-UI review. |
| Real assertion | `intake_embedded.cjs:29`: empty restored name vs fixture name. `job_division_tabs.cjs:54`: false vs true. `job_log_save_responsiveness.cjs:18`: actual placement adds `due: ''`, expected object omits it (test stops before its save-button assertions). `popup_click_retention.cjs:40`: outside click closes shared intake/job card/job-info editor; APA and Snapshot retain correctly. |
| Incomplete VM fixture | `apa_drop_save.cjs:16`: `window is not defined`. `jobs_move_prompt.cjs:12`: `pendingCardDrop is not defined`. These are fixture ReferenceErrors, not real UI assertion failures. |
| Passed despite CI exclusion | `companycam_gateway_reliability.cjs`, `job_draft_recovery.cjs`, `job_log_subcontractors.cjs` all pass in the guarded synthetic run. Their `.github/ci-skips.json` entries are stale relative to this evidence. |
| Requires live app | `shell_startup_styles.cjs:6` navigates to DEV_TEST_URL; deliberately not run. **Unverified**. |

Totals for the selected dependency-enabled run: **3 passed, 9 failed, 12 run**. This is not a full 144-script certification. No harness timeout occurred; the reported 30s timeouts are Playwright results returned by the scripts.

### CI blind spots

`.github/workflows/windows.yml:64` sets LINGUAR_CI=1. `tests/conftest.py:191` onward applies the skip policy only under that flag. `.github/ci-skips.json` skips six Python modules, individual tests, and 15 Node scripts; therefore a green CI run is intentionally narrower than a normal developer run. The missing hotfix import is not removed by this policy. `.github/workflows/windows.yml:78` runs top-level Node scripts after npm ci but omits the named skip list. At least three skip reasons now contradict observed passes; other listed reasons differ from the current first failure. No CI settings were modified.

## 4. Update paths and older clients

- Current committed reader: `home_web_assets/updates.js:56` → `home_web.py:805` → `update_check.py:16`. It reads the **GitHub public releases repository's main/trial version.txt**, with a six-second timeout (`update_check.py:26,33`). No updates.oneloss.work selector or fallback exists in tracked text at this commit.
- Publisher source: `tools/publish_desktop_release.py:20,94` writes channel manifests through GitHub's contents API after its release workflow. It was not run. This audit does not publish an installer or change a feed.
- Installer: `home_web.py:819` checks the manifest, downloads its installer, then `:849` invokes `os.startfile`. There is **no digest/signature validation or URL-origin allowlist in this download/launch path** (`:842–849`). Publisher-side hash calculation is not client-side authenticity verification. This is a concrete trust-boundary hardening gap, not a claim that a release has been compromised.
- Historical reader at `3f3ec66:update_check.py` points to the **source repository's main/version.txt**. `4cf769b` changes to the releases repository. Thus “older client” is not one uniform population: those very old builds need their original manifest path maintained; later GitHub-feed builds continue to need the releases repository manifest. They cannot discover a new Cloudflare hostname from code that never references it.
- **Unverified:** what serves updates.oneloss.work, its active route, redirects, deployed content, installer signatures and the actual versions employees have installed. No production route or server was contacted. Its absence in this repo is not evidence the service does not exist elsewhere.

## 5. Dead weight and source structure

Original workspace inventory (not this clean audit worktree) shows 42,333 files / 6,045,746,829 bytes under Output, plus versioned build/dist directories listed below. These are **generated/release candidates, not approved deletions**. No binary was executed. Historical installers may be irreplaceable without matching build inputs, signing state and dependency versions. `Output/` is already ignored (`.gitignore:76`); “untracked” includes ignored artifacts here and does not mean Git currently reports every one in status.

The clean audit worktree contains no copied build outputs. Original status: 257 tracked modifications, 726 untracked individual files. The large dirty working tree materially increases risk of testing a different app than the branch sent for review. Nothing was staged or removed there.

Static AST inventory found 47 top-level Python modules without a direct static import. **These are candidates, not proven dead code.** Example counterexamples: `home_web.py:227,241,277` dynamically imports job_notes_web/automations_web; `launcher.py:215,1398` uses string-dispatched tools; `Linguar_Hub.spec:82,108` explicitly packages dynamic imports. CLI/one-shot scripts can legitimately have no importers. No orphan was approved for removal; runtime use is **unverified** without entry-point tracing.

Exact normalized AST duplicates (functions at least 11 lines): nested `_find_year_folder` implementations at `audit_logic.py:1099` and `:1253`; `_request_via_trello` at `daily_photos_gui.py:1397`, `run_audit_gui.py:4875`, `snapshot_gui.py:2268`; another identical pair at `run_audit_gui.py:5260`, `snapshot_gui.py:2633`; `_show_menu` at `launcher.py:943,1105`. These are duplicated implementations, not necessarily duplicate top-level definitions overriding each other. No entire Python file was an exact text duplicate. Extract only after behavior tests; do not wholesale move the module tree.

## 6. Integrations: implemented versus unverified

### Trello — posting is NOT globally disabled

The requested “confirm posting is disabled” premise is contradicted by code:

- `trello_client.py:1718–1732` posts comments; `:1657` creates cards; `:575` marks notifications read. `_creds()` blocks only paths.IS_DEV (`:27`). The module's “read-only client” header is stale.
- `pipeline_web.py:2524` reports `posted_trello=False` for a local shared-storage success, but `:2536–2544` has a compatibility fallback that calls `tc.post_comment`. One return field cannot establish global write prohibition.
- `supabase/functions/trello-sync/core.ts:259–264` contains server comment POST; `:268` gates mirroring on TRELLO_EMS_COMMENTS_ENABLED, and `:289` gates the handler on TRELLO_SYNC_ENABLED. Defaults are false in `index.ts:10–11`; deployed environment values are **unverified**. Flags defaulting off are not code deletion or universal write guards.

### CompanyCam

Real client and server adapters exist: local token fallback (`companycam_api.py:32`), authenticated cloud gateway (`:71`), personal connection gate for writes (`:87`), project creation (`:575`), and photos/download APIs. Server gateway membership checks and method/path restrictions exist (`supabase/functions/companycam-gateway/index.ts:120–149`), with personal OAuth credential or franchise-key fallback (`:149`). OAuth callback and encrypted credential helpers are present. These are wired implementations, not UI-only stubs. Actual configured accounts, secrets, deployments and permissions are **unverified**. Guarded gateway fixture passes.

### Resend

`git grep` for `api.resend.com` and `RESEND_API_KEY` in HEAD returns no matches. There is no verified Resend API transport in this audited repo. “resend” hits in DocuSign reminder code mean resend-tracking, not the Resend provider. Hosted Auth SMTP settings or another repository may use it; **unverified**, not asserted absent globally.

### Microsoft

Active Outlook read integration exists: `outlook_local.py:45,216,261` uses desktop COM; `adjuster_monitor.py:535` imports it, as do XA/email scans. `_one_shot/outlook_client.py:87–101,153,246` implements Graph device-code auth and read fallback with Mail.Read/User.Read/offline_access. `settings_web.py:39–40` exposes Graph app/tenant IDs, but that alone does not prove current Microsoft SSO or shared-mailbox sending is integrated. No verified Graph sendMail path or Resend-backed mail sender was found. App registration, consent, shared EMS permissions, reply deduplication and login identity linkage are **unverified**. No email or authorization request was made.

## 7. Risk hotspots

- Largest Python files: audit_web.py 9,982 lines; run_audit_gui.py 7,463; hygiene_gui.py 5,098; snapshot_gui.py 4,370; apa_monitor_gui.py 3,940; initial_upload_queue.py 3,765; pipeline_web.py 3,414. Size alone is not a bug; these mix UI, provider work, state and recovery, making small source/test drift hard to isolate. Command-derived counts below.
- Last 100 reachable HEAD commits: docs/l-ops-platform.md 75 changes; pipeline_web_assets/app.js 21; pipeline_web_assets/index.html 20; calendar_preview.html 20; pipeline_web.py 14; weekly_calendar.js 14. This window includes merge/history effects and is not an author productivity metric.
- AST found 2,046 broad Exception/BaseException/bare handlers with a single pass or return. This includes tests and intentional user-facing errors; it is **not** 2,046 bugs. Concrete silent examples: `pipeline_web.py:2511` drops actor lookup exceptions and proceeds with a generic actor; `adjuster_monitor.py:741,750` and `_one_shot/outlook_client.py:298` merit focused review. Some analytics catches return explicit errors and should not be mislabeled silent.
- Python scan found no missing explicit timeout among direct `urllib.request.urlopen` and common `requests.*` calls it recognized. Aliases/wrappers and all SDK defaults are **unverified**. Counterexample requiring action is TypeScript: gateway fetches at `companycam-gateway/index.ts:31,40,60,68,85,103,171` have no signal/timeout; shared OAuth fetches at `_shared/companycam-oauth.ts:38,46` likewise. Contrast `trello-sync/core.ts:184,209` and `comment-parent/core.mjs:18,28,37,62`, which use AbortSignal timeouts. Unbounded server calls can prolong pending desktop requests; no runtime outage was induced.

## Evidence: commands and outputs

All source inspection used git/rg/Get-Content or parsing text with stdlib AST/JSON. No application module was imported outside the explicitly guarded pytest process. Failed exploratory commands for absent files/glob syntax produced no evidence and no changes. Credential scanners never print matched values. Auxiliary audit scripts/logs live outside the repo in a temporary audit directory and are not staged.

### Branch and base

```text
git fetch origin main
From https://github.com/ManTreeJoe/Servpro-Ems-Tools
 * branch main -> FETCH_HEAD

git rev-parse origin/main
5cacf1dd903809d2f123bb0206418881cfab25e4

git worktree add -b codex/codebase-audit ../codebase-audit origin/main
branch 'codex/codebase-audit' set up to track 'origin/main'.
HEAD is now at 5cacf1d Merge pull request #5 from ManTreeJoe/codex/employee-setup-wizard
```

### Required pytest command (network/process/shared-drive guard active)

```text
python -m pytest tests/ -q

=================================== ERRORS ====================================
_____________ ERROR collecting tests/test_job_log_scope_hotfix.py _____________
ImportError while importing test module 'C:\Users\NathanBupte\Documents\Codex\2026-08-25\referenced-chatgpt-conversation-this-is-an\codebase-audit\tests\test_job_log_scope_hotfix.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
..\..\..\..\..\AppData\Local\Programs\Python\Python312\Lib\importlib\__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests\test_job_log_scope_hotfix.py:7: in <module>
    from pipeline_web import _job_log_placement_scope, _job_log_for_placement
E   ImportError: cannot import name '_job_log_placement_scope' from 'pipeline_web' (C:\Users\NathanBupte\Documents\Codex\2026-08-25\referenced-chatgpt-conversation-this-is-an\codebase-audit\pipeline_web.py)
=========================== short test summary info ===========================
ERROR tests/test_job_log_scope_hotfix.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 40.79s

```

The temporary sitecustomize guard (not committed) patched socket.socket.connect/connect_ex/create_connection to raise, rejected subprocess.Popen/os.system/os.startfile, and rejected X-drive/UNC open/scandir/listdir (allowing Windows NUL). APPDATA/LOCALAPPDATA pointed to scratch; PYTEST_DISABLE_PLUGIN_AUTOLOAD=1, PYTHONDONTWRITEBYTECODE=1, LINGUAR_CHANNEL=trial. LINGUAR_CI unset. An initial run reported `INTERNALERROR ... AUDIT: shared drive access disabled` for NUL; the second run above reached collection. No security restriction on networking was removed.

### Node output

```text
node tests/job_conversation.cjs
Error: Cannot find module 'playwright'
```

For these 12 commands, existing NODE_PATH supplied Playwright. `node --require <scratch>/node-guard.cjs` blocked Node HTTP/fetch and browser requests except the fixture's own loopback server. Service workers were disabled. The preload patched only the test process; no repository file changed.

```text
node --require <scratch>/node-guard.cjs tests/apa_drop_save.cjs
exit: 1
ReferenceError: window is not defined
    at Object.drop (evalmachine.<anonymous>:59:21)
    at C:\Users\NathanBupte\Documents\Codex\2026-08-25\referenced-chatgpt-conversation-this-is-an\codebase-audit\tests\apa_drop_save.cjs:16:18
    at Object.<anonymous> (C:\Users\NathanBupte\Documents\Codex\2026-08-25\referenced-chatgpt-conversation-this-is-an\codebase-audit\tests\apa_drop_save.cjs:23:3)
    at Module._compile (node:internal/modules/cjs/loader:1871:14)
    at Object..js (node:internal/modules/cjs/loader:2002:10)
    at Module.load (node:internal/modules/cjs/loader:1594:32)
    at Module.<anonymous> (node:internal/modules/cjs/loader:1396:12)
    at Module._load (C:\Users\NATHAN~1\AppData\Local\Temp\oneloss-audit-7ad52394d017421f9cd22092914c711f\node-guard.cjs:8:55)
    at wrapModuleLoad (node:internal/modules/cjs/loader:255:19)
    at Module.executeUserEntryPoint [as runMain] (node:internal/modules/run_main:154:5)

```

```text
node --require <scratch>/node-guard.cjs tests/companycam_gateway_reliability.cjs
exit: 0
(node:15844) ExperimentalWarning: stripTypeScriptTypes is an experimental feature and might change at any time
(Use `node --trace-warnings ...` to show where the warning was created)
CompanyCam connection status update failed
PASS: failed credential lookup is closed; health failure preserves provider response.

```

```text
node --require <scratch>/node-guard.cjs tests/intake_embedded.cjs
exit: 1
AssertionError [ERR_ASSERTION]: Expected values to be strictly equal:
+ actual - expected

+ ''
- 'Test customer'

    at C:\Users\NathanBupte\Documents\Codex\2026-08-25\referenced-chatgpt-conversation-this-is-an\codebase-audit\tests\intake_embedded.cjs:29:10 {
  generatedMessage: true,
  code: 'ERR_ASSERTION',
  actual: '',
  expected: 'Test customer',
  operator: 'strictEqual',
  diff: 'simple'
}

```

```text
node --require <scratch>/node-guard.cjs tests/job_conversation.cjs
exit: 1
locator.fill: Timeout 30000ms exceeded.
Call log:
  - waiting for locator('[data-comment-search]')
    - locator resolved to <input type="search" data-comment-search="" aria-label="Search comments" placeholder="Search comments"/>
    - fill("packing")
  - attempting fill action
    2 × waiting for element to be visible, enabled and editable
      - element is not visible
    - retrying fill action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and editable
      - element is not visible
    - retrying fill action
      - waiting 100ms
    57 × waiting for element to be visible, enabled and editable
       - element is not visible
     - retrying fill action
       - waiting 500ms

    at C:\Users\NathanBupte\Documents\Codex\2026-08-25\referenced-chatgpt-conversation-this-is-an\codebase-audit\tests\job_conversation.cjs:66:47 {
  name: 'TimeoutError'
}

```

```text
node --require <scratch>/node-guard.cjs tests/job_division_tabs.cjs
exit: 1
AssertionError [ERR_ASSERTION]: Expected values to be strictly equal:

false !== true

    at C:\Users\NathanBupte\Documents\Codex\2026-08-25\referenced-chatgpt-conversation-this-is-an\codebase-audit\tests\job_division_tabs.cjs:54:10 {
  generatedMessage: true,
  code: 'ERR_ASSERTION',
  actual: false,
  expected: true,
  operator: 'strictEqual',
  diff: 'simple'
}

```

```text
node --require <scratch>/node-guard.cjs tests/job_draft_recovery.cjs
exit: 0
PASS: actual modal drafts recover without submission; cancel and acknowledged post clear recovery.

```

```text
node --require <scratch>/node-guard.cjs tests/job_log_save_responsiveness.cjs
exit: 1
AssertionError [ERR_ASSERTION]: Expected values to be strictly deep-equal:
+ actual - expected

  {
    board: 'EMS Work',
+   due: '',
    lane: 'Scheduled',
    source: 'app_board'
  }

    at C:\Users\NathanBupte\Documents\Codex\2026-08-25\referenced-chatgpt-conversation-this-is-an\codebase-audit\tests\job_log_save_responsiveness.cjs:18:10 {
  generatedMessage: true,
  code: 'ERR_ASSERTION',
  actual: [Object],
  expected: [Object],
  operator: 'deepStrictEqual',
  diff: 'simple'
}

```

```text
node --require <scratch>/node-guard.cjs tests/job_log_subcontractors.cjs
exit: 0
Subcontractor Job Log: PASS

```

```text
node --require <scratch>/node-guard.cjs tests/job_workspace_incremental.cjs
exit: 1
locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator('#job-tab-files')

    at C:\Users\NathanBupte\Documents\Codex\2026-08-25\referenced-chatgpt-conversation-this-is-an\codebase-audit\tests\job_workspace_incremental.cjs:31:40 {
  name: 'TimeoutError'
}

```

```text
node --require <scratch>/node-guard.cjs tests/job_workspace_loading_state.cjs
exit: 1
locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator('#job-tab-files')

    at C:\Users\NathanBupte\Documents\Codex\2026-08-25\referenced-chatgpt-conversation-this-is-an\codebase-audit\tests\job_workspace_loading_state.cjs:42:40 {
  name: 'TimeoutError'
}

```

```text
node --require <scratch>/node-guard.cjs tests/jobs_move_prompt.cjs
exit: 1
ReferenceError: pendingCardDrop is not defined
    at Object.onLaneDrop (evalmachine.<anonymous>:3:3)
    at C:\Users\NathanBupte\Documents\Codex\2026-08-25\referenced-chatgpt-conversation-this-is-an\codebase-audit\tests\jobs_move_prompt.cjs:12:13
    at Object.<anonymous> (C:\Users\NathanBupte\Documents\Codex\2026-08-25\referenced-chatgpt-conversation-this-is-an\codebase-audit\tests\jobs_move_prompt.cjs:19:3)
    at Module._compile (node:internal/modules/cjs/loader:1871:14)
    at Object..js (node:internal/modules/cjs/loader:2002:10)
    at Module.load (node:internal/modules/cjs/loader:1594:32)
    at Module.<anonymous> (node:internal/modules/cjs/loader:1396:12)
    at Module._load (C:\Users\NATHAN~1\AppData\Local\Temp\oneloss-audit-7ad52394d017421f9cd22092914c711f\node-guard.cjs:8:55)
    at wrapModuleLoad (node:internal/modules/cjs/loader:255:19)
    at Module.executeUserEntryPoint [as runMain] (node:internal/modules/run_main:154:5)

```

```text
node --require <scratch>/node-guard.cjs tests/popup_click_retention.cjs
exit: 1
FAIL: shared intake popup: clicking outside dismissed the popup

0 !== 1

FAIL: job card: clicking outside dismissed the popup

0 !== 1

FAIL: job info editor: clicking outside dismissed the popup

0 !== 1

PASS: APA editor ignores outside clicks/releases; explicit Close works.
PASS: Snapshot popup ignores outside clicks/releases; explicit Close works.
AssertionError [ERR_ASSERTION]: Expected values to be strictly deep-equal:
+ actual - expected

+ [
+   'shared intake popup: clicking outside dismissed the popup\n\n0 !== 1\n',
+   'job card: clicking outside dismissed the popup\n\n0 !== 1\n',
+   'job info editor: clicking outside dismissed the popup\n\n0 !== 1\n'
+ ]
- []

    at C:\Users\NathanBupte\Documents\Codex\2026-08-25\referenced-chatgpt-conversation-this-is-an\codebase-audit\tests\popup_click_retention.cjs:40:10 {
  generatedMessage: true,
  code: 'ERR_ASSERTION',
  actual: [Array],
  expected: [],
  operator: 'deepStrictEqual',
  diff: 'simple'
}

```

### Static inventory command/output

`python <scratch>/static.py` used `git ls-files`, AST (without imports), and `git log -100 --format= --name-only HEAD`. Counts and locations:

```text
LARGEST [[9982, "audit_web.py"], [7463, "run_audit_gui.py"], [5098, "hygiene_gui.py"], [4370, "snapshot_gui.py"], [3940, "apa_monitor_gui.py"], [3765, "initial_upload_queue.py"], [3414, "pipeline_web.py"], [3104, "audit_logic.py"], [2877, "ems_db_sqlite.py"], [2756, "persistence.py"], [2589, "trello_client.py"], [2314, "job_notes_gui.py"]]
BROAD_SWALLOW_COUNT 2046 EXAMPLES ["_one_shot/outlook_client.py:298", "adjuster_monitor.py:579", "adjuster_monitor.py:741", "adjuster_monitor.py:750", "analytics_web.py:45", "analytics_web.py:60", "analytics_web.py:74", "analytics_web.py:89", "analytics_web.py:155", "analytics_web.py:176", "apa_logic.py:138", "apa_logic.py:429", "apa_monitor_gui.py:360", "apa_monitor_gui.py:685", "apa_monitor_gui.py:703", "apa_monitor_gui.py:884", "apa_monitor_gui.py:976", "apa_monitor_gui.py:2129", "apa_monitor_gui.py:2133", "apa_monitor_gui.py:2137", "apa_monitor_gui.py:2635", "apa_monitor_gui.py:2735", "apa_monitor_gui.py:2781", "apa_monitor_gui.py:3076", "apa_monitor_gui.py:3081", "apa_monitor_gui.py:349", "apa_monitor_gui.py:624", "apa_monitor_gui.py:1667", "apa_monitor_gui.py:1673", "apa_monitor_gui.py:2111"]
NO_EXPLICIT_TIMEOUT []
NO_STATIC_IMPORT_TOP_LEVEL ["automations_web", "backfill_carriers", "backfill_children", "backfill_departments", "backfill_folder_aliases", "backfill_job_facts", "backfill_parent_jobs", "card_observation_history", "cheat_sheet_gui", "check_departments", "conformance", "dedupe_photos", "dev_check_inline_js", "dev_lint", "dev_runtime", "dispute_tracker_gui", "disputes_web", "fill_snapshot", "hygiene_gui", "import_carriers_from_trello", "job_identity_review", "job_notes_web", "job_reconciliation_web", "kpi_gui", "make_icon", "migrate_canon_carrier_keys", "migrate_to_supabase", "multi_unit_web", "native_boards_web", "new_job_gui", "operations_portal", "photo_folders_web", "pipeline_gui", "print_pngs_by_folder", "reconcile_jobs", "rename_job_folders", "rename_mariah_to_bates", "rename_review_page", "repair_conflated_job", "repair_to_children", "run_doc_roundtrip", "sort_files_gui", "spreadsheet_gui", "spreadsheet_web", "wc_audit_gui", "wc_audit_web", "xa_email_ingest_cron"]
MOST_CHANGED_LAST100 [('docs/l-ops-platform.md', 75), ('pipeline_web_assets/app.js', 21), ('pipeline_web_assets/index.html', 20), ('run_doc_editor_web_assets/calendar_preview.html', 20), ('pipeline_web.py', 14), ('run_doc_editor_web_assets/weekly_calendar.js', 14), ('version.txt', 10), ('job_settings.py', 9), ('analytics_web_assets/index.html', 9), ('tests/schedule_live.cjs', 9), ('tests/calendar_preview.cjs', 9), ('pipeline_web_assets/app.css', 8)]
TARGETING_LOCATIONS
.github/ci-skips.json:11,12
_packaging/config.json:51,52
_packaging/make_shipped_config.py:38,160,164
config.py:38
employee_setup.py:19
job_workspace_cache.py:19
settings_web.py:49,50,103
supabase/functions/_shared/companycam-oauth.ts:15,26,38,46,128
supabase/functions/comment-parent/index.ts:3,4,5
supabase/functions/companycam-gateway/index.ts:19,30,39,59,67
supabase/functions/companycam-oauth-callback/index.ts:72
supabase/functions/trello-sync/core.ts:200,201,203,204
supabase/functions/trello-sync/core_test.ts:152,160
supabase/functions/trello-sync/ems_comments_test.ts:97
supabase/functions/trello-sync/index.ts:4,5
supabase_client.py:71,72,77,78
tools/verify_rls_boundary.py:32,33
trial_preflight.py:91,92
UPDATE_DOMAIN_TRACKED
EXACT_DUPLICATE_PY
[]

```
### Original-workspace generated candidates / duplicates

`python <scratch>/weight.py` used `git status --porcelain --untracked-files=all`, recursive file counts/byte sizes for named build directories, and AST equality for functions of at least 11 lines. No contents or customer names were printed.

```text
ORIGINAL_STATUS {'tracked-change': 257, 'untracked': 726}
GENERATED_CANDIDATE build 16 38034509
GENERATED_CANDIDATE build-1.8.25 16 38972857
GENERATED_CANDIDATE build-1.8.26 16 39210562
GENERATED_CANDIDATE build-1.8.27 16 39356203
GENERATED_CANDIDATE build-1.8.28 16 39533323
GENERATED_CANDIDATE build-1.8.29 16 42467227
GENERATED_CANDIDATE build-main-1.8.45-isolated 16 43132090
GENERATED_CANDIDATE dist 1250 119234100
GENERATED_CANDIDATE dist-1.8.25 1295 120436623
GENERATED_CANDIDATE dist-1.8.26 1314 123028020
GENERATED_CANDIDATE dist-1.8.27 1329 123193631
GENERATED_CANDIDATE dist-1.8.28 1355 123371442
GENERATED_CANDIDATE dist-1.8.29 1372 132703079
GENERATED_CANDIDATE dist-main-1.8.45-isolated 1426 152425010
GENERATED_CANDIDATE node_modules 913 49213547
GENERATED_CANDIDATE Output 42333 6045746829
PACKAGED_CONNECTION_KEYS_PRESENT ['supabase_anon_key', 'supabase_url', 'trello_api_key']
PACKAGED_ENDPOINT_CLASS hosted-supabase
DUPLICATED_FUNCTIONS [['audit_logic.py:1099 _find_year_folder', 'audit_logic.py:1253 _find_year_folder'], ['daily_photos_gui.py:1397 _request_via_trello', 'run_audit_gui.py:4875 _request_via_trello', 'snapshot_gui.py:2268 _request_via_trello'], ['launcher.py:943 _show_menu', 'launcher.py:1105 _show_menu'], ['run_audit_gui.py:5260 _request_via_trello', 'snapshot_gui.py:2633 _request_via_trello']]

```
### Negative / positive source checks

```text
git grep -n -E 'api\.resend\.com|RESEND_API_KEY|updates\.oneloss\.work' HEAD -- .
(no matches; exit 1)

git grep -n '_job_log_placement_scope' HEAD -- pipeline_web.py tests/test_job_log_scope_hotfix.py
HEAD:tests/test_job_log_scope_hotfix.py:7:from pipeline_web import _job_log_placement_scope, _job_log_for_placement
HEAD:tests/test_job_log_scope_hotfix.py:20:    return _job_log_placement_scope(FULL, primary, placements, 'EMS', provider)
HEAD:tests/test_job_log_scope_hotfix.py:41:    decision = _job_log_placement_scope(SHORT, {'card_id': 'https://trello.com/c/' + SHORT}, [], 'EMS')
HEAD:tests/test_job_log_scope_hotfix.py:101:    decision = _job_log_placement_scope(SHORT.lower(), {'card_id': SHORT}, [], 'EMS')
(no pipeline_web.py definition)

git log -5 --format='%h %s' -- update_check.py
4cf769b Move channel feeds to public releases repo and package Trial CI installers
e55ca9d Add Main/Trial channels — two side-by-side apps, two update branches
6ba4951 One-click auto-update: banner downloads + launches the installer
3f3ec66 v1.1.0 — audit streamline, XA notes, CompanyCam pull, per-dept browsers, update check

git show 3f3ec66:update_check.py (RAW_URL excerpt)
RAW_URL = ("https://raw.githubusercontent.com/ManTreeJoe/"
           "Servpro-Ems-Tools/main/version.txt")
```

### History secret scan (location-only output)

`python <scratch>/secrets.py`: enumerated `git rev-list --objects --all`, used `git cat-file --batch-check` and `--batch` to inspect text blobs up to 2 MB. Patterns: private-key headers; GitHub/Resend/secret-key prefixes; JWT-shaped values with local role decoding; credential-field string assignments >=24 characters. It never prints values. Public sb_publishable/application keys are not reported as private secrets. Extensions: py, ts, js, cjs, mjs, sh, bat, cmd, json, env, yml, yaml, toml, txt, md, ps1, ini, cfg. This heuristic is explicitly not exhaustive.

```text
{
  "refs": "all locally fetched refs",
  "text_blobs_scanned": 4213,
  "oversize_excluded": [],
  "findings": []
}

```

## Ranked top 10

| Rank | Severity | Finding and evidence | One-line fix idea | One small PR? |
|---|---|---|---|---|
| 1 | high | Dev defaults to Main targeting; committed launcher lacks IsolatedDev (`tools/launch_notification_shell.py:7–12`). | Make mode/profile/backend selection explicit and fail closed, with subprocess environment contract tests. | Yes, if limited to launch contract. |
| 2 | high | Full Python suite cannot collect (`tests/test_job_log_scope_hotfix.py:7`). | Reconcile the committed scope helper API and focused test together, then rerun full collection. | Yes. |
| 3 | high | Installer downloaded and launched without client digest/signature/origin validation (`home_web.py:842–849`). | Validate an approved manifest origin and verified installer integrity/authenticity before execution. | No; separate manifest contract and client rollout. |
| 4 | high | Trello posting is not globally disabled (`pipeline_web.py:2536`, `trello_client.py:1731`, sync `core.ts:263`). | If no-post is the policy, add a single enforced write boundary with fake tests for all callers. | No, cross-client/server policy requires staged work. |
| 5 | med | Gateway/OAuth fetches have no explicit deadline (`companycam-gateway/index.ts:31,171`). | Add bounded fetch with explicit errors and no blind write retries. | Yes. |
| 6 | med | Popup outside-click closes editing surfaces (observed popup_click_retention failures). | Register guarded close callbacks per dialog and test unsaved-work refusal. | Yes, one dialog family at a time. |
| 7 | med | CI skips three scripts that now pass and hides changing failures (`.github/ci-skips.json`). | Remove proven stale exclusions, pin reproducible fixtures, and require dated reasons for remaining skips. | Yes. |
| 8 | med | Old clients cannot discover the new update hostname (`update_check.py:16`; historical 3f3ec66). | Document and test legacy GitHub manifest continuity before any feed migration. | Yes for compatibility contract; deployment separate. |
| 9 | med | Broad catches can erase diagnostic identity and errors (`pipeline_web.py:2511`; 2,046 candidate handlers). | Add sanitized logging at one critical save/identity boundary without changing success semantics. | Yes, narrowly scoped. |
| 10 | low | Large ignored release/build corpus and dynamic imports make cleanup unsafe (inventory; `Linguar_Hub.spec:82`). | Inventory/recovery-label artifacts and prove one candidate unused before any deletion or extraction. | Yes for inventory only; cleanup needs separate approval. |
