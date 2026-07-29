"""Initial Upload Queue — Trello-driven view of jobs ready for upload.

Scans the WORK IN PROGRESS Trello board's INITIAL INSPECTIONS/RE-INSPECTIONS
and MONITOR lanes, filters out jobs that are already uploaded (INITIAL UPLOAD
checklist item ticked), self-pay (name suffix "-Self Pay"), and renders the
rest as a checklist-driven punch list. The user can:

  - Tick / untick any of the four INITIAL - ADMIN checklist items live
    (Trello round-trip via PUT /cards/{id}/checkItem/{itemId}).
  - Mark a card commercial — same `CommercialToggle` semantics as the
    main audit; commercial rows render greyed + struck-through but stay
    visible (per user's preference).
  - Open the card in Trello (↗) or pin/unpin it locally (📌).

Caching: the Trello scan + per-job folder resolution is expensive enough
that we don't want to repeat it every time the dialog opens within a day.
`persistence.{get,set,clear}_initial_queue_cache()` buckets the result by
MM-DD-YYYY — anything older is automatically refetched on next open. The
🔄 Refresh button is the explicit override for mid-day changes.
"""
import os
import re
import threading
import tkinter as tk
import webbrowser
import zipfile
from tkinter import messagebox

import config
import persistence
from job_widgets import extract_job_year, open_trello_pin_dialog
from theme import (BG, BORDER, FLAG_RED, GREEN, GREEN_DARK,
                   TEXT_DARK, TEXT_GRAY, TEXT_MUTED, WHITE,
                   SURFACE_2, NEUTRAL_HOVER,
                   SUCCESS_BG, SUCCESS_FG, SUCCESS_HOVER,
                   INFO_BG, INFO_FG, INFO_HOVER,
                   LINK_BG, LINK_FG, LINK_HOVER,
                   WARN_BG, WARN_FG)
from tool_panel import ScrollableFrame, ToolPanel, run_standalone, show_toast
from trello_icon import trello_icon
from ui_buttons import (
    done_button, send_button, link_button, secondary_button,
    icon_button, trello_link_button,
)


# Workcenter quick-import (mirrors run_audit_gui's _make_workcenter_action
# but minimal — just the URL + wait-for-zip + extract flow). Three filename
# shapes Workcenter produces:
#   attachments.zip                       (single, fresh download)
#   attachments (1).zip                   (Chrome dedupe suffix on re-DL)
#   attachments-part-1-of-3.zip           (multi-part split for big jobs)
# The multi-part case must extract ALL parts into the same target — they're
# independent zips that together make up the full export.
_WC_ATTACHMENTS_RE = re.compile(
    r'^attachments(?:\s*\(\d+\)|-part-\d+-of-\d+)?\.zip$',
    re.IGNORECASE)
_WC_MULTIPART_RE = re.compile(
    r'^(?P<base>.+?)-part-(?P<n>\d+)-of-(?P<m>\d+)\.zip$',
    re.IGNORECASE)
_DOWNLOADS = os.path.join(os.environ.get("USERPROFILE", ""), "Downloads")


# Matches trailing date suffixes Trello cards drag around — the WIP
# automation tags cards with the creation date ("- 05/09/26",
# " 5-9-26"). The run-doc never carries the date in the client name,
# so we strip it before comparing.
_TRAIL_DATE_RE = re.compile(
    r"[\s,\-]*\b\d{1,2}[/.\-]\d{1,2}(?:[/.\-]\d{2,4})?\s*$")
# "Last, First" → "First Last" so comma-form and space-form hash to
# the same key. Matches the snapshots_excel approach.
def _norm_client_for_run_doc(name):
    """Normalize a client name (from either an IUQ card or a run-doc
    row) into a stable lowercase form for fuzzy matching:

      • Lowercase + collapse whitespace
      • Strip trailing date suffix ("- 05/09/26")
      • Comma-swap ("Sanchez, Jacqueline" → "jacqueline sanchez")

    Returns "" for blank input.

    ── Sibling canon functions (don't confuse) ──────────────────────
    `persistence._canon_pin_key` → strips " - Carrier" suffix; use for
        Trello-pin / folder-path / APA-cross-reference lookups.
    `ems_db.canon_key` → alias of `_canon_pin_key`.
    `snapshots_excel._canon_name_key` → preserves " - X" suffix because
        in spreadsheets " - X" is a sub-job identifier that must stay
        distinct.
    Use THIS function when: fuzzy-matching a card name against the
    day's run-doc text (which may have date suffixes / comma-form
    flips that the other canons don't handle).
    """
    s = (name or "").strip()
    if not s:
        return ""
    # Strip trailing date suffix before anything else — the comma logic
    # below shouldn't see the date.
    s = _TRAIL_DATE_RE.sub("", s).strip()
    # Collapse all internal whitespace + lowercase.
    s = " ".join(s.split()).lower()
    if "," in s:
        parts = [p.strip() for p in s.split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            s = " ".join(f"{parts[1]} {parts[0]}".split())
    return s


def _group_wc_zips(filenames, downloads_dir):
    """Collapse multi-part zip sets into single groups.

    Input: filenames already filtered to the WC zip pattern, sorted
    newest-mtime first. Output: list of (label, [absolute_paths]) tuples
    in the same newest-first order — multi-part siblings collapsed onto
    the most-recent member's slot. Single zips become a 1-element group."""
    groups = []
    seen_keys = set()
    for fn in filenames:
        m = _WC_MULTIPART_RE.match(fn)
        if m:
            key = (m.group("base").lower(), m.group("m"))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            siblings = sorted(
                [f for f in filenames
                 if (lambda mm: mm and (mm.group("base").lower(),
                                          mm.group("m")) == key
                     )(_WC_MULTIPART_RE.match(f))],
                key=lambda f: int(_WC_MULTIPART_RE.match(f).group("n")))
            label = (f"{m.group('base')}-part-*-of-{m.group('m')}.zip "
                     f"({len(siblings)}/{m.group('m')} parts)")
            paths = [os.path.join(downloads_dir, s) for s in siblings]
            groups.append((label, paths))
        else:
            groups.append((fn, [os.path.join(downloads_dir, fn)]))
    return groups


# ── Trello board / lane identifiers ─────────────────────────────────────────
# Hard-coded because this team's WIP board is stable. If the board is ever
# rebuilt these would need to be updated — keeping them in config.json was
# considered but adds setup churn without solving a real "we change boards"
# problem the user has reported.

WIP_BOARD_SHORTLINK = "r6lH2zC1"

LIST_ID_INITIAL_INSPECTIONS = "5d8b8f4dd2de731b0d14820a"
LIST_ID_MONITOR             = "5d8b8f9efc75564d577c2751"
# Cards in active workflow regularly get punted into Office Questions
# while the office chases down a missing piece (carrier #, claim, scope,
# adjuster contact). Including this lane catches those stranded jobs
# the user said they often miss — same filter rules apply.
LIST_ID_OFFICE_QUESTIONS    = "6418c2e9cbd115b996b218ab"
# Active mitigation cards — many of these still owe an Initial Upload
# (the upload happens AFTER the initial visit but the card has already
# moved on into ongoing work). Without this lane the queue silently
# misses those backlogged uploads.
LIST_ID_WORK_IN_PROGRESS    = "5d8ed3eb58bc2f545d67ad8e"
# WIP board's TBS lane — virtual / property-mgmt-pipeline intake. Cards
# here still carry the INITIAL - ADMIN checklist with INITIAL UPLOAD
# pending. Atadero, Christian (2026-05-11) was the trigger: lived here
# while the queue scanned only the other WIP lanes.
LIST_ID_TBS_NEW_LOSS        = "67c5e6972030aea9ebb733f7"
# Pending Approvals / Property Management lane on the WIP board.
# Cards parked here while the office waits on a property manager
# sign-off still owe Initial Upload paperwork — surfacing them keeps
# the queue honest about pre-approval pending work.
LIST_ID_PENDING_APPROVALS_PM = "65b2e43da4e935e43f310985"
# AR Board "DROP BOX - VIRTUALLY" — intake holding lane on the AR
# (accounts receivable) board for jobs that have transitioned past
# the WIP-board lanes but still owe paperwork upload. Alcocer, Joel
# & Maria (2026-05-11) was the trigger.
LIST_ID_AR_DROP_BOX         = "67acf2a98e89060eb7aa09fc"

# Display labels for the lane badge. Order in this dict is also the
# render order (Python preserves dict insertion order). The loop in
# fetch_queue_from_trello iterates .keys() so adding a new list_id
# here is enough to extend the scan.
LANE_LABEL_BY_LIST_ID = {
    LIST_ID_INITIAL_INSPECTIONS:  "Initial Insp.",
    LIST_ID_MONITOR:              "Monitor",
    LIST_ID_OFFICE_QUESTIONS:     "Office Q.",
    LIST_ID_WORK_IN_PROGRESS:     "WIP",
    LIST_ID_TBS_NEW_LOSS:         "TBS",
    LIST_ID_PENDING_APPROVALS_PM: "Pending PM",
    LIST_ID_AR_DROP_BOX:          "AR Drop",
}

# The two checklists this team uses on every WIP card. Each has its own
# template items in a meaningful order. Names matched case-insensitively
# against Trello so a rename to mixed-case still works. The lookup uses
# EXACT name match (not prefix) so "INITIAL" can't accidentally bind to
# "INITIAL - ADMIN" or vice versa.
ADMIN_CHECKLIST_NAME = "INITIAL - ADMIN"
ADMIN_ITEMS_ORDER = (
    "INITIAL PAPERWORK",
    "INITIAL PHOTOS/PHOTO REPORT",
    "INITIAL UPLOAD",
    "PHYSICAL SKETCH",
)

INITIAL_CHECKLIST_NAME = "INITIAL"
INITIAL_ITEMS_ORDER = (
    "INITIAL PAPERWORK",
    "INITIAL PHOTOS",
    "PRELIMINARY SKETCH",
    "PRELIMINARY SCOPE",
    "INITIAL PHOTO REPORT",
    "INITIAL ADJUSTER UPDATE",
)

# (display_name, expected_items) — drives both fetch (per-card payload
# build) and render (one row of buttons per entry). Order here is the
# top-to-bottom render order on each card.
TRACKED_CHECKLISTS = (
    (ADMIN_CHECKLIST_NAME,   ADMIN_ITEMS_ORDER),
    (INITIAL_CHECKLIST_NAME, INITIAL_ITEMS_ORDER),
)

# The card-completion gate: only the INITIAL UPLOAD item (in the ADMIN
# checklist) decides whether a card drops out of the queue. Other items
# tick/untick freely without removing the row — they're progress
# indicators, not the finish line.
ITEM_INITIAL_UPLOAD = "INITIAL UPLOAD"


# Canonical completion comments — when the user ticks one of these
# checklist items to ✓, the matching templated comment is auto-posted
# on the Trello card. Matches the phrases the user has been typing by
# hand for months, locked in by [[trello-completion-phrases]] memory.
# Match is case-insensitive on the item name; first hit wins. Post
# happens on the tick-complete edge only — un-ticking does NOT delete
# the prior comment (Trello doesn't support that anyway).
ITEM_AUTO_COMMENTS = {
    "initial photos/photo report": "Initial Photo Report Created and Uploaded to OD.",
    "initial photo report":        "Initial Photo Report Created and Uploaded to OD.",
    "initial upload":              "Initial Upload submitted To WC.",
}


# ── Card → derived fields ───────────────────────────────────────────────────

def _strip_self_pay_suffix(name):
    """Return (base_name, is_self_pay) from a card title.

    Trello card titles take forms like:
        'Donahoo, Jeffrey-Self Pay'
        'Smith, John - Self Pay'
        'Garcia, Maria-SelfPay'
        'Brown, Bob'

    The hyphen-then-self-pay-token suffix is the canonical signal per the
    user's confirmation. Match is permissive on the separator (with or
    without space) and the spelling ('self pay' vs 'selfpay').
    """
    if not name:
        return ("", False)
    raw = name.strip()
    lower = raw.lower()
    for sep in ("-", " - ", " -"):
        for token in ("self pay", "selfpay"):
            needle = f"{sep}{token}"
            if lower.endswith(needle):
                return (raw[: -len(needle)].rstrip(" -"), True)
    return (raw, False)


def _to_folder_name(client):
    """Convert a client name to OD folder format.

    Only transforms names in 'Last, First' format (comma present):
      'Casillas, Miguel & Virginia' -> 'Casillas Miguel'
      'Smith, John - AAA'           -> 'Smith John'

    Non-personal names without a comma are left exactly as-is:
      'Temuku Hills'                -> 'Temuku Hills'
      'Stater Bros.HQ Distribution' -> 'Stater Bros.HQ Distribution'
    """
    import re as _re
    name = (client or "").strip()
    if ',' not in name:
        return name
    # Personal name — strip spouse/co-insured suffix then remove comma
    name = _re.sub(r'\s*[&]\s*\S.*$', '', name).strip()
    name = _re.sub(r'\s+\band\b\s+\S.*$', '', name, flags=_re.IGNORECASE).strip()
    name = name.replace(', ', ' ').replace(',', ' ').strip()
    return name


def _strip_carrier_suffix(name):
    """Return the client portion of a card name like 'Smith, John - AAA'
    or 'Aldana, Celia- AAA' (techs are inconsistent about the spacing).

    Splits on the LAST hyphen surrounded by optional spaces — the trailing
    portion is treated as carrier+optional-suffix and dropped. Carriers
    are typically short alpha codes (AAA, FAR, ALL) so the tail length
    is bounded; longer tails (e.g. " - mit ext day 5") still get stripped,
    which is fine since they're never part of the OneDrive folder name.

    Returns the stripped name. Falls back to the full name when there's
    no hyphen at all."""
    if not name:
        return ""
    raw = name.strip()
    # Walk back from the end and trim everything past the last `-` that
    # has at least one alpha char following it. Tolerates `-AAA`, `- AAA`,
    # ` -AAA`, ` - AAA` uniformly without per-spacing case logic.
    import re as _re
    m = _re.search(r"\s*-\s*[A-Za-z][\w &/]*\s*$", raw)
    if m:
        return raw[: m.start()].rstrip(" -")
    return raw


def _find_checklist(card, name):
    """Return the dict for the named checklist on `card`, or None when
    the card has no such checklist (older cards predate the template).
    Exact match, case-insensitive.

    `name` may also be an iterable of acceptable names (tuple/list) —
    the first match wins, so callers can pass primary + alias names
    without a sweep at every call site. Used for the CLOSE OUT
    checklist which appears as both 'CLOSE OUT' and 'CLOSE OUT - ADMIN'
    on different cards in the wild."""
    if isinstance(name, (tuple, list, set)):
        targets = [str(n).strip().lower() for n in name if n]
    else:
        targets = [str(name).strip().lower()]
    for cl in card.get("checklists") or []:
        nm = (cl.get("name") or "").strip().lower()
        for t in targets:
            if nm == t:
                return cl
    return None


def _items_dict(checklist):
    """Index a checklist's items by uppercased name so per-name lookups
    don't care about whitespace drift between cards."""
    out = {}
    for it in (checklist or {}).get("checkItems") or []:
        nm = (it.get("name") or "").strip().upper()
        if nm:
            out[nm] = it
    return out


def _initial_upload_done(card):
    """True if the INITIAL UPLOAD item (in INITIAL - ADMIN) is ticked.
    Cards without the checklist at all return False — they show up in
    the queue so the user can add the checklist or upload manually."""
    cl = _find_checklist(card, ADMIN_CHECKLIST_NAME)
    if not cl:
        return False
    it = _items_dict(cl).get(ITEM_INITIAL_UPLOAD)
    if not it:
        return False
    return (it.get("state") or "").lower() == "complete"


# ── Trello fetch ────────────────────────────────────────────────────────────

def _card_to_row(c, *, lane, list_id):
    """Transform a raw Trello card dict into the IUQ row shape expected
    by the renderer. Used by both the lane-scan path and the APA-merge
    path (which fetches one card at a time via get_card and needs the
    same checklist parsing). Returns None when the card is Self-Pay.
    """
    full_name = c.get("name") or ""
    base, is_self_pay = _strip_self_pay_suffix(full_name)
    if is_self_pay:
        return None
    done = _initial_upload_done(c)

    checklists_data = []
    for cl_name, expected in TRACKED_CHECKLISTS:
        cl = _find_checklist(c, cl_name)
        items_by_name = _items_dict(cl) if cl else {}
        items = []
        for item_name in expected:
            it = items_by_name.get(item_name)
            if it:
                items.append({
                    "id":    it.get("id", ""),
                    "name":  item_name,
                    "state": (it.get("state") or "").lower(),
                })
            else:
                items.append({"id": "", "name": item_name,
                               "state": "missing"})
        checklists_data.append({
            "name":    cl_name,
            "id":      (cl.get("id") or "") if cl else "",
            "present": cl is not None,
            "items":   items,
        })
    present_cls = [cl for cl in checklists_data if cl.get("present")]
    if present_cls:
        checklists_data = present_cls
    else:
        checklists_data = checklists_data[:1]

    return {
        "card_id":    c.get("id", ""),
        "shortUrl":   c.get("shortUrl", ""),
        "name":       full_name,
        "client":     _strip_carrier_suffix(base),
        "lane":       lane,
        "list_id":    list_id,
        "board_id":   c.get("idBoard", ""),
        "labels":     [(l.get("name") or "")
                        for l in (c.get("labels") or [])],
        "checklists": checklists_data,
        "done":       done,
    }


def _resolve_apa_card(client_name):
    """Find the Trello card matching `client_name` for an APA-merged
    IUQ row. Two-tier lookup so the cheap path wins most of the time:

      1. Pinned card via persistence.get_trello_card_id (one read).
      2. Fuzzy name search via tc.find_cards_by_name (one API call,
         skipped when no pinned card AND the name is too short to
         search safely).

    Returns the lane label of the card's idList (so the row can show
    its real lane instead of generic "APA") plus the raw Trello card
    dict. Returns (None, None) when no card matches.
    """
    import trello_client as tc

    client_name = (client_name or "").strip()
    if not client_name:
        return None, None

    card_id = ""
    try:
        card_id = persistence.get_trello_card_id(client_name) or ""
    except Exception:
        card_id = ""

    if not card_id:
        # Search by the name's first meaningful token (surname). Short
        # tokens (<4 chars) skip the search to avoid over-matching
        # ("Lee" / "Wu" would hit every card containing those letters).
        token = (client_name.replace(",", " ").split() or [""])[0]
        if len(token) >= 4:
            try:
                hits = tc.find_cards_by_name(token, max_results=5)
            except Exception:
                hits = []
            for h in hits:
                hname = (h.get("name") or "").lower()
                if _norm_for_apa_match(client_name) in _norm_for_apa_match(hname):
                    card_id = h.get("card_id", "")
                    break

    if not card_id:
        return "APA", None

    try:
        card = tc.get_card(card_id)
    except Exception:
        return "APA", None
    if not card:
        return "APA", None

    # Resolve the card's actual lane name so the row reads with its
    # real lane (e.g. "AR Drop" / "Pending PM") rather than generic
    # "APA". Falls back to "APA" when the lane id isn't in our scanned
    # set — the row still renders, just with the synthetic lane tag.
    lane = LANE_LABEL_BY_LIST_ID.get(card.get("idList") or "", "APA")
    return lane, card


def _fetch_queue_from_trello():
    """Pull cards from both target lists, filter out completed/self-pay,
    return a list of dicts shaped for the renderer:

        {
          'card_id':   str,
          'shortUrl':  str,
          'name':      str,    # full Trello card title
          'client':    str,    # name with self-pay/carrier suffixes stripped
          'lane':      str,    # 'Initial Insp.' or 'Monitor'
          'list_id':   str,
          'board_id':  str,
          'labels':    [str],
          'checklist_id':  str | None,
          'items':     [{'id', 'name', 'state'}],   # 4 admin items, in order
        }

    On any network/auth failure returns an empty list. Callers should
    surface the error path separately — empty just means 'nothing to do'."""
    import trello_client as tc
    from concurrent.futures import ThreadPoolExecutor

    # Fetch each lane in parallel — sequential fetches were
    # ~4× the latency of the bottleneck because every list incurs
    # full Trello round-trip latency before the next can start.
    # `cards_in_list_with_checklists` is independent per list, so
    # there's no shared-state hazard. Cap the pool at the lane
    # count (small) so we don't oversubscribe Trello's rate limit.
    list_ids = list(LANE_LABEL_BY_LIST_ID.keys())

    def _fetch_one(list_id):
        try:
            return list_id, (tc.cards_in_list_with_checklists(list_id) or [])
        except Exception:
            return list_id, []

    out = []
    progress_updates = []  # batched persistence write at end of scan
    max_workers = max(1, min(len(list_ids), 4))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for list_id, cards in ex.map(_fetch_one, list_ids):
            lane = LANE_LABEL_BY_LIST_ID.get(list_id, "")
            for c in cards:
                row = _card_to_row(c, lane=lane, list_id=list_id)
                if row is not None:
                    out.append(row)
                cid = c.get("id") or ""
                if cid:
                    done, total = tc.checklist_progress(c)
                    if total > 0:
                        progress_updates.append((cid, done, total))
    if progress_updates:
        try:
            persistence.set_checklist_progress_bulk(progress_updates)
        except Exception:
            pass
    out.sort(key=lambda r: (r["lane"], r["client"].lower()))
    # Merge in APA Monitor "Initial Uploads" entries that aren't already
    # covered by a Trello-fetched row. The APA doc is the user's
    # authoritative list of what's being chased today; if they typed a
    # client into APA's Initial Uploads but the corresponding Trello card
    # isn't in one of the scanned lanes (or the card hasn't been created
    # yet), the row would silently miss the IUQ. Synthesized rows carry
    # `from_apa=True` + lane="APA" so the UI can render them with a
    # distinguishing chip without polluting the manual-add path.
    try:
        apa_data = _load_apa_clients_today()
    except Exception:
        apa_data = {}
    apa_initial = (apa_data.get("Initial Uploads") or {}) if apa_data else {}
    if apa_initial:
        existing_keys = {
            _norm_for_apa_match(c.get("client") or "")
            for c in out
            if (c.get("client") or "").strip()
        }
        for apa_key, apa_text in apa_initial.items():
            # Substring OR token-overlap match. Without the token-set
            # check, dedupe missed Last,First vs First Last variants
            # (e.g. Trello "Johnson, Hugh" + APA "Hugh Johnson"
            # both appeared as separate IUQ rows).
            if any(_names_overlap(apa_key, ek)
                   for ek in existing_keys if ek):
                continue
            client_name = (apa_text or "").strip()
            if not client_name:
                continue

            # Try to find the matching Trello card so the row carries
            # real checklists + a working shortUrl. Two-tier lookup
            # (pinned-id first, fuzzy name-search second). Falls back
            # to a bare-bones row when no card matches — better to
            # show the entry with no checklists than to hide it from
            # the queue entirely.
            real_lane, real_card = _resolve_apa_card(client_name)
            if real_card is not None:
                row = _card_to_row(real_card,
                                    lane=real_lane or "APA",
                                    list_id=real_card.get("idList") or "")
                if row is not None:
                    row["from_apa"] = True
                    out.append(row)
                    continue

            # No Trello card found — synthesize a minimal row so the
            # entry still shows up in the queue.
            out.append({
                "card_id":    "",
                "shortUrl":   "",
                "name":       client_name,
                "client":     client_name,
                "lane":       "APA",
                "list_id":    "",
                "board_id":   "",
                "labels":     [],
                "checklists": [],
                "done":       False,
                "from_apa":   True,
            })
    # Merge in manual entries the user has added via "➕ Add" — for jobs
    # whose Trello card lives in a board/lane we don't scan, or one-off
    # intake work that never had a card. Manual rows share the same
    # render path as Trello rows; the `manual` flag drives the ✕ Remove
    # button + suppresses checklist rendering (no checklists on disk).
    try:
        manual = persistence.get_manual_iuq_cards()
    except Exception:
        manual = []
    for m in manual:
        client = (m.get("client") or "").strip()
        if not client:
            continue
        # If a Trello-fetched / APA-synthesized row already covers this
        # client (case-insensitive), skip the manual one so the user
        # sees the real data, not the placeholder.
        if any((c.get("client") or "").lower() == client.lower()
                for c in out):
            continue
        out.append({
            "card_id":    (m.get("card_id") or "").strip(),
            "shortUrl":   (m.get("card_url") or "").strip(),
            "name":       client,
            "client":     client,
            "lane":       "Manual",
            "list_id":    "",
            "board_id":   "",
            "labels":     [],
            "checklists": [],
            "done":       False,
            "manual":     True,
        })
    return out


# ── Initial-photo presence check ────────────────────────────────────────────

_PIC_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".bmp",
             ".tif", ".tiff", ".gif", ".mp4", ".mov", ".m4v", ".avi"}


