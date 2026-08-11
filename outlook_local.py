"""Local Outlook reader via Windows COM.

Uses the already-authenticated Outlook desktop session — no Azure app,
no admin consent, no Graph tokens. This module is the live backend for
the suite's email features (`xa_email_ingest`, `adjuster_monitor`,
`trello_hygiene`). A Graph-API variant once lived alongside this one
but was archived after IT declined to approve the Azure app registration.

Requires:
- `pywin32` (`pip install pywin32`)
- Outlook desktop installed and running on this machine

Limitations:
- Outlook must be RUNNING when the scan fires. If it's closed the COM
  Dispatch will start a new instance silently, but for shared / cached
  mailboxes the data may not be fully synced.
- COM is single-threaded — calls block on Outlook itself, so a large
  scan competes with whatever the user is doing in the UI.
- Windows-only (pywin32 isn't available on Mac / Linux).
"""
from __future__ import annotations

import datetime as _dt
import sys


# Outlook OlObjectClass.olMail = 43; we filter to mail items only so
# meeting requests, calendar invites, and read receipts don't leak into
# the message list (they raise AttributeError on .SenderEmailAddress).
_OL_MAIL_CLASS = 43
# OlDefaultFolders constants we route through.
_OL_FOLDERS = {
    "inbox":      6,   # olFolderInbox
    "sent":       5,   # olFolderSentMail
    "drafts":    16,   # olFolderDrafts
    "outbox":     4,   # olFolderOutbox
    "junk":      23,   # olFolderJunk
    "deleted":    3,   # olFolderDeletedItems
}


_APP = None


def _outlook_app():
    """Connect to (or start) the Outlook desktop COM server. Caches the
    Application object on the module for re-use across scans."""
    global _APP
    if _APP is not None:
        return _APP
    import win32com.client
    _APP = win32com.client.Dispatch("Outlook.Application")
    return _APP


def _resolve_folder(folder: str):
    """Return the Outlook MAPI folder for `folder`. `folder` can be a
    well-known key ('inbox', 'sent', etc.) or a slash-separated path
    relative to the default mailbox ('Inbox/EMS', 'Inbox/Carriers/AAA').
    """
    app = _outlook_app()
    ns = app.GetNamespace("MAPI")
    key = (folder or "inbox").strip().lower()
    if key in _OL_FOLDERS:
        return ns.GetDefaultFolder(_OL_FOLDERS[key])
    # Fall back to path navigation: split on / and walk Folders.
    parts = [p for p in folder.split("/") if p.strip()]
    if not parts:
        return ns.GetDefaultFolder(_OL_FOLDERS["inbox"])
    # Try starting from default Inbox (most common case for sub-folders),
    # else from the root of the first store.
    base = ns.GetDefaultFolder(_OL_FOLDERS["inbox"])
    if parts[0].lower() == "inbox":
        parts = parts[1:]
    for p in parts:
        try:
            base = base.Folders(p)
        except Exception:
            raise RuntimeError(f"Outlook folder not found: {folder}")
    return base


def _normalize_dt(d) -> _dt.datetime | None:
    """Coerce pywin32's datetime (often tz-aware via pywintypes) to a
    naive UTC-naive datetime so it can be compared against the caller's
    naive `since` parameter without TypeError."""
    if d is None:
        return None
    try:
        if hasattr(d, "tzinfo") and d.tzinfo is not None:
            # pywintypes datetime → convert to UTC, then drop tz.
            return d.astimezone(_dt.timezone.utc).replace(tzinfo=None)
        return _dt.datetime(d.year, d.month, d.day,
                            d.hour, d.minute, d.second)
    except Exception:
        return None


def _safe_get(obj, attr, default=""):
    try:
        v = getattr(obj, attr)
    except Exception:
        return default
    return v if v is not None else default


