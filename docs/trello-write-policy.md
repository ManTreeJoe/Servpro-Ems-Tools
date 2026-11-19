# Trello write policy

All desktop Trello HTTP requests pass through `trello_client._guarded_urlopen`; `_call` and multipart upload also check before credential reads or local write bookkeeping. Mutating methods are disabled unless the operator explicitly sets `ONELOSS_TRELLO_WRITES_ENABLED=true`. Missing, misspelled, uppercase or truthy-looking values do not opt in. Isolated Dev remains blocked even with that opt-in.

The server runtime has the same policy in `_shared/trello-write-guard.mjs`. Sync reads and comment mirroring use that transport. `TRELLO_EMS_COMMENTS_ENABLED=true` alone cannot enable posting. The read-only comment-parent gateway supplies no write opt-in. No server secret/flag/deployment is changed by this PR.

This disables ALL mutations by default, including creates, comments, edits, deletes, checklist updates, attachment uploads and notification read acknowledgements. Local OneLoss saves are not disabled. Pending delivery can remain queued; do not enable writes without reviewing the backlog and retry behavior first. Some legacy public helpers catch errors and return None/False; denial never means provider success.

Python and JavaScript require separate runtime implementations of one policy; they share the exact flag and fail-closed semantics. Focused tests cover both. A source regression check rejects new Trello endpoint owners and desktop raw HTTP calls outside the guarded transport. It is a review tripwire, not proof against dynamically constructed/obfuscated endpoints or arbitrary future network libraries. Provider tests must explicitly opt in with fake transports when testing successful writes; no live credentials belong in tests.
