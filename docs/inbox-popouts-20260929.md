# Inbox navigation and contextual pop-outs

## Implemented

- Sidebar tool right-click → Open in new window. Job board card, Stages row,
  and opened job title offer the same command. No new visible toolbar buttons.
- Native pywebview child windows use the same login/data with independent panel
  API objects. Only the selected tool's API is initialized. One registry avoids
  duplicate windows for a tool/card. Closing a pop-out does not close the main
  window. Opening one does not remove or re-render the original tool or draft.
  Existing job draft persistence/version checks remain in place; unsaved forms
  are not copied automatically. Native child close requires confirmation.
- Workspace switches are blocked while child windows remain open, avoiding
  a mix of old workspace views and newly scoped API calls.
- Notifications use bounded, formatted two-line previews. Read message opens
  a keyboard-dismissible reading pane. Reduced-motion is honored. Loading
  preserves the existing feed. New workspace/reader transitions are 150–160ms.
- Clicking a Trello notification resolves its exact saved card link, selects
  its division, then scrolls to/highlights its exact action ID. If not already
  in the loaded conversation, one bounded read fetches that action and verifies
  it belongs to the same card. It never imports Job Logs or changes links.
- Missing/ambiguous/inaccessible job links or missing comments show an explicit
  Trello fallback; no customer-name guessing. Live read confirmed Trello returns
  `idAction` separately from notification `id`; the latter is never used as a
  comment ID. A sampled unlinked live notification correctly failed closed.

## Verification

21 focused Python tests passed, covering duplicate windows, independent APIs,
URL/context construction, exact card/comment identity, wrong-card rejection,
and existing personal-notification/drawer behavior. Browser tests passed for
compact previews, safe Markdown, reading pane, missing-link fallback, exact
navigation payload, reduced-width layout, contextual pop-out and preserved
source text, comment highlighting, and the personal inbox. Desktop/narrow
screenshots were inspected. No customer comment, assignment or notification
state was changed in testing.

Uses existing shared-link read permissions; no database migration or policy
change. Trello reference: https://developer.atlassian.com/cloud/trello/rest/api-group-notifications/

Limitations: pop-outs retain their own form state rather than transferring an
open form from the main window. If a card pop-out has switched to another card,
a later notification will not discard that work to force navigation. It asks
the user to finish the current draft. Cross-tool workflows such as Snapshot
creation return to the main shell. Native window controls require DEV acceptance
testing in addition to the mocked window lifecycle tests.