def _build_folder_index(audit_base):
    """One scandir per year folder under `audit_base` returns a list of
    `(folder_name, full_path)` tuples for all client folders in current
    year and previous year. Cheap — does NOT walk into the folders.

    Returns [] when the base is unreachable. The index is built once per
    queue load and reused across every card lookup, so per-card cost
    becomes a substring match instead of a network listdir."""
    import re as _re
    from datetime import datetime as _dt
    if not audit_base or not os.path.isdir(audit_base):
        return []
    cur_year = _dt.today().year
    out = []
    for y in (cur_year, cur_year - 1):
        try:
            with os.scandir(audit_base) as it:
                year_dirs = [e for e in it
                              if e.is_dir(follow_symlinks=False)
                              and str(y) in e.name
                              and not ("LA" in e.name.upper()
                                       and "FIRE" in e.name.upper())]
        except OSError:
            year_dirs = []
        for yd in year_dirs:
            try:
                with os.scandir(yd.path) as it2:
                    for e in it2:
                        if e.is_dir(follow_symlinks=False):
                            out.append((e.name, e.path))
            except OSError:
                continue
    return out


def _norm_for_match(s):
    """Lowercase, strip non-alpha, collapse whitespace. Matches the audit's
    own `_norm` so behavior is consistent with what users expect from the
    main audit's folder resolution."""
    import re as _re
    return _re.sub(r'\s+', ' ',
                    _re.sub(r'[^a-z ]', ' ', s.lower())).strip()


def _resolve_job_folder(client_name, folder_index):
    """Find the OneDrive job folder for `client_name` by matching
    against `folder_index`. Returns the absolute path or None.

    Match rule: shares `_names_overlap` with the IUQ APA-dedupe so
    the two stay consistent. Substring OR ≥2-token overlap — handles
    casing, spacing, comma-form vs space-form, and Last,First vs
    First Last reorderings (e.g. card 'Johnson, Hugh' matches folder
    'Hugh Johnson').

    Honors a user-pinned override (`persistence.get_folder_path`) as
    the first lookup — same source of truth the main audit uses, so
    a right-click "Change folder…" set in EITHER panel applies
    everywhere."""
    if not client_name:
        return None
    try:
        pinned = persistence.get_folder_path(client_name)
    except Exception:
        pinned = None
    if pinned and os.path.isdir(pinned):
        return pinned
    if not folder_index:
        return None
    name_norm = _norm_for_match(client_name)
    for folder, fpath in folder_index:
        if _names_overlap(name_norm, _norm_for_match(folder)):
            return fpath
    return None


def _count_initial_photos(job_path):
    """Count image files under `<job_path>/EMS/PICS/` (and CONTENTS/PICS,
    bare PICS) in any subfolder whose name contains 'initial' or
    'inspection'. Photos at PICS root (no stage subfolder) also count.

    Returns 0 when the job folder isn't found or has no PICS tree."""
    if not job_path or not os.path.isdir(job_path):
        return 0
    pics_roots = []
    for parent, leaf in (("EMS", "PICS"), ("CONTENTS", "PICS"),
                          ("EMS", "Photos"), ("", "PICS"),
                          ("", "Photos")):
        parts = [p for p in (parent, leaf) if p]
        candidate = os.path.join(job_path, *parts)
        if os.path.isdir(candidate):
            pics_roots.append(candidate)
    if not pics_roots:
        return 0
    count = 0
    for root in pics_roots:
        try:
            for cur, _dirs, files in os.walk(root):
                rel = os.path.relpath(cur, root).lower()
                if (rel == "."
                        or "initial" in rel
                        or "inspection" in rel):
                    for f in files:
                        ext = os.path.splitext(f)[1].lower()
                        if ext in _PIC_EXTS:
                            count += 1
        except OSError:
            continue
    return count


# ── APA cross-reference ────────────────────────────────────────────────────
# Read today's saved APA Monitor docx and pull the client names off the
# Initial Uploads + Daily Uploads sections. The queue uses this set to
# stamp a `✓ on APA` pill on rows whose client is already tracked there
# — visibility-only, never filters anything out.

def _norm_for_apa_match(s):
    """Lowercase, strip non-alpha, collapse spaces. Same shape we use
    for the audit's folder match. 'Smith, John' and 'John A Smith' both
    normalize to overlapping token sets so a Last/First reorder doesn't
    break the cross-reference."""
    import re as _re
    return _re.sub(r"\s+", " ",
                    _re.sub(r"[^a-z ]", " ", (s or "").lower())).strip()


def _names_overlap(a_norm: str, b_norm: str) -> bool:
    """True when two pre-normalized client names look like the same
    person. Two-tier check:
      • Bidirectional substring (len ≥ 4) — catches casing / spacing
        / extra-token cases like 'smith john' ⊂ 'smith john a'.
      • Token-set overlap (≥ 2 tokens of length ≥ 2) — catches
        Last,First vs First Last reorderings like
        'johnson hugh' / 'hugh johnson'.

    Without the token tier, the IUQ's APA-merge dedupe missed dupes
    where one source carried 'Last, First' and the other 'First Last'
    (e.g. Hugh Johnson appearing twice in Initial Uploads)."""
    if not a_norm or not b_norm:
        return False
    if len(a_norm) >= 4 and a_norm in b_norm:
        return True
    if len(b_norm) >= 4 and b_norm in a_norm:
        return True
    a_toks = {t for t in a_norm.split() if len(t) >= 2}
    b_toks = {t for t in b_norm.split() if len(t) >= 2}
    return len(a_toks & b_toks) >= 2


def _load_apa_clients_today():
    """Return a dict of {section: {normalized_client_name: original_text}}
    extracted from today's saved APA Monitor docx. Sections covered are
    Initial Uploads and Daily Uploads — those are the user-confirmed
    cross-reference targets.

    Empty dict on any failure (no APA doc saved yet, parser error,
    permission issue). Lazy-imports apa_monitor_gui so the queue tool
    starts up even if APA's deps aren't loadable."""
    try:
        import apa_logic as apa
    except Exception:
        return {}
    try:
        path = apa.doc_path_for_today()
    except Exception:
        return {}
    if not path or not os.path.isfile(path):
        return {}
    try:
        sections = apa.parse_existing_doc(path)
    except Exception:
        return {}
    out = {}
    for sec_name in (apa.SEC_INITIAL_UPLOADS, apa.SEC_DAILY_UPLOADS):
        bucket = {}
        for entry in sections.get(sec_name, []) or []:
            # parse_existing_doc returns (text, highlighted) tuples;
            # we only care about the text. strip_status_from_text gives
            # us the clean 'Client - Carrier' base before normalizing
            # so '-Initial-pending' suffixes don't sneak into the key.
            text = entry[0] if isinstance(entry, tuple) else entry
            base = apa.strip_status_from_text(text)
            key = _norm_for_apa_match(base)
            if key:
                bucket.setdefault(key, base)
        out[sec_name] = bucket
    return out


def _apa_section_for_client(apa_data, client_name):
    """If `client_name` matches a row in today's APA Initial Uploads or
    Daily Uploads, return a short label naming which section. Otherwise
    return ''.

    Match is bidirectional substring on normalized forms with a 4-char
    floor (matches the audit's own folder-resolution rule). Initial wins
    over Daily when both contain the same client (rare but possible)."""
    if not apa_data or not client_name:
        return ""
    key = _norm_for_apa_match(client_name)
    if not key:
        return ""
    # Sections in priority order — Initial outranks Daily.
    for section_label, section_short in (
            ("Initial Uploads", "Initial"),
            ("Daily Uploads",   "Daily")):
        bucket = apa_data.get(section_label) or {}
        for apa_key in bucket.keys():
            if ((len(key) >= 4 and key in apa_key)
                    or (len(apa_key) >= 4 and apa_key in key)):
                return section_short
    return ""


# ── View (Frame, embeddable in any host) ──────────────────────────────────
# Split from the ToolPanel wrapper so the audit panel can host the same
# UI inside its tab strip without subprocessing a second window. The view
# packs all of its widgets into `self` (a Frame) — the host just packs
# this view in turn. Standalone mode wraps it in `InitialUploadApp`.

class InitialUploadView(tk.Frame):
    """The Initial Upload Queue UI as a reusable Frame.

    Pack into any parent (a Toplevel/ToolPanel for standalone, an audit
    tab Frame for embedded). All state (cards, APA cross-reference,
    poll/lifecycle) lives on the view, not the host."""

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._cards    = []
        self._apa_data = {}
        self._loading  = True
        self._build_ui()
        self._load_async(force_refresh=False)


