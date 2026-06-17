"""Canonical XactAnalysis note templates.

When the user needs to drop a status update into the XA assignment
notes — apology, scan-pending, estimate-underway, awaiting-paperwork
— typing it from scratch every time is friction. This module is the
one place those phrases live so the Hygiene panel can surface them as
one-click clipboard copies.

Each template is a (key, label, text) triple:
  key   — stable identifier used by callers / persistence
  label — short text for the popup menu ("📐 Scan in progress…")
  text  — the full note body the user pastes into XA

Add new entries by appending to TEMPLATES below — the popup menu picks
them up automatically. The first matching `key` wins on lookup, so
keys must stay unique.
"""

# Templates listed top-to-bottom in the popup menu. Order is
# intentional: most-frequent at the top.
TEMPLATES = [
    ("apology",
     "🔔 Apology — team is working on it",
     "Our apologies for the delay. Please note our estimating team is "
     "diligently working on the file."),

    ("scan_in_progress",
     "📐 Scan in progress — needs more time",
     "The Docusketch/scan is currently in process and requires additional "
     "time to finalize. We appreciate your patience while our team completes "
     "the measurements; the estimate will follow shortly thereafter."),

    ("estimate_underway",
     "✏️ Estimate underway",
     "The estimate is in progress and will be submitted shortly. We will "
     "update XactAnalysis as soon as the file is uploaded."),

    ("awaiting_paperwork",
     "📝 Awaiting signed paperwork from insured",
     "We are currently awaiting signed paperwork from the insured. Once "
     "received, services will proceed and the file will be updated "
     "accordingly."),

    ("awaiting_authorization",
     "✋ Awaiting authorization to proceed",
     "We are awaiting authorization to proceed with services. We will "
     "follow up with the insured and update the file once authorization "
     "is received."),

    ("services_complete",
     "✅ Services complete — uploading documentation",
     "Services have been completed on this file. The estimate and "
     "supporting documentation (photos, sketch, paperwork) will be "
     "uploaded to XactAnalysis shortly."),

    ("ds_ordered",
     "📐 Docusketch ordered",
     "A Docusketch has been ordered for this property. We will provide "
     "an update once the measurements are returned and the estimate is "
     "underway."),

    ("monitor_check",
     "📊 Monitoring in progress",
     "Equipment remains on site and is being monitored. Daily moisture "
     "readings are being recorded; we will update the file when drying "
     "goals are met."),

    ("inquiry_received",
     "📨 Inquiry received — 48h response",
     "Your inquiry has been received. Please allow our estimating team "
     "48 hours to address."),
]


def get(key):
    """Return the (label, text) for `key`, or (None, None) if missing.
    Useful for callers that want to look up a specific template by id
    (e.g. analytics / suggested-template heuristics)."""
    for k, label, text in TEMPLATES:
        if k == key:
            return (label, text)
    return (None, None)


def copy_to_clipboard(widget, text):
    """Copy `text` to the system clipboard via the widget's Tk root.

    DOES NOT call clipboard_clear() first — on Windows with a clipboard
    manager (Ditto, ClipMate, Win+V history) running, the explicit
    clear can deadlock the Tk event loop. `clipboard_append` implicitly
    clears on the first call within a Tk session, which is what we want.
    """
    if not widget or not text:
        return False
    try:
        widget.clipboard_append(text)
        widget.update()  # Push the clipboard write to the OS now
                          # rather than at the next idle pass.
    except Exception:
        return False
    return True
