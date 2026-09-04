# Linguar Hub UI Control Audit

Status: Trial-first working standard. This audit uses Job Audit’s compact button language and the Client → Job → Division → Work Period structure.

## Shared control foundation

All 24 web workspaces load `web_shared/workspace_controls.css`. That shared layer now owns the workspace header, action row, canonical buttons, primary action, menu stacking, modal action alignment, and status bar. Individual tools still own their content layout and workflow-specific controls.

The placement contract is:

- Header left: workspace identity and view.
- Header right: search/filter, one primary action, routine actions, refresh, then `More`.
- Job workspace: identity, division, update actions, Job Info, connected systems, then `More`.
- Modal footer: safe exit first, committing action last; destructive actions separated and confirmed.

Configuration, export, bulk maintenance, and specialist actions belong in `More`. Primary work must stay visible and must never require right-click.

Remaining cleanup should remove local duplicate control rules as each panel is touched. Settings, Snapshot, and legacy specialist tools contain the largest amount of inline presentation code; migrate those styles into named local classes without changing their workflows.

## Naming map

| Area | Use | Avoid |
|---|---|---|
| Client records | Clients | Job Audit as a destination name |
| Active operational cards | Jobs | Pipeline in user-facing copy |
| Today’s dispatch document | Daily Run | Run doc when naming the destination |
| Editing today’s document | Daily Run Editor | Run Doc Editor |
| File/compliance check | Check or Recheck | Audit when the user only needs the result |
| Closeout PDF workflow | Snapshot | Generate when Create is clearer |
| Lifecycle refresh | Update Stages | Sync lifecycle |
| System troubleshooting | System Health | Data & Sync Health |

Technical terms may remain in logs and administrator diagnostics. User-facing controls should name the result.

## Primary navigation

| Tool | Decision | Reason |
|---|---|---|
| Jobs | Keep first | Main operational board and active-work source |
| Daily Run | Keep directly under Jobs | Today’s scheduled work |
| Clients | Keep | Account, contact, claim, and history lookup |
| Snapshot | Keep | Established office term for closeout |
| Daily Run Editor | Renamed | Distinguishes viewing/checking from editing |
| APA | Keep | Established company term |
| Exceptions | Keep | Cross-workflow items needing intervention |
| Billing Disputes | Renamed | “Disputes” alone did not say what kind |
| Forms & Resources | Renamed | States what users will find |
| System Health | Renamed | Shorter and task-oriented |

Hidden-by-default specialist tools should remain available in Settings rather than crowding the sidebar: Photo Folders, Notifications, Hygiene, KPI, WC Audit, Spreadsheets, Job Notes, and Multi-Unit.

## Controls changed in this pass

- Jobs: `Customize` → `Board Appearance`
- Jobs: `Sync Jobs` → `Refresh Jobs`
- Jobs: `Thresholds` → `Stage Deadlines`
- Jobs: `Export` → `Export Stages`
- Jobs: `Sync lifecycle` → `Update Stages`
- Snapshot: `Queue` → `Closeout Queue`
- Snapshot: `Manual snapshot` → `New Snapshot`
- Snapshot: `Generate PDF` → `Create Snapshot PDF`
- Daily Run: `Run Audit` → `Check Daily Run`
- Daily Run: `Open run-doc` → `Open Daily Run`

## Placement rules

- Keep the top row for frequent actions only: create/update, copy, open core systems, and refresh.
- Put configuration and exports under `More` unless they are the page’s primary job.
- Do not place Daily Run actions in Clients or client-directory actions in Daily Run.
- Keep destructive actions behind confirmation or undo.
- Never require right-click; context menus may provide shortcuts only.
- Never hide routine actions in horizontal scrolling containers.
- Use one `Copy` menu when 3 or more copy targets exist.

## Keep, move, or remove next

| Control | Recommendation |
|---|---|
| Open legacy app | Keep in Support tools during migration; remove after 2 stable Main releases |
| Global refresh | Keep bottom-left; rename tooltip to `Refresh current screen & counts` |
| Client Usage report | Move to Reports if it is office-wide rather than client-specific |
| Client Overview | Rename once its exact content is finalized; “Overview” is too vague |
| Push new losses → APA | Keep in Daily Run More menu only |
| Post daily misses → Trello | Keep in Daily Run More menu while Trello remains active |
| Full re-scan | Keep in Daily Run More; rename `Recheck All Files` |
| Photo Folders | Keep hidden while CompanyCam is primary |
| Job Notes standalone tool | Keep hidden; Job Log is the preferred per-job surface |
| Hygiene standalone tool | Keep hidden; surface its actionable findings on Jobs cards |
| KPI standalone tool | Fold into a future Reports dashboard after metric definitions stabilize |
| WC Audit | Keep specialist/optional until routine usage is confirmed |

## Accessibility and interaction follow-up

- Add accessible names to remaining icon-only day navigation buttons.
- Replace remaining `...` loading copy with the ellipsis character `…`.
- Add `name`, correct input types, and labels to older forms.
- Ensure every popover uses `overscroll-behavior: contain` and stays within its modal.
- Preserve keyboard alternatives for board dragging and card-shelf gestures.
- Virtualize or progressively render any list that can exceed 50 rows.

## Design-integrity cleanup

- Removed unwired board `Customize`, Dispatch range, and Reports range controls from the Operations shell.
- Removed decorative lane ellipsis marks that looked like menus but did nothing.
- Replaced the blank gradient welcome tile with the established Hub logo.
- Replaced dashboard-style wording with direct operational labels.
- Browser Tools no longer shows the Windows application updater or legacy-app launcher.
- Job and Dispatch cards use native buttons so click and keyboard behavior agree.

## Decision boundary

No capability is deleted during this pass. A control can be hidden or moved when its destination is clear. Removal requires usage evidence or an explicit approval because specialist tools may be infrequent rather than obsolete.
