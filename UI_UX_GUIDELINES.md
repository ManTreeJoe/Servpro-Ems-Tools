# Linguar Hub UI/UX Guidelines

## Purpose

Linguar Hub should feel like one product, even while its tools are being migrated from Trello and older desktop workflows. New work must strengthen the existing interface language instead of introducing a new visual system inside each panel.

The current visual source of truth is the Job Audit interface. Its buttons, action grouping, cards, typography, spacing, states, and interaction language should be reused across Jobs, Clients, Snapshot, APA, and related tools.

## Product structure

- **Clients** is the account-level workspace: contacts, properties, claims, job history, shared details, and all work performed for that client.
- **Jobs** is the operational workspace: active claims displayed as cards on boards and lanes.
- A job card represents one claim. EMS, Contents, and Recon remain distinct work divisions connected to that claim.
- A job card must provide a visible **Client page** action. Users should never need a right-click to reach a primary destination.
- Snapshot is a closeout workflow launched from a job, not a separate information hierarchy.

## Source-of-truth rule

Before creating or changing a component:

1. Find the equivalent component in Job Audit.
2. Reuse its markup, CSS class, wording, sizing, and behavior when possible.
3. If reuse is not technically possible, copy the established visual tokens exactly.
4. Introduce a new pattern only when no established pattern solves the problem.
5. Document any approved new pattern here before using it in multiple places.

Do not redesign an established component merely because it appears in a new panel.

## Buttons

Job Audit buttons are canonical:

- Background: `var(--surface-2)`
- Text: `var(--text)`
- Border: `1px solid var(--border)`
- Padding: `7px 11px`
- Radius: `7px`
- Font: inherited, `12px`, weight `600`
- Hover: `var(--border)` with border `#55585d`
- Focus: `2px solid #79b48d`, offset `2px`
- Disabled: opacity `.4`, no active cursor
- Primary: `var(--green)` background and border with white text
- Primary hover: `var(--green-hover)`

Rules:

- Use green for the single primary action in a group, not every important-looking action.
- Keep operational verbs visible: `Add update`, `Open folder`, `Build photo report`.
- Do not invent transparent, pill, gradient, glowing, or oversized variants unless explicitly approved.
- Do not use vertical text labels.
- Icons support labels; they do not replace labels for unfamiliar actions.
- Right-click menus are shortcuts only. Setup, linking, navigation, and other primary actions must have visible controls.

## Action layout

- Group actions by user intent: Open, Import, Reports, Job details, Update, Finish.
- Follow the Job Audit grouping order when the same actions appear elsewhere.
- Keep the most common action first and visually primary.
- Put less-used actions behind one visible `More` or `All actions` control.
- Avoid rows of equally emphasized buttons.
- Action toolbars wrap at narrow widths. Do not require horizontal scrolling to reach routine actions.

## Copy actions

- Copy values must come from the saved Job Info record, not a card title or loosely parsed label.
- A combined Copy menu should use the standard action-button appearance.
- Copy is a frequent action. Keep it beside the primary job action and never place it beyond a horizontally scrolling action rail.
- The menu must show the field label and a preview of the exact value that will be copied.
- Include a clear `Job summary` option for copying all available fields.
- Close the menu and show a short confirmation after copying.
- Never hide essential copy actions behind a right-click.

## Cards and overlays

- Single click opens a job card.
- Click-and-hold or dragging moves a card; a normal click must remain fast and reliable.
- Open cards appear above the board while preserving board context.
- Show loading inside the card being opened; do not replace the whole board with a loading state.
- Keep identity first: client, claim number, lifecycle state, and division.
- Put frequent actions near the top so routine work does not require scrolling.
- A visible `Client page` action moves from the claim-level card to the account-level workspace.

## Divisions and checklists

- EMS, Contents, and Recon are per-job divisions, not global application modes.
- Each division can have its own Trello card during migration.
- Division card linking must expose visible `Link`, `Change`, and `Remove` actions.
- Checklists retain their own EMS/Contents/Recon tabs inside the Checklists section.
- Switching a checklist tab must make the selected division unmistakable.
- Missing division cards should show a direct link action instead of an empty or disabled mystery control.

## Navigation

- Clients is the account/history level.
- Jobs is the active operational board level.
- Navigation labels should describe what users manage, not internal modules or legacy code names.
- Keep the sidebar stable. Add new top-level destinations only when they represent a genuinely different workspace.
- On narrow windows, the sidebar collapses to recognizable icons with accessible labels/tooltips.

## Forms and setup

- Setup flows must be visible, sequential, and written in plain language.
- Show the next action and the current state together.
- Never require a hidden gesture to connect a folder, Trello card, CompanyCam project, or division.
- Warn before a risky mismatch and explain what will be linked.
- Preserve entered data when validation fails.

## Responsive behavior

- Test normal desktop, narrow desktop, and maximized layouts.
- Text must not overlap, clip, or force controls off-screen.
- Prefer wrapping within content sections and horizontal scrolling only for board lanes and compact action rails.
- Vertical scrolling must remain vertical inside columns and documents.
- Respect `prefers-reduced-motion` and retain visible keyboard focus.

## Writing

- Use short, concrete labels in sentence case.
- Use the same term everywhere for the same action.
- Say what happened and what the user can do next.
- Avoid backend terminology such as schema names, table names, or internal module names in ordinary UI.

## Anti-template standard

Linguar Hub must look like a restoration operations tool, not a generated SaaS dashboard.

- Every visible control must perform its labeled action. Hide unfinished controls; never use decorative `•••`, fake filters, or placeholder mode switches.
- Use the established Hub logo and real provider marks. Do not substitute emoji, letter tiles, blank gradient squares, or invented icons when an approved asset exists.
- Keep SERVPRO green as a functional brand/status color. Do not add neon glow, decorative gradients, glass panels, grid-paper backgrounds, or ambient animation without an operational reason.
- Headings name the work directly: `Jobs needing action`, `Today’s schedule`, and `Jobs by lane`. Avoid slogan-like eyebrow triplets and vague labels such as `Control room`, `Pulse`, `Exposure`, or `Pressure`.
- Metrics must answer a current workflow question and open the records behind the number. Do not add generic KPI cards merely to fill space.
- Empty and loading states explain what is happening or what action comes next. They are not decorative mood content.
- Use one restrained signature: the Hub mark with division colors. Everything else stays quiet, compact, and consistent with Job Audit.
- Browser screens never imitate desktop-only behavior. Installers, Windows launch actions, and local file controls appear only where they can work.
- Before merging UI work, list every new button and verify its event handler, keyboard path, loading state, and failure message.

## Review checklist

Before a Trial build is handed to the user:

- Compare changed components against Job Audit.
- Confirm existing shared styles were reused before adding CSS.
- Verify primary actions are visible without right-clicking.
- Verify buttons match the canonical button specification.
- Test Copy actions and confirm their source values.
- Test card open, client-page navigation, division switching, and checklist tabs.
- Test at narrow and normal window widths.
- Run focused UI tests and JavaScript syntax checks.
- Open only the local Trial build; do not close or replace Main.

## Future cleanup

The canonical Job Audit action, tab, card, modal, and menu styles should move into a shared component stylesheet. After that extraction, panels must import the shared components instead of duplicating their CSS.
