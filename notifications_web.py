"""Trello Notifications — Pywebview panel.

Pulls the EMS Admin's Trello notifications (`GET /members/me/notifications`)
into the app so they're accessible + organized without leaving for Trello's
bell. Grouped BY BOARD, unread-first, click a row to open the card, and
mark-read writes back to Trello so the real bell clears too.

Launch:
    python notifications_web.py
    # or via the home shell — sidebar "🔔 Notifications"

Bridge: every public method on `Api` is callable from JS as
`await pywebview.api.method_name(...)`. Returns are JSON-serializable.
"""
from __future__ import annotations

import os
import sys
import webbrowser

import webview

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

ASSETS_DIR = os.path.join(_HERE, "notifications_web_assets")
INDEX_HTML = os.path.join(ASSETS_DIR, "index.html")

# Trello notification type → (emoji, short label) for the UI. Unknown
# types fall back to a generic bell + the raw type string.
_TYPE_META = {
    "mentionedOnCard":      ("📣", "Mention"),
    "commentCard":          ("💬", "Comment"),
    "changeCard":           ("✏", "Card change"),
    "addedToCard":          ("➕", "Added to card"),
    "removedFromCard":      ("➖", "Removed from card"),
    "cardDueSoon":          ("⏰", "Due soon"),
    "addedToBoard":         ("📋", "Added to board"),
    "addAdminToBoard":      ("🛡", "Made board admin"),
    "makeAdminOfBoard":     ("🛡", "Made board admin"),
    "addedAttachmentToCard": ("📎", "Attachment"),
    "reactionAdded":        ("🙂", "Reaction"),
    "addedMemberToCard":    ("👤", "Member added"),
}


def _shape(n):
    """Flatten one raw Trello notification into the fields the UI needs."""
    n = n or {}
    data = n.get("data") or {}
    card = data.get("card") or {}
    board = data.get("board") or {}
    list_ = data.get("list") or data.get("listAfter") or {}
    creator = n.get("memberCreator") or {}
    ntype = n.get("type") or ""
    emoji, label = _TYPE_META.get(ntype, ("🔔", ntype or "Notification"))
    # The human-readable body varies by type: a comment/mention carries
    # data.text; a card change carries the field that moved.
    snippet = (data.get("text") or "").strip()
    if not snippet and ntype == "changeCard":
        la = data.get("listAfter") or {}
        lb = data.get("listBefore") or {}
        if la or lb:
            snippet = f"moved {lb.get('name','?')} → {la.get('name','?')}"
    short = card.get("shortLink") or card.get("id") or ""
    return {
        "id":        n.get("id") or "",
        "type":      ntype,
        "icon":      emoji,
        "type_label": label,
        "unread":    bool(n.get("unread")),
        "date":      n.get("date") or "",
        "card_name": card.get("name") or "",
        "card_short": short,
        "card_url":  f"https://trello.com/c/{short}" if short else "",
        "board":     board.get("name") or "",
        "list":      list_.get("name") or "",
        "snippet":   snippet,
        "by":        creator.get("fullName") or creator.get("username") or "",
    }


class Api:
    """Methods exposed to JS via `pywebview.api`."""

    def __init__(self):
        self._window = None

    def attach(self, window):
        self._window = window

    # ── Feed ─────────────────────────────────────────────────────────
    def list_notifications(self, only_unread: bool = False,
                           limit: int = 60) -> dict:
        """Return notifications grouped BY BOARD, unread groups first.

        Each group: {board, items:[shaped], unread, total}. Items inside
        a group are unread-first then newest-first. `only_unread` limits
        to unread. Returns {ok, groups, total, unread}.
        """
        try:
            import trello_client as tc
            raw = tc.list_notifications(limit=limit,
                                        only_unread=bool(only_unread))
        except Exception as ex:
            return {"ok": False, "error": str(ex), "groups": [],
                    "total": 0, "unread": 0}
        groups: dict = {}
        for n in raw:
            it = _shape(n)
            key = it["board"] or "(no board)"
            groups.setdefault(key, []).append(it)
        out = []
        for board, items in groups.items():
            # Unread-first, then newest-first within the board.
            items.sort(key=lambda i: (0 if i["unread"] else 1,
                                      "" if not i["date"] else i["date"]),
                       reverse=False)
            items.sort(key=lambda i: i["date"], reverse=True)
            items.sort(key=lambda i: 0 if i["unread"] else 1)
            unread = sum(1 for i in items if i["unread"])
            out.append({"board": board, "items": items,
                        "unread": unread, "total": len(items)})
        # Boards with unread float to the top; then by most-recent item.
        out.sort(key=lambda g: (0 if g["unread"] else 1,
                                g["items"][0]["date"] if g["items"] else ""),
                 reverse=False)
        out.sort(key=lambda g: g["items"][0]["date"] if g["items"] else "",
                 reverse=True)
        out.sort(key=lambda g: 0 if g["unread"] else 1)
        total_unread = sum(g["unread"] for g in out)
        return {"ok": True, "groups": out, "total": len(raw),
                "unread": total_unread}

    def unread_count(self) -> dict:
        """Cheap unread count for the sidebar badge."""
        try:
            import trello_client as tc
            return {"ok": True, "count": tc.unread_notification_count()}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "count": 0}

    # ── Actions ──────────────────────────────────────────────────────
    def mark_read(self, notification_id: str, read: bool = True) -> dict:
        try:
            import trello_client as tc
            ok = tc.mark_notification_read(notification_id, read=bool(read))
            return {"ok": bool(ok)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def mark_all_read(self) -> dict:
        try:
            import trello_client as tc
            ok = tc.mark_all_notifications_read()
            return {"ok": bool(ok)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def open_url(self, url: str) -> bool:
        if not url:
            return False
        try:
            webbrowser.open(url)
            return True
        except Exception:
            return False


def main(argv=None):
    api = Api()
    window = webview.create_window(
        title="Trello Notifications — Linguar Hub",
        url=INDEX_HTML,
        js_api=api,
        width=1100, height=820,
        min_size=(640, 480),
    )
    api.attach(window)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
