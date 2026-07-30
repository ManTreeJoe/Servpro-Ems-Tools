"""Trello read-only client.

Auth via API key + token from %APPDATA%\\EMS Automation\\config.json:
    trello_api_key, trello_token, trello_workspace_id, trello_boards_exclude

Phase 1: list_boards (workspace boards minus excludes), find_cards_by_name
(search cards across included boards). CLI smoke test for both.

Future phases will add checklist read/write so APA Monitor's Initial Upload
rows can deep-link to the matching Trello card and toggle a checklist item.
"""
import json
import re as _re
import sys
import time
import urllib.parse
import urllib.request

import config

API_BASE = "https://api.trello.com/1"
_USER_AGENT = "EMS-Automation/1.0"


def _creds():
    cfg = config.load()
    key = (cfg.get("trello_api_key") or "").strip()
    token = (cfg.get("trello_token") or "").strip()
    if not key or not token:
        raise RuntimeError(
            "Trello not configured. Set trello_api_key and trello_token in "
            r"%APPDATA%\EMS Automation\config.json")
    return key, token


def _call(path, *, params=None, method="GET", data=None, _max_retries=5):
    """GET (or POST/PUT) against Trello API. Auth params appended automatically.
    `data` is form-encoded for write methods. Raises urllib HTTPError on non-2xx.

    Retries on HTTP 429 (rate limit) and 503 (transient), honoring the
    server's `Retry-After` header when present, else exponential backoff
    (1, 2, 4, 8, 8s). Trello's limits are ~100 req / 10s per key — a big
    Snapshots reconcile fires ~1.7k calls and WILL trip that without this,
    so closed jobs near the end of the workbook were misrouting to Needs
    Attention on a transient 429 rather than their real sheet."""
    key, token = _creds()
    qs = dict(params or {})
    qs["key"] = key
    qs["token"] = token
    url = f"{API_BASE}{path}?{urllib.parse.urlencode(qs)}"
    body = None
    headers = {"User-Agent": _USER_AGENT}
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    attempt = 0
    while True:
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read()
            break
        except urllib.request.HTTPError as ex:
            # 429 (rate limit) is always safe to retry — the request was
            # rejected, never processed. 503 (transient) can occur AFTER
            # Trello accepted a write, so retrying a POST risks a DUPLICATE
            # card/comment; only retry 503 for idempotent methods.
            retryable = (ex.code == 429
                         or (ex.code == 503 and method != "POST"))
            if retryable and attempt < _max_retries:
                retry_after = ex.headers.get("Retry-After") if ex.headers else None
                try:
                    delay = float(retry_after) if retry_after else 0.0
                except (TypeError, ValueError):
                    delay = 0.0
                if delay <= 0:
                    delay = float(min(2 ** attempt, 8))
                time.sleep(delay)
                attempt += 1
                continue
            raise
    if not raw:
        return None
    return json.loads(raw)


# Boards excluded from the hygiene / quality / customer-complaint scans
# by NAME (case-insensitive substring). The AR board is a billing follow-
# up surface — its cards are by design quiet for weeks and would dominate
# hygiene with non-actionable noise. ar_followup.py reads the AR board
# directly for its XA-apology section so the dedicated workflow still
# works; only the workspace-wide quality sweeps drop it.
QUALITY_EXCLUDED_BOARD_NAMES = (
    "ar board", "ar-board", "ar followup", "accounts receivable",
)

_QUALITY_EXCLUDED_IDS_CACHE: set[str] | None = None


def _is_quality_excluded_name(name) -> bool:
    nl = (name or "").lower()
    return any(tok in nl for tok in QUALITY_EXCLUDED_BOARD_NAMES)


def quality_excluded_board_ids() -> set[str]:
    """Set of board ids whose names match QUALITY_EXCLUDED_BOARD_NAMES.

    Resolved once via list_boards() and cached for the process lifetime.
    Use this to filter card hits returned from search APIs that can't
    pre-filter by name (e.g. `find_cards_by_name` searches the whole
    workspace; callers route results through this set to drop AR-board
    matches in hygiene / customer-complaint flows).
    """
    global _QUALITY_EXCLUDED_IDS_CACHE
    if _QUALITY_EXCLUDED_IDS_CACHE is not None:
        return _QUALITY_EXCLUDED_IDS_CACHE
    out: set[str] = set()
    try:
        for b in list_boards() or []:
            if _is_quality_excluded_name(b.get("name", "")):
                bid = b.get("id") or ""
                if bid:
                    out.add(bid)
    except Exception:
        # On Trello hiccup, return empty (allow rather than block) —
        # better to surface an AR card occasionally than to silently
        # hide every card because the network was momentarily flaky.
        out = set()
    _QUALITY_EXCLUDED_IDS_CACHE = out
    return out


def invalidate_caches():
    """Drop EVERY process-lifetime cache that is scoped to the active
    Trello workspace. Called on a department (OC/IE) switch so the next
    call re-resolves against the newly-active workspace instead of
    returning the previous department's board/list ids.

    The in-process switch only reloads the web page, not the Python
    process, so any module-level cache seeded before the switch survives
    it. Every cache here is keyed on (or derived from) a board looked up
    BY NAME in the active workspace, so it MUST be reset — otherwise IE
    keeps serving OC's LOGS/AR board (or an empty "" sentinel when the
    name doesn't exist in the other workspace, i.e. "can't find any
    cards"). If you add another name-resolved workspace cache, reset it
    here too."""
    global _QUALITY_EXCLUDED_IDS_CACHE
    global _logs_board_id_cache, _ar_board_id_cache, _logs_list_ids_cache
    global _WARNED_NO_BOARDS
    _WARNED_NO_BOARDS = False
    _QUALITY_EXCLUDED_IDS_CACHE = None
    _logs_board_id_cache = None
    _ar_board_id_cache = None
    _logs_list_ids_cache = None
    _LIST_NAME_CACHE.clear()
    _MEMBER_NAME_CACHE.clear()


_WARNED_NO_BOARDS = False


def _warn_no_boards(detail):
    """Log (once per process) that the active department can't see any
    Trello boards. Silent [] here is what made a mis-pointed workspace look
    like broken name-matching for weeks."""
    global _WARNED_NO_BOARDS
    if _WARNED_NO_BOARDS:
        return
    _WARNED_NO_BOARDS = True
    try:
        import ems_log
        dept = config.active_department() or "(single-dept)"
        ems_log.warn("trello", f"no boards for department {dept}: {detail}")
    except Exception:
        pass


def list_boards(*, exclude_quality: bool = False):
    """Return [{id, shortLink, name, url}] for every open board in the
    configured workspace, with `trello_boards_exclude` filtered out.
    Excludes match either the shortLink or the full board id.

    When `exclude_quality=True`, also drop boards whose names match
    QUALITY_EXCLUDED_BOARD_NAMES (the AR / billing boards). Default is
    False so existing single-purpose callers like ar_followup still see
    every board.
    """
    cfg = config.load()
    org_id = (cfg.get("trello_workspace_id") or "").strip()
    if not org_id:
        _warn_no_boards("no trello_workspace_id configured")
        return []
    excludes = set(cfg.get("trello_boards_exclude") or [])
    raw = _call(
        f"/organizations/{org_id}/boards",
        params={"fields": "id,name,shortLink,url,closed", "filter": "open"},
    )
    out = []
    for b in raw or []:
        if b.get("closed"):
            continue
        if b.get("shortLink") in excludes or b.get("id") in excludes:
            continue
        if exclude_quality and _is_quality_excluded_name(b.get("name", "")):
            continue
        out.append({
            "id":        b["id"],
            "shortLink": b.get("shortLink", ""),
            "name":      b.get("name", ""),
            "url":       b.get("url", ""),
        })
    if not out:
        # Zero boards means every downstream card search returns nothing,
        # which reads to the user as "matching is broken" rather than
        # "you're pointed at the wrong workspace". Say so in the log.
        _warn_no_boards(
            f"workspace {org_id} returned no usable boards "
            f"(raw={len(raw or [])}, excluded={len(excludes)})")
    return out


def find_cards_by_name(query, *, max_results=20):
    """Search included boards for cards matching `query`. Uses Trello's
    full-text search (fuzzy, handles Last/First reorders), then filters
    by board id so results from excluded boards never leak in.

    Returns list of dicts:
      {board, card_id, name, url, list_id, list_name}
    """
    query = (query or "").strip()
    if not query:
        return []
    boards = list_boards()
    if not boards:
        return []
    board_index = {b["id"]: b["name"] for b in boards}
    raw = _call("/search", params={
        "query":       query,
        "modelTypes":  "cards",
        "idBoards":    ",".join(b["id"] for b in boards),
        "card_fields": "id,name,shortUrl,idBoard,idList,closed",
        "cards_limit": str(max_results),
    })
    cards = (raw or {}).get("cards", []) if isinstance(raw, dict) else []
    if not cards:
        return []
    # Per-board list-name lookup, lazily cached so multiple cards from
    # the same board only cost one extra API call.
    list_cache = {}
    out = []
    for c in cards:
        if c.get("closed"):
            continue
        bid = c.get("idBoard")
        if bid not in list_cache:
            try:
                lists = _call(f"/boards/{bid}/lists",
                              params={"fields": "id,name"})
                list_cache[bid] = {l["id"]: l["name"] for l in lists or []}
            except Exception:
                list_cache[bid] = {}
        lid = c.get("idList")
        out.append({
            "board":     board_index.get(bid, "(unknown)"),
            "card_id":   c["id"],
            "name":      c.get("name", ""),
            "url":       c.get("shortUrl", ""),
            "list_id":   lid,
            "list_name": list_cache[bid].get(lid, ""),
        })
    return out


