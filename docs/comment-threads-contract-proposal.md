# Shared comments and threads — incremental implementation

Status: resumed by explicit user approval on 2026-10-06, including permission
to implement without waiting for L OPS. See the incremental contract below.

Date: 2026-10-06. Owner: OneLoss/shared backend.
Branch: `handoff/paperclip-source-20261003`.
L OPS web/mobile adoption remains a separate handoff. No Main release is authorized.

## First implementation contract (supersedes provisional names below)

Migration `20261006224224_shared_comment_threads.sql` adds shared annotations
and native replies to the existing exact-card feed. RPC `job_comment_threads`
takes `p_action`, `p_card`, `p_data`. Actions: read (200-row pages, `after`/`next`),
pin (id, pinned, expected), reply (parent, body, operation_id), claim and finish.
The authenticated `comment-parent` Edge Function now verifies the exact parent
directly with Trello and imports it without waiting for the background snapshot.
It checks user-scoped mirror RLS first, then verifies the live card board and
action/card association; client text/author names cannot establish identity. No
schema change is needed. Imported bodies
are labelled saved context in the thread, not proof the original still exists.

Every native reply has an app-owned `oneloss:<operation UUID>` identity, immutable
parent/root, authenticated author and durable delivery state. Card authorization
uses the mirror's enabled-source/all-required-departments boundary. All actions
fail closed; no fallback to an unlinked ordinary comment. Pins are card-shared.
Main clients do not consume these records and remain unchanged.

Reply-all: OneLoss adds the verified provider author's username and original
@mentions to the reply body, case-insensitively deduplicated against each other
and existing reply mentions, excluding the posting user's Trello username.
The same body is saved in OneLoss and sent to Trello. L OPS must adopt this
preparation step before calling the shared reply RPC. A pending native reply
without a provider mapping cannot yet supply verified provider-author context;
its draft is preserved rather than posting with guessed recipients.

The author's desktop claims delivery once and sends a normal Trello comment
with parent reference and operation marker. Uncertain results are never reposted;
later reads reconcile a unique exact marker/body from the server mirror. This
is not a server delivery worker: if the author closes before claiming, they
must retry their saved draft. OneLoss still retains the reply. Edit/delete of
native replies and dedicated reply-author notifications are follow-up work;
existing subscribed-member notifications are queued after confirmed delivery.

L OPS must paginate the shared records, merge native replies into the regular
feed, deduplicate provider_id/operation-marker echoes, leave chronological order
unchanged by pins, and offer a separate thread projection. Keep existing cached
content on shared-read failure. Do not infer threads from old @mentions. Future
provider-independent conversation/job mapping requires a coordinated migration;
this increment deliberately retains exact Trello-card conversation scope.

## Verified starting point

Read-only inspection of OneLoss project `oqwwapqnzzhefqxobadl` found
`public.hub_trello_mirror_cards`, but no `crm_pipeline_cards` or
`crm_pipeline_activity` tables. `pipeline_store.add_activity` returns an empty
result on storage failure; `PipelineApi.post_job_comment` then falls back to
Trello. Do not build thread identity on the assumption that this optional
activity store exists. The local SQLite comment projection is a read cache,
not a shared or durable thread authority.

## User-visible contract

- Every reply appears in the normal chronological feed, never thread-only.
- Reply targets one exact comment. A preview and View thread open its related
  conversation without replacing the draft or losing the feed position.
- Old @mentions do not establish relationships automatically.
- The thread view includes root plus descendants, with pagination; it must not
  mistake the currently loaded feed page for the entire thread.
- Trello receives a normal comment with a readable reply reference. OneLoss
  owns the relationship. A plain Trello reply/mention stays unthreaded unless
  a verified OneLoss publication mapping establishes its parent.

## Proposed identities and records

Use a dedicated comments module; do not install the entire optional legacy CRM
schema just to enable replies. Names below remain provisional.

`job_conversations`: UUID identity, department, canonical OneLoss job UUID,
division and placement identity. Initially map the exact Trello workspace/card
pair, but retain an app-owned identity after Trello retirement. WIP and
Estimating placements have separate conversations; no name-based joins.

`job_comments`: UUID identity, conversation UUID, nullable parent UUID, nullable
root UUID (roots identify themselves), body, authenticated author UUID for
native comments, separate provider actor identity for imported comments,
created/edited/deleted timestamps, and revision. Parent/root must be in the
same conversation. Reject cycles and attempts to alter parents after creation.
Keep deletion tombstones so remaining replies still have intelligible context.

`comment_provider_links`: comment UUID, provider/workspace/card/action identity,
unique provider action mapping. A Trello echo maps to its existing native
comment rather than creating another feed entry. Don't turn a Trello actor
name into an authenticated app user identity.

`comment_delivery`: durable outbox with unique operation UUID, comment UUID,
destination and delivery state. Creation of comment and outbox is atomic.
Retries reuse the operation ID. A timeout is uncertain delivery, not proof of
failure; reconcile before reposting. Persist confirmed provider action IDs.

## API and access requirements

- Paginated read by conversation/cursor, paginated thread read, delta updates
  including tombstones, and create/edit/delete commands with operation IDs.
- Server validates the author from authentication, conversation membership,
  franchise/job scope, parent access, and expected revision. Client-supplied
  author IDs and department labels are not authorization.
- RLS on every exposed table, deny anonymous access, and explicit grants.
  Only approved worker paths may write provider identities/delivery outcomes.
- Failed/partial provider reads cannot delete saved comments. Apply provider
  deletions only from explicit deletion events or verified complete snapshots.
- Local cache -> shared saved feed -> background provider refresh. No blank
  replacement on network failure. Refreshes are scoped and deduplicated.
- Notification recipients: original author and explicit mentions, plus existing
  subscribed-member rules; exclude self and deduplicate by comment/recipient.
  Notifications link to the exact comment and conversation.

## L OPS decisions required

Confirm the shared source project and mapping of L OPS users/jobs/placements
to OneLoss identities. Do not assume the two apps use matching UUIDs. Agree
the API, permissions, pagination, outbox ownership and notification ownership.
Record accepted changes in `docs/l-ops-platform.md` before writing migrations.

## Required release checks

Cross-franchise denial; author spoofing denial; invalid/cross-card parent
rejection; retry/echo deduplication; delayed cache cannot overwrite live edits;
parent deletion; thread pagination; simultaneous edits; two-user visibility;
Trello outage/recovery; native and imported comments together; old Main clients
continue to work. Never silently fall back to an unlinked ordinary comment
when the user submitted a threaded reply.
