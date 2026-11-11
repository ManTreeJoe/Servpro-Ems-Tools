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
    emoji, label = _TYPE_META.get(ntype, ("🔔", "Job activity"))
    # The human-readable body varies by type: a comment/mention carries
    # data.text; a card change carries the field that moved.
    snippet = (data.get("text") or "").strip()
    if not snippet and ntype == "changeCard":
        la = data.get("listAfter") or {}
        lb = data.get("listBefore") or {}
        if la or lb:
            before, after = lb.get("name"), la.get("name")
            if before and after:
                snippet = f"Moved {before} → {after}"
            elif after:
                snippet = f"Moved to {after}"
            elif before:
                snippet = f"Moved from {before}"
            else:
                snippet = "Moved card"
        elif "closed" in (data.get("old") or {}) and isinstance(card.get("closed"), bool):
            snippet = "Archived card" if card["closed"] else "Unarchived card"
        elif data.get("boardAfter"):
            destination = data["boardAfter"].get("name")
            snippet = f"Moved to board {destination}" if destination else "Moved to another board"
        elif "due" in (data.get("old") or {}):
            snippet = f"Due date changed to {card['due']}" if card.get("due") else "Due date removed"
        elif "name" in (data.get("old") or {}):
            snippet = f"Renamed card to {card['name']}" if card.get("name") else "Renamed card"
        elif "desc" in (data.get("old") or {}):
            snippet = "Updated card description"
    if not snippet:
        snippet = {
            "commentCard": "Comment text unavailable. Open the card to check.",
            "mentionedOnCard": "Mention text unavailable. Open the card to check.",
            "changeCard": "Card updated — details unavailable. Open the card to check.",
        }.get(ntype, label)
    short = card.get("shortLink") or card.get("id") or ""
    return {
        "id":        n.get("id") or "",
        "type":      ntype,
        "is_move": bool(data.get("listBefore") or data.get("listAfter") or data.get("boardBefore") or data.get("boardAfter")),
        "icon":      emoji,
        "type_label": label,
        "unread":    bool(n.get("unread")),
        "date":      n.get("date") or "",
        "card_name": card.get("name") or "",
        "card_short": short,
        "card_id": card.get('id') or short,
        "comment_id": (n.get('idAction') or '') if ntype in ('commentCard','mentionedOnCard','reactionAdded') else '',
        "card_url":  f"https://trello.com/c/{short}" if short else "",
        "board":     board.get("name") or "",
        "list":      list_.get("name") or "",
        "snippet":   snippet,
        "by":        creator.get("fullName") or creator.get("username") or "",
    }


def _unread_identity(source, row):
    """Count one comment once only when both exact provider IDs agree."""
    if source == 'trello':
        card = ((row.get('data') or {}).get('card') or {}).get('id') or ''
        comment = row.get('idAction') or ''
        is_comment = row.get('type') in ('commentCard', 'mentionedOnCard')
    else:
        card = row.get('card_id') or ''
        comment = row.get('comment_id') or ''
        is_comment = row.get('kind') in ('comment', 'mention')
    if is_comment and card and comment:
        return ('comment', str(card).lower(), str(comment).lower())
    return (source, str(row.get('id') or ''))