def card_url_for_client(client):
    """Convenience helper: look up a card by client name, return the
    shortUrl of the best match, or None when nothing matches.

    "Best" = first non-closed result Trello's search returns. Trello's
    own ranker handles fuzzy/typo cases (we feed it the raw insured
    name) so this is good enough for the link-out cases.
    """
    if not (client or "").strip():
        return None
    try:
        results = find_cards_by_name(client, max_results=5)
    except Exception:
        return None
    for r in results:
        url = r.get("url")
        if url:
            return url
    return None


def card_url_from_id(card_id):
    """Return a web-openable URL for `card_id` without a network call.

    Trello accepts the full 24-char card id as a path segment in
    /c/<id> and redirects to the canonical shortLink URL — so we can
    build a working link even when the row data only carries an id.
    Used by Hygiene row renderers that have a pinned card but no
    cached shortUrl (e.g. estimate requests whose adjuster_monitor
    output preserved card_id but dropped card_url)."""
    cid = (card_id or "").strip()
    if not cid:
        return ""
    return f"https://trello.com/c/{cid}"


def open_card_for_client(client):
    """Find the first matching Trello card for `client` and open its
    short URL in the user's default browser. Returns True on success.
    Used by the audit's right-click menu and APA's Initial Upload row.
    Logs but never raises so a Trello outage doesn't crash the GUI."""
    url = card_url_for_client(client)
    if not url:
        return False
    try:
        import webbrowser
        webbrowser.open(url)
        return True
    except Exception:
        return False


# ── Phase 2: pinned-card read + round-trip ─────────────────────────────────

# Single GET that returns everything the job-notes pane needs to render the
# card. Including actions inline saves a second round-trip per refresh.
_CARD_FIELDS = "name,desc,shortUrl,idBoard,idList,labels,due,dueComplete," \
               "dateLastActivity,closed,idMembers"
_CARD_ACTIONS = "commentCard,updateCard:idList,updateCard:closed," \
                "addAttachmentToCard,addMemberToCard,removeMemberFromCard"


# Module-level cache: board_id → {list_id: list_name}. List metadata
# is essentially static (admins rename a lane maybe once a quarter), so
# caching across the process lifetime trims one HTTP round-trip per
# job-notes refresh — meaningful when polling every 30s.
_LIST_NAME_CACHE = {}


def get_lane_name(board_id, list_id):
    """Resolve a list_id to its display name, caching the per-board lookup.
    Empty string when the lookup fails (network, deleted list, etc.) so
    callers can fall back to a generic 'unknown lane' display."""
    if not board_id or not list_id:
        return ""
    by_list = _LIST_NAME_CACHE.get(board_id)
    if by_list is None:
        try:
            lists = _call(f"/boards/{board_id}/lists",
                          params={"fields": "id,name"})
            by_list = {l["id"]: l.get("name", "") for l in lists or []}
        except Exception:
            by_list = {}
        _LIST_NAME_CACHE[board_id] = by_list
    return by_list.get(list_id, "")


def get_card_lane(card_id):
    """Return a card's CURRENT lane (list) display name, or "".

    Light-weight: fetches ONLY idBoard/idList (no checklists, members,
    attachments, or actions like the full `get_card`), then resolves the
    lane via `get_lane_name`'s per-board cache — so re-routing a whole APA
    doc costs ~one cheap card call per item plus one board-list call per
    distinct board. Used by the APA "refresh lanes from Trello" button.
    """
    if not card_id:
        return ""
    try:
        c = _call(f"/cards/{card_id}", params={"fields": "idBoard,idList"})
    except Exception:
        return ""
    if not c:
        return ""
    return get_lane_name(c.get("idBoard"), c.get("idList"))


def list_notifications(*, limit=50, only_unread=False):
    """Fetch the current member's Trello notifications, newest-first.

    Each item: {id, type, unread, date, data{card,board,text,...},
    memberCreator{fullName,username}}. `type` is e.g. mentionedOnCard /
    commentCard / changeCard / addedToCard / makeAdminOfBoard / etc.
    Returns [] on any failure. Powers the in-app Notifications panel.
    """
    params = {
        "limit": str(max(1, min(int(limit or 50), 1000))),
        "filter": "all",
        "memberCreator": "true",
        "memberCreator_fields": "fullName,username",
    }
    if only_unread:
        params["read_filter"] = "unread"
    try:
        return _call("/members/me/notifications", params=params) or []
    except Exception:
        return []


def unread_notification_count():
    """Count of UNREAD Trello notifications (for a sidebar/topbar badge).
    Cheap-ish: fetches unread ids only. 0 on failure."""
    try:
        r = _call("/members/me/notifications",
                  params={"read_filter": "unread", "fields": "id",
                          "limit": "1000"}) or []
        return len(r)
    except Exception:
        return 0


def mark_notification_read(notification_id, read=True):
    """Mark ONE notification read (read=True → unread=false) or unread.
    Writes back to Trello so the real bell clears. True on success."""
    if not notification_id:
        return False
    try:
        _call(f"/notifications/{notification_id}", method="PUT",
              params={"unread": "false" if read else "true"})
        return True
    except Exception:
        return False


def mark_all_notifications_read():
    """Mark EVERY notification read (POST /notifications/all/read)."""
    try:
        _call("/notifications/all/read", method="POST")
        return True
    except Exception:
        return False


# Identifier patterns used by parse_card_identifier for the manual-link
# path. Trello card URLs always wrap the shortLink (8 alphanumeric chars);
# the full card_id is a 24-char lowercase hex string. Both are accepted by
# every Trello /cards/{id} endpoint, so we don't need to resolve one to
# the other here — get_card() handles whichever form is returned.
_TRELLO_URL_RE     = _re.compile(
    r"trello\.com/c/([A-Za-z0-9]{8})(?:/|$|\?)")
_TRELLO_SHORT_RE   = _re.compile(r"^[A-Za-z0-9]{8}$")
_TRELLO_FULLID_RE  = _re.compile(r"^[a-f0-9]{24}$")


def parse_card_identifier(text):
    """Extract a Trello card id from a pasted URL, shortLink, or raw id.

    Accepts any of:
      - https://trello.com/c/abc12345/some-slug   → 'abc12345'
      - https://trello.com/c/abc12345             → 'abc12345'
      - trello.com/c/abc12345                     → 'abc12345'
      - abc12345                                  → 'abc12345'
      - 24-char hex full card id                  → returned as-is

    Returns None if the input doesn't look like any of those — caller can
    then surface an inline 'doesn't look like a Trello link' error rather
    than a confusing 404 from a half-validated id."""
    s = (text or "").strip()
    if not s:
        return None
    m = _TRELLO_URL_RE.search(s)
    if m:
        return m.group(1)
    if _TRELLO_SHORT_RE.match(s):
        return s
    if _TRELLO_FULLID_RE.match(s):
        return s
    return None


def cards_in_list(list_id, *, fields="id,name,shortUrl,idBoard,idList,closed"):
    """Return open cards currently in the given Trello list (lane).
    Used by the Snapshot tool's auto-pull (ESTIMATING → SNAPSHOT lane)
    and any other workflow that needs the contents of a specific lane."""
    if not list_id:
        return []
    try:
        raw = _call(f"/lists/{list_id}/cards",
                    params={"fields": fields, "filter": "open"})
    except Exception:
        return []
    return [c for c in (raw or []) if not c.get("closed")]


def move_card(card_id, list_id, *, pos=None):
    """Move a card to another list (lane) on Trello. Returns True on
    success, False on any failure (logged to ems.log).

    Used by the Pipeline board's drag-to-move. `pos` optionally controls
    the in-lane position ("top"/"bottom"/number); omitted = Trello's
    default (bottom)."""
    if not card_id or not list_id:
        return False
    params = {"idList": list_id}
    if pos is not None:
        params["pos"] = pos
    try:
        _call(f"/cards/{card_id}", method="PUT", params=params)
        return True
    except Exception as ex:
        try:
            import ems_log
            ems_log.warn("trello", f"move_card {card_id}->{list_id} failed: {ex}")
        except Exception:
            pass
        return False


