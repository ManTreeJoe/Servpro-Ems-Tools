# OneLoss 1.8.49 release contents

This release must be built fresh from published Main after the final release commit. The previous quarantined candidate is retired and must never be distributed or reused.

Included work:
- #12: Microsoft sign-in, pending approval, server-assigned franchise/roles, separate emergency administrator recovery.
- #18: repaired access fixtures and Microsoft-flow tests; approval SQL runs in CI.
- #15: backend administrator checks and employee settings secret redaction.
- #16: one owner per connection/folder/account setting; legacy launcher settings retained.
- #17: grouped settings, People & access approvals, and advanced action confirmations.
- Release correction: successful Settings sign-out reloads the shell into admission; failed sign-out leaves the screen intact.

#18 and #15 were merged into Main with merge commits. #16 and #17 originally targeted their stacked feature branches; their heads are integrated into Main in that order using explicit merge commits. Verify ancestry and the first-parent log before building.

The final release receipt must record Main's full source commit, merge hashes, installer SHA-256, and results from testing that exact package: Microsoft login, pending denial, People & access approval, emergency recovery, and non-admin secret redaction. Do not publish until those checks pass. Keep server-wide Microsoft-only enforcement off until the team has updated; keep the GitHub 1.8.48 transition feed available.