def _recipients(item) -> list[dict]:
    """Convert the Recipients collection to the Graph-shaped list. Type
    on a Recipient: 1 = To, 2 = CC, 3 = BCC. We return only To here so
    the carrier-detection logic in xa_email_ingest doesn't get confused
    by ems@ being a CC on every outbound."""
    out: list[dict] = []
    try:
        recips = item.Recipients
        # COM collections are 1-indexed.
        for i in range(1, recips.Count + 1):
            r = recips.Item(i)
            try:
                t = int(_safe_get(r, "Type", 1))
            except (TypeError, ValueError):
                t = 1
            if t != 1:
                continue   # skip CC/BCC for the To-list
            addr = _safe_get(r, "Address", "")
            # Exchange addresses come as DN format ("/o=ExchLabs/...")
            # — try the SMTP resolver to get the actual email.
            if addr and not addr.startswith(""):
                pass
            # AddressEntry.GetExchangeUser().PrimarySmtpAddress for
            # Exchange recipients; falls back to .Address for SMTP.
            try:
                ae = r.AddressEntry
                if ae is not None:
                    eu = None
                    try:
                        eu = ae.GetExchangeUser()
                    except Exception:
                        eu = None
                    if eu is not None:
                        smtp = _safe_get(eu, "PrimarySmtpAddress", "")
                        if smtp:
                            addr = smtp
            except Exception:
                pass
            name = _safe_get(r, "Name", "") or addr
            out.append({"emailAddress": {"address": addr, "name": name}})
    except Exception:
        pass
    return out


def _sender(item) -> dict:
    """Sender as Graph-shaped {emailAddress: {address, name}}."""
    addr = _safe_get(item, "SenderEmailAddress", "")
    name = _safe_get(item, "SenderName", "") or addr
    # Same Exchange-DN issue as recipients — translate via Sender.
    try:
        s = item.Sender
        if s is not None:
            try:
                eu = s.GetExchangeUser()
            except Exception:
                eu = None
            if eu is not None:
                smtp = _safe_get(eu, "PrimarySmtpAddress", "")
                if smtp:
                    addr = smtp
    except Exception:
        pass
    return {"emailAddress": {"address": addr, "name": name}}


def _body_preview(item, limit: int = 255) -> str:
    """First `limit` characters of the body, newlines flattened.
    `limit=0` means the whole thing.

    255 matches Graph's bodyPreview and is the right default for display
    — but it is not enough to READ a machine-generated mail. A DocuSketch
    delivery notice spends its first ~250 characters on tracking URLs and
    only then reaches "Project name <the job>", so a caller that parses
    bodies has to ask for more. See `list_recent_messages(body_limit=)`.
    """
    body = _safe_get(item, "Body", "") or ""
    body = body.replace("\r\n", " ").replace("\n", " ").strip()
    return body[:limit] if limit else body


def _entry_id(item) -> str:
    return _safe_get(item, "EntryID", "")


def _to_dict(item, body_limit: int = 255) -> dict:
    """One MailItem → Graph-shaped message dict."""
    received = _normalize_dt(_safe_get(item, "ReceivedTime", None))
    received_iso = (received.isoformat(timespec="seconds") + "Z"
                    if received is not None else "")
    return {
        "id":               _entry_id(item),
        "subject":          _safe_get(item, "Subject", "") or "",
        "from":             _sender(item),
        "toRecipients":     _recipients(item),
        "receivedDateTime": received_iso,
        "bodyPreview":      _body_preview(item, body_limit),
        "hasAttachments":   bool(_safe_get(item, "Attachments", None)
                                  and item.Attachments.Count > 0),
        # webLink is a Graph-only field. COM can't generate one, but we
        # can hand the EntryID through the `outlook:` URL scheme so the
        # GUI's "Open email" button still works (Outlook handles it).
        "webLink":          (f"outlook:{_entry_id(item)}"
                             if _entry_id(item) else ""),
    }


# ── Public API ──────────────────────────────────────────────────────────────