def get_list(list_id, *, fields="id,name,idBoard"):
    """Fetch a single Trello list (lane) by id. Returns the raw dict
    (`{"id", "name", "idBoard", ...}`) or None on any failure.

    Used by classifiers that need the lane name from a card id — given
    a card we can read `idList`, then this gets the lane name. Cheaper
    than fetching the full board listing when we only need one lane."""
    if not list_id:
        return None
    try:
        return _call(f"/lists/{list_id}", params={"fields": fields})
    except Exception:
        return None


def cards_in_list_with_checklists(list_id, *,
                                   fields=("id,name,desc,shortUrl,idBoard,"
                                           "idList,labels,closed")):
    """Like cards_in_list but each card includes its full `checklists`
    array (with checkItems and their states). One HTTP round-trip per
    list — Trello inlines the checklists when asked.

    Used by the audit's Initial Upload Queue to filter by 'INITIAL UPLOAD'
    completion state without per-card detail fetches."""
    if not list_id:
        return []
    try:
        raw = _call(f"/lists/{list_id}/cards", params={
            "fields":           fields,
            "filter":           "open",
            "checklists":       "all",
            "checklist_fields": "name",
        })
    except Exception:
        return []
    return [c for c in (raw or []) if not c.get("closed")]


def set_check_item_state(card_id, check_item_id, state):
    """Toggle a checklist item's completion state on a card.

    `state` must be 'complete' or 'incomplete'. Returns True on success,
    False on any failure (network, auth, 404). Used by the Initial Upload
    Queue's per-row checkbox clicks so the user can tick items without
    leaving the audit panel.

    Failures log to ems.log so a silent "tick didn't propagate" symptom
    leaves a trail — callers that just check the boolean return get
    failure logging for free instead of each having to wire it."""
    if not card_id or not check_item_id:
        return False
    if state not in ("complete", "incomplete"):
        return False
    try:
        _call(f"/cards/{card_id}/checkItem/{check_item_id}",
              method="PUT", data={"state": state})
        return True
    except Exception as ex:
        try:
            import ems_log
            ems_log.warn("trello_client",
                          f"set_check_item_state failed "
                          f"card={card_id} item={check_item_id} "
                          f"state={state}: {ex}")
        except Exception:
            pass
        return False


def delete_check_item(checklist_id, check_item_id):
    """Permanently remove a checklist item from a Trello checklist.

    Returns True on success, False on any failure (network, auth, 404).
    Used by the Initial Upload Queue and CLOSE OUT dialog so the user
    can drop items that don't apply to this job — the deletion is
    mirrored on Trello so other team members see the same shortened
    checklist."""
    if not checklist_id or not check_item_id:
        return False
    try:
        _call(f"/checklists/{checklist_id}/checkItems/{check_item_id}",
              method="DELETE")
        return True
    except Exception:
        return False


def get_card(card_id, *, actions_limit=50):
    """Return one card with the fields, checklists, members, attachments,
    and last `actions_limit` activity actions in a single API call.

    Returns the raw Trello card dict (callers usually pass it straight
    into `format_activity_feed` / `parse_card_desc`). None on 404."""
    if not card_id:
        return None
    try:
        return _call(f"/cards/{card_id}", params={
            "fields":         _CARD_FIELDS,
            "checklists":     "all",
            "checklist_fields": "name",
            "attachments":    "true",
            "attachment_fields": "name,url,date,isUpload",
            "members":        "true",
            "member_fields":  "fullName,username",
            "actions":        _CARD_ACTIONS,
            "actions_limit":  str(actions_limit),
        })
    except urllib.request.HTTPError as ex:
        if ex.code == 404:
            return None
        raise


def get_all_comments(card_id, *, max_pages=20):
    """Fetch every comment action on a card, paging past Trello's 50-per-request
    cap. Returns a list of commentCard action dicts in the same shape `get_card`
    returns under `actions`, ordered newest-first.

    Trello's `/cards/{id}/actions` endpoint takes a `before` cursor (action id
    or ISO date). We page by feeding the oldest action's id back as `before`
    until a page returns fewer than 50 items, capped at `max_pages` so a
    runaway loop can't burn the rate limit.
    """
    if not card_id:
        return []
    out = []
    before = None
    for _ in range(max_pages):
        params = {"filter": "commentCard", "limit": "50"}
        if before:
            params["before"] = before
        try:
            page = _call(f"/cards/{card_id}/actions", params=params) or []
        except urllib.request.HTTPError:
            break
        if not page:
            break
        out.extend(page)
        if len(page) < 50:
            break
        before = page[-1].get("id")
        if not before:
            break
    return out


# Sheet routing — Snapshots Excel reconciliation
# ────────────────────────────────────────────────────────────────────────
# A card's "completed-ness" is determined by which board it lives on:
#   - On the AR_BOARD_NAME or LOGS_BOARD_NAME board → closed (Completed
#     or Incomplete). Archived cards + terminal lanes also count.
#   - Anywhere else (WIP, Estimating, etc.) → still active (NEW LOSS)
# Within the closed bucket, the card is Incomplete when any of these
# signals fire — otherwise it's Completed.
LOGS_BOARD_NAME = "THE LOGS - EMS"
# Accounts-Receivable board. Per the user (2026-06-12) this is where the
# franchise actually parks closed jobs (Completed/Incomplete) — they sit
# in AR waiting on payment. So a card on the AR board counts as CLOSED,
# same as the LOGS board / archived / a terminal lane. Matched by
# whitespace-collapsed name ("AR  BOARD" in Trello has a double space).
AR_BOARD_NAME = "AR BOARD"

# Comment-text phrases that mark a closed card as Incomplete. Matched
# as case-insensitive substrings against the joined-comments blob.
# Expanded 2026-05-13 — the prior tuple was just two phrases and missed
# every cancelled / declined / denied / comped job whose closeout note
# used different wording. Order doesn't matter (any match wins) but
# we group by theme for readability.
_INCOMPLETE_COMMENT_MARKERS = (
    # No final estimate produced
    "no final estimate", "no final est", "no final invoice",
    "estimate only", "scope only", "monitor only", "moisture check only",
    # Comp / no-charge
    "comp service", "comp'd", "comp service",
    "complimentary", "no charge", "non-billable", "non billable",
    # Cancelled / withdrawn (homeowner side)
    "cancelled by homeowner", "cancelled by insured", "cancelled by client",
    "homeowner cancelled", "homeowner declined",
    "insured declined", "client declined",
    "did not proceed", "not proceeding", "did not move forward",
    "no work performed", "no work done",
    "withdrawn", "voided", "void by",
    # Carrier / claim denial
    "claim denied", "denied by carrier", "claim withdrawn",
    "no claim filed", "self-pay declined",
    # 3rd party / wrong-territory handoff
    "3rd party", "third party", "wrong franchise", "wrong territory",
    "transferred to", "handed off to",
    # Customer chose a competitor / declined our proposal. The phrasing
    # that loses these jobs ("we moved ahead with another firm") never
    # tripped any marker before, so the card sat in estimating limbo.
    "another firm", "another company", "another contractor",
    "another vendor", "another restoration", "going with another",
    "went with another", "moved ahead with another", "moved forward with another",
    "going a different direction", "different direction",
    "chose another", "going elsewhere", "declined our proposal",
    "declined our estimate", "declined the proposal", "declined the estimate",
    "going in house", "going in-house", "in-house crew",
    # Generic incomplete tag
    "marked incomplete", "incomplete job",
)

# Trello label-name substrings that ALSO mark a card as Incomplete.
# Same case-insensitive substring rule against any label name on the
# card. Catches franchises that use a label-driven workflow
# ("Cancelled" / "Comp" / "Declined" / "No Final" labels) instead of
# leaving a comment.
_INCOMPLETE_LABEL_KEYWORDS = (
    "cancel", "comp'd", "complimentary",
    "declined", "withdrawn", "voided", "denied",
    "incomplete", "no charge", "no final",
)
_LOSS_LABEL_NAMES = {
    "water": "Water", "mold": "Mold", "fire": "Fire", "smoke": "Smoke",
    "bio": "Bio", "asbestos": "Asbestos", "lead": "Lead",
    "storm": "Storm", "vandalism": "Vandalism", "general": "General",
}

_logs_board_id_cache = None
_ar_board_id_cache = None


def _norm_board_name(name):
    """Lowercase + collapse internal whitespace so "AR  BOARD" matches
    "AR BOARD" and stray double-spaces don't break board lookup."""
    return " ".join(str(name or "").split()).lower()


def get_logs_board_id():
    """Return the cached id of the LOGS_BOARD_NAME board, or None when
    the workspace doesn't have such a board / we can't reach Trello.
    Looked up once per process (board ids are stable)."""
    global _logs_board_id_cache
    if _logs_board_id_cache is not None:
        return _logs_board_id_cache or None
    try:
        for b in list_boards() or []:
            if _norm_board_name(b.get("name")) == _norm_board_name(LOGS_BOARD_NAME):
                _logs_board_id_cache = b["id"]
                return _logs_board_id_cache
    except Exception:
        pass
    _logs_board_id_cache = ""
    return None


