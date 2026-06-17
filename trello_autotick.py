"""Auto-tick Trello checklist items when matching artifacts land in OD.

Background — the EMS Admin's daily flow includes ticking off Trello
checklist items on the INITIAL - ADMIN / INITIAL checklists after the
underlying file lands (an ATP PDF, a Sketch zip, a batch of Initial
photos, …). That's a redundant manual step: the file IS the evidence;
the checkbox just announces it. This module is the bridge.

Hooks for callers — each import / generation success path passes the
event kind here and we map it to one or more checklist items to tick.

Public API:
    autotick(card_id, *, events=("sp_photos",), client="", silent=False)
        → ticks every item in INITIAL_CHECKLIST_MAP[event] across both
          tracked checklists. Returns list of (checklist_name,
          item_name) tuples that were newly ticked (i.e. previously
          incomplete).

    SUPPORTED_EVENTS — the set of kind strings callers may pass.

Best-effort end to end: missing card, no checklist, Trello hiccup all
silently return []. Caller does not need to handle failures.

Why a separate module: the autotick policy (which event → which item)
should live in ONE place rather than be re-derived inside every import
site. Adds a new tick rule = one edit here, not N edits across the
suite.
"""
from __future__ import annotations

from typing import Iterable

# Acceptable checklist names — the three admin checklists the EMS Admin
# works out of, across the whole job lifecycle:
#   INITIAL - ADMIN     (intake → initial upload)
#   IN PROGRESS - ADMIN (demo / additional work / docusketch order)
#   CLOSE OUT - ADMIN   (final photos / sketch / scope / snapshot / paperwork)
# "INITIAL" is kept as a legacy fallback for older cards. Matching is
# case-insensitive and whitespace-normalized (see `_norm`), so hyphen /
# spacing variants ("INITIAL ADMIN" vs "INITIAL - ADMIN") all resolve.
_ADMIN_CHECKLIST_NAME = "INITIAL - ADMIN"
_INITIAL_CHECKLIST_NAME = "INITIAL"
_IN_PROGRESS_CHECKLIST_NAME = "IN PROGRESS - ADMIN"
_CLOSE_OUT_CHECKLIST_NAME = "CLOSE OUT - ADMIN"

_TRACKED_CHECKLIST_NAMES = (
    _ADMIN_CHECKLIST_NAME,
    _IN_PROGRESS_CHECKLIST_NAME,
    _CLOSE_OUT_CHECKLIST_NAME,
    _INITIAL_CHECKLIST_NAME,
)

# event-kind → tuple of acceptable item names (any/all that exist on
# the actual checklist will be ticked). Matched case-insensitively
# against the checklist's checkItems.
INITIAL_CHECKLIST_MAP: dict[str, tuple[str, ...]] = {
    # SP photos imported into PICS/Initial — covers the "Initial photos"
    # variant on either checklist.
    "sp_photos_initial": (
        "INITIAL PHOTOS",
        "INITIAL PHOTOS/PHOTO REPORT",
    ),
    # WC photos imported — same coverage as SP photos.
    "wc_photos_initial": (
        "INITIAL PHOTOS",
        "INITIAL PHOTOS/PHOTO REPORT",
    ),
    # Initial photo report PDF generated / uploaded. Distinct event
    # because the report is the deliverable from the photos, not the
    # raw photo batch.
    "initial_photo_report": (
        "INITIAL PHOTO REPORT",
        "INITIAL PHOTOS/PHOTO REPORT",
    ),
    # Docusketch zip imported. Different teams use either the ADMIN
    # "PHYSICAL SKETCH" label or the INITIAL "PRELIMINARY SKETCH"
    # label — tick whichever exists.
    "docusketch_imported": (
        "PHYSICAL SKETCH",
        "PRELIMINARY SKETCH",
    ),
    # Scope.pdf written via the Scope dialog. Only present in INITIAL
    # checklist; ADMIN doesn't track scope.
    "scope_saved": (
        "PRELIMINARY SCOPE",
    ),
    # Initial paperwork (ATP / CIF / CER / COS) — files dropped into
    # EMS/DOCS. Coarse — anything that satisfies "INITIAL PAPERWORK"
    # ticks both lists' versions.
    "initial_paperwork": (
        "INITIAL PAPERWORK",
    ),
    # Final stage event — Initial Upload submitted to WC. This one is
    # the gating item that drops the card OUT of the IUQ, so we tick
    # it only when the user explicitly posts the canonical
    # confirmation comment via the Process workflow.
    "initial_upload_submitted": (
        "INITIAL UPLOAD",
    ),
    # WC docs imported — could satisfy paperwork depending on what's
    # in the zip. Default coarse tick of INITIAL PAPERWORK; caller can
    # override with explicit events if they know the WC zip only had
    # specific items.
    "wc_docs_imported": (
        "INITIAL PAPERWORK",
    ),

    # ── IN PROGRESS - ADMIN checklist ───────────────────────────────
    # Demo / mid-job photos imported into a Demo (or other in-progress)
    # PICS subfolder.
    "demo_photos": (
        "DEMO PHOTOS",
    ),

    # ── CLOSE OUT - ADMIN checklist ─────────────────────────────────
    # Final-stage photos imported (Final / Post / Completion subfolder).
    "final_photos": (
        "FINAL PHOTOS",
    ),
    # Snapshot handoff PDF generated — ticks the SNAPSHOT close-out item.
    "snapshot_generated": (
        "SNAPSHOT",
    ),
    # Final paperwork (DocuSign packet / signed COS) imported into DOCS.
    "final_paperwork": (
        "FINAL PAPERWORK",
    ),
    # Final sketch (a docusketch imported at close-out time rather than
    # initial). Distinct from PHYSICAL SKETCH so the caller can target
    # the right lifecycle stage.
    "final_sketch": (
        "FINAL SKETCH",
    ),
}

