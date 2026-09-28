# Job Log toolbar polish — local DEV

Replaced the stacked header controls with a title/Add update row and a wrapping secondary toolbar: Refresh saved log, Pull from the current division's Trello card, Print / PDF. Save status sits below a quiet divider. Print stays disabled for empty logs with an explanatory tooltip.

No persistence, deletion or import semantics changed. Refresh remains explicit. The in-place section patch now moves the entire incoming toolbar so current handlers and PDF entry data remain attached.

UI-design and anti-ui-slop polish guidance: reuse existing tokens/buttons, preserve action labels, keep the primary action distinct, check desktop/narrow rendering and avoid overflow.

Verification: job_log_toolbar.cjs (alignment, narrow wrapping, disabled empty print, editor opening), job_log_dismiss.cjs (deleted rows stay deleted after stale refresh), job_log_save_responsiveness.cjs (in-place save and draft preservation). Not published or restarted.