def get_ar_board_id():
    """Return the cached id of the AR_BOARD_NAME board, or None when the
    workspace has no such board / Trello is unreachable. Looked up once
    per process (board ids are stable). Used by `card_is_closed` so cards
    parked in Accounts Receivable count as closed jobs."""
    global _ar_board_id_cache
    if _ar_board_id_cache is not None:
        return _ar_board_id_cache or None
    try:
        for b in list_boards() or []:
            if _norm_board_name(b.get("name")) == _norm_board_name(AR_BOARD_NAME):
                _ar_board_id_cache = b["id"]
                return _ar_board_id_cache
    except Exception:
        pass
    _ar_board_id_cache = ""
    return None


def card_xa_link(card):
    """Extract the XactAnalysis URL from a card's templated desc, or "".

    The card's LINKS section carries the XA link, but the real cards name
    it `EMS Xactanalysis Link` / `Pack out Xactanalysis Link` — NOT a
    plain `Xactanalysis Link`. So match ANY LINKS key whose letters
    contain "xactanalysis", preferring the EMS link, then a plain one,
    then Pack out. parse_card_desc already strips the markdown wrapper to
    the bare URL; we validate it's http(s) so a stray "(pending)"
    placeholder isn't fed to webbrowser.open.

    Returns the URL string or "" — callers can branch on truthiness.
    """
    if not card:
        return ""
    try:
        fields = parse_card_desc(card.get("desc"))
    except Exception:
        return ""
    links = fields.get("LINKS") or {}

    def _alnum(k):
        return "".join(ch for ch in (k or "").lower() if ch.isalnum())

    def _rank(k):
        kl = _alnum(k)
        if "ems" in kl:     return 0   # EMS XactAnalysis — primary
        if "packout" in kl: return 2   # Pack out — last resort
        return 1                       # plain "Xactanalysis Link"

    cands = [(k, v) for k, v in links.items()
             if "xactanalysis" in _alnum(k)]
    for k, v in sorted(cands, key=lambda kv: _rank(kv[0])):
        raw = (v or "").strip()
        low = raw.lower()
        if low.startswith("http://") or low.startswith("https://"):
            return raw
    return ""


def card_companycam_link(card):
    """Extract a CompanyCam project URL from a card's templated desc, or "".

    Mirrors `card_xa_link`. The card's LINKS section may carry a
    "CompanyCam Link: [label](url)" line (admins add it like the Video /
    Docusketch / XactAnalysis links). Tolerant of prefixed key spellings
    — matches ANY LINKS key whose letters contain "companycam" (so "EMS
    CompanyCam Link" / "Company Cam Link" all work) — and validates the
    value is an http(s) URL so a stray "(pending)" placeholder isn't fed
    to webbrowser.open. Returns the bare URL or "".
    """
    if not card:
        return ""
    try:
        fields = parse_card_desc(card.get("desc"))
    except Exception:
        return ""
    links = fields.get("LINKS") or {}
    for k, v in links.items():
        key = "".join(ch for ch in (k or "").lower() if ch.isalnum())
        if "companycam" in key:
            raw = (v or "").strip()
            low = raw.lower()
            if low.startswith("http://") or low.startswith("https://"):
                return raw
    return ""


def card_loss_type(card):
    """Inspect a card's labels and return all matching loss types joined
    with ", ". Empty string when none of the labels look like a loss
    type. Match is case-insensitive and substring-tolerant so labels
    like "Water Damage" or "Mold Job" still resolve to "Water" / "Mold".

    Multi-cause jobs (e.g. a card with both Water + Mold labels) come
    back as "Water, Mold". Output order is canonical — driven by the
    order in `_LOSS_LABEL_NAMES` — so the same set of labels always
    renders identically in the spreadsheet (no flicker between syncs).

    Accepts either a full Trello card dict (`labels=[{"name": ...}, ...]`)
    OR a simplified shape where labels is a list of plain strings — the
    initial upload queue uses the simplified shape and reusing this
    helper there keeps loss-type extraction in one place.
    """
    if not card:
        return ""
    raw_labels = card.get("labels") or []
    labels_lower = []
    for lab in raw_labels:
        if isinstance(lab, str):
            labels_lower.append(lab.strip().lower())
        elif isinstance(lab, dict):
            labels_lower.append((lab.get("name") or "").strip().lower())
    labels_lower = [n for n in labels_lower if n]
    if not labels_lower:
        return ""
    found = []
    for key, display in _LOSS_LABEL_NAMES.items():
        if any(key in nm for nm in labels_lower):
            found.append(display)
    return ", ".join(found)


# List-name substrings that mark a card's lane as a terminal/closed
# lane (for franchises that close jobs by moving the card to a "Closed
# out" / "Logs" / "Paid" list instead of the LOGS board). Deliberately
# CONSERVATIVE — excludes ambiguous mid-workflow words like "complete"
# / "done" that are common non-final lane names ("Mitigation Complete")
# and would wrongly close open jobs.
_CLOSED_LIST_KEYWORDS = (
    "logs", "log -", "archive", "archived",
    "closed out", "close out", "closeout", "closed",
    "paid", "invoiced", "billed out",
)


def card_is_closed(card, *, list_name=None):
    """True when a card represents a CLOSED job — via ANY of the close
    workflows a franchise might use: moved to the AR board or the LOGS
    board, archived (Trello `closed`), or sitting in a clearly-terminal
    lane. The lane check needs `list_name` (resolve via
    get_list(card['idList'])); it's skipped when not supplied."""
    if not card:
        return False
    if card.get("closed"):                     # archived
        return True
    logs_id = get_logs_board_id()
    if logs_id and card.get("idBoard") == logs_id:   # on LOGS board
        return True
    ar_id = get_ar_board_id()
    if ar_id and card.get("idBoard") == ar_id:       # on AR board
        return True
    if list_name:
        ln = str(list_name).lower()
        if any(kw in ln for kw in _CLOSED_LIST_KEYWORDS):
            return True
    return False


def _closed_via_archive_only(card, *, list_name=None):
    """True when the ONLY thing closing this card is a Trello archive
    (``card['closed']``) — it is NOT on the LOGS or AR board and NOT in a
    terminal/closeout lane.

    The franchise archives a still-live card to KILL a job (homeowner
    bailed, wrong territory, duplicate), so an archive-in-place is a dead
    job → Incomplete. A card that instead reached the LOGS board, the AR
    board, or a "Closed out" / "Logs" / "Paid" lane finished cleanly →
    Completed. Returns False for any non-archived card, so the distinction
    is "archived where it sat" vs "logged/archived as done"."""
    if not card or not card.get("closed"):
        return False
    logs_id = get_logs_board_id()
    if logs_id and card.get("idBoard") == logs_id:
        return False
    ar_id = get_ar_board_id()
    if ar_id and card.get("idBoard") == ar_id:
        return False
    if list_name:
        ln = str(list_name).lower()
        if any(kw in ln for kw in _CLOSED_LIST_KEYWORDS):
            return False
    return True


def card_route_status(card, *, comments_text=None, list_name=None):
    """Decide where a card belongs in the Snapshots workbook.

    Returns one of "completed" | "incomplete" | "new_loss".

    A card is "closed" when `card_is_closed` is True (LOGS board OR
    archived OR a terminal lane name). An open card → "new_loss". A
    closed card → "incomplete" if a cancel/comp/declined LABEL or
    closeout COMMENT marker is present.

    A card that is closed ONLY because it was archived where it sat — not
    on the LOGS/AR board, not in a closeout/logs/paid lane — is treated as
    a DEAD job → "incomplete" (`_closed_via_archive_only`). A card that
    reached the LOGS board or a terminal lane finished cleanly →
    "completed". This is what keeps archived recon cards out of Completed
    while preserving logged/paid ones there.

    Caller may pre-fetch comments via `get_all_comments` and pass the
    joined text in for more reliable coverage on long-running cards.
    When `comments_text` is None, the card's bundled `actions` list is
    scanned (last-50 only). `list_name` (the card's lane) lets the
    terminal-lane close path fire.
    """
    if not card:
        return "new_loss"
    if not card_is_closed(card, list_name=list_name):
        return "new_loss"

    # Label-based markers — catches franchises that close cards by
    # adding a "Cancelled" / "Comp" / "Declined" label instead of (or
    # in addition to) leaving a closeout comment.
    for lab in card.get("labels") or []:
        nm = ""
        if isinstance(lab, dict):
            nm = (lab.get("name") or "").lower()
        elif isinstance(lab, str):
            nm = lab.lower()
        if nm and any(kw in nm for kw in _INCOMPLETE_LABEL_KEYWORDS):
            return "incomplete"

    if comments_text is None:
        actions = card.get("actions") or []
        comments_text = "\n".join(
            (a.get("data", {}).get("text") or "")
            for a in actions if a.get("type") == "commentCard"
        )
    blob = (comments_text or "").lower()
    if any(m in blob for m in _INCOMPLETE_COMMENT_MARKERS):
        return "incomplete"
    # Archived where it sat (no LOGS/AR board, no terminal lane) = the job
    # was killed, not logged → Incomplete. Logged/paid cards fall through.
    if _closed_via_archive_only(card, list_name=list_name):
        return "incomplete"
    return "completed"