def list_recent_messages(*, folder: str = "inbox",
                          since: _dt.datetime | None = None,
                          top: int = 50,
                          body_limit: int = 255) -> list[dict]:
    """Return up to `top` most-recent mail items from `folder`. `since`
    filters to items with ReceivedTime >= since (naive UTC). Output is
    sorted newest-first.

    Mirrors the Graph client's signature so consumers (xa_email_ingest,
    adjuster_monitor, trello_hygiene.scan_inbox_for_complaints) can
    switch backends transparently.
    """
    target = _resolve_folder(folder)
    items = target.Items
    try:
        items.Sort("[ReceivedTime]", True)   # descending
    except Exception:
        pass
    out: list[dict] = []
    # COM iterators on Items don't support len() reliably; iterate and
    # break once we've passed `since` or hit `top`.
    for item in items:
        try:
            cls = int(_safe_get(item, "Class", 0))
        except (TypeError, ValueError):
            cls = 0
        if cls != _OL_MAIL_CLASS:
            continue
        rt = _normalize_dt(_safe_get(item, "ReceivedTime", None))
        if rt is None:
            continue
        if since is not None and rt < since:
            # Items are sorted newest-first; once we cross the since
            # cutoff, everything below is also too old.
            break
        try:
            out.append(_to_dict(item, body_limit=body_limit))
        except Exception:
            # One bad item shouldn't poison the whole scan.
            continue
        if len(out) >= top:
            break
    return out


def get_message_body(message_id: str) -> str:
    """Return the message body as plain text. `message_id` is the
    Outlook EntryID returned by `list_recent_messages` under the `id`
    field. Returns "" on any failure (deleted item, expired session,
    invalid id) so the caller can degrade gracefully."""
    if not message_id:
        return ""
    try:
        ns = _outlook_app().GetNamespace("MAPI")
        item = ns.GetItemFromID(message_id)
    except Exception:
        return ""
    if item is None:
        return ""
    return _safe_get(item, "Body", "") or ""


# ── CLI smoke test ─────────────────────────────────────────────────────────

def _cli(argv: list[str]) -> int:
    if not argv:
        print("Usage:")
        print("  python outlook_local.py whoami")
        print("  python outlook_local.py recent [--days=1] [--top=20]")
        print("  python outlook_local.py body <entry_id>")
        return 1
    cmd = argv[0]
    if cmd == "whoami":
        try:
            ns = _outlook_app().GetNamespace("MAPI")
            user = ns.CurrentUser
            print(f"  {_safe_get(user, 'Name', '?')}")
            print(f"  address: {_safe_get(user, 'Address', '')}")
            return 0
        except Exception as ex:
            print(f"ERROR: {ex}")
            return 1
    if cmd == "recent":
        days, top = 1, 20
        for a in argv[1:]:
            if a.startswith("--days="):
                try: days = int(a.split("=", 1)[1])
                except ValueError: pass
            elif a.startswith("--top="):
                try: top = int(a.split("=", 1)[1])
                except ValueError: pass
        since = (_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
                 - _dt.timedelta(days=days))
        try:
            msgs = list_recent_messages(since=since, top=top)
        except Exception as ex:
            print(f"ERROR: {ex}")
            return 1
        if not msgs:
            print(f"(no messages in the last {days} day(s))")
            return 0
        for m in msgs:
            sender = ((m.get("from") or {}).get("emailAddress") or {}).get(
                "address", "")
            recv = (m.get("receivedDateTime") or "")[:16].replace("T", " ")
            subj = (m.get("subject") or "")[:80]
            print(f"  {recv}  {sender:30s}  {subj}")
        return 0
    if cmd == "body":
        if len(argv) < 2:
            print("Usage: python outlook_local.py body <entry_id>")
            return 1
        body = get_message_body(argv[1])
        print(body[:2000])
        return 0
    print(f"Unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
