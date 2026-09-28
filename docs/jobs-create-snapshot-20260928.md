# Create Snapshot from Jobs

Local DEV change, not restarted/published.

Job card → Job Log → Create Snapshot opens the existing Snapshot editor in the shell's focused workspace, above Jobs. The handoff includes the exact card ID, client and selected division. It bypasses the candidate queue and does not require moving the card into a Snapshot lane first. Existing unsaved Job Log edits must be saved/cancelled first. A card ID is required; unlinked jobs currently show the action disabled.

The existing Snapshot prefill reads Trello card facts and saved completed Job Log entries (not a new comment-to-log import). The selected division is now passed into the saved log projection lookup; the app client name takes priority for that lookup. Existing prefill/audit behavior is retained. This is not an app-only/offline Snapshot redesign. PDF generation and Trello posting/moving remain explicit existing controls.

UI-design/anti-ui-slop polish guidance kept the action in the existing Job Log toolbar. Existing print-only export remains separate.

Verification: job_log_toolbar.cjs verifies exact card/division/create handoff and toolbar layout; eight Python checks across snapshot_loading_flow, snapshot_job_log_sync and snapshot_closeout_queue passed. Live customer PDF generation/posting was not performed.

Manual DEV check: select the intended EMS/Contents/Recon job card, open Job Log, click Create Snapshot. Confirm the customer and completed rows in the editor before generating. Close Snapshot to return to Jobs. No release created.
