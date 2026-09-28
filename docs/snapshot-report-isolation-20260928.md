# Snapshot release safety

Supersedes the write-back behavior described in jobs-create-snapshot-20260928.md.

Report inputs save only the local Snapshot draft. Generation no longer calls the Job Log synchronizer. The legacy bridge rejects write-back from cached older frontends. The standalone historical helper remains for compatibility/testing but is not used by the Snapshot UI or generator.

Drafts retain sourceClient/cardId/division independently of the editable insured heading. These are included in the generation payload; revision ownership uses sourceClient, revision metadata and drafted state use the exact card ID, and history filters by card/division. No generation-time lookup of a name-based Trello pin. Prefill no longer creates a pin. A saved-Job-Log read failure is shown as a warning rather than a successful empty import.

Existing Trello-based field prefill, explicit post/move controls and automatic audit remain. This is not a full app-only Snapshot rewrite. Existing PDF output naming still uses the insured heading; revision history remains job-owned.

Tests: test_snapshot_report_isolation.py checks no Job Log writes, no name-pin lookup, exact card/division metadata, history isolation, draft identity and legacy-bridge rejection. Existing Snapshot tests retained.
