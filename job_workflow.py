"""OneLoss-owned job commands and the transitional Trello outbox.

The UI commits to the application database first. Trello is a delivery
target: this module records the exact operation to mirror and the quiet sync
adapter acknowledges it later. Keeping that rule behind this small interface
prevents individual buttons from growing their own network/rollback behavior.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import paths


DB_PATH = str(Path(paths.DATA_DIR) / "job_workflow.sqlite3")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect():
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trello_outbox (
          operation_key TEXT PRIMARY KEY,
          operation_type TEXT NOT NULL,
          job_key TEXT NOT NULL,
          entry_id TEXT NOT NULL,
          card_id TEXT,
          comment_id TEXT,
          payload_json TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          attempts INTEGER NOT NULL DEFAULT 0,
          last_error TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          completed_at TEXT
        )
    """)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def queue_job_log(job_key: str, saved: dict, card_id: str, mirror_text: str) -> dict:
    """Queue an immutable optional new-entry post, never a linked edit."""
    entry_id = str(saved.get("entry_id") or "").strip()
    card_id = str(card_id or "").strip()
    comment_id = str(saved.get("trello_comment_id") or "").strip()
    if not entry_id or not card_id:
        return {"queued": False, "reason": "no linked Trello card"}
    if comment_id:
        return {"queued": False, "reason": "Already linked; comments are independent"}
    key = f"job-log:{entry_id}"
    now = _now()
    operation_type = "comment.create"
    with _connect() as conn:
        conn.execute("""
            INSERT INTO trello_outbox
              (operation_key,operation_type,job_key,entry_id,card_id,
               comment_id,payload_json,status,attempts,last_error,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,'pending',0,NULL,?,?)
            ON CONFLICT(operation_key) DO NOTHING
        """, (key, operation_type, job_key, entry_id, card_id,
              comment_id or None, json.dumps({"text": mirror_text}), now, now))
    return {"queued": True, "operation_key": key, "operation_type": operation_type}


def cancel_job_log_delivery(job_key: str, entry_id: str) -> None:
    """Retain the outbox record but stop unsent delivery of a deleted log."""
    with _connect() as conn:
        conn.execute("""UPDATE trello_outbox SET status='cancelled', updated_at=?
                        WHERE operation_key=? AND job_key=? AND status='pending'""",
                     (_now(), f"job-log:{entry_id}", job_key))


def queue_job_log_delete(job_key: str, entry_id: str, card_id: str,
                         comment_id: str) -> dict:
    """Cancel an unsent create, or queue deletion of its exact mirror."""
    key = f"job-log:{str(entry_id or '').strip()}"
    with _connect() as conn:
        prior = conn.execute(
            "SELECT operation_type,comment_id FROM trello_outbox WHERE operation_key=?",
            (key,)).fetchone()
        remote_id = str(comment_id or (prior["comment_id"] if prior else "") or "").strip()
        if not remote_id:
            conn.execute("DELETE FROM trello_outbox WHERE operation_key=?", (key,))
            return {"queued": False, "cancelled_unsent_create": bool(prior)}
        now = _now()
        conn.execute("""
            INSERT INTO trello_outbox
              (operation_key,operation_type,job_key,entry_id,card_id,
               comment_id,payload_json,status,attempts,last_error,created_at,updated_at)
            VALUES (?, 'comment.delete', ?, ?, ?, ?, '{}', 'pending', 0, NULL, ?, ?)
            ON CONFLICT(operation_key) DO UPDATE SET
              operation_type='comment.delete', job_key=excluded.job_key,
              card_id=excluded.card_id, comment_id=excluded.comment_id,
              payload_json='{}', status='pending', attempts=0, last_error=NULL,
              updated_at=excluded.updated_at, completed_at=NULL
        """, (key, job_key, entry_id, card_id or None, remote_id, now, now))
    return {"queued": True, "operation_key": key, "operation_type": "comment.delete"}


def pending(limit: int = 100) -> list[dict]:
    with _connect() as conn:
        # Retain old operations for inspection, but never execute mutations
        # created under the former linked-comment contract.
        conn.execute("""UPDATE trello_outbox SET status='held',
                     last_error='Legacy linked-comment mutation held for review'
                     WHERE status='pending' AND operation_type IN
                     ('comment.update','comment.delete')""")
        rows = conn.execute("""
            SELECT * FROM trello_outbox WHERE status='pending'
            ORDER BY created_at, operation_key LIMIT ?
        """, (max(1, min(int(limit or 100), 500)),)).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
        except ValueError:
            item["payload"] = {}
        out.append(item)
    return out


def acknowledge(operation_key: str, *, external_id: str = "") -> None:
    """Complete one operation and persist a newly-created Trello comment id."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM trello_outbox WHERE operation_key=?",
                           (operation_key,)).fetchone()
        if not row:
            return
        now = _now()
        conn.execute("""
            UPDATE trello_outbox SET status='complete', completed_at=?,
              updated_at=?, comment_id=COALESCE(NULLIF(?,''),comment_id), last_error=NULL
            WHERE operation_key=?
        """, (now, now, external_id, operation_key))
        job_key, entry_id = row["job_key"], row["entry_id"]
        operation_type = row["operation_type"]
    if external_id and operation_type == "comment.create":
        # Adapter acknowledgement; bypass the command interface so this
        # metadata patch cannot enqueue itself again.
        try:
            import ems_db
            current = next((item for item in ems_db.list_job_log_entries(job_key)
                            if item.get("entry_id") == entry_id), None)
            if current:
                ems_db.save_job_log_entry(
                    job_key, {**current, "trello_comment_id": external_id})
        except Exception:
            pass


def claim_delivery(operation_key: str) -> bool:
    """Only one worker may send; interrupted sends require reconciliation."""
    with _connect() as conn:
        cursor = conn.execute("""UPDATE trello_outbox SET status='sending',updated_at=?
            WHERE operation_key=? AND status='pending' AND operation_type='comment.create'""",
            (_now(), operation_key))
        return cursor.rowcount == 1


def fail(operation_key: str, error: str) -> None:
    with _connect() as conn:
        conn.execute("""
            UPDATE trello_outbox SET attempts=attempts+1,last_error=?,updated_at=?,
                status=CASE WHEN status='sending' THEN 'needs_review' ELSE status END
            WHERE operation_key=?
        """, (str(error or "Trello did not accept the operation"), _now(), operation_key))


def status() -> dict:
    with _connect() as conn:
        pending_count = conn.execute(
            "SELECT COUNT(*) FROM trello_outbox WHERE status='pending'").fetchone()[0]
        failed_count = conn.execute(
            "SELECT COUNT(*) FROM trello_outbox WHERE (status='pending' AND attempts>0) OR status IN ('needs_review','sending','held')").fetchone()[0]
    return {"pending": pending_count, "failed": failed_count}
