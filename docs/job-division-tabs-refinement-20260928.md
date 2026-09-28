# Job division tabs refinement

The job identity now comes first, followed by available insurance/loss-type badges and a single EMS / Contents / Recon tab row. Tabs have equal heights and an underlined selection rather than raised folder shapes. Existing verified-card eligibility, keyboard navigation and unsaved-draft protection remain.

The job workspace no longer renders the independent comment-division selector. Its comments follow the selected workspace division, identified in the comment header. Loading status and errors remain visible without a redundant row. Send to pills remain independent multi-select posting destinations. The reusable conversation component still supports its standalone selector when not mounted in the workspace.

Badges display existing job fields only. This is not the proposed database-owned editable tag feature or a Trello-to-app migration.

UI-design and anti-ui-slop polish guidance kept the change within existing colors/components and required desktop/narrow rendering checks. Regression coverage includes tab placement, equal height, badges, absent duplicate selector, draft protection, comment switching, posting controls and linked preloading.

Local development change after 1.8.23; not yet published or installed.
