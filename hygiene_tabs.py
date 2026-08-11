"""Hygiene tab groupings — the one definition both panels read.

The Tk panel and the web panel each carried their own copy of this
table (`hygiene_gui._TABS`, `hygiene_web._TABS_DEF`), and they drifted:
web's "action" tab had gained `eq_on_site`, `lost_job` and
`xa_inquiries`, and the Tk copy never got them, so those sections
belonged to no tab there and fell out of the Tk view entirely.

Section keys route to tabs by exact match, so a key present in one copy
and absent from the other is a silently-missing section, not an error.
That is the same trap as the shared audit-detail renderer: two copies of
a routing table is one copy too many.

Everything here is plain data and pure functions — no Tk, no Trello, no
I/O — so the web panel, the Tk panel and the background scan worker can
all import it. Web's superset won the merge: adding the three keys to
the Tk side routes them to Action Needed, which is where they belong.
"""

# Each entry: (tab_key, display_label, tuple_of_section_keys).
# Keep tab keys stable — persistence stores the last-selected tab.
TABS = (
    ("action",  "🔴 Action Needed",
     ("wc_audit_due", "weekly", "estimates", "eq_on_site", "lost_job",
      "adjuster_pending", "xa_inquiries", "disputes", "concerns", "ipr",
      "xa_apology", "docusketch_needed", "docusketch",
      "docusign", "docusign_resends", "missing_items")),
    ("quality", "⚠ Trello quality",
     ("hygiene", "handoff", "closeout", "stalled", "anomalies",
      "open_jobs")),
    ("stale",   "📝 Stale notes",
     ("xa_gaps",)),
)

DEFAULT_TAB = TABS[0][0]
TAB_KEYS = {t[0] for t in TABS}
SECTION_TO_TAB = {sk: t[0] for t in TABS for sk in t[2]}

# JSON-safe form for the web panel's initial payload.
TABS_PAYLOAD = [{"key": k, "label": lbl, "sections": list(secs)}
                for k, lbl, secs in TABS]

# Short label for the Re-scan button (without icons / parens). Lets us
# write "↻ Re-scan Trello quality" instead of "↻ Re-scan ⚠ Trello quality".
TAB_BUTTON_LABELS = {
    "action":  "Action items",
    "quality": "Trello quality",
    "stale":   "Stale notes",
}


def tab_section_keys(tab_key):
    """Return the section keys owned by a tab (empty tuple if unknown)."""
    for t_key, _label, sec_keys in TABS:
        if t_key == tab_key:
            return sec_keys
    return ()


def scan_flags_for_tab(tab):
    """Return the include-flag dict that drives the background scan.

    `tab=None` (full pass) keeps the original behavior — every section,
    every email walk. Per-tab variants skip the work the tab doesn't
    need. The dict has these keys:

      hygiene/handoff/closeout/xa_gaps/ipr — passed straight through
        to scan_workspace's include_* flags.
      any_workspace                       — False short-circuits the
        scan_workspace call entirely (stale tab pulls from email).
      ar_followup                         — whether to refresh xa_apology.
      xa_gaps_only                        — special path for the stale
        tab that bypasses the Trello walk.
    """
    if tab is None:
        return dict(
            hygiene=True, handoff=True, closeout=True,
            xa_gaps=True, ipr=True, estimates=True, weekly=True,
            any_workspace=True, ar_followup=True,
            xa_gaps_only=False)
    if tab == "action":
        return dict(
            hygiene=True,   # for customer_complaint rule + email scan
            handoff=False, closeout=False,
            xa_gaps=False,  ipr=True, estimates=True, weekly=True,
            any_workspace=True, ar_followup=True,
            xa_gaps_only=False)
    if tab == "quality":
        return dict(
            hygiene=True,   # for non-complaint rules
            handoff=True,   closeout=True,
            xa_gaps=False,  ipr=False, estimates=False, weekly=False,
            any_workspace=True, ar_followup=False,
            xa_gaps_only=False)
    if tab == "stale":
        return dict(
            hygiene=False, handoff=False, closeout=False,
            xa_gaps=True,  ipr=False, estimates=False, weekly=False,
            any_workspace=False, ar_followup=False,
            xa_gaps_only=True)
    # Unknown tab → fall back to full scan rather than no-op so the user
    # never gets a silently-empty result.
    return dict(
        hygiene=True, handoff=True, closeout=True,
        xa_gaps=True, ipr=True, estimates=True, weekly=True,
        any_workspace=True, ar_followup=True,
        xa_gaps_only=False)