def card_creation_date(card_id):
    """Return the card's creation datetime, or None.

    Trello card ids are Mongo ObjectIds — the first 4 bytes (8 hex
    chars) encode the creation Unix timestamp. No API call needed.
    """
    if not card_id or len(card_id) < 8:
        return None
    try:
        import datetime as _dt
        ts = int(card_id[:8], 16)
        return _dt.datetime.fromtimestamp(ts)
    except (ValueError, OSError):
        return None


_DATE_RECEIVED_PATTERNS = (
    "%m/%d/%Y", "%m/%d/%y",
    "%-m/%-d/%Y", "%-m/%-d/%y",
    "%m-%d-%Y", "%m-%d-%y",
    "%Y-%m-%d",
)


def _parse_us_date(s):
    """Parse a user-typed US-style date out of a card desc field.
    Accepts m/d/yyyy, mm/dd/yyyy, mm-dd-yyyy, yyyy-mm-dd. Returns a
    naive datetime so it round-trips with openpyxl cells."""
    if not s:
        return None
    s = s.strip().split()[0] if s.strip() else ""
    if not s:
        return None
    import datetime as _dt
    # Manual split avoids strptime's strict zero-padding requirement,
    # which would reject "3/01/2026" but accept "03/01/2026".
    if "/" in s or "-" in s:
        sep = "/" if "/" in s else "-"
        parts = s.split(sep)
        if len(parts) == 3:
            try:
                a, b, c = (int(p) for p in parts)
            except ValueError:
                return None
            if a > 31:           # yyyy-mm-dd
                y, m, d = a, b, c
            else:                # mm/dd/yyyy or mm/dd/yy
                m, d, y = a, b, c
                if y < 100:
                    y += 2000 if y < 70 else 1900
            try:
                return _dt.datetime(y, m, d)
            except ValueError:
                return None
    return None


def card_folder_search_terms(card):
    """Return an ordered list of name-string candidates that audit_logic's
    folder resolver can try when the run-doc client name didn't match a
    job folder.

    The cards on this team's boards expose three signals that often
    differ from the run-doc form of the client name — any of them can
    be the actual file-system filing name:

      • CUSTOMER INFORMATION → CUSTOMER NAME / NAME / INSURED
        (commercial jobs file under property name; residential under the
        insured's name — the run-doc sometimes carries one and the
        folder carries the other)
      • CUSTOMER INFORMATION → ADDRESS, PROPERTY ADDRESS
        (some commercial properties file by street, e.g. "1416 Avila Dr")
      • The card NAME itself, after stripping trailing date / claim
        suffixes (audit row already tries the desc-stripped form, but
        cards drag through "Smith, John - 5/9/26" variants that the
        plain name lookup doesn't reach)

    Returned terms are deduped (case-insensitive) and ordered most-
    specific first so the resolver locks onto a unique match early.
    Empty input → []."""
    if not card:
        return []
    terms = []
    seen = set()

    def _push(s):
        if not s:
            return
        s = str(s).strip()
        if not s:
            return
        # Drop trailing parens / pipe-comments / em-dash suffixes the
        # filer sometimes appends ("Smith, John (95823)" → "Smith, John").
        s = _re.sub(r'\s*[\(\|].*$', '', s).strip()
        s = _re.sub(r'\s+-\s+\d.*$', '', s).strip()
        if not s:
            return
        k = s.lower()
        if k in seen:
            return
        seen.add(k)
        terms.append(s)

    # Card name first — even though the run-doc's name didn't resolve,
    # the Trello card's name format (often "Last, First") sometimes does.
    _push(card.get("name"))

    try:
        fields = parse_card_desc(card.get("desc"))
    except Exception:
        fields = {}

    cust = fields.get("CUSTOMER INFORMATION") or {}
    for k in ("CUSTOMER NAME", "INSURED", "NAME",
              "PROPERTY NAME", "BUSINESS NAME"):
        _push(cust.get(k))

    # Address is high-value for commercial / address-filed jobs. Use the
    # first two address tokens ("1416 Avila") as a separate term — the
    # full address rarely matches a folder name verbatim, but the street
    # number + street name prefix usually does.
    for k in ("ADDRESS", "PROPERTY ADDRESS", "LOSS ADDRESS"):
        addr = (cust.get(k) or "").strip()
        if not addr:
            continue
        _push(addr)
        parts = addr.split()
        if len(parts) >= 2:
            _push(" ".join(parts[:2]))
            _push(" ".join(parts[:3]))

    pd = fields.get("PROPERTY DETAILS") or {}
    for k in ("PROPERTY NAME", "BUSINESS NAME", "PROPERTY ADDRESS"):
        _push(pd.get(k))

    return terms


def card_received_date(card):
    """Pull "Date Received" from the card desc's PROPERTY DETAILS
    section. Returns a datetime or None when the field is blank /
    unparseable. Callers should fall back to `card_creation_date`
    only when this returns None — the desc value is what the user
    typed and is the source of truth."""
    if not card:
        return None
    try:
        fields = parse_card_desc(card.get("desc"))
    except Exception:
        return None
    pd = fields.get("PROPERTY DETAILS") or {}
    return _parse_us_date(pd.get("DATE RECEIVED"))


_logs_list_ids_cache = None


def _logs_list_ids():
    """Return the set of list ids that live on the LOGS - EMS board.
    Cached per-process. Used by `card_closing_date` to detect the
    most recent move INTO the closed-jobs board."""
    global _logs_list_ids_cache
    if _logs_list_ids_cache is not None:
        return _logs_list_ids_cache
    bid = get_logs_board_id()
    if not bid:
        _logs_list_ids_cache = set()
        return _logs_list_ids_cache
    try:
        lists = _call(f"/boards/{bid}/lists", params={"fields": "id"}) or []
        _logs_list_ids_cache = {l.get("id") for l in lists if l.get("id")}
    except Exception:
        _logs_list_ids_cache = set()
    return _logs_list_ids_cache


