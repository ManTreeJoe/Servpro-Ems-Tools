# Windows CI and downloadable builds

The **Windows tests and build** workflow runs on pushes to every branch, pull
requests targeting `main`, and manual runs. Its independent Windows tests and
Windows PyInstaller build jobs both must be green before review approval.
Python 3.12 and Node 22 are used; pip and npm download caches are enabled.

Tests install `python -m pip install -r requirements.txt pytest openpyxl==3.1.5 pypdf` and `npm ci`,
then run `python -m pytest tests/ -ra --junitxml=pytest-results.xml` and
`node tests/<filename>.cjs` for each top-level script. Each nonzero script exit
fails the job, while the loop continues to report all failures. Pytest results
are also uploaded for review. Browser tests use the runner's installed Edge;
no Playwright Chromium binary download is needed.

The pytest step sets `LINGUAR_CI=1`. `.github/ci-skips.json` records every
CI-only Python module/test and Node script skip with its specific reason.
Pytest reports module skips during collection and individual test skips in
its summary; the Node loop prints each script skip. Normal local pytest runs
do not apply this policy. `openpyxl` and `pypdf` are additional test dependencies for the spreadsheet
and rendered-PDF contracts.

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
It is not a configured franchise release. The existing spec is unchanged. The complete application folder is uploaded directly (GitHub creates one download ZIP) and
retained as `Linguar-Hub-<branch>-<short sha>` for 14 days. Branch slashes become
hyphens. Packaging uses no live client configuration. Trial publishing alone uses the optional releases token described below.

## Download and try a build on the Windows laptop

1. Sign in to GitHub in your browser with access to the private
   `ManTreeJoe/Servpro-Ems-Tools` repository.
2. Open **Actions**, select **Windows tests and build**, and open the green run
   for the branch/commit you want to test. Check that both jobs passed.
3. Scroll to **Artifacts** on the run summary and click the
   `Linguar-Hub-<branch>-<short sha>` artifact (not `pytest-results`).
4. In File Explorer, use **Extract All** once on the downloaded artifact ZIP.
   Open the extracted folder; it directly contains the EXE and `_internal`.
5. Confirm `Linguar Hub.exe` and `_internal` are beside each other. Keep the whole
   folder together and launch the EXE from the extracted folder, not the ZIP.
   No GitHub CLI, Python installation, or admin install is required to extract
   the build. Existing company Windows execution policies still apply.
6. Report the run URL, commit, and observed behavior to the Chief of staff.

Expired artifacts require a new workflow run: **Actions → Windows tests and
build → Run workflow**, select the branch, and wait for both jobs to finish.

## Trial installer and updater

1. Open **Actions → Windows tests and build → Run workflow**, select the
   desired branch, and run it. The **Trial installer** job runs only on manual
   dispatch and waits for **Windows tests** to pass.
2. Download the `Linguar-Hub-Trial-Setup-<base>-trial.<run_number>` artifact.
   Its download ZIP contains one Setup EXE. Extract it once and run it to
   install for your Windows user without an admin prompt. Trial installs
   alongside Main. These CI builds use the unconfigured seed described above.
3. Inno Setup is located from the runner's installed Program Files directories.
   CI passes the absolute `dist/Linguar Hub Trial` source directory explicitly
   because the script's local default is `..\dist`. The installer is checked at
   `Output/Linguar-Hub-Trial-Setup-<version>.exe`; its resolved path is written
   to the run summary. Only the packaged `_internal/version.txt` is stamped
   with the Trial version; the source manifest and spec remain unchanged.
4. The installer artifact uploads before publishing. With no
   `RELEASES_REPO_TOKEN`, the summary says **Skipping publish, secret not
   configured** and the installer remains downloadable for 14 days.
5. Once the board configures that secret, the same job creates a draft
   prerelease in [linguar-hub-releases](https://github.com/ManTreeJoe/linguar-hub-releases/releases),
   uploads and checks the installer's size and SHA-256, publishes the prerelease
   without marking it Latest, then updates `trial/version.txt` on that repo's
   `main` branch. Both Main and Trial check their public channel feed on launch;
   Trial's **Update available** banner delivers subsequent test builds without
   a separate application ZIP/unzip process.

The job exposes the secret as a job-level environment variable; publish and
skip steps test `env.RELEASES_REPO_TOKEN`, not `secrets.*` in their conditions.
The board must create the public releases-only repo and seed `main/version.txt`
and `trial/version.txt` on its `main` branch. It must then add the private code
repo's `RELEASES_REPO_TOKEN` Actions secret: a fine-grained PAT scoped only to
the releases repo with **Contents: Read and write**. CI does not create these.

## Stable release publishing

Stable installers and the public `main/version.txt` feed now live in
`ManTreeJoe/linguar-hub-releases`, not the private code repository. On the
board's publishing machine, use the existing Git credential helper and manual
publisher (which still uses its existing `requests` dependency):

```powershell
python tools/publish_desktop_release.py draft --version 1.8.26 --commit <source-sha> --installer <Setup.exe> --notes <notes.txt>
python tools/publish_desktop_release.py publish --version 1.8.26 --commit <source-sha> --installer <Setup.exe> --notes <notes.txt>
```

Use identical arguments for both commands. The draft step uploads and verifies
size/hash; publish checks the matching draft and asset again before making it
public and updating `main/version.txt` through the Contents API. A mismatched
asset leaves the draft unpublished; neither command overwrites an existing
asset. The source SHA is recorded in release notes. The release tag targets the
releases repo's `main`, since private source commits do not exist there.
The credential must have write access to the releases repo. The root
`version.txt` in this code repo remains the bundled application version.

Feed updates occur after release publication. If a Contents API update fails,
the release may already be public while the feed remains unchanged; repair the
channel manifest on the releases repo's `main` branch after verifying the asset.
For rollback, install a known-good installer from that public repo and restore
its channel manifest there so the faulty update is no longer offered.
Already-installed builds using the old feed need a one-time upgrade arranged
by the board before they can discover this new feed.