class Api:
    """Methods exposed to JS via `pywebview.api`."""

    def __init__(self):
        self._window = None

    def attach(self, window):
        self._window = window

    def realtime_credentials(self):
        """Use the signed-in user's existing, RLS-protected live connection."""
        try:
            import schedule_store
            store = schedule_store.ScheduleStore()
            return {'ok': True, 'url': store.url, 'key': store.key,
                    'token': store.token, 'department': store.department, 'user': store.user}
        except Exception:
            return {'ok': False, 'error': 'Live updates unavailable; backup refresh active.'}

    # ── Feed ─────────────────────────────────────────────────────────
    def job_comment_reactions(self, card_id, action_id, code=None, active=None):
        """React without opening the card or changing notification read state."""
        from job_comment_reactions import reactions
        return reactions(card_id, action_id, code, active)

    def desktop_settings(self, mode=None, sound=None):
        import desktop_notifications
        return desktop_notifications.settings(mode, sound)

    def desktop_test(self):
        import desktop_notifications
        return desktop_notifications.test_notification()

    def desktop_open(self, token):
        import desktop_notifications
        return desktop_notifications.open_alert(token)

    def notification_job(self, card_id, comment_id=''):
        try:
            from notification_navigation import resolve_card
            result = resolve_card(card_id)
            import re
            result['commentId'] = comment_id if re.fullmatch(r'[0-9a-fA-F]{24}', str(comment_id or '')) else ''
            return result
        except ValueError as ex:
            return {'ok': False, 'error': str(ex)}
        except Exception:
            return {'ok': False, 'error': 'The job link could not be checked. Retry or open in Trello.'}

    def personal_inbox(self, filter_name='all', unread=False):
        import personal_notifications as pn
        import threading
        threading.Thread(target=pn.flush, daemon=True).start()
        result = pn.call('inbox', filter=filter_name, unread=bool(unread))
        result['pending_delivery'] = pn.pending_count()
        return result

    def personal_read(self, notification_id, read=True):
        from personal_notifications import call
        return call('read', id=notification_id, read=bool(read))

    def personal_mute(self, card_id, muted):
        from personal_notifications import call
        return call('mute', card_id=card_id, muted=bool(muted))

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
        except Exception:
            return {"ok": False, "error": "Trello notifications could not refresh. Check your connection and retry.", "groups": [],
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
        """Exact combined unread count, or unavailable if a source is incomplete."""
        try:
            import trello_client as tc
            import personal_notifications as pn
            trello = tc.list_all_unread_notifications()
            personal = pn.call('inbox', filter='all', unread=True)
            if not personal.get('ok'):
                return {'ok': False, 'count': None, 'error': 'OneLoss unread count unavailable.'}
            items = personal.get('items')
            if not isinstance(items, list):
                return {'ok': False, 'count': None, 'error': 'OneLoss unread count unavailable.'}
            # The existing service returns at most 100 rows and has no cursor.
            # Refuse to present a truncated count as an exact total.
            if len(items) >= 100:
                return {'ok': False, 'count': None, 'error': 'OneLoss unread count exceeds the verifiable page.'}
            if any(not isinstance(row, dict) or not row.get('id') for row in items):
                return {'ok': False, 'count': None, 'error': 'OneLoss unread count unavailable.'}
            identities = {_unread_identity('trello', row) for row in trello}
            identities.update(_unread_identity('personal', row) for row in items if not row.get('read_at'))
            return {'ok': True, 'count': len(identities)}
        except Exception:
            return {'ok': False, 'count': None, 'error': 'Unread count unavailable. Refresh to retry.'}

    # ── Actions ──────────────────────────────────────────────────────
    def mark_read(self, notification_id: str, read: bool = True) -> dict:
        try:
            import trello_client as tc
            ok = tc.mark_notification_read(notification_id, read=bool(read))
            return {"ok": bool(ok)}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def mark_card_read(self, card_id: str) -> dict:
        """Clear only this exact card, reporting incomplete provider results."""
        import re
        import trello_client as tc
        import personal_notifications as pn
        card = str(card_id or '').strip()
        if not re.fullmatch(r'[a-fA-F0-9]{24}', card):
            return {'ok': False, 'error': 'This card cannot be verified. Open it and refresh notifications.'}
        card = card.lower()
        failures = []
        try:
            rows = tc.list_all_unread_notifications()
            if not isinstance(rows, list):
                raise ValueError('incomplete response')
            for row in rows:
                raw_card = ((row.get('data') or {}).get('card') or {}).get('id', '')
                if str(raw_card).lower() == card:
                    if not row.get('id') or not tc.mark_notification_read(row['id'], read=True):
                        raise ValueError('read not confirmed')
        except Exception:
            failures.append('Trello')
        try:
            actor = (pn.sb.current_user() or {}).get('id')
            if not actor:
                raise ValueError('no signed-in user')
            result = pn.call('inbox', filter='all', unread=True)
            rows = result.get('items') if result.get('ok') else None
            # This endpoint has a 100-item limit and no cursor; an incomplete
            # page cannot prove we found every notification for the card.
            if not isinstance(rows, list) or len(rows) >= 100:
                raise ValueError('incomplete response')
            for row in rows:
                if (pn.sb.current_user() or {}).get('id') != actor:
                    raise ValueError('user changed')
                if not isinstance(row, dict):
                    raise ValueError('invalid response')
                if str(row.get('card_id') or '').lower() == card and not row.get('read_at'):
                    if not row.get('id') or not pn.call('read', id=row['id'], read=True).get('ok'):
                        raise ValueError('read not confirmed')
        except Exception:
            failures.append('OneLoss')
        if failures:
            return {'ok': False, 'error': ' and '.join(failures) + ' read status could not be fully confirmed. Refresh and retry.'}
        return {'ok': True}

    def mark_all_read(self) -> dict:
        try:
            import trello_client as tc
            ok = tc.mark_all_notifications_read()
            return {"ok": bool(ok)}
        except Exception as ex:
            # Never expose raw provider exceptions: their URLs may hold tokens.
            from urllib.error import HTTPError, URLError
            if isinstance(ex, HTTPError):
                guidance = {
                    401: 'Reconnect your Trello account, then retry.',
                    403: 'Your Trello connection does not have permission to mark notifications read. Reconnect with write access.',
                    429: 'Trello is rate-limiting requests. Wait a moment, then retry.',
                }.get(ex.code, 'Refresh notifications to check their state before retrying.')
                return {'ok': False, 'error': f'Trello returned HTTP {ex.code}. {guidance}'}
            if isinstance(ex, (URLError, TimeoutError)):
                return {'ok': False, 'error': 'Trello could not confirm the change. Check your connection and refresh notifications before retrying.'}
            return {'ok': False, 'error': 'The app could not confirm the read-status change. Check your Trello connection and refresh before retrying.'}

    def clear_all_sources(self) -> dict:
        """Explicit user action: mark all Trello and OneLoss notifications read."""
        import personal_notifications as pn
        trello = self.mark_all_read()
        try:
            personal = pn.clear_unread()
        except Exception:
            personal = {'ok': False, 'error': 'OneLoss read status could not be confirmed.'}
        return {'ok': bool(trello.get('ok') and personal.get('ok')),
                'trello': trello, 'personal': personal}

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
        title="Trello Notifications — OneLoss",
        url=INDEX_HTML,
        js_api=api,
        width=1100, height=820,
        min_size=(640, 480),
    )
    api.attach(window)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
