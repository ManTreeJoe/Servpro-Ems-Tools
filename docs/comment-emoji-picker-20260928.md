# Floating Trello reaction picker

Supersedes the inline six-choice control in comment-reactions-20260928.md. Local DEV; not restarted or published.

React opens a fixed-position popup anchored to the comment and clamped inside the viewport. Search, six content categories, All, and Recent browse 78 bundled native emojis. This is a compact catalogue, not full Trello emoji/skin-tone parity. Recent successful selections are stored on this PC in localStorage (emoji codes only); failure to access storage does not prevent reacting.

Selecting closes the popup and submits the existing desired-state Trello mutation. Confirmed counts appear as pills under the message. Clicking a pill toggles only the current user's reaction. Exact card/action and connected-account checks, no blind retries, and sanitized errors remain. On uncertain writes, pills are disabled until reopening React successfully reloads the provider state. Catalogue codes are validated server-side; other existing provider reactions can still be toggled through their pills.

No per-comment background reads. Existing reactions are fetched on opening React, as before. Escape closes only the picker and returns focus; outside pointer-down or scrolling the comment pane dismisses it. A removed/replaced owner closes the popup. Popup search does not resize the comment stream. UI-design and anti-ui-slop polish skills guided the compact floating layout and narrow-window checks.

Verification: updated comment_reactions.cjs tests real comment rendering, catalogue/search, viewport bounds, no search-induced layout shift, selection closes, counts/toggle, failure recovery, Recent, Escape, outside dismissal and removed-owner cleanup. Nine backend tests passed, including expanded-catalogue writes and rejection of non-emoji codes. Screenshot inspected at 420px viewport. No live customer reaction writes during tests.

Manual DEV test after restart: React on a safe test comment, search/select an emoji, confirm it in Trello, remove via its pill; then reopen to check Recent. The picker should float without pushing comments.
