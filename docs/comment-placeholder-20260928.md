# Comment placeholder

The rich editor's `isEmpty` includes empty lists, so a visible numbered/bullet marker overlapped “Write an update”. Placeholder visibility now requires precisely one empty plain paragraph. Text, pasted/restored content, lists, quotes and other structure suppress it. Clearing back to an empty paragraph restores it; posting/draft serialization is unchanged.

Regression: `tests/comment_placeholder.cjs` reproduces the numbered-list overlap before the fix and checks list, typed text, restored draft and clear behavior. Rebuilt the checked-in editor bundle from `tools/comment-editor/editor.js`. Local DEV change, not published.
