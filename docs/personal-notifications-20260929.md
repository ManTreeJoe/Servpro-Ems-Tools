# OneLoss job membership and personal inbox

## Scope

Job Overview → Members manages native OneLoss membership. Assignments use the
shared canonical job, so a linked WIP/Estimating copy does not create a second
membership list. Members must already have department and source-board access.
Membership does not grant permissions. Trello memberships remain separate.

Notifications defaults to My OneLoss inbox, not the connected Trello account.
The other source is explicitly labelled Connected Trello account. Native inbox
supports All activity, @mentions, My jobs, unread-only, read/unread, Open job and
mute/unmute. Read state and mute are shared across PCs. Mute includes mentions
and does not remove existing notifications. Only the latest 100 matching items
are displayed. Refresh is explicit; there is no new polling loop, OS push or
email delivery in this slice.

Mention suggestions distinguish OneLoss from Trello. Native people receive
stable `ol.<email-local-part>.<id-prefix>` handles; names remain the searchable
display labels. Handles are deliberately separate from Trello usernames: no
automatic cross-account mapping or impersonation. Raw Trello comments posted
outside OneLoss remain in the separate Trello account feed, not the personal
OneLoss inbox. New OneLoss comments from Jobs, Daily Run and Snapshot notify
members and explicitly mentioned native people. Historical comments are not
backfilled. Other automated/canned posting paths are not event producers here.

## Reliability and authorization

`personal_notifications.py` owns the bridge and a local SQLite delivery outbox.
Only confirmed comment IDs enqueue. Pending notifications are retried in bounded
batches after a new comment or opening/refreshing Notifications. A failure never
reposts the comment. Pending count is visible in the inbox. Queues are scoped to
the original signed-in user; the database also rejects an actor mismatch.
An unavailable shared link is retained for retry, not silently re-linked by name.

Migration `20260929180516_oneloss_personal_notifications.sql` was applied only to
Linguar Hub (`oqwwapqnzzhefqxobadl`). Private tables store membership, preferences,
handles, event deduplication and inbox records. Clients have no table privileges.
The public SECURITY INVOKER RPC delegates to a narrowly scoped private function
that checks identity and current job/board access on every operation. Display
metadata is used only for names, never permissions. Recipient selection excludes
the author and muted/inaccessible users. An event is processed once even if the
response is lost or membership changes before replay.

## Verification

- `supabase/tests/personal_notifications.sql`: real database transaction with
  synthetic users/job/card, then rollback. Membership, duplicate membership,
  mention classification, replay, mute, own-only read state, private-table denial,
  unauthorized assignments and directory reads, actor spoofing, and revoked
  department access passed. No real customer record or notification was created.
- 41 focused Python tests passed (outbox, shared comment API, display-name and
  existing posting behavior, Trello mention lookup).
- Browser: Members successful/failed saves, rollback of checkbox on failure,
  keyboard close, inbox open/read/unread/mute/filter/error states, desktop and
  390px layouts passed; screenshots inspected.
- Existing comment mention keyboard/cache/destination tests passed, including
  native suggestions when Trello fails. Daily Run/Snapshot shared comment tests
  passed (formatting, reactions, drafts, multi-post and stable refresh).

Advisors show no new exposed-function warning or missing notification foreign-key
index. Private tables deliberately have RLS without policies and no client table
grants ([RLS notice](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy)).
The checked RPC is the only access path. Newly added FK indexes may be reported
unused until traffic arrives. Existing unrelated admin-function and password
protection warnings remain unchanged ([function review](https://supabase.com/docs/guides/database/database-linter?lint=0029_authenticated_security_definer_function_executable),
[password protection](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection)).
Authorization follows the current [Supabase RLS guidance](https://supabase.com/docs/guides/database/postgres/row-level-security).

DEV restart and packaged release have not been performed for this change.
