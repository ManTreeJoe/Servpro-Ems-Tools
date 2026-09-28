"""Canonical paperwork projection for the Job Workspace.

The UI must not infer paperwork from whichever provider happens to finish
loading first.  This pure module is the interface between stored job facts,
the latest folder audit, and the forms list shown by desktop/web clients.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

from audit_logic import (COMMERCIAL_FORM_NAMES, IPR_FORM_NAME,
                         REQUIRED_FORMS, SELF_PAY_FORMS)


def _norm(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _matches_issue(label: str, issues: list[str]) -> bool:
    wanted = _norm(label)
    return any(_norm(issue) == wanted or _norm(issue).startswith(wanted + " ")
               for issue in issues)


def build_paperwork(master: Mapping | None,
                    audit: Mapping | None) -> dict:
    """Return every expected form with an honest evidence state.

    ``unknown`` means the form is required but no completed audit is stored.
    An empty missing list is only treated as proof when ``audit_complete`` is
    true (or the caller is an older, already-completed audit payload).
    """
    master = dict(master or {})
    audit = dict(audit or {})
    issues = [str(item) for item in (audit.get("form_issues") or [])]
    explicit_complete = audit.get("audit_complete")
    audit_complete = (explicit_complete is True or
                      (explicit_complete is None and bool(
                          audit.get("path") or audit.get("folder"))))
    job_type = _norm(master.get("job_type") or audit.get("job_type"))
    commercial = bool(audit.get("is_commercial") or job_type == "commercial")
    self_pay = bool(audit.get("is_self_pay") or job_type in {"self pay", "selfpay"})
    metadata = master.get("metadata") if isinstance(master.get("metadata"), dict) else {}
    overrides = metadata.get("requirement_overrides") or {}
    if not isinstance(overrides, dict):
        overrides = {}

    expected = []
    for label, _pattern in REQUIRED_FORMS:
        if commercial and _norm(label) in COMMERCIAL_FORM_NAMES:
            continue
        expected.append((label, "intake", "required"))
    if self_pay:
        expected.extend((label, "self-pay", "required")
                        for label, _pattern in SELF_PAY_FORMS)
    # Keep the report visible as part of the normal list. It remains not due
    # until an audit explicitly asks for it or the job has reached field work.
    expected.append((IPR_FORM_NAME, "field", "conditional"))

    rows = []
    for label, group, requirement in expected:
        key = "paperwork_" + _norm(label).replace(" ", "_")
        missing = _matches_issue(label, issues)
        manual = overrides.get(key) if isinstance(overrides.get(key), dict) else {}
        manual_state = str(manual.get("state") or "")
        if manual_state == "completed":
            status, source = "present", "saved job decision"
        elif manual_state == "not_applicable":
            status, source = "not_applicable", "saved job decision"
        elif missing:
            status, source = "missing", "folder audit"
        elif label == IPR_FORM_NAME and not audit_complete:
            status, source = "not_due", "waiting for field evidence"
        elif label == IPR_FORM_NAME and audit_complete and not missing:
            # check_forms only adds IPR once initial photos make it due. A
            # clean result alone therefore cannot prove that report exists.
            status, source = "not_due", "not required by latest audit"
        elif audit_complete:
            status, source = "present", "folder audit"
        else:
            status, source = "unknown", "not checked yet"
        rows.append({
            "key": key, "label": label, "group": group,
            "requirement": requirement, "status": status, "source": source,
            "manual_actor": str(manual.get("actor") or ""),
            "manual_at": str(manual.get("at") or ""),
        })

    counts = {state: sum(1 for row in rows if row["status"] == state)
              for state in ("present", "missing", "unknown", "not_due",
                            "not_applicable")}
    return {
        "items": rows,
        "counts": counts,
        "audit_complete": audit_complete,
        "source": "saved job + folder audit",
    }
