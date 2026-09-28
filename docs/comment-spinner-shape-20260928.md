# Comment loading spinner shape

The comment-count badge rule targeted every span inside `.activity-head`. Moving the loading status into that header caused its spinner to inherit a 24px minimum width, 2px/7px padding and a filled badge background. The nominal 16px circle became a 24x16 rotating capsule.

Scoped the badge rule to the actual direct-child `data-comment-count` element. The shared spinner remains 16x16, transparent and circular. No request, timing or refresh behavior changes. Reduced-motion support stays intact.

Bug-diagnosis and UI polish skills guided a real-header browser reproduction. `tests/comment_spinner_shape.cjs` failed at 24x16 before the fix and passes at 16x16 afterward; checks zero padding, transparent background and no search-row shift on completion. Existing `tests/comments_loading.cjs` covers pending/empty/error/retry and reduced motion. Local DEV change; restart/reload needed, not published.
