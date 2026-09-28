"""Review-gated XactAnalysis assignment-email intake.

Saved ``.eml`` messages become durable local drafts.  Importing is deliberately
side-effect free: no Loss, Trello card, folder, or CompanyCam project is created
until the existing New Loss screen is reviewed and its Create button is used.

The original RFC822 message is preserved under the app data directory.  Draft
metadata is stored separately so ordinary app logs never need to contain PII.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

import paths
from new_loss_intake import parse_assignment_email


_ROOT = Path(paths.data("xa_assignment_intake"))
_MESSAGES = _ROOT / "messages"
_INDEX = _ROOT / "drafts.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _html_to_text(value: str) -> str:
    value = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value,
                   flags=re.I | re.S)
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"</(?:p|div|tr|li|h\d|td)>", "\n", value, flags=re.I)
    value = html.unescape(re.sub(r"<[^>]+>", " ", value))
    lines = [re.sub(r"\s+", " ", line).strip()
             for line in value.replace("\r", "").splitlines()]
    return "\n".join(line for line in lines if line)


def _message_text(message) -> str:
    plain: list[str] = []
    rich: list[str] = []
    parts = message.walk() if message.is_multipart() else (message,)
    for part in parts:
        if part.get_content_disposition() == "attachment":
            continue
        try:
            content = part.get_content()
        except Exception:
            continue
        if not isinstance(content, str):
            continue
        if part.get_content_type() == "text/plain":
            plain.append(content)
        elif part.get_content_type() == "text/html":
            rich.append(_html_to_text(content))
    return "\n".join(plain or rich)


def _canon(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _read_index() -> dict[str, dict[str, Any]]:
    try:
        value = json.loads(_INDEX.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_index(value: dict[str, dict[str, Any]]) -> None:
    _ROOT.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="drafts-", suffix=".json",
                                    dir=str(_ROOT))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, _INDEX)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _match_keys(fields: dict[str, Any]) -> dict[str, str]:
    xa = _canon(fields.get("xa_id"))
    claim = _canon(fields.get("claim_number"))
    address = _canon(fields.get("address"))
    return {
        "exact_assignment": f"xa:{xa}" if xa else "",
        "claim_property": (f"claim:{claim}|property:{address}"
                           if claim and address else ""),
        "claim": f"claim:{claim}" if claim else "",
        "property": f"property:{address}" if address else "",
    }


def _public(draft: dict[str, Any]) -> dict[str, Any]:
    """Return the UI-safe draft shape (never the stored body or local path)."""
    return {
        "id": draft.get("id", ""),
        "status": draft.get("status", "needs_review"),
        "source": {
            "file_name": (draft.get("source") or {}).get("file_name", ""),
            "subject": (draft.get("source") or {}).get("subject", ""),
            "received": (draft.get("source") or {}).get("received", ""),
            "sender": (draft.get("source") or {}).get("sender", ""),
            "attachment_names": (draft.get("source") or {}).get(
                "attachment_names", []),
        },
        "fields": dict(draft.get("fields") or {}),
        "warnings": list(draft.get("warnings") or []),
        "match": dict(draft.get("match") or {}),
        "created_at": draft.get("created_at", ""),
        "approved_at": draft.get("approved_at"),
        "result": dict(draft.get("result") or {}),
    }


def ingest_eml(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Create or return one review draft from a saved RFC822 message."""
    source = Path(path)
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    draft_id = digest[:20]
    message = BytesParser(policy=policy.default).parsebytes(raw)
    body = _message_text(message)
    fields = parse_assignment_email(body)
    attachments = [name for part in message.iter_attachments()
                   if (name := part.get_filename())]

    warnings: list[str] = []
    sender = str(message.get("from", ""))
    if not any(host in sender.lower()
               for host in ("xactware", "xactanalysis", "verisk")):
        warnings.append("Sender is not a recognized XA/Verisk address; verify it.")
    for key, label in (("insured_name", "customer name"),
                       ("address", "property address"),
                       ("claim_number", "claim number"),
                       ("xa_id", "XA ID")):
        if not fields.get(key):
            warnings.append(f"Missing {label}.")

    index = _read_index()
    existing = index.get(draft_id)
    if existing:
        return {"ok": True, "created": False, "draft": _public(existing)}

    match = _match_keys(fields)
    related: list[dict[str, str]] = []
    for other in index.values():
        other_match = other.get("match") or {}
        relation = ""
        if match["exact_assignment"] and (
                match["exact_assignment"] == other_match.get("exact_assignment")):
            relation = "same_xa_assignment"
        elif match["claim_property"] and (
                match["claim_property"] == other_match.get("claim_property")):
            relation = "same_claim_and_property"
        elif match["claim"] and match["claim"] == other_match.get("claim"):
            relation = "same_claim_different_property"
        elif match["property"] and match["property"] == other_match.get("property"):
            relation = "same_property_different_claim"
        if relation:
            related.append({"draft_id": str(other.get("id") or ""),
                            "relation": relation})
    if related:
        warnings.append("Possible related or duplicate assignment; review before creating.")
    match["candidates"] = related

    _MESSAGES.mkdir(parents=True, exist_ok=True)
    stored_name = f"{draft_id}.eml"
    (_MESSAGES / stored_name).write_bytes(raw)
    draft = {
        "id": draft_id,
        "status": "needs_review",
        "source": {
            "file_name": source.name,
            "stored_message": stored_name,
            "sha256": digest,
            "internet_message_id": str(message.get("message-id", "")),
            "subject": str(message.get("subject", "")),
            "received": str(message.get("date", "")),
            "sender": sender,
            "attachment_names": attachments,
        },
        "fields": fields,
        "match": match,
        "warnings": warnings,
        "created_at": _now(),
        "approved_at": None,
        "approved_by": None,
        "result": {},
    }
    index[draft_id] = draft
    _write_index(index)
    return {"ok": True, "created": True, "draft": _public(draft)}


def list_drafts(*, include_completed: bool = False) -> list[dict[str, Any]]:
    rows = []
    for draft in _read_index().values():
        if not include_completed and draft.get("status") != "needs_review":
            continue
        rows.append(_public(draft))
    return sorted(rows, key=lambda row: row.get("created_at", ""), reverse=True)


def mark_approved(draft_id: str, *, card_id: str = "", card_url: str = "",
                  approved_by: str = "") -> dict[str, Any]:
    index = _read_index()
    draft = index.get(str(draft_id or ""))
    if not draft:
        return {"ok": False, "error": "XA intake draft was not found."}
    if draft.get("status") == "approved":
        return {"ok": True, "draft": _public(draft), "already_approved": True}
    draft["status"] = "approved"
    draft["approved_at"] = _now()
    draft["approved_by"] = str(approved_by or "")
    draft["result"] = {"trello_card_id": str(card_id or ""),
                       "trello_card_url": str(card_url or "")}
    _write_index(index)
    return {"ok": True, "draft": _public(draft)}

