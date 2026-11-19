# 1.8.48 updater source recovery

Recovered from ignored local `Output/private-updates-transition-20261119/`:
- `update_check.py`: Main private-metadata preference and GitHub fallback; Trial GitHub-only.
- `home_web.py`: only the private-download browser handoff block, not the rest of the snapshot.

Also present in `Output/source-main-1.8.48-private-updates/`. The transition directory includes an integration report marking that prepared patch unbuilt/unpublished. This PR does not assert the state of any deployed feed and makes no server, route, version-manifest or release changes.

The public metadata contains a checksum, but this code checks its format only; it does not authenticate the manifest or verify the browser-downloaded executable. Private installation remains an employee browser/download action. The existing GitHub installer flow is retained. Installer signature/integrity hardening remains a separate requirement before automatic rollout.

Older clients have no private-feed preference and still need their original GitHub manifest maintained. Do not replace that manifest with a private-only installer URL for clients that try to download/execute it directly. Rollout and compatibility verification are not authorized by this recovery PR.

Tests use fake HTTP responses and an extracted method with a fake browser opener. No feeds, browser sign-in, installer or app launcher is contacted/run.