def card_closing_date(card_id):
    """When did the card most recently land on the LOGS - EMS board?

    Only the LOGS - EMS move counts as "closed" for the spreadsheet —
    archive/closed flags don't, per user (2026-05-07): "only jobs in
    the logs are closed". Returns None when the card never moved
    there; callers leave the Closing Date cell blank.
    """
    if not card_id:
        return None
    logs_lists = _logs_list_ids()
    if not logs_lists:
        return None
    try:
        actions = _call(
            f"/cards/{card_id}/actions",
            params={"filter": "updateCard:idList", "limit": "50"}) or []
    except Exception:
        return None
    import datetime as _dt
    for a in actions:
        list_after = (a.get("data") or {}).get("listAfter") or {}
        if list_after.get("id") in logs_lists:
            iso = a.get("date") or ""
            try:
                return _dt.datetime.fromisoformat(
                    iso.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                continue
    return None


# Templates for the audit-row 💬 button. Keys match substring fragments
# from the audit's form_issues / photo_issues strings (case-insensitive).
# First match wins, so list more-specific keys first. Falls back to a
# generic "missing X" message for anything not matched.
_AUDIT_COMMENT_TEMPLATES = [
    ("atp",          "ATP not in file — please upload to OD."),
    ("cif",          "CIF not in file — please upload to OD."),
    ("cer",          "CER not in file — please upload to OD."),
    ("cos",          "COS not in file — please upload to OD."),
    ("scope",        "Scope not yet uploaded to OD — please upload."),
    ("docusketch",   "Docusketch not yet imported — please request / upload."),
    ("initial photo report",
                     "Initial Photo Report not uploaded to OD — please upload."),
    ("initial pic",  "Initial photos not yet uploaded to OD — please upload."),
    ("initial photo","Initial photos not yet uploaded to OD — please upload."),
    ("demo pic",     "Demo photos not yet uploaded to OD — please upload."),
    ("demo photo",   "Demo photos not yet uploaded to OD — please upload."),
    ("final pic",    "Final photos not yet uploaded to OD — please upload."),
    ("final photo",  "Final photos not yet uploaded to OD — please upload."),
    ("post pic",     "Post photos not yet uploaded to OD — please upload."),
    ("post photo",   "Post photos not yet uploaded to OD — please upload."),
    ("mold prep",    "Mold Prep photos not yet uploaded to OD — please upload."),
    ("contents",     "Contents photos not yet uploaded to OD — please upload."),
    ("equipment",    "Equipment photos not yet uploaded to OD — please upload."),
    ("reinspect",    "Reinspection photos not yet uploaded to OD — please upload."),
    ("sketch",       "Sketch not yet uploaded to OD — please upload."),
]


def audit_finding_comment_template(issue_text):
    """Return a templated Trello comment for an audit-row issue string
    (e.g. "ATP missing", "Demo pics missing"). User can edit the result
    before posting. Falls back to a generic "Missing: {text}" form so
    every audit row has *some* default."""
    s = (issue_text or "").strip()
    if not s:
        return ""
    low = s.lower()
    for needle, template in _AUDIT_COMMENT_TEMPLATES:
        if needle in low:
            return template
    # Strip a trailing " missing" the audit may have appended so the
    # generic fallback reads cleanly.
    base = _re.sub(r"\s*missing\s*$", "", s, flags=_re.IGNORECASE).strip() or s
    return f"Missing: {base} — please upload to OD."


def create_card(list_id, name, *, desc="", pos="bottom"):
    """Create a new card in `list_id` with the given `name`. Optionally
    pass `desc` to seed the description. Returns the created card dict
    (with `id`, `shortUrl`, etc.) on success, or None on failure.

    Used by the IUQ when a row was added manually for a job that
    doesn't have a Trello card yet — one click and the card appears
    in the right lane, ready for the rest of the audit flow."""
    if not list_id or not (name or "").strip():
        return None
    params = {"idList": list_id, "name": name.strip(), "pos": pos}
    if desc and desc.strip():
        params["desc"] = desc.strip()
    return _call("/cards", method="POST", data=params)


def post_comment(card_id, text):
    """Post `text` as a new comment on the card. The author is whichever
    user owns the trello_token in their config. Returns the created
    action dict (so callers can show "posted as <name>") or None on failure.

    Failures log to ems.log so fire-and-forget callers (scheduled
    escalation notes, docusign reminders, etc.) leave a trail when
    Trello refuses the write — the silent-failure path used to be
    completely invisible."""
    if not card_id or not (text or "").strip():
        return None
    try:
        return _call(f"/cards/{card_id}/actions/comments",
                     method="POST", data={"text": text})
    except Exception as ex:
        try:
            import ems_log
            preview = (text or "").strip().splitlines()[0][:80]
            ems_log.warn("trello_client",
                          f"post_comment failed card={card_id} "
                          f"preview={preview!r}: {ex}")
        except Exception:
            pass
        return None


def attach_file(card_id, file_path, *, name=None, mime=None):
    """Upload `file_path` as an attachment on the card.

    Trello's attachment endpoint requires multipart/form-data — our
    standard `_call` only does form-urlencoded, so this helper builds
    the multipart body inline (stdlib only — no `requests` dependency).
    Returns the attachment dict (id, url, etc.) or None on failure.

    `name` overrides the file name visible on Trello (defaults to the
    basename). `mime` overrides the content-type (defaults to
    application/octet-stream for unknown extensions; .pdf → application/pdf)."""
    import os as _os
    import mimetypes as _mt
    import uuid as _uuid
    if not card_id or not file_path or not _os.path.isfile(file_path):
        return None
    key, token = _creds()
    fname = name or _os.path.basename(file_path)
    if not mime:
        mime, _ = _mt.guess_type(fname)
        mime = mime or "application/octet-stream"
    with open(file_path, "rb") as fh:
        payload = fh.read()
    boundary = f"----EMS{_uuid.uuid4().hex}"

    def _field(name, value):
        return (f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n").encode("utf-8")

    file_header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; '
        f'filename="{fname}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8")
    body = (
        _field("key", key) + _field("token", token) + _field("name", fname)
        + file_header + payload + f"\r\n--{boundary}--\r\n".encode("utf-8"))

    url = f"{API_BASE}/cards/{card_id}/attachments"
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "User-Agent": _USER_AGENT,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        })
    try:
        # Attachment uploads can take a few seconds for large PDFs —
        # generous timeout vs the 15s default on _call (which assumes
        # tiny JSON payloads).
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
    except Exception as ex:
        try:
            import ems_log
            ems_log.warn("trello_client",
                          f"attach_file failed card={card_id} "
                          f"name={fname!r}: {ex}")
        except Exception:
            pass
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def get_member_me():
    """Return the authenticated user's Trello profile (id, fullName,
    username). Used to display "Posting as <name>" in the composer so
    the user knows whose token they're using before they hit send."""
    try:
        return _call("/members/me",
                     params={"fields": "id,fullName,username"})
    except Exception:
        return None


# ── Attachment download (pull photos off a card) ───────────────────────────
# Counterpart to attach_file: techs attach inspection photos straight to the
# Trello card, so this lets the import flows pull them down — organized by
# WHO uploaded them and WHEN — instead of routing through a WC zip export.

_TC_IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp",
    ".bmp", ".tif", ".tiff", ".gif",
}
_TC_INVALID_FN = _re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MEMBER_NAME_CACHE: dict[str, str] = {}


def _tc_sanitize(name, *, fallback):
    """Strip characters Windows forbids in file/folder names."""
    cleaned = _TC_INVALID_FN.sub("_", (name or "").strip()).rstrip(". ")
    return cleaned or fallback


def _is_image_attachment(att):
    """True for uploaded image attachments (skips external URL links and
    non-image uploads like PDFs)."""
    if not att or not att.get("isUpload"):
        return False
    mime = (att.get("mimeType") or "").lower()
    if mime.startswith("image/"):
        return True
    name = att.get("fileName") or att.get("name") or att.get("url") or ""
    import os as _os
    ext = _os.path.splitext(name.split("?")[0])[1].lower()
    return ext in _TC_IMAGE_EXTS


def card_attachments(card_id, *, image_only=False):
    """Return a card's attachments with the full field set needed to
    download + label them (id, name, fileName, url, date, isUpload,
    mimeType, idMember, bytes). When `image_only`, keep only uploaded
    image attachments. Empty list on error / no card."""
    if not card_id:
        return []
    try:
        raw = _call(f"/cards/{card_id}/attachments", params={
            "fields": ("id,name,fileName,url,date,isUpload,"
                       "mimeType,idMember,bytes"),
        }) or []
    except Exception:
        return []
    if image_only:
        raw = [a for a in raw if _is_image_attachment(a)]
    return raw


def _attachment_uploaders(card_id):
    """Map {attachment_id: uploader_full_name} from addAttachmentToCard
    actions (paged past the 50-per-request cap). The action's
    memberCreator is the most reliable uploader source — attachment
    `idMember` is sometimes null on older items."""
    out: dict[str, str] = {}
    before = None
    for _ in range(20):
        params = {"filter": "addAttachmentToCard", "limit": "50"}
        if before:
            params["before"] = before
        try:
            page = _call(f"/cards/{card_id}/actions", params=params) or []
        except Exception:
            break
        if not page:
            break
        for act in page:
            att = (act.get("data") or {}).get("attachment") or {}
            aid = att.get("id")
            mc = act.get("memberCreator") or {}
            who = mc.get("fullName") or mc.get("username") or ""
            if aid and who and aid not in out:
                out[aid] = who
        if len(page) < 50:
            break
        before = page[-1].get("id")
    return out


def _member_name(member_id):
    """Resolve a member id to a full name (cached). Fallback uploader
    source when the action feed didn't cover an attachment."""
    if not member_id:
        return ""
    if member_id in _MEMBER_NAME_CACHE:
        return _MEMBER_NAME_CACHE[member_id]
    name = ""
    try:
        m = _call(f"/members/{member_id}",
                  params={"fields": "fullName,username"})
        if m:
            name = m.get("fullName") or m.get("username") or ""
    except Exception:
        name = ""
    _MEMBER_NAME_CACHE[member_id] = name
    return name


