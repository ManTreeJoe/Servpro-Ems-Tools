# Shared comments: Daily Run and Snapshot

The Daily Run/Audit and Snapshot drawers now load the same Markdown renderer, rich editor, exact-card mention picker, and floating Trello reaction picker as Jobs. Quick Import loads the same shared assets/API as well; its workflow was not independently exercised.

- Bold, italic, strike, lists, quotes, links, plain-text paste and corrected placeholder behavior reuse the existing editor bundle.
- Read-division and multi-select Send-to pills use saved linked cards. Unavailable/conflicting destinations remain disabled; there is no fuzzy linking or auto-pinning. The starting card is the default recipient. Successful recipients are deselected on a partial failure; unconfirmed recipients require checking before retry.
- Mentions are scoped to selected destination card IDs. Reaction reads/writes are on demand through the existing verified Trello action/card handler.
- Text drafts persist per exact card in local browser storage. Switching cards restores the matching draft; a late send response cannot clear another card's composer. Drafts are removed only after all requested destinations confirm success.
- Reads, posting and attachment previews use the selected card ID rather than a customer-name pin. Legacy callers retain their default pin behavior.
- Refresh leaves loaded comments in place with a circular header spinner. Request tokens reject stale reads after switching jobs. No new polling or automatic Job Log imports were added.
- General-comment entry points from Add update and Snapshot now open the shared thread. Structured Job Log/site-visit/contract workflows remain separate and unchanged.

Validation: focused Python drawer, bridge, Snapshot isolation and comment-management tests; headless Edge checks for Daily Run and Snapshot sharing formatting, mentions, reactions, per-card drafts, division reads, partial posting and stable refresh. Screenshot inspected in dark theme. No customer comments or reactions were posted during tests. Not published or restarted as part of this change.
