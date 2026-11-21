# OneLoss agent guide

## Safety and scope

This repository is the existing **Windows desktop app**, not the separate web/mobile project. Python hosts pywebview HTML/JS panels; older Tk tools still have callers. There is no Vite/Next dev server or root npm build script.

**Dev is not proof of safe data.** The explicit source launcher fences Python HTTP to a hosted test project and loopback; it is not an OS sandbox, does not fence browser traffic, and does not prove that the hosted project's records are synthetic. Main/Trial can access live records, provider connections, Outlook, and shared drives. Never launch Main, read mail, modify providers/servers, deploy SQL, drain queues, publish installers or alter release feeds without explicit task authorization. Keep Trello writes off; a write pause does not block reads. The 1.8.49 release is held for Defender review: a passing CI build does not clear it for distribution.

Use a clean `codex/<issue>` branch/worktree from current `origin/main`. Preserve unrelated local changes. Never reset, stash, clean or delete another person's work. Do not import application modules merely to inspect them: `paths.py`, configuration and database modules have import-time effects.

## Setup and exact commands

Use Windows, Python 3.12, Node 22, npm, Git and Microsoft Edge/WebView2. From the repository root in PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
npm ci
```

`requirements-dev.txt` includes runtime/build dependencies, pytest, openpyxl (already explicitly installed by legacy CI), and mypy. Root Node dependencies are test-only Playwright and PGlite. Do not run npm install just to refresh a lockfile.

Development launch, **only after verifying the Dev profile and test backend are safe for the task**:

```powershell
$env:ONELOSS_TRELLO_WRITES_ENABLED = 'false'
python tools/launch_notification_shell.py IsolatedDev
```

`Dev` is also accepted and uses the same fence. No argument or unknown modes fail closed. `dev_runtime.py` defines the allowed test host; do not substitute a live endpoint. `home_web.py` is the packaged entry point; running it directly bypasses explicit launcher-mode selection. No app launch is needed for source checks or synthetic browser tests.

Checks (run from the root):

```powershell
python dev_lint.py
python .github/agent_checks.py typecheck
python .github/test_ci_policy.py
python .github/test_agent_workflow.py
$env:LINGUAR_CI = '1'
$env:ONELOSS_TRELLO_WRITES_ENABLED = 'false'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
python -m pytest tests/ -ra --junitxml=test-results/pytest.xml
python .github/agent_checks.py node-tests
python -m PyInstaller --noconfirm --distpath dist-ci --workpath build-ci Linguar_Hub.spec
```

Run tests/builds in a disposable Windows runner or reviewed isolated environment with no credentials, host profiles or shared drives. `tests/conftest.py` redirects APPDATA but is **not** a network sandbox. CI uses an unconfigured `_packaging/config.json`; never build from your personal config. Locally, prepare the same seed in a disposable checkout only:

```powershell
python -c "import json; from pathlib import Path; Path('_packaging/config.json').write_text(json.dumps(dict(trello_token='', companycam_api_token='', appearance='system')), encoding='utf-8')"
```

Do not commit this generated seed change. It is tracked packaging input, not a developer settings file. Build does not mean install, execute, sign, publish or release. Do not use `build.bat` for a read-only review; it has other side effects.

Lint is the existing Tk/scandir rule checker, not a general formatter. The new mypy gate checks tracked root Python modules with `--check-untyped-defs --follow-imports=skip --ignore-missing-imports`; it does not cover all JS, nested Python or Deno. Node runner executes top-level `.cjs` and `.mjs` tests with a 120-second per-script limit and the existing reviewed `.github/ci-skips.json`. Do not expand skips or suppress errors to get green CI. Existing lint/type/test debt may block this initial workflow: report exact failures and keep the PR draft rather than claim success.

The comment editor has its own locked build, needed only for changes there:

```powershell
npm --prefix tools/comment-editor ci
npm --prefix tools/comment-editor run build
```

## Project structure

Root `*_web.py` files expose pywebview APIs. Root service modules implement jobs, configuration, provider clients, notifications and persistence. `home_web.py` binds panel APIs; `launcher.py` is the legacy Tk launcher. `Linguar_Hub.spec` and `.iss` define packaging. `version.txt` is source release metadata, not permission to update a live feed.

| Folder | Purpose |
| --- | --- |
| `.github/` | CI, reviewed skip policy, agent contracts and templates. Legacy `windows.yml` remains; this PR does not dispatch its Trial publisher. |
| `.local-test-tools/` | Older auxiliary Node dependency manifest; root package/lock is the CI authority. |
| `_one_shot/` | Historical repair/import scripts; potentially destructive, never auto-run. |
| `_packaging/` | Shipped configuration generator and sanitized packaging inputs. |
| `bulletin_watch/` | Separate bulletin watcher and its non-secret source configuration. |
| `deploy/` | Employee-access server administration/deployment scripts; not test fixtures. |
| `docs/` | Design, migration, operations and release documentation; verify historical claims against code. |
| `form_templates/` | Application PDF templates and provenance notes; do not flatten/sanitize blindly. |
| `supabase/` | SQL/migrations, configuration and edge functions; never apply to live as part of CI. |
| `tests/` | Python, synthetic DOM/browser and in-memory SQL tests. |
| `tools/` | Developer utilities, explicit source launcher, publishing and comment-editor source; inspect before execution. |
| `web_shared/` | Shared browser utilities, styles and vendored assets. |
| `analytics_web_assets/`, `kpi_web_assets/` | Analytics and KPI panels. |
| `apa_web_assets/`, `audit_web_assets/`, `wc_audit_web_assets/` | APA, audit and Workcenter audit panels. |
| `automations_web_assets/`, `health_web_assets/` | Workflow automation and health panels. |
| `cheat_sheet_web_assets/`, `resources_web_assets/` | Reference/help and resources. |
| `clients_web_assets/`, `multi_unit_web_assets/` | Client and multi-unit management. |
| `disputes_web_assets/`, `exceptions_web_assets/`, `hygiene_web_assets/` | Dispute, exception and operational hygiene panels. |
| `home_web_assets/` | Shell, sidebar, admission and setup wizard. |
| `job_notes_web_assets/`, `job_reconciliation_web_assets/` | Job notes and identity/link reconciliation. |
| `native_boards_web_assets/`, `pipeline_web_assets/` | Native boards, Jobs board and job card UI. |
| `notifications_web_assets/`, `operations_web_assets/` | Notifications and operations overview. |
| `photo_folders_web_assets/`, `quickimport_web_assets/` | Photo folder and import tools. |
| `run_doc_editor_web_assets/` | Daily Run and schedule editor. |
| `settings_web_assets/` | Settings, role-specific layout and access approvals. |
| `snapshot_web_assets/`, `spreadsheet_web_assets/` | Snapshot/document and spreadsheet tools. |

Generated `build*`, `dist*`, `installer*`, `Output/`, `node_modules/` and `test-results/` are not source. Ignore rules do not untrack existing files or authorize deletion. Keep old releases intact.

## Conventions and change rules

- Match surrounding code: Python four-space indentation, snake_case functions, `Api` classes; browser JS is mostly plain DOM code and pywebview bridge calls. Preserve public API method names and persisted config keys. Avoid broad reformatting.
- Keep each PR small and focused on one issue. Add/update meaningful tests for every change, including failure, permission and retry cases. Use fake providers and synthetic customer data. Do not use a real account to make tests pass.
- Run lint, typecheck, tests and build before opening a review-ready PR; fix regressions. If a baseline failure or environment limitation prevents success, record it and open only a clearly marked draft. Never hide failures with `continue-on-error`, new skips or weakened assertions.
- Never commit secrets, personal profiles, `.env` files or customer records. `.env.example` is names-only reference, not production configuration; this app does not automatically load dotenv. Never paste credential values into logs, PRs or screenshots.
- Do not edit lockfiles by hand. Add dependencies only when needed and explain why in the PR; regenerate the matching lockfile with the package manager. Do not touch unrelated files.
- Never turn off access checks or Trello guards. Server-assigned franchise permissions are authoritative. Handle errors explicitly; do not silently fall back from Dev to Main or claim saved credentials prove connectivity.

## Pull requests and Codex review

Title: concise imperative, e.g. `fix: preserve pending notification on failed lookup`.
Body: short summary of what changed and why, focused change list, exact test commands/results, and `Closes #<issue>` with a real issue number. If no issue was supplied, state that; never invent one. Explain dependencies, skips and unverified behavior.

Review guidelines: flag correctness bugs, security/privacy issues, missing tests, broken edge cases, permission/environment leaks and violations of this guide. Give file/line evidence and practical impact. Skip pure style nitpicks. Check provider failures, malformed bridge responses, duplicate requests, role changes and queue retries. Do not accept test passes as malware clearance or permission to publish.

The `ci` job is intended as a required check. Repository administrators must enable branch protection and Codex automatic review separately; adding this file does not enable those account settings or grant agents merge/release permission.
