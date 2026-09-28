# Trello comment reactions — DEV, 2026-09-28

Implemented real Trello action reactions, not local-only emoji decoration.

## Behavior

- `React` appears beneath comments with a real Trello action ID, including app-posted comments with an external ID.
- Opening it reads current reactions and shows the connected Trello account. Six quick choices: thumbs up, heart, smile, celebrate, eyes, check. Existing other emoji also appear.
- Select to add your reaction; select your active reaction to remove it. Counts and names come from Trello. Another person's reaction cannot be removed by the app.
- No extra requests while comments load. Reads happen on opening the control or pressing Refresh reactions. Counts are not automatically polled or displayed before opening. This is a deliberate first-version performance tradeoff, not full Trello UI parity.
- Local comments without a Trello action do not offer this control. No local-only fallback, queued reaction, Job Log import, or database migration.

## Safety and implementation

`job_comment_reactions.py` verifies the action type and exact card, then reads the connected Trello member. Writes accept desired state, not blind toggle, and check fresh reactions first. A process-local nonblocking lock prevents simultaneous reaction writes. Requests have five-second per-request timeouts and no automatic retries. A write uses up to four provider requests; the timeout is per request, not a total operation deadline.

After a write, the app reads confirmed provider state. Any timeout/error hides mutation choices until a fresh read succeeds; it never claims an uncertain write failed to reach Trello. Provider exception URLs are not exposed. The existing durable Trello write barrier remains in place.

UI uses existing comment styling, keyboard-accessible buttons, counts, selected states, a connected-account label and inline error/retry feedback. Escape closes the reaction panel before the job modal. Requests completing after a comment is replaced do not alter its replacement or another division. Reopening reloads provider state; no persistent reaction cache.

API references: [action reactions](https://developer.atlassian.com/cloud/trello/rest/api-group-actions/) and [nested reactions](https://developer.atlassian.com/cloud/trello/guides/rest-api/nested-resources/).

## Verification and manual check

Mocked backend tests cover add/remove, idempotent retry, other-member preservation, wrong-card/input rejection, sanitized uncertain-write handling, read-only behavior and JSON/form transport compatibility. Browser checks cover actual comment rendering, no initial requests, toggling/counts, errors/retry, keyboard close and rerendered comments. Existing division, loading and mention regressions also pass.

Live Trello writes have NOT been exercised against customer comments. Not published or restarted yet.

After a DEV restart, on a safe test comment:
1. Open React and verify the connected account name.
2. Add thumbs up. Open the same comment in Trello and confirm the reaction and account.
3. Click thumbs up again; confirm it disappears in Trello without deleting anyone else's reaction.
4. Add a reaction in Trello, then Refresh reactions in OneLoss.
5. Switch EMS/Contents/Recon and confirm each reaction belongs only to its exact comment/card.