SUPPORTED_EVENTS: frozenset[str] = frozenset(INITIAL_CHECKLIST_MAP)


def _norm(name: str) -> str:
    return (name or "").strip().upper()


def _find_checklist(card: dict, names: Iterable[str]):
    targets = {(n or "").strip().lower() for n in names if n}
    for cl in (card.get("checklists") or []):
        if (cl.get("name") or "").strip().lower() in targets:
            return cl
    return None


def autotick(card_id: str, *,
             events: Iterable[str] = (),
             client: str = "",
             silent: bool = False) -> list[tuple[str, str]]:
    """Tick the checklist items associated with `events` on `card_id`.

    `events` is an iterable of keys from INITIAL_CHECKLIST_MAP. Items
    that are already complete are left alone (idempotent). Items that
    don't exist on the card are silently skipped.

    Returns list of (checklist_name, item_name) tuples that were newly
    ticked, so the caller can build a "ticked 2 items" toast.

    `client` is informational — used only in the optional log line
    when `silent` is False. Does NOT affect ticking.

    `silent=True` suppresses the ems_log info line. Use when the
    caller is going to render its own toast/UI and doesn't want a
    duplicate log entry.
    """
    if not card_id:
        return []
    events = [e for e in events if e in INITIAL_CHECKLIST_MAP]
    if not events:
        return []
    # Union of item names across all requested events.
    targets: set[str] = set()
    for ev in events:
        for nm in INITIAL_CHECKLIST_MAP[ev]:
            targets.add(_norm(nm))
    if not targets:
        return []

    try:
        import trello_client as tc
    except Exception:
        return []
    try:
        card = tc.get_card(card_id)
    except Exception:
        return []
    if not card:
        return []

    ticked: list[tuple[str, str]] = []
    # Walk EVERY tracked checklist on the card (INITIAL / IN PROGRESS /
    # CLOSE OUT - ADMIN). An event ticks its matching item wherever it
    # lives — so a "final_photos" event finds FINAL PHOTOS on CLOSE OUT,
    # a docusketch finds PHYSICAL SKETCH on INITIAL, etc.
    _tracked_norms = {_norm(n) for n in _TRACKED_CHECKLIST_NAMES}
    for cl in (card.get("checklists") or []):
        if _norm(cl.get("name")) not in _tracked_norms:
            continue
        cl_label = cl.get("name") or "?"
        for item in (cl.get("checkItems") or []):
            if _norm(item.get("name")) not in targets:
                continue
            if (item.get("state") or "").lower() == "complete":
                continue
            ok = False
            try:
                ok = bool(tc.set_check_item_state(
                    card_id, item.get("id") or "", "complete"))
            except Exception:
                ok = False
            if ok:
                ticked.append((cl_label, item.get("name") or "?"))

    if ticked and not silent:
        try:
            import ems_log
            who = client or card_id
            items_txt = ", ".join(f"{cl}/{nm}" for cl, nm in ticked)
            ems_log.info("trello_autotick",
                         f"ticked for {who!r}: {items_txt}")
        except Exception:
            pass

    return ticked


def autotick_summary(ticked: list[tuple[str, str]]) -> str:
    """Render a one-liner the caller can use in a toast / status bar.

    `ticked` is the return value of autotick(). Returns "" when nothing
    was ticked so the caller can short-circuit a no-op toast.
    """
    if not ticked:
        return ""
    n = len(ticked)
    if n == 1:
        cl, nm = ticked[0]
        return f"✓ Trello: ticked '{nm}' on {cl}"
    return f"✓ Trello: ticked {n} checklist items"
