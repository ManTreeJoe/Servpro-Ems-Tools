# Comment reference alignment

Used the user's existing drawer screenshot as the visual reference, following the UI refinement skills: retain distinct comment bubbles, colored initial avatars, readable author/timestamps, and blue highlighted @mentions without removing the new composer, destination pills or reactions.

Jobs, Daily Run, and Snapshot now share display-only mention decoration and deterministic name-based avatar colors/initials. Matching author names (case-insensitive) receive the same color across screens. The palette uses darker colors with white initials. This is not a Trello profile-photo/identity synchronization feature.

Mention decoration skips email addresses, links, inline code and code blocks. It runs after safe Markdown rendering using DOM text nodes. Original Markdown, editor input, saved comments and post payloads are unchanged. Mention chips are visual indicators, not profile links. Both light and dark theme chip colors are defined.

Validation: browser regression checks for safe rendering, unchanged raw text, avatar consistency, shared drawer features and screenshot review. No production publishing or app restart included.