def _download_attachment(att, dest_path):
    """Download one uploaded attachment to `dest_path`. Trello requires
    the OAuth Authorization header (not query-param key/token) for the
    /download/ URL of uploaded files — without it the URL 401s."""
    url = att.get("url")
    if not url:
        return False
    key, token = _creds()
    req = urllib.request.Request(url, headers={
        "User-Agent": _USER_AGENT,
        "Authorization": (f'OAuth oauth_consumer_key="{key}", '
                          f'oauth_token="{token}"'),
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    with open(dest_path, "wb") as fh:
        fh.write(data)
    return True


def download_card_photos(card_id, dest_dir, *,
                          group_by_uploader_date=True, image_only=True):
    """Download uploaded photo attachments from a Trello card into
    `dest_dir`, organized into "<Uploader> <MM-DD-YYYY>" subfolders by
    who uploaded each photo and when it was uploaded.

    Set `group_by_uploader_date=False` to drop everything flat into
    `dest_dir` instead. `image_only=False` pulls every uploaded file
    (PDFs, docs) too.

    Returns {ok, downloaded, skipped, folders, errors[, note]}.
    Collision-safe: a name clash inside a folder gets a " (N)" suffix.
    """
    import os as _os
    from datetime import datetime as _dtm
    if not card_id:
        return {"ok": False, "error": "no card_id", "downloaded": 0}
    atts = card_attachments(card_id, image_only=image_only)
    if not atts:
        return {"ok": True, "downloaded": 0, "skipped": 0, "folders": [],
                "errors": [], "note": "no photo attachments on card"}
    uploaders = _attachment_uploaders(card_id)
    try:
        _os.makedirs(dest_dir, exist_ok=True)
    except OSError as ex:
        return {"ok": False, "error": str(ex), "downloaded": 0}

    downloaded = 0
    errors: list[str] = []
    folders: set[str] = set()
    for att in atts:
        aid = att.get("id") or ""
        who = (uploaders.get(aid) or _member_name(att.get("idMember"))
               or "Unknown")
        raw_date = att.get("date") or ""
        if raw_date:
            try:
                date_str = _dtm.strptime(
                    raw_date[:10], "%Y-%m-%d").strftime("%m-%d-%Y")
            except Exception:
                date_str = raw_date[:10] or "no-date"
        else:
            date_str = "no-date"

        if group_by_uploader_date:
            sub = _tc_sanitize(f"{who} {date_str}", fallback="Unknown")
            target_dir = _os.path.join(dest_dir, sub)
        else:
            target_dir = dest_dir
        try:
            _os.makedirs(target_dir, exist_ok=True)
        except OSError as ex:
            errors.append(f"{who}/{date_str}: {ex}")
            continue
        folders.add(target_dir)

        fname = _tc_sanitize(
            att.get("fileName") or att.get("name") or f"{aid}.jpg",
            fallback=f"{aid or 'photo'}.jpg")
        stem, ext = _os.path.splitext(fname)
        if not ext:
            mime = (att.get("mimeType") or "").lower()
            ext = ("." + mime.split("/")[-1]) if "/" in mime else ".jpg"
            fname = stem + ext
        dst = _os.path.join(target_dir, fname)
        n = 2
        while _os.path.exists(dst):
            dst = _os.path.join(target_dir, f"{stem} ({n}){ext}")
            n += 1
        try:
            if _download_attachment(att, dst):
                downloaded += 1
            else:
                errors.append(f"{fname}: no download url")
        except Exception as ex:
            errors.append(f"{fname}: {ex}")

    return {"ok": True, "downloaded": downloaded,
            "skipped": len(atts) - downloaded,
            "folders": sorted(folders), "errors": errors}


# ── Description parser ─────────────────────────────────────────────────────
# Card desc on this team's boards follows a strict template:
#
#     **CUSTOMER INFORMATION**
#     Customer Name: Antonio Vargas Garcia
#     Address: 2146 Marigold Ct San Jacinto 92582
#     ...
#     ---
#     **INSURANCE INFORMATION**
#     Insurance Company: Farmers
#     Claim Number: 7010107128-1
#     ...
#
# So a "section header in **bold** + `Key: Value` lines" parser handles every
# real card without regex gymnastics. Empty values stay empty (so the UI can
# decide whether to render the row).

_SECTION_RE = _re.compile(r"^\*\*([^*]+)\*\*\s*$")
_KV_RE      = _re.compile(r"^([A-Za-z][^:]{0,40}):\s*(.*)$")


def parse_card_desc(desc):
    """Return {section_name: {field_name: value}} for the templated card desc.
    Section names + field names are stripped + uppercased to keep callers
    from caring about whitespace drift between cards."""
    if not desc:
        return {}
    out = {}
    cur_section = None
    for raw_line in desc.splitlines():
        line = raw_line.strip()
        if not line or line == "---":
            continue
        m = _SECTION_RE.match(line)
        if m:
            cur_section = m.group(1).strip().upper()
            out.setdefault(cur_section, {})
            continue
        if cur_section is None:
            continue
        m = _KV_RE.match(line)
        if not m:
            continue
        key = m.group(1).strip().upper()
        val = m.group(2).strip()
        # Strip Trello markdown link syntax: [label](url "tooltip") → url
        # Adjuster emails and links arrive wrapped this way; the URL is
        # what we want for click-out, the label is just a display alias.
        link_m = _re.match(r"\[([^\]]+)\]\((\S+?)(?:\s+\"[^\"]*\")?\)", val)
        if link_m:
            val = link_m.group(2)
        # Email fields come back as "mailto:foo@bar.com" — strip the
        # scheme so the rendered field shows just the address.
        if val.startswith("mailto:"):
            val = val[len("mailto:"):]
        out[cur_section][key] = val
    return out


# ── Activity-feed formatter ────────────────────────────────────────────────
# Renders the card as plain text in the same `Author · Date` header format
# job_notes_gui already styles via _RENDERED_HEADER_RE. Output sections:
#
#   Lane / labels / members header
#   Description (verbatim)
#   Checklist summary (compact, one line per checklist with done/total)
#   --- horizontal break ---
#   Activity actions, newest first (comments + lane moves + attachments)

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _fmt_action_date(iso):
    """Trello returns ISO-8601 UTC ('2026-05-05T18:18:18.113Z'). We only
    need the wall-clock format the existing message-card regex expects,
    so a manual parse beats pulling in dateutil for one timezone shift.
    UTC → local conversion uses the user's system tz."""
    if not iso:
        return ""
    try:
        # Strip fractional seconds + Z, parse as naive UTC, shift to local.
        from datetime import datetime, timezone
        s = iso.split(".")[0].rstrip("Z")
        dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc).astimezone()
        ampm = "AM" if dt.hour < 12 else "PM"
        hour12 = dt.hour % 12 or 12
        return (f"{_MONTHS[dt.month-1]} {dt.day}, {dt.year}, "
                f"{hour12}:{dt.minute:02d} {ampm}")
    except Exception:
        return iso[:19]


def _format_action(a):
    """Single action → one rendered block (header line + body), or None
    when the action type isn't worth surfacing (member changes etc.)."""
    typ  = a.get("type")
    who  = ((a.get("memberCreator") or {}).get("fullName")
            or "Unknown")
    when = _fmt_action_date(a.get("date", ""))
    data = a.get("data", {})
    header = f"{who} · {when}"
    if typ == "commentCard":
        body = (data.get("text") or "").strip()
        return f"{header}\n{body}"
    if typ == "updateCard":
        # Lane moves ("Moved card: A → B") are auto-generated when a
        # card crosses lanes; they pile up on long-running jobs and
        # bury real comments. The card's CURRENT lane is already
        # surfaced in the activity-feed header, so the historical
        # trail of moves doesn't add value to job notes.
        if "listAfter" in data:
            return None
        if "closed" in (data.get("old") or {}):
            now_closed = ((data.get("card") or {}).get("closed", False))
            return (f"{header}\n"
                    f"{'Closed (archived)' if now_closed else 'Reopened'} the card")
        return None
    # Attachment-add and member add/remove actions are auto-generated
    # housekeeping noise — they bury real comments and lane moves under
    # rows like "Attached: IMG_9087.jpeg" and "Added Victoria to the
    # card". Attachments are still available via the card payload's
    # `attachments` field for callers that need them; member roster is
    # available via `members`. The activity feed stays focused on
    # things humans typed or decided.
    if typ in ("addAttachmentToCard",
               "addMemberToCard",
               "removeMemberFromCard"):
        return None
    return None


# Compact "Job Info" header shown at the top of the activity feed.
# Pulls the highest-signal fields out of the templated desc so users see
# carrier/claim/adjuster/links at a glance without scrolling. Each entry
# is (label_in_output, section_in_desc, key_in_section). Empty values
# are skipped — the feed stays terse on cards that haven't been filled
# in yet.
_JOB_INFO_FIELDS = [
    ("Carrier",         "INSURANCE INFORMATION", "INSURANCE COMPANY"),
    ("Claim #",         "INSURANCE INFORMATION", "CLAIM NUMBER"),
    ("Adjuster",        "INSURANCE INFORMATION", "ADJUSTER NAME"),
    ("Adjuster phone",  "INSURANCE INFORMATION", "ADJUSTER NUMBER"),
    ("Adjuster email",  "INSURANCE INFORMATION", "ADJUSTER EMAIL"),
    ("Date of loss",    "PROPERTY DETAILS",      "DATE OF LOSS"),
    ("Cause of loss",   "PROPERTY DETAILS",      "CAUSE OF LOSS"),
    ("Address",         "CUSTOMER INFORMATION",  "ADDRESS"),
    ("Phone",           "CUSTOMER INFORMATION",  "PHONE NUMBER"),
    ("DocuSketch",      "LINKS",                 "DOCUSKETCH LINK"),
    ("XactAnalysis",    "LINKS",                 "XACTANALYSIS LINK"),
    ("Initial video",   "LINKS",                 "INITIAL VIDEO LINK"),
    ("Post video",      "LINKS",                 "POST VIDEO LINK"),
]


def _format_job_info(card):
    """Render the compact 'Job Info' block from parsed desc fields.
    Empty desc, no matching template sections, or every field empty →
    returns '' so callers know to skip."""
    fields = parse_card_desc(card.get("desc"))
    if not fields:
        return ""
    rows = []
    for label, sec, key in _JOB_INFO_FIELDS:
        v = (fields.get(sec) or {}).get(key, "").strip()
        if v:
            rows.append(f"**{label}:** {v}")
    if not rows:
        return ""
    return "**JOB INFO**\n\n" + "\n".join(rows)


def checklist_progress(card) -> tuple[int, int]:
    """Return (done_count, total_count) across ALL checklists on a card.
    Used by the audit / IUQ rows to render a one-glance ✓ X/Y chip
    so the user can tell a half-finished card from a complete one
    without opening Trello.

    `card` is a Trello card dict with `checklists` already inlined
    (use `cards_in_list_with_checklists` or `get_card` with the
    `checklists=all` query). Returns (0, 0) when no checklists exist
    — caller renders nothing in that case.
    """
    lists = card.get("checklists") or []
    done = total = 0
    for cl in lists:
        for it in (cl.get("checkItems") or []):
            total += 1
            if it.get("state") == "complete":
                done += 1
    return done, total


def _format_checklists(card):
    """Compact 'Checklists' block: one line per checklist with done/total
    plus the items so the audit/APA wire-up can reference them at a glance.
    Indented under each list so the desc-section parser doesn't misread it."""
    lists = card.get("checklists") or []
    if not lists:
        return ""
    rows = ["**CHECKLISTS**"]
    for cl in lists:
        items = cl.get("checkItems") or []
        done = sum(1 for it in items if it.get("state") == "complete")
        rows.append(f"  [{cl.get('name', '?')}]  ({done}/{len(items)})")
        for it in items:
            mark = "✓" if it.get("state") == "complete" else "·"
            rows.append(f"     {mark} {(it.get('name') or '').strip()}")
    return "\n".join(rows)


def format_multi_card_feed(cards, *, lane_name_lookup=None):
    """Render multiple linked cards as one buffer.

    `cards` is a list of card dicts (output of get_card). When the list
    has length 1, output matches `format_activity_feed(cards[0], ...)`
    so the styling pass (info_header / msg_header tags) doesn't have to
    care about cardinality.

    For 2+ cards, each card gets its own info section with a
    `**CARD: <name> [board · lane]**` header so the user can tell which
    pinned card the lane / labels / desc fields came from. Activity
    actions from every card are merged into a single newest-first
    stream, with each block prefixed by the source board so a comment
    on AR Board doesn't look identical to a comment on WIP.

    `lane_name_lookup(board_id, list_id) -> str` is optional; when
    omitted, lane names default to '' (caller can resolve and pass in
    via get_lane_name)."""
    cards = [c for c in (cards or []) if c]
    if not cards:
        return ""

    def _lane(c):
        if lane_name_lookup is None:
            return ""
        try:
            return lane_name_lookup(c.get("idBoard"), c.get("idList")) or ""
        except Exception:
            return ""

    if len(cards) == 1:
        return format_activity_feed(cards[0], lane_name=_lane(cards[0]))

    parts = []
    # Per-card structured blocks first (lane/labels/members + JOB INFO +
    # checklists). Each block starts with a banner naming the card so the
    # user can tell which pinned source the data belongs to.
    all_actions = []
    for c in cards:
        lane = _lane(c)
        # Card identity banner — uses the same `**HEADER**` markup the
        # info_header tag picks up so the multi-card view still gets the
        # amber-card styling per source.
        banner_bits = [c.get("name", "(unnamed card)")]
        if lane:
            banner_bits.append(f"lane: {lane}")
        banner = "**CARD: " + "  ·  ".join(banner_bits) + "**"

        meta_lines = []
        labels = [(l.get("name") or "").strip()
                  for l in (c.get("labels") or [])]
        labels = [l for l in labels if l]
        if labels:
            meta_lines.append(f"**Labels:** {', '.join(labels)}")
        members = [(m.get("fullName") or "").strip()
                   for m in (c.get("members") or [])]
        members = [m for m in members if m]
        if members:
            meta_lines.append(f"**Members:** {', '.join(members)}")
        due = c.get("due")
        if due:
            marker = "✓ done" if c.get("dueComplete") else ""
            meta_lines.append(
                f"**Due:** {_fmt_action_date(due)}  {marker}".rstrip())

        info_block = _format_job_info(c)
        notes = parse_card_desc(c.get("desc")).get("NOTES", {})
        note_lines = [f"**{k.title()}:** {v}" for k, v in notes.items() if v]
        cl_block = _format_checklists(c)

        sub_parts = [banner]
        if meta_lines:
            sub_parts.append("\n".join(meta_lines))
        if info_block:
            sub_parts.append(info_block)
        if note_lines:
            sub_parts.append("\n".join(note_lines))
        if cl_block:
            sub_parts.append(cl_block)
        parts.append("\n\n".join(sub_parts))

        # Tag each action with the originating board name so the merged
        # stream is unambiguous. Sort key is the raw ISO date string,
        # which sorts correctly lex order for a single source format.
        board_label = c.get("name", "?")
        for a in (c.get("actions") or []):
            block = _format_action(a)
            if not block:
                continue
            # Inject "[board name]" between the header line and body so
            # the user sees the source attribution but the existing
            # `Author · Date` regex (msg_header tag) still matches the
            # first line cleanly.
            head, _, rest = block.partition("\n")
            tagged = f"{head}  ·  [{board_label}]\n{rest}" if rest else head
            all_actions.append((a.get("date", ""), tagged))

    if all_actions:
        all_actions.sort(key=lambda x: x[0], reverse=True)
        rendered = [b for _, b in all_actions]
        parts.append("**ACTIVITY**\n\n" + "\n\n".join(rendered))

    return "\n\n---\n\n".join(parts)


def format_activity_feed(card, *, lane_name=""):
    """Plain-text rendering job_notes_gui pastes into its Text widget.
    Headers use 'Author · Date' so the existing message-card tagging
    picks them up without any new regex.

    `lane_name` is passed in (not derived) because the caller already
    has the boards/lists cache from list_boards()/find_cards_by_name —
    re-fetching it per refresh would double the polling cost."""
    if not card:
        return ""
    parts = []

    # Top metadata block — lane, labels, members. Simple bullet rows
    # so a glance answers "where is this card?" without scrolling.
    meta = []
    if lane_name:
        meta.append(f"**Lane:** {lane_name}")
    labels = [(l.get("name") or "").strip()
              for l in (card.get("labels") or [])]
    labels = [l for l in labels if l]
    if labels:
        meta.append(f"**Labels:** {', '.join(labels)}")
    members = [(m.get("fullName") or "").strip()
               for m in (card.get("members") or [])]
    members = [m for m in members if m]
    if members:
        meta.append(f"**Members:** {', '.join(members)}")
    due = card.get("due")
    if due:
        marker = "✓ done" if card.get("dueComplete") else ""
        meta.append(f"**Due:** {_fmt_action_date(due)}  {marker}".rstrip())
    if meta:
        parts.append("\n".join(meta))

    info_block = _format_job_info(card)
    if info_block:
        parts.append(info_block)

    # Free-form notes fields from the desc — separate from the structured
    # Job Info block above so empty templated fields stay hidden but any
    # actual hand-typed notes still surface.
    notes = parse_card_desc(card.get("desc")).get("NOTES", {})
    note_lines = [f"**{k.title()}:** {v}" for k, v in notes.items() if v]
    if note_lines:
        parts.append("\n".join(note_lines))

    cl_block = _format_checklists(card)
    if cl_block:
        parts.append(cl_block)

    # Activity feed — newest first, drop unrenderable action types.
    actions = card.get("actions") or []
    rendered = []
    for a in actions:
        block = _format_action(a)
        if block:
            rendered.append(block)
    if rendered:
        parts.append("**ACTIVITY**\n\n" + "\n\n".join(rendered))

    return "\n\n---\n\n".join(parts)


# ── CLI smoke test ──────────────────────────────────────────────────────────
def _cli(argv):
    if not argv:
        print("Usage:")
        print("  python trello_client.py boards            # list configured boards")
        print("  python trello_client.py search <query>    # search cards by name")
        return 1
    cmd = argv[0]
    try:
        if cmd == "boards":
            boards = list_boards()
            if not boards:
                print("No boards found (check trello_workspace_id in config).")
                return 1
            for b in boards:
                print(f"  {b['shortLink']:12s}  {b['name']}")
            return 0
        if cmd == "search":
            if len(argv) < 2:
                print("Usage: python trello_client.py search <query>")
                return 1
            query = " ".join(argv[1:])
            results = find_cards_by_name(query)
            if not results:
                print(f"No matches for {query!r}")
                return 0
            for r in results:
                lane = f"  [{r['list_name']}]" if r["list_name"] else ""
                print(f"[{r['board']}]{lane}")
                print(f"  {r['name']}")
                print(f"  {r['url']}")
                print()
            return 0
        print(f"Unknown command: {cmd}")
        return 2
    except RuntimeError as ex:
        print(f"ERROR: {ex}")
        return 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
