"""Dev-only native board foundation. No provider IDs, credentials or live writes.

The SQLite transaction commits a board change and its activity together.
Revision checks reject stale editors instead of silently losing their work.
Local storage is deliberately NOT the future shared production repository.
"""
import datetime
import json
import os
from pathlib import Path
import sqlite3
import uuid
from contextlib import contextmanager


def _id():
    return str(uuid.uuid4())


def _text(value):
    value = str(value or "").strip()
    if not value or len(value) > 2000:
        raise ValueError("Enter text between 1 and 2,000 characters.")
    return value


class BoardStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS board (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)")
            initial = {"id": _id(), "name": "OneLoss test board", "revision": 0,
                       "lanes": [{"id": _id(), "name": n} for n in
                                 ["Incoming loss", "Inspection", "Work in progress", "Ready to bill"]],
                       "cards": [], "events": []}
            db.execute("INSERT OR IGNORE INTO board VALUES (1, ?)", (json.dumps(initial),))

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def read(self):
        with self._connect() as db:
            return json.loads(db.execute("SELECT data FROM board WHERE id=1").fetchone()[0])

    def change(self, revision, action, values):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = json.loads(db.execute("SELECT data FROM board WHERE id=1").fetchone()[0])
            if revision != state["revision"]:
                raise ValueError("The board changed. Refresh before trying again; your change was not saved.")
            card = next((c for c in state["cards"] if c["id"] == values.get("card_id")), None)
            lane = next((l for l in state["lanes"] if l["id"] == values.get("lane_id")), None)
            if action == "create":
                if not lane:
                    raise ValueError("Choose a current lane.")
                card = {"id": _id(), "job_id": None, "title": _text(values.get("text")),
                        "lane_id": lane["id"], "archived": False}
                state["cards"].append(card)
                detail = "Created in " + lane["name"]
            elif action == "lane":
                name = _text(values.get("text"))
                state["lanes"].append({"id": _id(), "name": name})
                detail = "Added lane: " + name
            elif action in {"move", "archive", "restore", "comment", "rename", "up"}:
                if not card:
                    raise ValueError("Card not found. Refresh the board.")
                if action == "move":
                    if not lane or card["archived"]:
                        raise ValueError("Restore the card and choose a current lane.")
                    previous = next(l["name"] for l in state["lanes"] if l["id"] == card["lane_id"])
                    card["lane_id"] = lane["id"]
                    state["cards"].remove(card)
                    state["cards"].append(card)
                    detail = previous + " → " + lane["name"]
                elif action in {"archive", "restore"}:
                    card["archived"] = action == "archive"
                    detail = "Archived" if card["archived"] else "Restored"
                elif action == "up":
                    peers = [c for c in state["cards"] if c["lane_id"] == card["lane_id"] and not c["archived"]]
                    if card["archived"] or peers.index(card) == 0:
                        raise ValueError("This card is already first or archived.")
                    before = peers[peers.index(card) - 1]
                    state["cards"].remove(card)
                    state["cards"].insert(state["cards"].index(before), card)
                    detail = "Moved up in lane"
                else:
                    detail = _text(values.get("text"))
                    if action == "rename":
                        card["title"] = detail
                        detail = "Renamed: " + detail
            else:
                raise ValueError("Unsupported board action.")
            state["events"].append({"id": _id(), "card_id": card["id"] if card else None,
                                    "type": action, "text": detail, "actor": "Local Dev tester",
                                    "at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
            state["revision"] += 1
            db.execute("UPDATE board SET data=? WHERE id=1", (json.dumps(state),))
            return state


class Api:
    def _store(self):
        if os.environ.get("LINGUAR_DEV_MODE", "").lower().strip() not in {"1", "true", "yes", "on"}:
            raise PermissionError("New boards are available only in Dev.")
        return BoardStore(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) /
                          "OneLoss" / "dev-lab" / "native-boards.sqlite3")

    def load(self):
        return self._store().read()

    def change(self, revision, action, values):
        return self._store().change(revision, action, values)