class InitialUploadApp(ToolPanel):
    """Standalone-tool wrapper. Owns the title/geometry persistence and
    hosts an `InitialUploadView`. Kept as a separate class so the
    launcher's standalone fallback still works (and so people who don't
    want the audit-tab merge can run this directly via `python
    initial_upload_queue.py`)."""

    TOOL_TITLE = "Initial Upload Queue"
    TOOL_AUMID = "Servpro.EMS.InitialUpload"
    TOOL_GEOMETRY_KEY = "initial_upload_geometry"
    DEFAULT_GEOMETRY  = "960x680"

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Initial Upload Queue")
        self.configure(bg=BG)
        self.minsize(700, 480)
        self.restore_geometry()
        self._view = InitialUploadView(self)
        self._view.pack(fill="both", expand=True)
        self.bind("<Destroy>", self._on_destroy)

    def _on_destroy(self, event):
        # <Destroy> fires for every descendant being torn down too;
        # only react when the panel itself is the one going away.
        if event.widget is not self:
            return
        try:
            self.save_geometry()
        except Exception:
            pass

    # ── chrome ──────────────────────────────────────────────────────────────
    # Layout convention shared with Backlog + SP Recent so the four
    # audit tabs feel cohesive: NO redundant title (the tab strip is
    # already the title), a single thin control band with view-specific
    # primary controls on the left and 🔄 Refresh on the right, an
    # optional subtitle helper line, an italic status line, then the
    # scrollable body. Same fonts, same paddings, same button styles.
    def _build_ui(self):
        # Lifecycle cue — Initial Upload Queue is the INTAKE step in a
        # file's life. Blue strip mirrors Snapshot's green CLOSEOUT
        # banner so the two ends of the lifecycle visually echo each
        # other.
        tk.Label(
            self,
            text="🚀  INTAKE  ·  New files starting — pull from Trello lanes",
            font=("Segoe UI Variable", 9, "bold"),
            bg=INFO_BG, fg=INFO_FG,
            anchor="w", padx=14, pady=4
        ).pack(fill="x", side="top")

        ctl = tk.Frame(self, bg=BG, padx=14, pady=8)
        ctl.pack(fill="x")
        self._count_lbl = tk.Label(ctl, text="loading…",
                                    font=("Segoe UI Variable", 9, "bold"),
                                    bg=BG, fg=TEXT_DARK)
        self._count_lbl.pack(side="left")
        done_button(ctl, "🔄 Refresh", padx=12, pady=3,
                  command=self._on_refresh
                  ).pack(side="right")
        # Manual entry — for jobs whose Trello card isn't in one of the
        # scanned lanes (or doesn't exist yet). Dialog asks for the
        # client name + optional Trello URL; the row joins the queue
        # tagged "Manual" until the user removes it.
        send_button(ctl, "➕ Add", padx=12, pady=3,
                  command=self._open_add_manual_dialog
                  ).pack(side="right", padx=(0, 8))

        tk.Label(self,
                 text=("Trello WIP · Initial Inspections + Monitor + "
                       "Office Questions lanes  ·  excludes "
                       "already-uploaded and Self Pay"),
                 font=("Segoe UI Variable", 8), bg=BG, fg=TEXT_GRAY,
                 padx=14, anchor="w"
                 ).pack(fill="x")

        self._status_lbl = tk.Label(self, text="",
                                     font=("Segoe UI Variable", 8, "italic"),
                                     bg=BG, fg=TEXT_GRAY,
                                     padx=14, anchor="w")
        self._status_lbl.pack(fill="x", pady=(0, 4))

        self._scroll = ScrollableFrame(self, bg=BG, canvas_bg=WHITE)
        self._scroll.canvas.config(highlightthickness=1,
                                    highlightbackground=BORDER)
        self._scroll.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self._inner = self._scroll.inner

    # ── load / refresh ──────────────────────────────────────────────────────
    def _on_refresh(self):
        try:
            persistence.clear_initial_queue_cache()
        except Exception:
            pass
        # Force today's run-doc to re-parse — the user may have edited
        # the .docx since we last cached it.
        self._today_jobs_cache = None
        self._load_async(force_refresh=True)

    def _load_async(self, *, force_refresh):
        self._loading = True
        self._count_lbl.config(text="loading…")
        self._status_lbl.config(text="Fetching from Trello…" if force_refresh
                                 else "Loading…")
        for w in self._inner.winfo_children():
            try: w.destroy()
            except tk.TclError: pass

        # APA cross-reference is cheap (one .docx parse) and we want it
        # fresh on every load so a just-saved APA doc shows its rows
        # immediately. Always reload, even on cache hit.
        try:
            self._apa_data = _load_apa_clients_today()
        except Exception:
            self._apa_data = {}

        cached = None if force_refresh else persistence.get_initial_queue_cache()
        if cached is not None:
            # Hot path — cache hit, render synchronously.
            self._cards = cached
            self._loading = False
            self._status_lbl.config(text="Cached from earlier today  ·  "
                                          "click 🔄 Refresh for fresh data")
            self._render_rows()
            return

        # Cache miss: hit Trello on a thread so the UI stays responsive.
        def _bg():
            try:
                cards = _fetch_queue_from_trello()
                err = None
            except Exception as ex:
                cards, err = [], str(ex)

            # One-shot folder index — cheap (one scandir per year folder)
            # and reused for every card's photo-count lookup. Beats
            # calling audit_jobs per card (which would trigger the full
            # forms+photos check pipeline just to extract a path).
            try:
                import config
                audit_base = config.load().get("audit_base") or ""
                folder_index = _build_folder_index(audit_base)
            except Exception:
                folder_index = []

            # Forms audit reuses the same `check_forms` helper the main
            # audit runs — cheap (one scandir over EMS/DOCS) so we can
            # do it per-card up front and render "Missing: ATP, CIF"
            # right on the row. Without this the user had to open Run
            # Audit just to know what was missing for an Initial Upload.
            try:
                from audit_logic import check_forms as _check_forms
            except Exception:
                _check_forms = None

            for c in cards:
                try:
                    job_path = _resolve_job_folder(c["client"], folder_index)
                    c["job_path"]        = job_path or ""
                    c["initial_photos"]  = (_count_initial_photos(job_path)
                                             if job_path else 0)
                    if job_path and _check_forms is not None:
                        ems = os.path.join(job_path, "EMS")
                        base = ems if os.path.isdir(ems) else job_path
                        try:
                            c["form_issues"] = _check_forms(base) or []
                        except Exception:
                            c["form_issues"] = []
                    else:
                        c["form_issues"] = []
                except Exception:
                    c["job_path"]        = ""
                    c["initial_photos"]  = 0
                    c["form_issues"]     = []

            # SharePoint match-up — surface "new SP folder found" per
            # card so the user doesn't have to flip to the SP Recent
            # tab to know there's a fresh upload waiting. Scans SP
            # folders modified in the last 14 days, resolves each back
            # to an OD client folder, then matches against the cards
            # we just resolved job_paths for. Adds a `sp_match` dict
            # to each matched card so _build_row can render an inline
            # 🆕 SP chip with the missing-file count.
            try:
                from sp_recent_audit import (
                    _list_recent_sp_folders, _resolve_od_for_sp,
                    _count_missing_in_od,
                )
                from datetime import datetime as _dt, timedelta as _td
                _end_ts   = _dt.now().timestamp()
                _start_ts = (_dt.now() - _td(days=14)).timestamp()
                _sp_folders = _list_recent_sp_folders(_start_ts, _end_ts)
                _cur_year = _dt.today().year
                _years = [_cur_year, _cur_year - 1]
                _card_by_path = {}
                for c in cards:
                    p = c.get("job_path") or ""
                    if p:
                        _card_by_path[
                            os.path.normcase(os.path.normpath(p))] = c
                for _sp in _sp_folders:
                    try:
                        od_path, _od_name = _resolve_od_for_sp(
                            _sp.get("name") or "", audit_base,
                            years=_years,
                            sp_path=_sp.get("path") or "")
                    except Exception:
                        continue
                    if not od_path:
                        continue
                    key = os.path.normcase(os.path.normpath(od_path))
                    card = _card_by_path.get(key)
                    if card is None:
                        continue
                    try:
                        sp_count, od_count, missing = _count_missing_in_od(
                            _sp["path"], od_path)
                    except Exception:
                        sp_count = od_count = missing = 0
                    # When a single card matches multiple SP folders
                    # (rare — happens on multi-claim or re-inspection
                    # jobs) the freshest match wins; the `mtime` field
                    # on _sp is the SP folder's most-recent mtime.
                    prior = card.get("sp_match") or {}
                    if (not prior
                            or _sp.get("mtime", 0)
                                 >= prior.get("mtime", 0)):
                        card["sp_match"] = {
                            "sp_path":  _sp["path"],
                            "sp_name":  _sp.get("name", ""),
                            "sp_count": sp_count,
                            "od_count": od_count,
                            "missing":  missing,
                            "mtime":    _sp.get("mtime", 0),
                            "tech":     _sp.get("tech", ""),
                        }
            except Exception:
                # SP scan failures are non-fatal — IUQ still renders
                # cards without the chip; user can flip to SP Recent
                # to see the same data.
                pass

            # Intake-time spreadsheet sync. Every card visible in the
            # Initial Upload lanes should appear on Snapshots' NEW LOSS
            # sheet — that's the user's signal a file is in flight even
            # before the first audit run. `mark_new_loss` is idempotent
            # (case-insensitive name match in _apply_one), so re-scans
            # don't dupe rows. Loss type pulled from Trello label color
            # when present. Best-effort — a locked workbook just queues
            # the writes for next call, never blocks the UI refresh.
            try:
                import snapshots_excel as _sx
                import trello_client as _tc
                for c in cards:
                    name = (c.get("client") or "").strip()
                    if not name:
                        continue
                    try:
                        loss_type = _tc.card_loss_type(
                            {"labels": c.get("labels") or []})
                    except Exception:
                        loss_type = None
                    try:
                        _sx.mark_new_loss(name,
                                           type_of_loss=loss_type or None)
                    except Exception:
                        # Per-card failure shouldn't kill the rest of
                        # the batch — keep going.
                        pass
            except Exception:
                pass

            def _done():
                if err:
                    self._status_lbl.config(text=f"Trello error: {err}")
                    self._cards = []
                    self._loading = False
                    self._render_rows()
                    return
                self._cards = cards
                self._loading = False
                try:
                    persistence.set_initial_queue_cache(cards)
                except Exception:
                    pass
                self._status_lbl.config(text="Fresh from Trello")
                self._render_rows()
            self.after(0, _done)

        threading.Thread(target=_bg, daemon=True).start()

    # ── rendering ──────────────────────────────────────────────────────────
    def _render_rows(self):
        for w in self._inner.winfo_children():
            try: w.destroy()
            except tk.TclError: pass

        # Visibility filter — show every card whose INITIAL UPLOAD is
        # still unticked, PLUS any ticked card that's still on today's
        # APA Initial Uploads section (so the user can verify all the
        # other checklist items got ticked before the row drops out of
        # view). Done-and-not-on-APA cards stay in self._cards (the
        # cache) but render hidden until they leave APA.
        apa_data = getattr(self, "_apa_data", None) or {}
        def _visible(c):
            if not c.get("done"):
                return True
            return _apa_section_for_client(
                apa_data, c.get("client") or "") == "Initial"
        visible_cards = [c for c in self._cards if _visible(c)]

        n = len(visible_cards)
        self._count_lbl.config(text=f"{n} job{'s' if n != 1 else ''}")
        # Publish the visible count to persistence so the launcher's
        # IUQ tile can render a notification badge without spinning up
        # this panel. Same pattern Hygiene uses with
        # `hygiene_action_needed_count`.
        try:
            persistence.set_value("initial_upload_visible_count", int(n))
        except Exception:
            pass

        if not visible_cards and not self._loading:
            tk.Label(self._inner,
                     text=("✓ Nothing to do — every card in the target lanes "
                           "either has its INITIAL UPLOAD ticked or is Self Pay."),
                     font=("Segoe UI Variable", 10, "italic"),
                     bg=WHITE, fg=TEXT_GRAY, padx=20, pady=30
                     ).pack(fill="x")
            return

        # Top group: cards matching today's APA Initial Uploads section.
        # User explicitly wants APA-queued items first since the APA doc
        # is where admins manually park "needs initial upload" items —
        # those should bubble above the Trello-lane defaults.
        on_apa_initial = []
        rest = []
        for c in visible_cards:
            section = _apa_section_for_client(apa_data, c.get("client") or "")
            if section == "Initial":
                on_apa_initial.append(c)
            else:
                rest.append(c)
        on_apa_initial.sort(key=lambda r: (r.get("client") or "").lower())

        if on_apa_initial:
            tk.Label(self._inner,
                     text=f"  📋 On APA Initial Uploads  ({len(on_apa_initial)})",
                     font=("Segoe UI Variable", 9, "bold"),
                     bg=WARN_BG, fg=WARN_FG,
                     anchor="w", padx=10, pady=4
                     ).pack(fill="x", pady=(8, 2))
            for c in on_apa_initial:
                self._build_row(c)

        # 🆕 New Losses (today's run) — sourced from today's run-doc.
        # parse_run_doc flags any line containing "new loss" on the
        # entry, so this surfaces brand-new files as soon as ops adds
        # them to the .docx, regardless of which Trello lane the card
        # is currently parked in. Matched cards bubble up here instead
        # of rendering in their lane below. Unmatched run-doc entries
        # (file is on the run but no Trello card exists yet) render as
        # a placeholder so the admin can spot intake-side gaps.
        # Positioned between APA Initials and the lane block per user
        # preference — above Monitor, below APA Initials.
        try:
            today_jobs = self._today_run_doc_jobs()
        except Exception:
            today_jobs = []
        new_loss_jobs = [j for j in (today_jobs or [])
                         if j.get("new_loss")]
        new_loss_norms = {
            _norm_client_for_run_doc(j.get("client") or ""): j
            for j in new_loss_jobs
        }
        new_loss_norms.pop("", None)

        new_loss_cards = []
        remaining_rest = []
        for c in rest:
            cnorm = _norm_client_for_run_doc(c.get("client") or "")
            if cnorm and cnorm in new_loss_norms:
                new_loss_cards.append(c)
            else:
                remaining_rest.append(c)
        matched_norms = {
            _norm_client_for_run_doc(c.get("client") or "")
            for c in new_loss_cards
        }
        # Second pass — run-doc new-loss clients with no matching IUQ
        # lane card. Before treating them as "no Trello card yet",
        # consult the shared jobs DB: if any tool (right-click pin,
        # audit, snapshot) has already linked a card to this client,
        # promote it into the matched set so the row renders with
        # the card. This is what makes pin-from-other-surface work
        # in IUQ without each tool having to gossip directly.
        ems_db_promoted = []
        try:
            import ems_db
            import trello_client as _tc
            for norm, j in new_loss_norms.items():
                if norm in matched_norms:
                    continue
                client = (j.get("client") or "").strip()
                db_job = ems_db.find_job_by_name(client)
                if not db_job:
                    continue
                card_id = ems_db.get_link(db_job["canon_key"], "trello_card")
                if not card_id:
                    continue
                try:
                    card = _tc.get_card(card_id)
                except Exception:
                    card = None
                if not card:
                    continue
                # Synthesize a card dict shaped like the IUQ's other
                # `visible_cards` entries so _build_row works as-is.
                # Trello `labels` come back as dicts ({name,color,id,...});
                # the rest of the IUQ stores label NAMES as plain
                # strings (see _card_to_row line 377). Flatten here so
                # the `"  ·  ".join(...)` in _build_row doesn't choke
                # on a list of dicts with `sequence item 0: dict found`.
                _raw_labels = card.get("labels") or []
                _label_names = [
                    (l.get("name") or "") if isinstance(l, dict) else str(l)
                    for l in _raw_labels
                ]
                promoted = {
                    "card_id":     card.get("id", card_id),
                    "name":        card.get("name", client),
                    "client":      client,
                    "lane":        (db_job.get("metadata") or {}
                                    ).get("lane", ""),
                    "labels":      [n for n in _label_names if n],
                    "url":         card.get("shortUrl", ""),
                    "job_path":    "",
                    "initial_photos": 0,
                    "form_issues": [],
                    "done":        False,
                    "_from_ems_db": True,
                }
                ems_db_promoted.append(promoted)
                matched_norms.add(norm)
        except Exception:
            pass
        new_loss_cards.extend(ems_db_promoted)
        unmatched_new_losses = [
            j for n, j in new_loss_norms.items()
            if n not in matched_norms
        ]

        total_nl = len(new_loss_cards) + len(unmatched_new_losses)
        if total_nl:
            tk.Label(self._inner,
                     text=f"  🆕 New Losses (today's run)  ({total_nl})",
                     font=("Segoe UI Variable", 9, "bold"),
                     bg=WARN_BG, fg=WARN_FG,
                     anchor="w", padx=10, pady=4
                     ).pack(fill="x", pady=(8, 2))
            for c in sorted(new_loss_cards,
                            key=lambda r: (r.get("client") or "").lower()):
                self._build_row(c)
            for j in sorted(unmatched_new_losses,
                            key=lambda r: (r.get("client") or "").lower()):
                ph = tk.Frame(self._inner, bg=WHITE,
                              highlightthickness=1,
                              highlightbackground=BORDER)
                ph.pack(fill="x", padx=8, pady=3)
                body = tk.Frame(ph, bg=WHITE, padx=10, pady=8)
                body.pack(fill="x")
                tk.Label(body,
                         text=f"🆕  {j.get('client') or '(unnamed)'}",
                         font=("Segoe UI Variable", 11, "bold"),
                         bg=WHITE, fg=TEXT_DARK,
                         anchor="w").pack(side="left")
                slot = (j.get("time_slot") or "").strip()
                if slot:
                    tk.Label(body, text=f"  ·  {slot}",
                             font=("Segoe UI Variable", 9),
                             bg=WHITE, fg=TEXT_GRAY,
                             anchor="w").pack(side="left")
                tk.Label(body,
                         text="  ·  on run-doc, no Trello card yet",
                         font=("Segoe UI Variable", 9, "italic"),
                         bg=WHITE, fg=WARN_FG,
                         anchor="w").pack(side="left")

        # Remaining rows: keep the lane grouping the user is used to.
        # Cards already shown in the APA Initial / New Loss groups are
        # excluded so nothing renders twice.
        by_lane = {}
        for c in remaining_rest:
            by_lane.setdefault(c["lane"] or "Unknown", []).append(c)

        # Render lanes in the explicit order defined by LANE_LABEL_BY_LIST_ID
        # (Initial Insp. → Monitor → Office Q. → WIP → TBS → AR Drop).
        # Previously sorted alphabetically, which dragged "AR Drop" to the
        # TOP — user keeps AR Drop visually parked at the bottom because
        # it's an intake holding lane, not a workflow lane. Any lane name
        # that isn't in the canonical dict (defensive: future lane added,
        # rename) lands after the canonical ones, in alpha order.
        ordered_labels = list(LANE_LABEL_BY_LIST_ID.values())
        canonical = [l for l in ordered_labels if l in by_lane]
        leftovers = sorted(l for l in by_lane.keys() if l not in ordered_labels)
        # Property grouping helper — given a list of cards in render
        # order, sort them so multi-unit siblings cluster and inject
        # a "🏢 <Property> (N)" sub-header above the first card of
        # each property group. Properties with only one visible card
        # render flat (no sub-header — would just be noise).
        def _render_lane_cards(cards_in_lane):
            try:
                import ems_db as _db
            except Exception:
                _db = None
            # Map each card to its parent_canon (None when single-fam).
            def _parent_for(c):
                if _db is None:
                    return None
                client = (c.get("client") or "").strip()
                if not client:
                    return None
                prop, _unit = _db.detect_property_and_unit(client)
                return _db.canon_key(prop) if prop else None
            tagged = [(c, _parent_for(c)) for c in cards_in_lane]
            # Count siblings per parent to decide whether a property
            # group earns a sub-header.
            parent_counts: dict[str, int] = {}
            for _c, p in tagged:
                if p:
                    parent_counts[p] = parent_counts.get(p, 0) + 1
            # Stable sort: parented siblings group together; single-fam
            # interleaves in their original order via the position key.
            ordered = sorted(
                enumerate(tagged),
                key=lambda x: (
                    x[1][1] or "~zzz",   # cards with parent sort first
                    x[0],                # preserve incoming order within group
                ),
            )
            current_parent = None
            for _i, (c, parent) in ordered:
                if (parent and parent_counts.get(parent, 0) >= 2
                        and parent != current_parent):
                    # Property sub-header — a touch darker than the
                    # lane banner so it reads as nested.
                    parent_job = _db.find_property_of(
                        _db.canon_key((c.get("client") or "")))
                    if parent_job:
                        prop_label = parent_job["display_name"]
                    else:
                        # No umbrella row in DB — derive a clean label
                        # by Title-casing the canonical key.
                        prop_label = " ".join(
                            w.capitalize() for w in parent.split())
                    tk.Label(self._inner,
                             text=f"    🏢 {prop_label}  "
                                  f"({parent_counts[parent]})",
                             font=("Segoe UI Variable", 9, "bold"),
                             bg=LINK_BG, fg=LINK_FG,
                             anchor="w", padx=18, pady=3
                             ).pack(fill="x", pady=(2, 1))
                    current_parent = parent
                elif not parent:
                    # Leaving a property group — reset so the next
                    # sibling cluster gets its own header.
                    current_parent = None
                self._build_row(c)

        for lane in canonical + leftovers:
            tk.Label(self._inner,
                     text=f"  {lane}  ({len(by_lane[lane])})",
                     font=("Segoe UI Variable", 9, "bold"),
                     bg=SUCCESS_BG, fg=SUCCESS_FG,
                     anchor="w", padx=10, pady=4
                     ).pack(fill="x", pady=(8, 2))
            _render_lane_cards(by_lane[lane])
        # Auto-attach default tooltips to any inline buttons spawned by
        # _build_row — per-widget marker prevents double-attaching for
        # buttons that already have an explicit tooltip. View isn't a
        # ToolPanel so we call the freestanding helper directly.
        try:
            from tool_panel import attach_default_tooltips
            self.after_idle(lambda: attach_default_tooltips(self))
        except Exception:
            pass

    def _build_row(self, card):
        client = card.get("client") or "(unknown)"
        is_commercial = bool(self._is_commercial(client))

        row = tk.Frame(self._inner, bg=WHITE,
                        highlightthickness=1, highlightbackground=BORDER)
        row.pack(fill="x", padx=8, pady=3)

        body = tk.Frame(row, bg=WHITE, padx=10, pady=8)
        body.pack(fill="x")

        # Top line — name + actions
        top = tk.Frame(body, bg=WHITE)
        top.pack(fill="x")

        name_font = ("Segoe UI Variable", 11, "bold")
        name_color = TEXT_GRAY if is_commercial else TEXT_DARK
        # Strikethrough rendering via overstrike
        if is_commercial:
            name_font = ("Segoe UI Variable", 11, "bold overstrike")
        tk.Label(top, text=card.get("name") or client,
                 font=name_font, bg=WHITE, fg=name_color,
                 anchor="w").pack(side="left")

        # Time-slot pill — mirrors the audit row when this client is
        # on today's run-doc. Pulls from the parent RunAuditApp's
        # parsed jobs via `_time_slot_for_client`; silently no-ops when
        # IUQ is hosted outside the audit panel (standalone mode) or
        # the client isn't on the run-doc.
        try:
            time_slot = self._time_slot_for_client(client)
        except Exception:
            time_slot = ""
        if time_slot:
            ts_text = (time_slot if time_slot.startswith("@")
                       else f"🕒 {time_slot}")
            ts_lbl = tk.Label(top, text=f" {ts_text} ",
                                font=("Segoe UI Variable", 7, "bold"),
                                bg=LINK_BG, fg=LINK_FG,
                                padx=4, pady=1)
            ts_lbl.pack(side="left", padx=(8, 0))
            try:
                from tool_panel import attach_tooltip
                attach_tooltip(
                    ts_lbl,
                    f"Appointment time on today's run-doc: {time_slot}")
            except Exception:
                pass

        # Checklist progress chip — one-glance "X/Y items complete" on
        # the card. Green when 100%, amber when partial, hidden when no
        # checklists. Pulls directly from this row's card dict (which
        # already has the checklists inlined from
        # cards_in_list_with_checklists) so this is a free render — no
        # extra Trello call.
        try:
            import trello_client as _tc
            done, total = _tc.checklist_progress(card)
        except Exception:
            done, total = 0, 0
        if total > 0:
            chip_done = done >= total
            chip_bg = GREEN if chip_done else "#F5E5C8"
            chip_fg = WHITE if chip_done else "#7A5A1F"
            chip_text = (f"✓ {done}/{total}" if chip_done
                         else f"☑ {done}/{total}")
            cl_lbl = tk.Label(top, text=f" {chip_text} ",
                              font=("Segoe UI Variable", 7, "bold"),
                              bg=chip_bg, fg=chip_fg,
                              padx=4, pady=1)
            cl_lbl.pack(side="left", padx=(6, 0))
            try:
                from tool_panel import attach_tooltip
                attach_tooltip(
                    cl_lbl,
                    f"Trello checklist progress: {done} of {total} items "
                    f"complete." + (" All done." if chip_done else ""))
            except Exception:
                pass

        # Right-side action buttons. Trello logo button is the shared
        # factory now so every panel renders this exact same shape.
        # Right-click → 📌 Pin/Change Trello card via the shared menu —
        # mirrors the OD-folder right-click pattern.
        _client_for_pin = (card.get("name") or card.get("client")
                            or "").strip()
        trello_link_button(
            top, command=lambda c=card: self._open_card(c),
            client=_client_for_pin or None,
            pinned=bool((card.get("card_id") or "").strip()),
        ).pack(side="right")
        # ➕ Create Trello card — for rows without an `card_id` (manual
        # entries the user added when the job isn't on Trello yet).
        # One click creates a card in the Initial Inspections lane,
        # updates this row's card_id, and pins it to the client name
        # so the rest of the suite picks it up.
        if not (card.get("card_id") or "").strip():
            link_button(
                top, "➕ Trello card", padx=6, pady=1,
                command=lambda c=card: self._create_trello_card_for(c),
                tooltip=("Create a new Trello card in the Initial "
                         "Inspections lane for this client and pin it "
                         "so the audit + snapshot tools can find it."),
            ).pack(side="right", padx=(0, 6))
        # Manual rows get a ✕ Remove button so the user can drop their
        # own ad-hoc entries without editing state.json. Trello-fetched
        # rows don't show this — those come and go with the lane.
        if card.get("manual"):
            icon_button(
                top, "✕", fg=FLAG_RED, hover="#FBE3DD",
                font=("Segoe UI Variable", 9, "bold"),
                relief="flat", bd=0, padx=6, pady=1, cursor="hand2",
                command=lambda c=card: self._remove_manual_card(c)
            ).pack(side="right", padx=(0, 4))
        # Pin button — same visual as the Run Audit row's: count badge
        # ("📌 N") + green fill when at least one Trello card is
        # already pinned to this client, plain "📌" outline otherwise.
        # Click opens the multi-select pin dialog; on save the badge
        # updates in place (no row re-render needed).
        pinned_count = 0
        try:
            pinned_count = len(persistence.get_trello_card_ids(client))
        except Exception:
            pass
        pin_btn = tk.Button(
            top,
            text=f"📌 {pinned_count}" if pinned_count else "📌",
            font=("Segoe UI Variable", 8, "bold" if pinned_count else "normal"),
            bg=GREEN if pinned_count else WHITE,
            fg=WHITE if pinned_count else TEXT_DARK,
            activebackground=GREEN_DARK if pinned_count else "#EEEEEE",
            activeforeground=WHITE if pinned_count else TEXT_DARK,
            relief="flat" if pinned_count else "solid",
            bd=0 if pinned_count else 1,
            padx=8, pady=2, cursor="hand2")

        def _pin_done(_ids, _btn=pin_btn, _client=client):
            try:
                new_count = len(persistence.get_trello_card_ids(_client))
            except Exception:
                new_count = 0
            try:
                _btn.configure(
                    text=f"📌 {new_count}" if new_count else "📌",
                    font=("Segoe UI Variable", 8,
                          "bold" if new_count else "normal"),
                    bg=GREEN if new_count else WHITE,
                    fg=WHITE if new_count else TEXT_DARK,
                    activebackground=(GREEN_DARK if new_count
                                       else "#EEEEEE"),
                    relief="flat" if new_count else "solid",
                    bd=0 if new_count else 1)
            except tk.TclError:
                pass

        pin_btn.configure(
            command=lambda _client=client, _cb=_pin_done:
                open_trello_pin_dialog(self, _client, on_pinned=_cb))
        pin_btn.pack(side="right", padx=(0, 6))
        # Job Notes button removed per user (2026-05-08): Notes was
        # never used in the Initial Upload flow — keep this row's
        # buttons aligned with what the Daily Run audit row shows.

        # Action buttons on the top-right (mirrors the Daily Run audit
        # card's right-side toolbar). Pack `side="right"` so each new
        # button stacks to the LEFT of the previous one — final visual
        # order reads: OD | SP | WC | DS | [Make folders] | Pin | Trello.
        photos = card.get("initial_photos", 0)
        client_name = (card.get("client") or "").strip()
        job_path = card.get("job_path") or ""
        folder_on_disk = bool(job_path) and os.path.isdir(job_path)
        # EMS layout completeness — only "fully scaffolded" when the
        # client folder AND all three EMS subfolders are on disk. When
        # any of those are missing the 📂 Make folders button stays
        # visible; once the tree is complete it disappears (there's
        # nothing left for that button to do).
        ems_complete = (
            folder_on_disk
            and os.path.isdir(os.path.join(job_path, "EMS"))
            and os.path.isdir(os.path.join(job_path, "EMS", "DOCS"))
            and os.path.isdir(os.path.join(job_path, "EMS", "PICS")))

        # 📂 Make folders — only when the EMS subtree isn't fully
        # scaffolded. Brand-new cards (no folder on disk yet) and
        # half-scaffolded folders both surface this button; once the
        # tree is complete the button hides. The other action buttons
        # (📁 OD, 📥 SP, 📥 WC, 📝 DS) auto-create the folder on first
        # use too, so this button is the "do it explicitly without
        # importing anything" affordance.
        # NOTE on button shape: every per-row button in this section
        # uses link_button's defaults (font=9pt bold, padx=12, pady=5)
        # so they're all the same size and the text sits vertically
        # centered in the pill. Earlier code had a mix of font=7-bold
        # + padx=4 vs default + padx=6, which made smaller pills sit
        # alongside taller ones and looked like the text was
        # bottom-anchored. Unified per user request 2026-05-22.
        if not ems_complete and client_name:
            link_button(
                top, "📂 Make folders",
                command=lambda p=job_path, c=card:
                    self._make_job_folders(p, card=c),
                tooltip=("Create the EMS / DOCS / PICS structure under "
                         "this job's OD folder. Also creates the client "
                         "folder itself when it doesn't exist yet."),
            ).pack(side="right", padx=(4, 0))

        # OD / SP / Import — visible whenever the card has a client.
        # Each handler auto-derives + creates the job folder on first
        # use, so a brand-new loss card (no folder yet) doesn't need
        # to click 📂 Make folders first.
        if client_name:
            # 📥 Import — unified scanner that auto-routes whatever
            # zip is in Downloads (WC attachments OR DocuSign packet).
            link_button(
                top, "📥 Import",
                command=lambda c=card: self._smart_import_for_card(c),
                tooltip=("Scans Downloads for an importable zip — "
                          "Workcenter attachments (mixed photos+forms) "
                          "OR a signed DocuSign Final-Paperwork packet "
                          "— and drops the contents in the right place. "
                          "Picker if multiple kinds are downloaded."),
            ).pack(side="right", padx=(4, 0))
            # 📥 SP — label changes based on SP scan result.
            sp_match = card.get("sp_match") or {}
            sp_missing = int(sp_match.get("missing") or 0)
            if sp_missing > 0:
                sp_btn = link_button(
                    top, f"📥 SP +{sp_missing} new",
                    command=lambda c=card: self._import_sp_for_card(c),
                    tooltip=(
                        f"New SP folder matched: {sp_match.get('sp_name','')}\n"
                        f"  · SP files: {sp_match.get('sp_count', 0)}\n"
                        f"  · OD files: {sp_match.get('od_count', 0)}\n"
                        f"  · {sp_missing} missing in OD"),
                )
            elif sp_match:
                sp_btn = link_button(
                    top, "📁 SP matched",
                    command=lambda c=card: self._import_sp_for_card(c),
                    tooltip=(
                        f"SP folder matched: {sp_match.get('sp_name','')}\n"
                        f"  · {sp_match.get('sp_count', 0)} files (all in OD)"),
                )
            else:
                sp_btn = link_button(
                    top, "📥 SP",
                    command=lambda c=card: self._import_sp_for_card(c),
                )
            sp_btn.pack(side="right", padx=(4, 0))
            link_button(
                top, "📁 OD",
                command=lambda p=job_path, c=card:
                    self._open_od_folder(p, card=c),
            ).pack(side="right", padx=(4, 0))

        # 📌 Flag missing — opens the shared dialog. Same shape as the
        # snapshot tool's flag button so the user can pin gaps at
        # intake (paperwork the tech didn't bring in, photos that
        # weren't sent over yet) and the office has a tracked thread
        # all the way through to closeout.
        link_button(
            top, "📌 Flag missing",
            command=lambda c=card: self._open_flag_missing_dialog(c),
            tooltip="Flag a missing item at intake — adds a Trello "
                    "comment and tracks it in Hygiene.",
        ).pack(side="right", padx=(4, 0))

        # ⚡ Process — one-click end-of-intake action. Pops the shared
        # process_card_dialog that auto-detects on-disk state, ticks
        # the matching Trello checklist items, and posts the canonical
        # "Initial Upload submitted To WC." confirmation comment.
        # Skipped when the card has no Trello card_id (the dialog
        # can't tick checklist items without one) — rare but happens
        # when the row is hand-pinned via the property-mgmt flow.
        if card.get("card_id") and card.get("job_path"):
            done_button(
                top, "⚡ Process", padx=6, pady=1,
                font=("Segoe UI Variable", 8, "bold"),
                command=lambda c=card: self._open_process_dialog(c),
                tooltip="Chain the end-of-intake steps: create folders, "
                        "import SP photos, tick on-disk checklist items, "
                        "post 'Initial Upload submitted To WC.' to Trello.",
            ).pack(side="right", padx=(4, 0))

        # Photos / commercial / lane line
        meta = tk.Frame(body, bg=WHITE)
        meta.pack(fill="x", pady=(4, 4))

        # Initial photos can land in either OneDrive (most techs) or
        # Workcenter (Fernando uploads direct to WC). The count below
        # only walks OD's PICS folders — so a "0" reading on a
        # Fernando job doesn't mean photos are missing, just that we
        # haven't pulled them down from WC yet. Label says "in OD" so
        # the user doesn't waste time chasing photos that already
        # exist in Workcenter.
        photos = card.get("initial_photos", 0)
        photo_color = "#A6772A" if photos == 0 else GREEN_DARK
        if photos:
            photo_text = (f"📷 {photos} initial photo"
                          f"{'s' if photos != 1 else ''} in OD")
        else:
            photo_text = "⚠ no initial photos in OD (check WC too)"
        tk.Label(meta, text=photo_text, font=("Segoe UI Variable", 9, "bold"),
                 bg=WHITE, fg=photo_color).pack(side="left")

        # Forms audit summary — surfaces missing admin paperwork inline
        # so the user can decide to import (via 📥 WC / 📥 SP) without
        # opening Run Audit separately. Only shown when the job folder
        # was found AND at least one form is missing — clean folders
        # don't need a "✓ all forms present" line cluttering the row.
        form_issues = card.get("form_issues") or []
        if form_issues:
            shown = ", ".join(form_issues[:4])
            if len(form_issues) > 4:
                shown += f" +{len(form_issues) - 4} more"
            tk.Label(meta, text=f"  ·  📋 Missing: {shown}",
                     font=("Segoe UI Variable", 8, "bold"),
                     bg=WHITE, fg=WARN_FG).pack(side="left")

        # WC / SP / OD / Make folders moved to the top-right toolbar in
        # `top` above. The photo count stays here on the left — that's
        # informational, not a button.

        # Cross-reference badge — shows when the same client appears on
        # today's APA Monitor doc (Initial or Daily Uploads). Pure
        # visibility cue; never filters the row out.
        apa_section = _apa_section_for_client(self._apa_data, client)
        if apa_section:
            tk.Label(meta, text=f"  ✓ on APA ({apa_section})",
                     font=("Segoe UI Variable", 8, "bold"),
                     bg=WHITE, fg=SUCCESS_FG).pack(side="left")

        # Existing local labels from Trello — informational only.
        # Defensive: any code path that forgets to flatten dict
        # labels would otherwise crash the whole view with
        # `sequence item 0: dict found`. Normalize to strings here
        # so the join is bulletproof regardless of upstream shape.
        def _label_text(l):
            if isinstance(l, dict):
                return (l.get("name") or "").strip()
            return str(l).strip() if l else ""
        labels_str = "  ·  ".join(
            t for t in (_label_text(l) for l in card.get("labels") or []) if t)
        if labels_str:
            tk.Label(meta, text=f"  ·  {labels_str}",
                     font=("Segoe UI Variable", 8), bg=WHITE, fg=TEXT_GRAY
                     ).pack(side="left")

        # Commercial toggle (right side of meta line) — plain Checkbutton
        # because we don't have per-item cascade targets here. Persists via
        # `persistence.set_commercial` so the flag is shared with the main
        # audit's view of the same client.
        comm_var = tk.BooleanVar(value=is_commercial)
        def _on_comm(c=client, v=comm_var):
            try:
                persistence.set_commercial(c, v.get())
            except Exception:
                pass
            self._render_rows()
        tk.Checkbutton(meta, text="Comm.", variable=comm_var,
                       font=("Segoe UI Variable", 7),
                       bg=WHITE, activebackground=WHITE, selectcolor=WHITE,
                       command=_on_comm).pack(side="right")

        # One row per tracked checklist (INITIAL - ADMIN, INITIAL).
        # Label on the left, the per-item buttons to the right. Missing
        # checklists render the label in red so the user can see at a
        # glance which template a card hasn't been initialized with.
        for cl_data in card.get("checklists") or []:
            cl_row = tk.Frame(body, bg=WHITE)
            cl_row.pack(fill="x", pady=(4, 0))
            label_color = TEXT_GRAY if cl_data.get("present") else FLAG_RED
            label_text = cl_data.get("name") or ""
            if not cl_data.get("present"):
                label_text += "  (missing on card)"
            tk.Label(cl_row, text=label_text + ":",
                     font=("Segoe UI Variable", 8, "bold"),
                     bg=WHITE, fg=label_color, anchor="w",
                     width=28).pack(side="left")
            items_box = tk.Frame(cl_row, bg=WHITE)
            items_box.pack(side="left", fill="x", expand=True)
            cl_id = cl_data.get("id") or ""
            for it in cl_data.get("items") or []:
                self._build_check_box(items_box, card, it, cl_id, cl_data)

        # Right-click anywhere on the card → shared client menu (Change
        # folder, Pin to Trello, Edit aliases, Reset memory). Same
        # `attach_card_context_menu` helper the Daily Run audit uses, so
        # the right-click experience is identical across tools — a pin
        # set here applies in the audit panel and vice versa.
        #
        # Bound AFTER children are packed so the recursive walk inside
        # the helper picks up every label/button as a right-click
        # target. Available regardless of whether the job folder was
        # auto-resolved — that's the whole point: when auto-detect
        # MISSED the folder (Anthony Sanchez case), right-click is how
        # you point it at one.
        try:
            from job_widgets import attach_card_context_menu
            import config as _cfg
            audit_base = (_cfg.load().get("audit_base") or "") or None
            attach_card_context_menu(
                self, [row], client,
                audit_base=audit_base,
                on_change_folder=lambda _p, c=card: (
                    self._refresh_card_after_pin(c)))
        except Exception:
            pass

    def _build_check_box(self, parent, card, item, checklist_id="",
                          checklist_data=None):
        state = (item.get("state") or "").lower()
        is_done = (state == "complete")
        is_missing = (state == "missing")
        # Visual: ☑ green on done, ☐ grey on incomplete, ❓ red on missing
        if is_missing:
            text = f"❓ {item['name']}"
            fg = FLAG_RED
        elif is_done:
            text = f"☑ {item['name']}"
            fg = GREEN_DARK
        else:
            text = f"☐ {item['name']}"
            fg = TEXT_DARK

        btn = tk.Button(parent, text=text, font=("Segoe UI Variable", 9),
                        bg=WHITE, fg=fg, activebackground=SUCCESS_HOVER,
                        relief="flat", padx=8, pady=2, cursor="hand2",
                        anchor="w")
        btn.pack(side="left", padx=(0, 8))
        if is_missing:
            btn.config(state="disabled")
            return
        btn.config(command=lambda c=card, it=item, b=btn:
                    self._toggle_item(c, it, b))
        # Right-click → "Remove from Trello" so the user can drop items
        # that don't apply to this specific job. Only on items that
        # exist on Trello (skip ❓ missing items — nothing to delete).
        if checklist_id and item.get("id"):
            btn.bind(
                "<Button-3>",
                lambda e, c=card, it=item, b=btn, cid=checklist_id,
                       cdata=checklist_data:
                self._on_item_right_click(e, c, it, b, cid, cdata))

    # ── actions ─────────────────────────────────────────────────────────────
    def _refresh_card_after_pin(self, card):
        """Re-walk the audit signals on one card after its OD folder pin
        changed. Called from the shared `attach_card_context_menu` →
        "Change folder…" path (the helper persists the new pin; we just
        refresh the in-memory card + re-render).

        Mirrors the per-card walk in `_load_async` so the row's photo
        count + missing-forms line reflect the new path immediately —
        no need to wait for a full re-scan."""
        client = (card.get("client") or "").strip()
        if not client:
            return
        try:
            new = persistence.get_folder_path(client) or ""
        except Exception:
            new = ""
        card["job_path"] = new
        try:
            card["initial_photos"] = (_count_initial_photos(new)
                                       if new else 0) or 0
        except Exception:
            card["initial_photos"] = 0
        try:
            from audit_logic import check_forms as _check_forms
            if new:
                ems = os.path.join(new, "EMS")
                base = ems if os.path.isdir(ems) else new
                card["form_issues"] = _check_forms(base) or []
            else:
                card["form_issues"] = []
        except Exception:
            card["form_issues"] = []
        show_toast(self,
                   f"OD folder re-pinned for {client}",
                   kind="info")
        self._render_rows()

    def _ensure_job_folders(self, job_path):
        """Create the EMS\\DOCS + EMS\\PICS layout under `job_path` if
        any of those folders are missing. Returns a list of paths that
        were actually created (empty when everything already existed)
        so callers can show a meaningful confirmation toast.

        Also handles the case where `job_path` itself doesn't exist
        yet — creates the parent client folder too. This covers brand-
        new jobs where the OD client folder hasn't been scaffolded at
        all; the user clicks "📂 Make folders" and the whole tree
        (client + EMS + DOCS + PICS) appears in one shot.

        Used by the 📂 Make folders button AND auto-fired before SP / WC
        imports — a fresh job folder won't have these yet, and the
        import flows write files into them, so creating them on demand
        avoids "ENOENT" failures during extraction."""
        if not job_path:
            return []
        created = []
        # Step 1: create the client folder itself if missing.
        if not os.path.isdir(job_path):
            try:
                os.makedirs(job_path, exist_ok=True)
                created.append(job_path)
            except OSError:
                return []
        # Step 2: create the EMS subtree.
        targets = [
            os.path.join(job_path, "EMS"),
            os.path.join(job_path, "EMS", "DOCS"),
            os.path.join(job_path, "EMS", "PICS"),
        ]
        for t in targets:
            if not os.path.isdir(t):
                try:
                    os.makedirs(t, exist_ok=True)
                    created.append(t)
                except OSError:
                    # Permission / network drive blip — surface as a
                    # toast in the caller; don't block the import.
                    continue
        return created

    def _resolve_default_job_path(self, client):
        """Derive a default OD path for a client whose job folder
        doesn't exist yet. Picks <audit_base>/<current-year-jobs-
        folder>/<client>, returning "" when neither audit_base nor
        the year subfolder can be reached.

        Used by the "📂 Make folders" button when card['job_path'] is
        empty — without this fallback the button is a no-op for
        brand-new cards whose folder hasn't been scaffolded yet."""
        if not client:
            return ""
        try:
            audit_base = (config.load().get("audit_base") or "").strip()
        except Exception:
            audit_base = ""
        if not audit_base or not os.path.isdir(audit_base):
            return ""
        from datetime import datetime as _dt
        cur_year = _dt.today().year
        # Match the same year-folder convention _build_folder_index
        # uses: any directory whose name contains the year, e.g.
        # "2026 Jobs" or "2026 Jobs (active)".
        year_folder = ""
        try:
            with os.scandir(audit_base) as it:
                for e in it:
                    if not e.is_dir(follow_symlinks=False):
                        continue
                    if str(cur_year) not in e.name:
                        continue
                    if ("LA" in e.name.upper()
                            and "FIRE" in e.name.upper()):
                        continue
                    year_folder = e.path
                    break
        except OSError:
            return ""
        if not year_folder:
            return ""
        return os.path.join(year_folder, _to_folder_name(client))

    def _open_od_folder(self, job_path, card=None):
        """Open the job folder in Windows Explorer.

        For new-loss cards whose folder hasn't been scaffolded yet,
        auto-derive `<audit_base>/<year>/<client>`, create the EMS /
        DOCS / PICS tree, persist the resolved path, then open it.
        Mirrors the same "first click does the right thing" behavior
        the SP / WC / DS import buttons already use, so the OD button
        is never a dead affordance on a fresh row."""
        if not job_path or not os.path.isdir(job_path):
            if card is None:
                messagebox.showerror(
                    "Folder not found",
                    f"Job folder doesn't exist:\n{job_path}", parent=self)
                return
            client = (card.get("client") or "").strip()
            derived = self._resolve_default_job_path(client)
            if not derived:
                messagebox.showerror(
                    "No job folder",
                    f"Couldn't auto-create a folder for '{client}': "
                    "the audit_base or year-jobs subfolder is "
                    "unreachable.", parent=self)
                return
            self._ensure_job_folders(derived)
            job_path = derived
            card["job_path"] = derived
            try:
                import persistence as _per
                _per.set_folder_path(client, derived)
            except Exception:
                pass
            try:
                self._render_rows()
            except Exception:
                pass
            show_toast(self,
                       f"Created folder for {client} — opening…",
                       kind="success", duration=2500)
        try:
            os.startfile(job_path)
        except OSError as ex:
            messagebox.showerror("Couldn't open folder", str(ex),
                                  parent=self)

    def _make_job_folders(self, job_path, card=None):
        """Manual trigger for the standard EMS folder layout. Same
        logic as the auto-create on import; surfaces a toast either
        way so the user sees something happen.

        When `job_path` is empty / nonexistent AND `card` is supplied,
        derives a default path under `<audit_base>/<year>/<client>`
        and creates the whole tree (client folder + EMS / DOCS / PICS)
        in one shot. The card's `job_path` gets updated in place so a
        re-render picks up the new folder."""
        # Path derivation fallback for cards with no job_path yet —
        # the user wants the button to still work for brand-new jobs.
        if (not job_path or not os.path.isdir(job_path)) and card is not None:
            derived = self._resolve_default_job_path(
                (card.get("client") or "").strip())
            if derived:
                job_path = derived
            else:
                show_toast(
                    self,
                    "Couldn't pick a target folder — audit_base or "
                    "the year-jobs subfolder is unreachable.",
                    kind="warn", duration=4000)
                return
        created = self._ensure_job_folders(job_path)
        if not created:
            show_toast(self,
                       "EMS\\DOCS and EMS\\PICS already exist.",
                       kind="info")
            return
        # Update the card state so a re-render flips the "no folder"
        # branch to show OD / SP / WC buttons.
        if card is not None:
            card["job_path"] = job_path
            try:
                import persistence as _per
                _per.set_folder_path(card.get("client") or "",
                                       job_path)
            except Exception:
                pass
            try:
                self._render_rows()
            except Exception:
                pass
        show_toast(self,
                   f"Created {len(created)} folder(s) at {job_path}",
                   kind="success", duration=4000)

    def _find_audit_app(self):
        """Walk up the widget tree looking for a RunAuditApp ancestor.
        Returns it (so we can call audit_single_client → SP dialog) or
        None when the panel is running outside the launcher's audit
        host. Same pattern as sp_recent_audit._find_audit_app."""
        w = self
        for _ in range(20):
            if w is None:
                return None
            if w.__class__.__name__ == "RunAuditApp":
                return w
            w = getattr(w, "master", None)
        return None

    def _today_run_doc_jobs(self):
        """Parse today's run-doc directly and cache the result on the
        panel for the lifetime of the render pass. The IUQ refresh
        button clears the cache so a fresh import picks up edits to
        today's doc.

        Loading our own copy (instead of reading the audit panel's
        `self.jobs`) means the IUQ shows the right time slot even when
        the user has the audit set to a different day or hasn't opened
        the audit yet.
        """
        cached = getattr(self, "_today_jobs_cache", None)
        if cached is not None:
            return cached
        try:
            from datetime import datetime as _dt
            from run_audit_gui import _find_run_doc_for_date, parse_run_doc
            path = _find_run_doc_for_date(_dt.today())
            if not path:
                self._today_jobs_cache = []
                return []
            jobs, _run_date = parse_run_doc(path)
            self._today_jobs_cache = jobs or []
            return self._today_jobs_cache
        except Exception:
            self._today_jobs_cache = []
            return []

    def _time_slot_for_client(self, client):
        """Look up the run-doc time slot for `client` from TODAY's run
        doc. The IUQ's source is Trello, but when a card matches a job
        listed on today's run, the run-doc line carries an appointment
        window ("9-11", "@12pm") that the audit row already surfaces —
        mirror it here so the user sees the same "tech heading out at
        X" cue without flipping panels.

        Pulls from a per-render cache loaded directly from today's
        .docx (not from the audit panel's currently-loaded run-doc,
        which may be set to yesterday or some other day). Falls back
        to the audit panel's parsed jobs only when today's doc can't
        be located — keeps the old behavior alive for the rare case
        where the user is running IUQ offline.

        Name matching tolerates the form mismatches we see in the wild:
          • Case + whitespace
          • Trailing date suffix on Trello cards
            ("Avila Apartments 1416- 05/09/26" = "Avila Apartments 1416")
          • Comma-swap ("Sanchez, Jacqueline" = "Jacqueline Sanchez")
          • Token-set overlap once everything else has been normalized,
            so initials/abbreviations don't block the match

        Returns the slot string or "" when there's no matching client.
        """
        target_norm = _norm_client_for_run_doc(client)
        if not target_norm:
            return ""
        jobs = self._today_run_doc_jobs()
        if not jobs:
            audit_app = self._find_audit_app()
            if audit_app is not None:
                jobs = getattr(audit_app, "jobs", None) or []
        target_tokens = set(target_norm.split())
        target_nums = {t for t in target_tokens if t.isdigit()}
        for j in jobs:
            rd_norm = _norm_client_for_run_doc(j.get("client"))
            if not rd_norm:
                continue
            if rd_norm == target_norm:
                return (j.get("time_slot") or "").strip()
        # Second pass: token-set overlap. Requires ≥2 shared tokens to
        # avoid first-name-only collisions ("Maria" leaking from "Maria
        # Diestra" into "Rodriguez, Enrique & Maria"). If both sides
        # carry digit tokens (unit numbers like "Avila Apartments 1416"
        # vs "1017"), require those digit sets to match — otherwise
        # commercial properties with the same property name but
        # different units would falsely collide.
        for j in jobs:
            rd_norm = _norm_client_for_run_doc(j.get("client"))
            if not rd_norm:
                continue
            rd_tokens = set(rd_norm.split())
            if len(target_tokens & rd_tokens) < 2:
                continue
            rd_nums = {t for t in rd_tokens if t.isdigit()}
            if target_nums and rd_nums and target_nums != rd_nums:
                continue
            return (j.get("time_slot") or "").strip()
        return ""

    def _import_sp_for_card(self, card):
        """Quick SP import: ensure folder structure exists, then ask
        the parent audit panel to run a single-client audit and
        auto-open its SP download dialog. Mirrors sp_recent_audit's
        _import_sp_for_match flow."""
        client = (card.get("client") or "").strip()
        job_path = card.get("job_path") or ""
        if not client:
            return
        if job_path:
            self._ensure_job_folders(job_path)
        audit_app = self._find_audit_app()
        if audit_app is None:
            messagebox.showinfo(
                "Open from main launcher",
                "SP import needs the main Audit panel — open the "
                "launcher and run this from there.",
                parent=self)
            return
        try:
            audit_app.audit_single_client(client, then_open_sp=True)
            show_toast(self,
                       f"Auditing '{client}' — SP dialog will open "
                       "when done.", kind="info")
        except Exception as ex:
            messagebox.showerror("Couldn't trigger audit", str(ex),
                                  parent=self)

    def _resolve_pics_targets_for_card(self, card, unit_root):
        """Pick the PICS subfolder(s) for this card's photo import,
        driven by today's run-doc activity. Returns:
          • list[str] of absolute folder paths to write photos into
            (length 1 for unambiguous activities, length 2 when the
            operator picked 'Both' on the Demo/Mold Prep dialog)
          • None when the operator cancelled the picker.

        Routing rules live in audit_logic.resolve_pics_subfolder.
        Demo+Mold Prep is the one collision that requires operator
        input — every other case resolves to a single target.
        """
        import datetime as _dt
        client = (card.get("client") or "").strip()
        today_str = _dt.date.today().strftime("%m-%d-%Y")
        try:
            from run_audit_gui import _activity_labels_from_run_doc
            labels = _activity_labels_from_run_doc(today_str, client)
        except Exception:
            labels = []
        try:
            from audit_logic import resolve_pics_subfolder
            folder, needs_prompt = resolve_pics_subfolder(labels)
        except Exception:
            folder, needs_prompt = ("Initial", False)

        if not needs_prompt:
            return [os.path.join(unit_root, "EMS", "PICS",
                                  folder or "Initial")]

        # Demo + Mold Prep collision — prompt the operator.
        choice = self._prompt_demo_or_moldprep(client)
        if choice is None:
            return None
        if choice == "both":
            return [
                os.path.join(unit_root, "EMS", "PICS", "Demo"),
                os.path.join(unit_root, "EMS", "PICS", "Mold Prep"),
            ]
        return [os.path.join(unit_root, "EMS", "PICS", choice)]

    def _prompt_demo_or_moldprep(self, client_name):
        """Modal — operator picks Demo / Mold Prep / Both / Cancel
        when the run-doc lists both activities for the same day.
        Returns 'Demo', 'Mold Prep', 'both', or None (cancel)."""
        dlg = tk.Toplevel(self)
        dlg.title("Demo or Mold Prep?")
        dlg.resizable(False, False)
        dlg.grab_set()
        try:
            dlg.transient(self.winfo_toplevel())
        except Exception:
            pass
        wf = tk.Frame(dlg, bg=BG, padx=20, pady=16)
        wf.pack(fill="both", expand=True)
        tk.Label(wf,
                  text=("Run-doc lists BOTH Demo and Mold Prep for "
                        f"{client_name or 'this job'}."),
                  font=("Segoe UI Variable", 10, "bold"),
                  bg=BG, fg=TEXT_DARK,
                  wraplength=380, justify="left"
                  ).pack(anchor="w", pady=(0, 4))
        tk.Label(wf,
                  text=("Which PICS folder should the photos land in? "
                        "Pick 'Both' to copy each photo into both "
                        "folders."),
                  font=("Segoe UI Variable", 9),
                  bg=BG, fg=TEXT_GRAY,
                  wraplength=380, justify="left"
                  ).pack(anchor="w", pady=(0, 12))

        result = [None]

        def _set(v):
            result[0] = v
            dlg.destroy()

        for label, value in (
                ("📷  Demo only",          "Demo"),
                ("📷  Mold Prep only",     "Mold Prep"),
                ("📷  Both (copy to each)", "both")):
            tk.Button(wf, text=label,
                       font=("Segoe UI Variable", 10),
                       bg=SURFACE_2, fg=TEXT_DARK,
                       relief="flat", padx=16, pady=8,
                       anchor="w", cursor="hand2",
                       command=lambda v=value: _set(v)
                       ).pack(fill="x", pady=2)
        tk.Button(wf, text="Cancel",
                   font=("Segoe UI Variable", 9),
                   bg=SURFACE_2, fg=TEXT_DARK,
                   relief="flat", padx=12, pady=4,
                   command=dlg.destroy
                   ).pack(pady=(10, 0))
        dlg.wait_window()
        return result[0]

    def _request_docusign_via_trello(self, card):
        """Post a DocuSign request comment on the card's Trello card
        and seed a Hygiene pending-signature entry. Mirrors the
        Daily Run audit's `_request_via_trello` inner — per the 3-way
        audit parity rule, this affordance lives on every audit
        surface. User clicks "✍ Send DocuSign via Trello" from the
        IUQ row's Import dialog → this method runs."""
        client = (card.get("client") or "").strip()
        if not client:
            messagebox.showwarning(
                "No client",
                "This card has no client name on file — open it in "
                "Trello to set one before requesting DocuSign.",
                parent=self)
            return
        try:
            from docusketch_requests import find_card_for_client
            import docusign_requests as dsr
            hit = find_card_for_client(client)
        except Exception as ex:
            messagebox.showerror(
                "Lookup failed",
                f"Couldn't search Trello: {ex}", parent=self)
            return
        if hit is None:
            messagebox.showwarning(
                "No card found",
                f"Couldn't find a Trello card for '{client}'. Open "
                f"the card manually and request DocuSign via "
                f"Trello.", parent=self)
            return
        entry = dsr.request(hit["card_id"], client_name=client)
        if entry is None:
            messagebox.showerror(
                "Couldn't record",
                "Trello request failed. Check ems.log.", parent=self)
            return
        email = entry.get("email") or ""
        if entry.get("state") == "pending_signature":
            msg = (f"Posted to {entry['card_name']}.\n\n"
                   f"DocuSign paperwork sent to {email} — awaiting "
                   f"signature. The Hygiene panel's '✍ Docusign "
                   f"pending' section will nag daily until it's "
                   f"signed.")
        else:
            msg = (f"Posted to {entry['card_name']}.\n\n"
                   f"No email on file — pinged "
                   f"{dsr.KIMBERLY_HANDLE} on the Trello card to get "
                   f"one. Hygiene will show the row with a '✉ Got "
                   f"email' button.")
        if not entry.get("comment_posted", True):
            msg = ("Recorded locally, but the Trello comment failed "
                   "to post. Open the card and post manually.")
        messagebox.showinfo("DocuSign requested", msg, parent=self)

    def _smart_import_for_card(self, card):
        """Unified Downloads scanner. Mirrors the Daily Run audit +
        Snapshot audit's 📥 Import button per the 3-way audit parity
        rule (`feedback-audit-snapshot-parity`). Scans Downloads for
        Workcenter attachments*.zip and DocuSign Final-Paperwork zips,
        routes:
          • only WC zip(s) found → fire `_import_wc_for_card`
          • only DS zip(s) found → fire `_import_ds_for_card`
          • both kinds present → picker dialog (operator chooses)
          • neither → friendly "nothing to import" message naming what
            was looked for
        """
        import wc_zip_import as _wcz
        client = (card.get("client") or "").strip()

        try:
            wc_groups = _wcz.find_wc_zips(_DOWNLOADS, _WC_ATTACHMENTS_RE)
        except Exception:
            wc_groups = []
        try:
            import docusign_import as _dsi
            ds_zips = _dsi.find_docusign_zips(
                _DOWNLOADS, client_hint=client)
        except Exception:
            ds_zips = []

        # 3-way picker — always offer "✍ Send DocuSign via Trello"
        # so the user can request signatures from inside the IUQ row
        # even when no signed packet is in Downloads yet. The two
        # zip-driven options surface only when matching zips exist.
        dlg = tk.Toplevel(self)
        dlg.title("Import from Downloads")
        dlg.resizable(False, False)
        dlg.grab_set()
        try:
            dlg.transient(self.winfo_toplevel())
        except Exception:
            pass
        wf = tk.Frame(dlg, bg=BG, padx=20, pady=14)
        wf.pack(fill="both", expand=True)
        if wc_groups or ds_zips:
            head = "Pick an action:"
        else:
            head = ("No zips in Downloads — you can still request a "
                    "DocuSign via Trello:")
        tk.Label(wf, text=head,
                  font=("Segoe UI Variable", 10, "bold"),
                  bg=BG, fg=TEXT_DARK,
                  wraplength=380, justify="left"
                  ).pack(anchor="w", pady=(0, 10))

        def _fire_wc():
            dlg.destroy()
            self._import_wc_for_card(card)

        def _fire_ds_import():
            dlg.destroy()
            self._import_ds_for_card(card)

        def _fire_ds_request():
            dlg.destroy()
            self._request_docusign_via_trello(card)

        if wc_groups:
            tk.Button(wf,
                       text=f"📥 Workcenter attachments "
                            f"({len(wc_groups)} in Downloads)",
                       font=("Segoe UI Variable", 9),
                       bg=SURFACE_2, fg=TEXT_DARK,
                       relief="flat", padx=16, pady=8,
                       anchor="w", cursor="hand2",
                       command=_fire_wc).pack(fill="x", pady=3)
        if ds_zips:
            tk.Button(wf,
                       text=f"📝 DocuSign signed packet "
                            f"({len(ds_zips)} in Downloads)",
                       font=("Segoe UI Variable", 9),
                       bg=SURFACE_2, fg=TEXT_DARK,
                       relief="flat", padx=16, pady=8,
                       anchor="w", cursor="hand2",
                       command=_fire_ds_import).pack(fill="x", pady=3)
        tk.Button(wf, text="✍ Send DocuSign via Trello",
                   font=("Segoe UI Variable", 9),
                   bg=SURFACE_2, fg=TEXT_DARK,
                   relief="flat", padx=16, pady=8,
                   anchor="w", cursor="hand2",
                   command=_fire_ds_request).pack(fill="x", pady=3)
        tk.Button(wf, text="Cancel",
                   font=("Segoe UI Variable", 9),
                   bg=SURFACE_2, fg=TEXT_DARK,
                   relief="flat", padx=12, pady=4,
                   command=dlg.destroy
                   ).pack(pady=(12, 0))

    def _import_wc_for_card(self, card):
        """Quick Workcenter import: open the WC URL, wait for the user
        to download `attachments*.zip` to Downloads, then split-route
        the contents into the job's EMS folder — images into
        EMS/PICS/Initial/, all other files (PDFs, forms, etc.) into
        EMS/DOCS/. Auto-creates the EMS folder layout first if missing.

        Lighter-weight than run_audit_gui's full import (no per-row
        checklist toggling here — Initial Upload tracks via the
        Trello checklist round-trip, not local resolved-flags)."""
        client = (card.get("client") or "").strip()
        job_path = card.get("job_path") or ""
        if not job_path or not os.path.isdir(job_path):
            # No folder yet — auto-scaffold under <audit_base>/<year>/
            # <client> so the WC import has somewhere to land. Used to
            # error here with "Pin a folder via 📌 then retry" but
            # that 📌 button isn't on the IUQ row (the IUQ's 📌 is the
            # Trello card pin). Removing the friction: just make the
            # folder and proceed.
            derived = self._resolve_default_job_path(client)
            if derived:
                self._ensure_job_folders(derived)
                job_path = derived
                card["job_path"] = derived
                try:
                    import persistence as _per
                    _per.set_folder_path(client, derived)
                except Exception:
                    pass
                try:
                    show_toast(self,
                               f"Created job folder for {client} — "
                               "continuing with WC import…",
                               kind="info", duration=2500)
                except Exception:
                    pass
            else:
                messagebox.showerror(
                    "No job folder",
                    f"Couldn't auto-create a folder for '{client}': "
                    "the audit_base / year subfolder is unreachable. "
                    "Use right-click → Change folder… to pick one "
                    "manually, then retry.", parent=self)
                return
        wc_url = (config.load().get("workcenter_url") or "").strip()

        # Confirm-and-find via shared helpers. The IUQ variant of the
        # dialog used to have a slightly chattier preamble (client
        # name + split-routing note); we keep that text by inserting
        # it inline as a toast since the shared dialog stays clean.
        try:
            show_toast(self,
                       f"Import attachments*.zip for {client} → "
                       "Images go to EMS\\PICS\\Initial, PDFs → EMS\\DOCS",
                       kind="info", duration=4000)
        except Exception:
            pass
        import wc_zip_import as _wcz
        _pr = _wcz.prompt_for_wc_zip(self,
                                      workcenter_url=wc_url,
                                      label="attachments",
                                      kind="photos + forms")
        if not _pr:
            return
        if isinstance(_pr, list):
            chosen_label, chosen_paths = ("picked files", _pr)
        else:
            groups = _wcz.find_wc_zips(_DOWNLOADS, _WC_ATTACHMENTS_RE)
            if not groups:
                messagebox.showerror("Not Found",
                    "No Workcenter attachments*.zip found in Downloads.\n\n"
                    "Tip: use “📁 Pick a file…” to choose any file manually.",
                    parent=self)
                return
            picked = _wcz.pick_zip_group(self, groups, label="attachments")
            if picked is None:
                return
            chosen_label, chosen_paths = picked

        # Auto-create folder layout BEFORE extraction so the
        # extractall path always exists (extractall doesn't recurse-
        # create some intermediate directories on Windows when the zip
        # has flat filenames). This panel is exclusively for INITIAL
        # uploads — drop into PICS/Initial/ so audits match the
        # "initial" stage keyword and Daily Run finds them under the
        # right subfolder.
        self._ensure_job_folders(job_path)
        # Multi-unit: ask which unit these initial photos belong to.
        # `chosen_unit_path` = "" means property root; None = cancel.
        unit_root = job_path
        try:
            from multi_unit_gui import list_unit_subfolders
            unit_list = list_unit_subfolders(job_path)
        except Exception:
            unit_list = []
        if unit_list:
            try:
                from run_audit_gui import _ask_unit_for_import
                client_name = (card.get("client") or card.get("name") or "")
                picked = _ask_unit_for_import(
                    self, unit_list, kind="initial photos",
                    client_name=client_name)
                if picked is None:
                    return
                if picked:
                    unit_root = picked
            except Exception:
                pass
        # Workcenter exports bundle BOTH initial photos and admin forms
        # (ATP / CIF / CER / COS PDFs) into one zip. Extract to a temp
        # dir first, then split-route: images → EMS/PICS/Initial/, all
        # other files → EMS/DOCS/. Without this split, forms would land
        # under PICS where check_forms can't find them, leaving the
        # audit row claiming forms are missing the day after import.
        import shutil
        import tempfile
        # Activity-based PICS subfolder. Pulls today's run-doc activity
        # for this client and routes photos accordingly: Demo absorbs
        # Pack-out / Contents; Demo+MoldPrep prompts the operator; etc.
        # Falls back to "Initial" when there's no run-doc / no match —
        # matches the prior behavior for first-time intake jobs.
        pics_targets = self._resolve_pics_targets_for_card(
            card, unit_root)
        if pics_targets is None:
            return  # operator cancelled the Demo / Mold Prep picker
        ems_dir = os.path.join(unit_root, "EMS")
        docs_target = os.path.join(ems_dir, "DOCS")
        # Sticky-home routing: if ≥2 image filenames in the WC zip
        # already exist somewhere under EMS/PICS, redirect this batch
        # to that same OD subfolder. Overrides the run-doc destination
        # because "the folder that already has the matching photos" is
        # a stronger signal than today's run-doc activity.
        try:
            from wc_zip_import import find_sticky_home as _find_sticky
            _ems_pics_root = os.path.join(unit_root, "EMS", "PICS")
            _home = _find_sticky(chosen_paths, _ems_pics_root)
            if _home:
                pics_targets = [_home]
        except Exception:
            pass
        try:
            for pt in pics_targets:
                os.makedirs(pt, exist_ok=True)
            os.makedirs(docs_target, exist_ok=True)
        except OSError as ex:
            messagebox.showerror("Folder Error", str(ex), parent=self)
            return
        # The legacy code wrote to a single `pics_target`; keep that
        # variable name for the routing loop below, with the
        # multi-target case handled via shutil.copy2 to siblings.
        pics_target = pics_targets[0]
        try:
            from sharepoint import _IMAGE_EXTS as _img_exts
        except Exception:
            _img_exts = {".jpg", ".jpeg", ".png", ".heic", ".heif",
                         ".webp", ".bmp", ".tif", ".tiff", ".gif",
                         ".mp4", ".mov", ".m4v", ".avi"}
        photo_count = 0
        form_count = 0
        # Files whose move+copy fallback BOTH failed — never landed, so
        # they must not be counted as imported (audit bug #6).
        failed_imports: list[str] = []
        with tempfile.TemporaryDirectory(prefix="wc_iu_") as staging:
            try:
                _wcz.place_import_paths(chosen_paths, staging)
            except Exception as ex:
                messagebox.showerror("Extract Error", str(ex), parent=self)
                return
            # Walk the staging tree and route each file by extension. Use
            # basename-only at the destination so the WC zip's nested
            # folder structure doesn't leak into the job folder.
            import child_folder_ops as _cfops
            for root, _dirs, files in os.walk(staging):
                for fn in files:
                    src = os.path.join(root, fn)
                    ext = os.path.splitext(fn)[1].lower()
                    is_img = ext in _img_exts
                    dest_dir = pics_target if is_img else docs_target
                    # Collision-safe, cloud-aware move; returns the final
                    # landed path or None on total failure. Count ONLY on a
                    # confirmed write (bug #6) — the old `except: pass`
                    # swallowed double-failures and still counted them.
                    landed = _cfops.safe_move(src, dest_dir)
                    if not landed:
                        failed_imports.append(fn)
                        continue
                    if is_img:
                        photo_count += 1
                    else:
                        form_count += 1
                    # Multi-target case (Demo+Mold Prep "Both"):
                    # copy the landed file into each additional pics target
                    # so both folders end up with the same photo set.
                    if is_img and len(pics_targets) > 1:
                        for extra in pics_targets[1:]:
                            try:
                                os.makedirs(extra, exist_ok=True)
                                extra_dest = os.path.join(
                                    extra, os.path.basename(landed))
                                if os.path.exists(extra_dest):
                                    base, ext2 = os.path.splitext(
                                        os.path.basename(landed))
                                    n = 1
                                    while os.path.exists(extra_dest):
                                        extra_dest = os.path.join(
                                            extra,
                                            f"{base} ({n}){ext2}")
                                        n += 1
                                shutil.copy2(landed, extra_dest)
                            except OSError:
                                pass
        # Photos only: convert HEIC → JPEG and sort into per-room
        # subfolders (Bed 1, Bath 2, Garage…) in every pics target.
        # Both no-op safely when there's nothing to do.
        if photo_count:
            try:
                from wc_zip_import import (convert_heic_in_dir,
                                            organize_by_room)
                for pt in pics_targets:
                    convert_heic_in_dir(pt)
                    organize_by_room(pt)
            except Exception:
                pass
        # Recycle every part of the WC zip — Downloads cleanup per
        # user direction.
        try:
            from wc_zip_import import trash_imported_zips
            trash_imported_zips(chosen_paths)
        except Exception:
            pass
        # Refresh the row's photo count + UI.
        try:
            from initial_upload_queue import _count_initial_photos
            card["initial_photos"] = _count_initial_photos(job_path) or 0
        except Exception:
            pass
        self._render_rows()
        bits = []
        if photo_count:
            # Folder name(s) come from the activity-resolved target(s).
            pics_label = "/".join(os.path.basename(p)
                                    for p in pics_targets)
            bits.append(
                f"{photo_count} photo{'s' if photo_count != 1 else ''} "
                f"→ PICS/{pics_label}")
        if form_count:
            bits.append(f"{form_count} form{'s' if form_count != 1 else ''} → DOCS")
        if failed_imports:
            bits.append(
                f"⚠ {len(failed_imports)} file"
                f"{'s' if len(failed_imports) != 1 else ''} FAILED to import "
                f"(retry): {', '.join(failed_imports[:5])}"
                + (" …" if len(failed_imports) > 5 else ""))
        if not bits:
            bits.append("(zip was empty)")
        msg = "Imported from Workcenter:\n  " + "\n  ".join(bits)
        if len(chosen_paths) > 1:
            msg += f"\n\nFrom {len(chosen_paths)} parts ({chosen_label})."

        # Auto-tick Trello checklist items now that files are in place.
        # Both photos and forms can land in the same zip, so build the
        # event list from what actually came through.
        try:
            card_id = card.get("card_id") or card.get("id") or ""
            events: list[str] = []
            if photo_count:
                events.append("sp_photos_initial")
            if form_count:
                events.append("wc_docs_imported")
            if card_id and events:
                import trello_autotick as _at
                ticked = _at.autotick(card_id, events=tuple(events),
                                       client=client)
                if ticked:
                    msg += "\n\n" + _at.autotick_summary(ticked)
        except Exception:
            pass

        messagebox.showinfo("Workcenter Imported", msg, parent=self)

    def _import_ds_for_card(self, card):
        """DocuSign Final-Paperwork import. Locates
        `<Client>_Final_Paperwork.zip` in Downloads (surname-matched
        against this card's client), extracts every PDF into EMS/DOCS,
        and auto-ticks Trello's paperwork checklist line. Mirrors
        `_import_wc_for_card` but smaller — DocuSign only delivers
        signed forms (no photos), so we route everything to DOCS."""
        client   = (card.get("client") or "").strip()
        job_path = card.get("job_path") or ""
        if not job_path or not os.path.isdir(job_path):
            derived = self._resolve_default_job_path(client)
            if derived:
                self._ensure_job_folders(derived)
                job_path = derived
                card["job_path"] = derived
                try:
                    import persistence as _per
                    _per.set_folder_path(client, derived)
                except Exception:
                    pass
            else:
                messagebox.showerror(
                    "No job folder",
                    f"Couldn't auto-create a folder for '{client}'. "
                    "Use right-click → Change folder… to pick one, "
                    "then retry.", parent=self)
                return

        try:
            import docusign_import as dsi
        except ImportError as ex:
            messagebox.showerror(
                "DocuSign import unavailable", str(ex), parent=self)
            return

        zips = dsi.find_docusign_zips(_DOWNLOADS, client_hint=client)
        if not zips:
            messagebox.showerror(
                "Not Found",
                "No DocuSign Final-Paperwork zip found in Downloads.\n\n"
                "Expected: <Client>_Final_Paperwork.zip",
                parent=self)
            return

        chosen = zips[0]
        if len(zips) > 1:
            pick_dlg = tk.Toplevel(self)
            pick_dlg.title("Select DocuSign zip")
            pick_dlg.resizable(False, False)
            pick_dlg.grab_set()
            pf = tk.Frame(pick_dlg, bg=BG, padx=16, pady=14)
            pf.pack()
            tk.Label(pf,
                     text=f"Multiple DocuSign zips found for {client} — pick one:",
                     font=("Segoe UI Variable", 10, "bold"), bg=BG
                     ).pack(anchor="w", pady=(0, 8))
            pick_var = tk.IntVar(value=0)
            for idx, fn in enumerate(zips[:6]):
                tk.Radiobutton(pf, text=fn, variable=pick_var,
                                value=idx,
                                font=("Segoe UI Variable", 8),
                                bg=BG, activebackground=BG
                                ).pack(anchor="w", pady=2)
            picked = [None]
            def _pick():
                picked[0] = pick_var.get()
                pick_dlg.destroy()
            done_button(pf, "Import", padx=12, pady=4,
                         command=_pick
                         ).pack(pady=(12, 0), fill="x")
            pick_dlg.wait_window()
            if picked[0] is None:
                return
            chosen = zips[picked[0]]

        zip_path = os.path.join(_DOWNLOADS, chosen)
        self._ensure_job_folders(job_path)
        ems  = os.path.join(job_path, "EMS")
        docs = os.path.join(ems, "DOCS")
        os.makedirs(docs, exist_ok=True)

        try:
            landed = dsi.import_zip(zip_path, docs)
        except Exception as ex:
            messagebox.showerror("Extract Error", str(ex), parent=self)
            return
        # Recycle the source DocuSign packet — Downloads cleanup
        # per user direction.
        try:
            from wc_zip_import import trash_imported_zips
            trash_imported_zips(zip_path)
        except Exception:
            pass

        summary = dsi.summarize_landed(landed)
        msg = f"Imported DocuSign Final Paperwork:\n  {summary}\n\nInto: {docs}"

        # Auto-tick the Trello "paperwork" checklist line. Mirrors the
        # WC docs branch — same event so the canonical "wc_docs_imported"
        # rule fires, regardless of which import source delivered them.
        try:
            card_id = card.get("card_id") or card.get("id") or ""
            if card_id:
                import trello_autotick as _at
                ticked = _at.autotick(card_id,
                                       events=("wc_docs_imported",),
                                       client=client)
                if ticked:
                    msg += "\n\n" + _at.autotick_summary(ticked)
        except Exception:
            pass

        messagebox.showinfo("DocuSign Imported", msg, parent=self)

    def _toggle_item(self, card, item, btn):
        """Flip a checklist item's state on Trello, optimistically update
        the UI, and revert on failure. Posts run on a thread."""
        import trello_client as tc
        cur_state = (item.get("state") or "").lower()
        new_state = "incomplete" if cur_state == "complete" else "complete"
        # Optimistic UI flip
        item["state"] = new_state
        new_text = (f"☑ {item['name']}" if new_state == "complete"
                     else f"☐ {item['name']}")
        new_fg = GREEN_DARK if new_state == "complete" else TEXT_DARK
        try:
            btn.config(text=new_text, fg=new_fg, state="disabled")
        except tk.TclError:
            return

        def _bg():
            ok = tc.set_check_item_state(card.get("card_id"),
                                          item.get("id"), new_state)
            def _done():
                if not ok:
                    # Revert
                    item["state"] = cur_state
                    rev_text = (f"☑ {item['name']}" if cur_state == "complete"
                                 else f"☐ {item['name']}")
                    rev_fg = GREEN_DARK if cur_state == "complete" else TEXT_DARK
                    try:
                        btn.config(text=rev_text, fg=rev_fg, state="normal")
                    except tk.TclError:
                        pass
                    show_toast(self,
                               "Trello refused the toggle — your token may "
                               "lack write access. Item reverted.",
                               kind="error")
                    return
                try:
                    btn.config(state="normal")
                except tk.TclError:
                    pass

                # Auto-post the canonical completion comment when the
                # user ticks an item that has one. Runs on its own
                # background thread so the toggle UI returns instantly
                # even if Trello is slow to accept the comment post.
                if new_state == "complete":
                    canned = ITEM_AUTO_COMMENTS.get(
                        (item.get("name") or "").strip().lower())
                    card_id = card.get("card_id")
                    if canned and card_id:
                        def _post_comment(cid=card_id, text=canned,
                                           label=item.get("name", "")):
                            try:
                                ok = tc.post_comment(cid, text)
                            except Exception:
                                ok = None
                            if ok:
                                try:
                                    self.after(0, lambda: show_toast(
                                        self,
                                        f"✓ Posted to Trello: {text}",
                                        kind="info"))
                                except Exception:
                                    pass
                        threading.Thread(target=_post_comment,
                                          daemon=True).start()

                # If user just ticked INITIAL UPLOAD, the card may or
                # may not still belong in the visible queue. Update the
                # card's `done` flag so _render_rows's visibility filter
                # can decide:
                #   - on APA Initial Uploads → stays visible (so the
                #     user can verify every other checklist item got
                #     ticked before the row leaves the queue)
                #   - not on APA → filtered out of the visible list
                # Either way the card stays in self._cards (the cache)
                # so it can re-appear if the user later clears the APA
                # entry — keeping data over hiding it.
                if item["name"] == ITEM_INITIAL_UPLOAD:
                    card["done"] = (new_state == "complete")
                    try:
                        persistence.set_initial_queue_cache(self._cards)
                    except Exception:
                        pass
                    self._render_rows()
                    # Mirror this Initial Upload to the Snapshots Excel
                    # workbook as a NEW LOSS row — but only on the
                    # tick-complete edge, not on un-tick (un-ticking is
                    # an undo, not a new job-start signal). Loss type
                    # pulled from the card's Trello labels when present.
                    # Best-effort — never blocks the toggle UI.
                    if new_state == "complete":
                        try:
                            import snapshots_excel as _sx
                            import trello_client as _tc
                            client_name = (card.get("client") or "").strip()
                            if client_name:
                                loss_type = _tc.card_loss_type(
                                    {"labels": card.get("labels") or []})
                                _sx.mark_new_loss(
                                    client_name,
                                    type_of_loss=loss_type or None)
                        except Exception:
                            pass
            self.after(0, _done)

        threading.Thread(target=_bg, daemon=True).start()

    def _on_item_right_click(self, event, card, item, btn,
                              checklist_id, checklist_data):
        """Right-click on a checklist item button → context menu with
        'Remove from Trello'. Confirms before posting the delete so an
        accidental right-click doesn't trash an item.

        Deletion is mirrored on Trello via `delete_check_item` so other
        team members see the same shortened checklist; the local card
        cache is updated so the row redraws without the deleted item
        and we don't re-fetch the whole queue."""
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label=f"Remove '{item.get('name','')}' from Trello",
            command=lambda: self._delete_item_from_card(
                card, item, btn, checklist_id, checklist_data))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _delete_item_from_card(self, card, item, btn, checklist_id,
                                checklist_data):
        """Confirm + delete a checklist item from Trello, then trim it
        from the local card cache and redraw."""
        from tkinter import messagebox
        item_name = item.get("name", "")
        cl_name = (checklist_data or {}).get("name", "the checklist")
        if not messagebox.askyesno(
                "Remove checklist item?",
                f"Remove '{item_name}' from '{cl_name}' on Trello?\n\n"
                "This affects everyone on the card. Items that don't "
                "apply to this specific job can be safely removed.",
                parent=self):
            return
        # Optimistic UI — disable the button so a second click can't
        # double-fire the delete while the request is in flight.
        try:
            btn.config(state="disabled")
        except tk.TclError:
            pass
        item_id = item.get("id", "")
        card_id = card.get("card_id", "")

        def _bg():
            import trello_client as tc
            ok = tc.delete_check_item(checklist_id, item_id)
            def _done():
                if not ok:
                    try:
                        btn.config(state="normal")
                    except tk.TclError:
                        pass
                    show_toast(self,
                               "Trello refused the delete — your token "
                               "may lack write access.",
                               kind="error")
                    return
                # Trim the deleted item out of the card's local
                # checklist data so the row redraws without it. Also
                # write through to the persisted cache so the next
                # launcher open sees the same shortened list.
                for cl in card.get("checklists") or []:
                    if cl.get("id") == checklist_id:
                        cl["items"] = [
                            it for it in (cl.get("items") or [])
                            if it.get("id") != item_id]
                        break
                try:
                    persistence.set_initial_queue_cache(self._cards)
                except Exception:
                    pass
                self._render_rows()
                show_toast(self,
                           f"Removed '{item_name}' from Trello.",
                           kind="info")
            self.after(0, _done)

        threading.Thread(target=_bg, daemon=True).start()

    def _open_snapshot_spreadsheet(self):
        """Open the per-year Snapshots workbook directly in Excel — same
        file the Initial Upload tick writes NEW LOSS rows to. No filter
        dialog, just hand off to the OS so the user lands on the live
        spreadsheet."""
        from datetime import datetime as _dt
        try:
            import snapshots_excel as _sx
        except Exception:
            show_toast(self, "snapshots_excel module unavailable",
                       kind="error")
            return
        yr = _dt.today().year
        ok = _sx.open_in_excel(yr)
        if not ok:
            path = _sx.workbook_path(yr)
            show_toast(self,
                       f"No spreadsheet yet for {yr} — first NEW LOSS "
                       f"row will create it at {path}", kind="info")

    def _create_trello_card_for(self, card):
        """Create a Trello card in the Initial Inspections lane for a
        row that doesn't have one yet. Updates this row's `card_id`
        + `shortUrl` on success, pins the new id to the client name
        (so the audit/snapshot tools find it), and re-renders.

        Confirms first so an accidental click on a no-card row doesn't
        spam the board with empty cards."""
        client = (card.get("client") or "").strip()
        if not client:
            return
        if not messagebox.askyesno(
                "Create Trello card",
                f"Create a new Trello card for '{client}' in the "
                f"Initial Inspections lane?\n\n"
                f"The card will be pinned to this client so the audit "
                f"and snapshot tools find it automatically.",
                parent=self):
            return
        # Use the row's `name` if the user typed a fuller version when
        # they added the manual row; fall back to plain client name.
        card_name = (card.get("name") or client).strip()

        def _bg():
            try:
                import trello_client as tc
                created = tc.create_card(LIST_ID_INITIAL_INSPECTIONS,
                                          card_name)
                err = None
            except Exception as ex:
                created, err = None, str(ex)

            def _done():
                if err or not created:
                    messagebox.showerror(
                        "Couldn't create card",
                        f"Trello API rejected the create:\n\n{err or 'unknown error'}",
                        parent=self)
                    return
                cid = created.get("id") or ""
                short = created.get("shortUrl") or ""
                # Update the in-memory row + persistence pin so the
                # next render shows the link, checklist progress chip,
                # and audit-side recognition.
                card["card_id"] = cid
                card["shortUrl"] = short
                card["lane"] = LANE_LABEL_BY_LIST_ID.get(
                    LIST_ID_INITIAL_INSPECTIONS, "Initial Insp.")
                card["list_id"] = LIST_ID_INITIAL_INSPECTIONS
                # Drop the manual flag — the row now has a real Trello
                # source, so on next refresh it'll be picked up by the
                # lane scan and the ✕ Remove affordance can go.
                card.pop("manual", None)
                try:
                    persistence.add_trello_card_id(client, cid)
                except Exception:
                    pass
                try:
                    show_toast(self,
                               f"Created Trello card for {client}.",
                               kind="success", duration=2500)
                except Exception:
                    pass
                # Re-render the row so the ➕ button drops out and the
                # ↗ link starts working.
                try:
                    self._render_rows()
                except Exception:
                    pass
            try:
                self.after(0, _done)
            except tk.TclError:
                pass

        threading.Thread(target=_bg, daemon=True).start()

    def _open_card(self, card):
        url = card.get("shortUrl") or ""
        if not url and card.get("card_id"):
            url = f"https://trello.com/c/{card['card_id']}"
        if url:
            try:
                webbrowser.open(url)
            except Exception:
                pass

    def _open_process_dialog(self, card):
        """Pop the one-click "Process card" dialog. Chains the
        end-of-intake steps: scaffold missing folders, optionally
        import SP photos, autotick on-disk checklist items, post the
        canonical "Initial Upload submitted To WC." comment, and tick
        INITIAL UPLOAD to drop the row off the queue.

        On confirmed completion, fires a refresh of the queue so the
        processed card disappears (it's now ticked-as-uploaded and the
        IUQ filter excludes those)."""
        try:
            from process_card_dialog import open_process_dialog
        except Exception as ex:
            from tkinter import messagebox
            messagebox.showerror("Process dialog unavailable",
                                   f"Couldn't load module:\n{ex}",
                                   parent=self)
            return
        audit_app = None
        try:
            audit_app = self._find_audit_app()
        except Exception:
            audit_app = None

        def _on_done(ok):
            if not ok:
                return
            # Refresh the queue so the now-processed card drops off.
            # The IUQ filters out cards whose INITIAL UPLOAD item is
            # complete — our Process flow ticks that item, so a
            # refresh re-pulls and the row disappears.
            try:
                self._on_refresh()
            except Exception:
                pass

        open_process_dialog(
            self, card=card, audit_app=audit_app, on_done=_on_done)

    def _open_flag_missing_dialog(self, card):
        """Pop the shared "Flag missing item" dialog scoped to this
        card. The dialog calls missing_items_tracker with
        stage="initial" so Hygiene + the Trello comment attribute the
        gap to the intake step (not the final snapshot). Refreshes the
        row counts in place when the user submits — no full re-render
        of the queue is needed because the dialog only mutates tracker
        state, not the card payload."""
        client = (card.get("client") or "").strip()
        if not client:
            return
        card_id = card.get("card_id") or card.get("id") or ""
        tech_initials = (card.get("tech_initials") or "").strip()
        try:
            from flag_missing_dialog import open_flag_dialog
        except Exception as ex:
            from tkinter import messagebox
            messagebox.showerror("Flag dialog unavailable",
                                   f"Couldn't load module:\n{ex}",
                                   parent=self)
            return
        open_flag_dialog(
            self,
            client=client,
            card_id=card_id,
            card_url=(card.get("shortUrl")
                      or (f"https://trello.com/c/{card_id}"
                          if card_id else "")),
            tech_initials=tech_initials,
            stage="initial",
        )

    def _pin_card(self, card):
        client = card.get("client") or ""
        if not client:
            return
        # The shared dialog handles persisting the pin; we just route
        # the client name into it.
        open_trello_pin_dialog(self, client)

    def _open_notes(self, card):
        """Show a read-only preview of the saved Job Notes for this
        client. The full editor is a separate top-level tool — we
        offer a button to launch it scoped to the client so the user
        doesn't lose their place in the queue."""
        client = card.get("client") or ""
        if not client:
            return
        try:
            from job_notes_gui import has_note, load_note
        except Exception as ex:
            from tkinter import messagebox
            messagebox.showerror("Job Notes unavailable",
                                  f"Couldn't load module:\n{ex}",
                                  parent=self)
            return
        year = extract_job_year(card.get("job_path"))
        text = load_note(year, client) if has_note(year, client) else ""

        dlg = tk.Toplevel(self)
        dlg.title(f"Job Notes — {client}")
        dlg.configure(bg=BG)
        dlg.transient(self)
        try:
            dlg.geometry("640x520")
        except tk.TclError:
            pass

        head = tk.Frame(dlg, bg=BG, padx=14, pady=10)
        head.pack(fill="x")
        tk.Label(head, text=f"📝 {client}",
                 font=("Segoe UI Variable", 12, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(side="left")
        tk.Label(head, text=f"  ·  year {year}",
                 font=("Segoe UI Variable", 9), bg=BG, fg=TEXT_GRAY).pack(side="left")

        body = tk.Frame(dlg, bg=WHITE,
                         highlightthickness=1, highlightbackground=BORDER)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        if text.strip():
            txt = tk.Text(body, font=("Consolas", 9),
                           wrap="word", bg=WHITE, fg=TEXT_DARK,
                           relief="flat", padx=10, pady=8)
            txt.pack(fill="both", expand=True)
            txt.insert("1.0", text)
            txt.config(state="disabled")
        else:
            tk.Label(body,
                     text="No saved notes for this client yet.\n\n"
                          "Click 'Open in Job Notes' below to start one.",
                     font=("Segoe UI Variable", 10, "italic"),
                     bg=WHITE, fg=TEXT_GRAY,
                     padx=20, pady=30,
                     wraplength=560, justify="left").pack(fill="both",
                                                           expand=True)

        bot = tk.Frame(dlg, bg=BG, padx=14, pady=10)
        bot.pack(fill="x", side="bottom")
        def _open_full():
            try:
                import paths
                paths.spawn_tool("job_notes")
            except Exception:
                pass
        done_button(bot, "Open in Job Notes →", padx=14, pady=4,
                  command=_open_full).pack(side="left")
        secondary_button(bot, "Close", padx=14, pady=4,
                          command=dlg.destroy).pack(side="right")

    def _is_commercial(self, client):
        try:
            return persistence.is_commercial(client)
        except Exception:
            return False

    def _remove_manual_card(self, card):
        """Drop a manual entry from persistence and re-render. Trello-
        fetched rows never reach here (no ✕ button rendered)."""
        client = (card.get("client") or "").strip()
        if not client:
            return
        try:
            persistence.remove_manual_iuq_card(client)
        except Exception:
            pass
        # In-memory list: drop the row immediately so the user sees
        # the effect without waiting on a Trello refresh.
        self._cards = [c for c in (self._cards or [])
                       if not (c.get("manual")
                                and (c.get("client") or "").lower()
                                    == client.lower())]
        self._render_rows()
        try:
            show_toast(self, f"Removed manual entry for {client}",
                       kind="info", duration=2200)
        except Exception:
            pass

    def _open_add_manual_dialog(self):
        """Modal for adding a one-off client to the queue. Two fields:
        client name (required) and Trello card URL (optional — wires
        the row to a real card so the Trello-link button + autotick
        still work). Persists via persistence.add_manual_iuq_card."""
        dlg = tk.Toplevel(self)
        dlg.title("Add to Initial Upload Queue")
        dlg.configure(bg=BG)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        try:
            dlg.geometry("440x260")
        except tk.TclError:
            pass

        hdr = tk.Frame(dlg, bg=BG, padx=18, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="➕ Add manual entry",
                 font=("Fraunces", 16, "bold"),
                 bg=BG, fg=TEXT_DARK).pack(anchor="w")
        tk.Label(hdr,
                 text=("For jobs whose Trello card isn't in a scanned "
                       "lane, or one-offs without a card yet."),
                 font=("Segoe UI Variable", 9),
                 bg=BG, fg=TEXT_GRAY, wraplength=400, justify="left",
                 anchor="w").pack(fill="x", pady=(4, 0))

        body = tk.Frame(dlg, bg=WHITE, padx=18, pady=14)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        tk.Label(body, text="Client name",
                 font=("Segoe UI Variable", 10, "bold"),
                 bg=WHITE, fg=TEXT_DARK, anchor="w"
                 ).pack(fill="x")
        name_var = tk.StringVar()
        name_ent = tk.Entry(body, textvariable=name_var,
                             font=("Segoe UI Variable", 10),
                             bg=SURFACE_2, fg=TEXT_DARK,
                             relief="flat",
                             highlightthickness=1,
                             highlightbackground=BORDER)
        name_ent.pack(fill="x", pady=(2, 0), ipady=4)
        name_ent.focus_set()

        tk.Label(body, text="Trello card URL (optional)",
                 font=("Segoe UI Variable", 10, "bold"),
                 bg=WHITE, fg=TEXT_DARK, anchor="w"
                 ).pack(fill="x", pady=(12, 0))
        url_var = tk.StringVar()
        url_ent = tk.Entry(body, textvariable=url_var,
                            font=("Segoe UI Variable", 10),
                            bg=SURFACE_2, fg=TEXT_DARK,
                            relief="flat",
                            highlightthickness=1,
                            highlightbackground=BORDER)
        url_ent.pack(fill="x", pady=(2, 0), ipady=4)
        tk.Label(body,
                 text="Paste a https://trello.com/c/... link so the row "
                      "can post comments and tick checklists.",
                 font=("Segoe UI Variable", 8),
                 bg=WHITE, fg=TEXT_GRAY, anchor="w",
                 wraplength=380, justify="left"
                 ).pack(fill="x", pady=(2, 0))

        bot = tk.Frame(dlg, bg=BG, padx=18, pady=12)
        bot.pack(fill="x", side="bottom")

        def _extract_card_id(url):
            """Trello short URLs look like https://trello.com/c/<id>/...
            Pull the <id> segment. Returns "" when the URL doesn't
            match — the row still works for free-text but no card-
            backed actions fire."""
            import re as _re
            m = _re.search(r'trello\.com/c/([A-Za-z0-9]+)',
                            (url or "").strip())
            return m.group(1) if m else ""

        def _submit():
            client = (name_var.get() or "").strip()
            if not client:
                try:
                    from tkinter import messagebox
                    messagebox.showerror(
                        "Missing", "Enter a client name.", parent=dlg)
                except Exception:
                    pass
                return
            url = (url_var.get() or "").strip()
            cid = _extract_card_id(url)
            try:
                persistence.add_manual_iuq_card(
                    client, card_url=url, card_id=cid)
            except Exception:
                pass
            dlg.destroy()
            # Force a refresh — _on_refresh wipes the Trello cache so the
            # merged manual list shows up on the next render. Keeps the
            # data path consistent (no special "manual-only" reload).
            try:
                self._on_refresh()
            except Exception:
                pass
            try:
                show_toast(self,
                    f"Added {client} to the queue",
                    kind="info", duration=2400)
            except Exception:
                pass

        secondary_button(bot, "Cancel", padx=14, pady=4,
                          command=dlg.destroy
                          ).pack(side="right", padx=(6, 0))
        done_button(bot, "➕ Add", padx=14, pady=4,
                  command=_submit).pack(side="right")
        dlg.bind("<Return>", lambda _e: _submit())
        dlg.bind("<Escape>", lambda _e: dlg.destroy())


# Bind the body methods onto InitialUploadView. They were authored on the
# class historically (when there was only one class), so they live
# syntactically under InitialUploadApp. Both classes are tk.Frame
# subclasses, so the same `self` semantics work — we just rebind so the
# embedded view (audit-tab host) gets them too. Cleaner than copy/paste
# or a top-to-bottom rewrite.
for _m in ("_build_ui", "_on_refresh", "_load_async", "_render_rows",
           "_build_row", "_build_check_box", "_toggle_item",
           "_on_item_right_click", "_delete_item_from_card",
           "_open_card", "_pin_card", "_open_notes", "_is_commercial",
           "_open_snapshot_spreadsheet",
           "_ensure_job_folders", "_open_od_folder", "_make_job_folders",
           "_resolve_default_job_path",
           "_refresh_card_after_pin",
           "_find_audit_app", "_time_slot_for_client",
           "_today_run_doc_jobs",
           "_import_sp_for_card",
           "_import_wc_for_card",
           "_open_flag_missing_dialog",
           "_open_process_dialog",
           "_open_add_manual_dialog",
           "_remove_manual_card"):
    setattr(InitialUploadView, _m, getattr(InitialUploadApp, _m))
del _m


# ── CLOSE OUT dialog (used by Snapshot tool) ───────────────────────────────
# Same checklist pattern as the queue rows, but as a one-shot dialog
# scoped to a single client's pinned Trello card. The Snapshot tool is
# the only caller today; if more tools need a per-client checklist
# dialog later this can grow into a generic helper.

# Some cards label this checklist 'CLOSE OUT', others 'CLOSE OUT - ADMIN'.
# Tuple is tried in order — the first match on the card wins.
CLOSE_OUT_CHECKLIST_NAME = ("CLOSE OUT", "CLOSE OUT - ADMIN")
CLOSE_OUT_ITEMS_ORDER = (
    "FINAL PAPERWORK",
    "FINAL PHOTOS",
    "FINAL SKETCH",
    "FINAL SCOPE",
    "FINAL EQ COUNT",
    "SNAPSHOT",
)


def _resolve_card_for_client(parent, client):
    """Best-effort card lookup for the CLOSE OUT dialog. Returns the
    card_id or None.

    1. Pinned cards win — first pin is used.
    2. Otherwise fuzzy-search and use top hit.
    3. If nothing found, prompt the user via the pin dialog and let
       them pick / paste manually before retrying.
    """
    try:
        pinned = persistence.get_trello_card_ids(client)
    except Exception:
        pinned = []
    if pinned:
        return pinned[0]
    try:
        import trello_client as tc
        hits = tc.find_cards_by_name(client, max_results=5) or []
    except Exception:
        hits = []
    if hits:
        return hits[0].get("id")
    return None


def open_close_out_dialog(parent, client):
    """Open a CLOSE OUT checklist dialog for `client`'s Trello card.
    Renders the 6 CLOSE OUT items as toggleable buttons that round-trip
    to Trello on click. If no card is found, prompts to pin one.

    Used by the Snapshot tool from its preview-frame nav button."""
    if not client:
        return
    try:
        import trello_client as tc
    except Exception as ex:
        from tkinter import messagebox
        messagebox.showerror("Trello unavailable",
                              f"Couldn't load trello_client:\n{ex}",
                              parent=parent)
        return

    card_id = _resolve_card_for_client(parent, client)
    if not card_id:
        from tkinter import messagebox
        if messagebox.askyesno(
                "No Trello card",
                f"No Trello card found for '{client}'.\n\n"
                "Open the pin dialog so you can link one manually?",
                parent=parent):
            open_trello_pin_dialog(parent, client)
        return

    try:
        card = tc.get_card(card_id, actions_limit=1)
    except Exception as ex:
        from tkinter import messagebox
        messagebox.showerror("Trello fetch failed",
                              f"Couldn't load card:\n\n{ex}",
                              parent=parent)
        return
    if not card:
        from tkinter import messagebox
        messagebox.showerror("Card not found",
                              "Trello returned no card. The pinned card "
                              "may have been archived.",
                              parent=parent)
        return

    cl = _find_checklist(card, CLOSE_OUT_CHECKLIST_NAME)
    items_by_name = _items_dict(cl) if cl else {}

    dlg = tk.Toplevel(parent)
    dlg.title(f"CLOSE OUT — {client}")
    dlg.configure(bg=BG)
    dlg.transient(parent)
    try:
        dlg.geometry("520x460")
        dlg.resizable(False, False)
    except tk.TclError:
        pass

    head = tk.Frame(dlg, bg=BG, padx=14, pady=12)
    head.pack(fill="x")
    tk.Label(head, text="📋 CLOSE OUT",
             font=("Fraunces", 15, "bold"),
             bg=BG, fg=TEXT_DARK).pack(anchor="w")
    tk.Label(head, text=card.get("name") or client,
             font=("Segoe UI Variable", 9), bg=BG, fg=TEXT_GRAY,
             wraplength=480, justify="left",
             anchor="w").pack(fill="x", pady=(2, 0))

    if cl is None:
        tk.Label(dlg,
                 text=("⚠ This card has no 'CLOSE OUT' checklist.\n"
                       "Add the template on Trello first, then reopen."),
                 font=("Segoe UI Variable", 10, "italic"),
                 bg=BG, fg=FLAG_RED, padx=14, pady=20,
                 wraplength=480, justify="left").pack(fill="x")
    else:
        body = tk.Frame(dlg, bg=WHITE,
                         highlightthickness=1, highlightbackground=BORDER)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        for item_name in CLOSE_OUT_ITEMS_ORDER:
            it = items_by_name.get(item_name)
            row = tk.Frame(body, bg=WHITE, padx=14, pady=6)
            row.pack(fill="x")
            if not it:
                tk.Label(row, text=f"❓ {item_name}  (missing on card)",
                         font=("Segoe UI Variable", 10), bg=WHITE, fg=FLAG_RED,
                         anchor="w").pack(fill="x")
                continue
            state = (it.get("state") or "").lower()
            text = (f"☑ {item_name}" if state == "complete"
                     else f"☐ {item_name}")
            fg = GREEN_DARK if state == "complete" else TEXT_DARK
            btn = tk.Button(row, text=text,
                             font=("Segoe UI Variable", 10, "bold"),
                             bg=WHITE, fg=fg, activebackground=SUCCESS_HOVER,
                             relief="flat", padx=8, pady=4, cursor="hand2",
                             anchor="w")
            btn.pack(fill="x")
            # Per-button toggler — same optimistic-update + revert
            # pattern the queue uses, copy-locally because reusing the
            # queue's _toggle_item would tie this dialog to the queue's
            # `self._cards` cache lifecycle.
            def _make_toggle(btn=btn, item=dict(it), name=item_name):
                def _do():
                    cur = (item.get("state") or "").lower()
                    new = "incomplete" if cur == "complete" else "complete"
                    new_text = (f"☑ {name}" if new == "complete"
                                 else f"☐ {name}")
                    new_fg = GREEN_DARK if new == "complete" else TEXT_DARK
                    try:
                        btn.config(text=new_text, fg=new_fg, state="disabled")
                    except tk.TclError:
                        return
                    def _bg():
                        ok = tc.set_check_item_state(card.get("id"),
                                                      item.get("id"), new)
                        def _done():
                            try:
                                btn.config(state="normal")
                            except tk.TclError:
                                return
                            if ok:
                                item["state"] = new
                            else:
                                # Revert
                                try:
                                    btn.config(
                                        text=(f"☑ {name}"
                                              if cur == "complete"
                                              else f"☐ {name}"),
                                        fg=(GREEN_DARK
                                            if cur == "complete"
                                            else TEXT_DARK))
                                except tk.TclError:
                                    pass
                                show_toast(parent,
                                           "Trello refused the toggle.",
                                           kind="error")
                        dlg.after(0, _done)
                    threading.Thread(target=_bg, daemon=True).start()
                return _do
            btn.config(command=_make_toggle())

            # Right-click → delete this item from Trello. Items that
            # don't apply to this specific job (e.g. FINAL EQ COUNT on
            # a job with no equipment) can be removed so the shortened
            # checklist matches reality. Mirrors on Trello so other
            # team members see the same list.
            def _make_delete(btn=btn, item=dict(it), name=item_name,
                              row=row):
                def _on_right(_e):
                    menu = tk.Menu(dlg, tearoff=0)
                    menu.add_command(
                        label=f"Remove '{name}' from Trello",
                        command=lambda: _do_delete())
                    try:
                        menu.tk_popup(_e.x_root, _e.y_root)
                    finally:
                        menu.grab_release()
                def _do_delete():
                    from tkinter import messagebox
                    if not messagebox.askyesno(
                            "Remove checklist item?",
                            f"Remove '{name}' from CLOSE OUT on "
                            "Trello?\n\nThis affects everyone on the "
                            "card.", parent=dlg):
                        return
                    try:
                        btn.config(state="disabled")
                    except tk.TclError:
                        pass
                    def _bg():
                        ok = tc.delete_check_item(cl.get("id"),
                                                    item.get("id"))
                        def _done():
                            if not ok:
                                try:
                                    btn.config(state="normal")
                                except tk.TclError:
                                    pass
                                show_toast(parent,
                                           "Trello refused the delete.",
                                           kind="error")
                                return
                            # Drop the row from the dialog so the user
                            # sees the shortened list immediately.
                            try:
                                row.destroy()
                            except tk.TclError:
                                pass
                            show_toast(parent,
                                       f"Removed '{name}' from Trello.",
                                       kind="info")
                        dlg.after(0, _done)
                    threading.Thread(target=_bg, daemon=True).start()
                return _on_right
            btn.bind("<Button-3>", _make_delete())

    bot = tk.Frame(dlg, bg=BG, padx=14, pady=10)
    bot.pack(fill="x", side="bottom")
    link_button(bot, "Open card on Trello", padx=10, pady=4,
                 font=("Segoe UI Variable", 8, "bold"),
                 command=lambda c=card: webbrowser.open(
                  c.get("shortUrl") or f"https://trello.com/c/{c.get('id')}")
              ).pack(side="left")
    done_button(bot, "Close", padx=18, pady=4,
              command=dlg.destroy).pack(side="right")


def main(argv=None):
    """Standalone entry point — called by launcher.py's `--tool
    initial_upload` dispatch and by run_standalone in dev."""
    run_standalone(InitialUploadApp, geometry="960x680",
                    minsize=(700, 480))


if __name__ == "__main__":
    main()
