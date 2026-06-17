"""Job Notes — Pywebview panel (backend data tool).

Hidden from launcher nav by default (`_PANELS_HIDDEN_BY_DEFAULT`).
Kept as a backend data source for the timeline + expected-files
hover popover that other panels (audit, snapshot) render via
`job_notes_gui.build_hover_popover` through `attach_rich_tooltip`.
"""
from __future__ import annotations
import os, sys, datetime
import webview

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path: sys.path.insert(0, _HERE)

import job_notes_logic as jn

ASSETS_DIR = os.path.join(_HERE, "job_notes_web_assets")
INDEX_HTML = os.path.join(ASSETS_DIR, "index.html")


class Api:
    def __init__(self): self._window = None
    def attach(self, w): self._window = w

    def list_notes(self):
        try:
            rows = jn.list_saved_notes() or []
        except Exception:
            rows = []
        return [{
            "year":   r[0],
            "client": r[1],
            "mtime":  datetime.datetime.fromtimestamp(r[2]).strftime("%Y-%m-%d %H:%M") if r[2] else "",
            "mtime_epoch": float(r[2] or 0),
        } for r in rows]

    def load_note(self, year, client):
        try:
            return {"ok": True, "text": jn.load_note(year, client) or ""}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def find_any_note(self, client):
        """Cross-year lookup — returns the newest note for `client`."""
        try:
            res = jn.find_any_note_for_client(client)
            if res is None:
                return {"found": False}
            year, text = res
            return {"found": True, "year": year, "text": text}
        except Exception:
            return {"found": False}

    # ── P2: Compose + write note ────────────────────────────────────
    def save_note(self, year, client, text):
        """Save the note text to `<NOTES_ROOT>/<year>/<client>.md`."""
        if not client:
            return {"ok": False, "error": "client required"}
        try:
            year = year or str(datetime.date.today().year)
            path = jn.save_note(year, client, text or "")
            return {"ok": True, "path": path}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def post_note_to_trello(self, client, text):
        """Post the note text as a Trello comment on the client's pinned
        card. Mirrors the Tk Job Notes 'Post to Trello' button."""
        if not client or not text:
            return {"ok": False, "error": "client + text required"}
        try:
            import persistence as _per
            card_id = _per.get_trello_card_id(client) or ""
        except Exception:
            card_id = ""
        if not card_id:
            return {"ok": False,
                    "error": f"{client} has no Trello pin"}
        try:
            import trello_client as tc
            tc.post_comment(card_id, text)
            return {"ok": True, "card_id": card_id}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── Multi-card tab metadata (mirrors Tk _rebuild_trello_tabs) ───
    def list_pinned_cards_meta(self, client: str) -> list:
        """Return one entry per linked Trello card with the metadata
        the tab strip needs: card_id, name, board, lane, archived,
        last_activity. Empty list when 0–1 cards are pinned (the
        frontend hides the tab strip in that case)."""
        if not client:
            return []
        try:
            import persistence as _per
            import trello_client as tc
            ids = list(_per.get_trello_card_ids(client) or [])
            out = []
            for cid in ids:
                try:
                    card = tc.get_card(cid)
                except Exception:
                    continue
                if not card:
                    continue
                lane = ""
                try:
                    lane = tc.get_lane_name(card.get("idBoard"),
                                             card.get("idList")) or ""
                except Exception:
                    pass
                board_name = ""
                try:
                    for b in (tc.list_boards() or []):
                        if b.get("id") == card.get("idBoard"):
                            board_name = b.get("name") or ""
                            break
                except Exception:
                    pass
                out.append({
                    "card_id":       cid,
                    "name":          card.get("name") or "",
                    "board":         board_name,
                    "lane":          lane,
                    "archived":      bool(card.get("closed")),
                    "last_activity": card.get("dateLastActivity") or "",
                })
            return out
        except Exception:
            return []

    # ── Refresh-from-Trello (mirrors Tk job_notes_gui.py:2155) ──────
    # Re-fetches a card + returns the formatted activity feed so the
    # web Job Notes panel can show the live comment stream without
    # the user manually pasting / reloading. Used by the ↻ Refresh
    # button + the 60s auto-refresh tick.
    def refresh_trello_feed(self, card_id: str):
        """Pull card + format activity feed. Returns
        {ok, text, lane, last_activity, archived}."""
        if not card_id:
            return {"ok": False, "error": "no card_id"}
        try:
            import trello_client as tc
            card = tc.get_card(card_id)
            if not card:
                return {"ok": False, "error": "card not found"}
            lane = ""
            try:
                lane = tc.get_lane_name(card.get("idBoard"), card.get("idList")) or ""
            except Exception:
                pass
            text = ""
            try:
                text = tc.format_activity_feed(card, lane_name=lane) or ""
            except Exception as ex:
                return {"ok": False, "error": f"format failed: {ex}"}
            return {"ok": True,
                    "text": text,
                    "lane": lane,
                    "last_activity": card.get("dateLastActivity") or "",
                    "archived": bool(card.get("closed")),
                    "name": card.get("name") or ""}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def post_trello_comment(self, card_id, text):
        """Post an arbitrary comment to a specific Trello card. Mirrors
        Tk job_notes_gui.py:2014 _open_compose_dialog → tc.post_comment.
        Different from post_note_to_trello (which posts the entire note
        body to the client's pinned card) — this one posts an arbitrary
        text to a specific card_id, supporting the multi-card case
        where a client is linked to 2+ cards."""
        if not card_id or not text or not text.strip():
            return {"ok": False, "error": "card_id + text required"}
        try:
            import trello_client as tc
            result = tc.post_comment(card_id, text.strip())
            if not result:
                return {"ok": False, "error": "Trello post returned no result"}
            return {"ok": True, "card_id": card_id}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def open_trello_for(self, client):
        if not client:
            return False
        try:
            import persistence as _per, webbrowser as _wb
            cid = _per.get_trello_card_id(client) or ""
            if not cid:
                return False
            _wb.open(f"https://trello.com/c/{cid}")
            return True
        except Exception:
            return False

    # ── Pin Trello card (mirrors Tk job_notes_gui.py:2130 _pin_to_trello) ──
    def search_trello_cards(self, query: str):
        """Fuzzy-search Trello cards by name. Returns a flat list of
        {card_id, name, lane, board} dicts for the pin picker."""
        if not query or len(query.strip()) < 2:
            return []
        try:
            import trello_client as tc
            hits = tc.find_cards_by_name(query.strip()) or []
            return [{
                "card_id": h.get("card_id") or h.get("id") or "",
                "name":    h.get("name") or "",
                "lane":    h.get("list_name") or h.get("lane") or "",
                "board":   h.get("board") or h.get("board_name") or "",
                "url":     h.get("url") or h.get("shortUrl") or "",
            } for h in hits[:20]]
        except Exception:
            return []

    def get_pinned_card_ids(self, client: str):
        """Return ALL pinned card_ids for `client` (multi-card support).
        Used by the Pin dialog to show the current pin list + the
        compose modal's tab strip."""
        if not client:
            return []
        try:
            import persistence as _per
            return list(_per.get_trello_card_ids(client) or [])
        except Exception:
            return []

    def set_pinned_card_ids(self, client: str, card_ids):
        """Persist a new pin set. Empty list clears. Mirrors Tk's
        job_widgets.open_trello_pin_dialog save."""
        if not client:
            return {"ok": False, "error": "no client"}
        try:
            import persistence as _per
            ids = [c.strip() for c in (card_ids or []) if c and c.strip()]
            _per.set_trello_card_ids(client, ids)
            return {"ok": True, "card_ids": ids}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    def get_pinned_card_for_item(self, client):
        """Return the pinned Trello card id for `client`. Used by the
        shared trello_hover.js helper from inside the Job Notes iframe."""
        if not client:
            return {"card_id": "", "url": ""}
        try:
            import persistence as _per
            cid = _per.get_trello_card_id(client) or ""
            return {"card_id": cid,
                    "url": f"https://trello.com/c/{cid}" if cid else ""}
        except Exception:
            return {"card_id": "", "url": ""}

    def open_notes_folder(self):
        """Open the notes folder in Explorer."""
        try:
            os.startfile(getattr(jn, "_NOTES_ROOT", "."))
            return True
        except Exception:
            return False

    def open_in_notepad(self, year, client):
        """Open the saved note in Notepad for power editing."""
        try:
            path = jn._notes_path(year, client)
            if not os.path.isfile(path): return False
            import subprocess
            subprocess.Popen(["notepad.exe", path])
            return True
        except Exception:
            return False

    # ── Tk parity: timeline + expected files + Trello-paste cleaner ─
    def parse_timeline(self, text):
        """Scan note text for canonical job stages — same parser the
        Tk panel uses for its left-rail timeline. Returns a list of
        stage labels in canonical order."""
        try:
            return list(jn.parse_stages(text or "") or [])
        except Exception:
            return []

    def expected_files_for(self, text):
        """Union of expected-file labels at or after every detected
        stage in the note. Drives the 'Expected files' card."""
        try:
            stages = jn.parse_stages(text or "") or []
            return list(jn.expected_files(stages) or [])
        except Exception:
            return []

    def all_stages(self):
        """Full canonical stage list (used by the timeline render so
        every stage shows, with detected ones highlighted)."""
        try:
            return [s[0] for s in jn.STAGES]
        except Exception:
            return []

    def clean_trello_paste(self, text):
        """Run a raw Trello copy-paste blob through the Tk panel's
        comment-block normalizer — converts "•/Reply/Add link" lines,
        relative timestamps, and run-together author headers into a
        clean newest-first comment list."""
        if not text:
            return {"ok": True, "text": ""}
        try:
            cleaned = jn.clean_trello_paste(text) or ""
            return {"ok": True, "text": cleaned}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "text": text}

    # ── Tk parity: aliases for cross-name lookup ─────────────────────
    def get_aliases(self, client):
        """Return the persisted alias list for a client (alternate
        names that Job-Notes lookups will also try)."""
        if not client:
            return []
        try:
            import persistence as _per
            return list(_per.get_search_aliases(client) or [])
        except Exception:
            return []

    def set_aliases(self, client, aliases):
        """Replace the alias list for a client."""
        if not client:
            return {"ok": False, "error": "client required"}
        try:
            import persistence as _per
            cleaned = [a.strip() for a in (aliases or []) if a and a.strip()]
            _per.set_search_aliases(client, cleaned)
            return {"ok": True, "aliases": cleaned}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}


def main(argv=None):
    api = Api()
    win = webview.create_window(
        title="Job Notes — EMS Tools (web)",
        url=INDEX_HTML, js_api=api,
        width=1200, height=820, min_size=(720, 500))
    api.attach(win)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
