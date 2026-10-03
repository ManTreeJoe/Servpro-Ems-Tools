# Windows CI and downloadable builds

The **Windows tests and build** workflow runs on pushes to every branch, pull
requests targeting `main`, and manual runs. Its independent Windows tests and
Windows PyInstaller build jobs both must be green before review approval.
Python 3.12 and Node 22 are used; pip and npm download caches are enabled.

Tests install `python -m pip install -r requirements.txt pytest openpyxl==3.1.5` and `npm ci`,
then run `python -m pytest tests/ -ra --junitxml=pytest-results.xml` and
`node tests/<filename>.cjs` for each top-level script. Each nonzero script exit
fails the job, while the loop continues to report all failures. Pytest results
are also uploaded for review. Browser tests use the runner's installed Edge;
no Playwright Chromium binary download is needed.

The pytest step sets `LINGUAR_CI=1`. `.github/ci-skips.json` records every
CI-only Python module/test and Node script skip with its specific reason.
Pytest reports module skips during collection and individual test skips in
its summary; the Node loop prints each script skip. Normal local pytest runs
do not apply this policy. `openpyxl` is installed as an additional test dependency
because the legacy spreadsheet tests import it.

Explicit scope exclusions:

- `tests/shell_startup_styles.cjs`: requires `DEV_TEST_URL` and a live dev server;
  CI provides neither. The loop prints this skip reason in each run.
- `tests/server_sync_db/`: separate package, dependency lockfile, and runner;
  outside this workflow's top-level `tests/*.cjs` scope. No tests are deleted.

The build follows `build.bat`: install `requirements-build.txt`, run
`pyinstaller --noconfirm Linguar_Hub.spec`, and copy `README.txt` beside the EXE.
Before tests and packaging, CI generates an unconfigured seed with the existing
`make_shipped_config.build({})` policy and audits it. It contains only blank
personal tokens and the system appearance setting; no live settings are read.
The board approved this smoke-test artifact: shared franchise, Supabase, Trello,
and paths must be configured in Settings before connected workflows can work.
It is not a configured franchise release. The existing spec is unchanged. The complete application folder is zipped and
retained as `Linguar-Hub-<branch>-<short sha>` for 14 days. Branch slashes become
hyphens. CI uses no repository secrets or live client configuration.

## Download and try a build on the Windows laptop

1. Sign in to GitHub in your browser with access to the private
   `ManTreeJoe/Servpro-Ems-Tools` repository.
2. Open **Actions**, select **Windows tests and build**, and open the green run
   for the branch/commit you want to test. Check that both jobs passed.
3. Scroll to **Artifacts** on the run summary and click the
   `Linguar-Hub-<branch>-<short sha>` artifact (not `pytest-results`).
4. In File Explorer, use **Extract All** on the downloaded artifact ZIP. Extract
   the application ZIP inside it too. Open the resulting `Linguar Hub` folder.
5. Confirm `Linguar Hub.exe` and `_internal` are beside each other. Keep the whole
   folder together and launch the EXE from the extracted folder, not the ZIP.
   No GitHub CLI, Python installation, or admin install is required to extract
   the build. Existing company Windows execution policies still apply.
6. Report the run URL, commit, and observed behavior to the Chief of staff.

Expired artifacts require a new workflow run: **Actions → Windows tests and
build → Run workflow**, select the branch, and wait for both jobs to finish.
