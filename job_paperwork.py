"""Canonical paperwork projection for the Job Workspace.

The UI must not infer paperwork from whichever provider happens to finish
loading first.  This pure module is the interface between stored job facts,
the latest folder audit, and the forms list shown by desktop/web clients.
"""
from __future__ import annotations

import re
from pathlib import Path
from collections.abc import Mapping

from audit_logic import (COMMERCIAL_FORM_NAMES, IPR_FORM_NAME,
                         REQUIRED_FORMS, SELF_PAY_FORMS)

# Reviewed company State Farm EMS template. These are documents, not tasks.
STATE_FARM_FORMS = (
    'State Farm — Authorization to Pay',
    'State Farm — Authorization to Repair (ATR California)',
    'State Farm Warranty Form',
    'Scope',
)


def _norm(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _matches_issue(label: str, issues: list[str]) -> bool:
    wanted = _norm(label)
    return any(_norm(issue) == wanted or _norm(issue).startswith(wanted + " ")
               for issue in issues)


def build_paperwork(master: Mapping | None,
                    audit: Mapping | None) -> dict:
    """Return every expected form with an honest evidence state.

    ``unknown`` means file evidence has not been confirmed. Filename matches
    are suggestions, and a clean legacy audit is not proof of availability.
    Staff completion decisions are preserved separately from file status.
    """
    master = dict(master or {})
    audit = dict(audit or {})
    issues = [str(item) for item in (audit.get("form_issues") or [])]
    # Older cached audits removed sibling-folder matches from form_issues.
    # Restore those as missing unless exact-job file evidence proves otherwise.
    issues.extend(str(item.get('label') or '') for item in
                  (audit.get('misplaced_forms') or []) if isinstance(item, dict))
    explicit_complete = audit.get("audit_complete")
    audit_complete = explicit_complete is True
    # Older/cached audits marked execution complete even when no folder was
    # found. An empty issue list in that case is not evidence of any files.
    folder_unavailable = audit.get("found") is False
    if folder_unavailable:
        audit_complete = False
    metadata = master.get("metadata") if isinstance(master.get("metadata"), dict) else {}
    section = str(audit.get('selected_division') or 'EMS').upper()
    section_name = {'EMS':'EMS', 'CONTENTS':'Contents', 'RECON':'Recon'}.get(section, section)
    facts = (metadata.get('section_profile_facts') or {}).get(section_name, {})
    settings = metadata.get('settings') or {}
    job_type = _norm(facts.get('payer_type') or master.get("job_type") or audit.get("job_type"))
    commercial = bool(audit.get("is_commercial") or job_type == "commercial" or
                      _norm(master.get('property_type') or settings.get('property_type')) == 'commercial')
    self_pay = bool(job_type in {"self pay", "selfpay"} or
                    (not facts.get('payer_type') and audit.get("is_self_pay")))
    carrier = _norm(facts.get('carrier') or audit.get('carrier') or master.get('carrier') or settings.get('carrier'))
    state_farm = section == 'EMS' and not self_pay and carrier in ('state farm', 'statefarm', 'state farm insurance')
    overrides = metadata.get("requirement_overrides") or {}
    if not isinstance(overrides, dict):
        overrides = {}

    expected = []
    for label, _pattern in REQUIRED_FORMS:
        if commercial and _norm(label) in COMMERCIAL_FORM_NAMES and not (
                self_pay and label == 'Cert of Satisfaction'):
            continue
        expected.append((label, "intake", "required"))
    if state_farm:
        # State Farm uses Authorization to Pay, not Authorization to Perform.
        expected = [(label, 'intake', 'required') for label, _pattern in REQUIRED_FORMS
                    if label != 'Auth to Perform']
        existing = {label for label, _group, _requirement in expected}
        expected.extend((label, 'State Farm EMS', 'required') for label in STATE_FARM_FORMS
                        if label not in existing)
    # Keep the report visible as part of the normal list. It remains not due
    # until an audit explicitly asks for it or the job has reached field work.
    expected.append((IPR_FORM_NAME, "field", "conditional"))
    if section == 'EMS':
        expected = [('Initial Scope' if label == 'Scope' else label, group, requirement)
                    for label, group, requirement in expected]
        expected.append(('Final Scope', 'closeout', 'conditional'))
    final_scope_due = master.get('lifecycle_stage') in ('closeout', 'closed')
    if self_pay:
        # Self-pay is a replacement packet, not an addition to the insurance
        # packet. Explicit job-specific requirements are appended below.
        expected = [('Home Improvement Contract', 'self-pay', 'required'),
                    ('Cert of Satisfaction', 'self-pay', 'required')]
    # An optional ATP remains visible while its scan is unavailable so a
    # missing scan cannot make an existing document silently disappear.
    evidence = (audit.get('form_file_evidence') or {}).get('Auth to Perform') or {}
    atp_confirmation = (((metadata.get('form_confirmations') or {}).get('EMS') or {})
                        .get('Auth to Perform'))
    if (section == 'EMS' and (not evidence.get('checked') or evidence.get('files') or atp_confirmation)
            and not any(label == 'Auth to Perform' for label, _, _ in expected)):
        expected.append(('Auth to Perform', 'additional form', 'optional'))
    # Additive, section-scoped requirements. Support both the standard forms
    # and the additional scanner labels: a deliberately configured ATP must
    # remain visible even if the selected payer normally omits it.
    from form_file_evidence import PATTERNS
    configured = metadata.get('paperwork_required_forms')
    configured = configured.get(section, []) if isinstance(configured, dict) else []
    configured = configured if isinstance(configured, list) else []
    supported = {label for label, _ in REQUIRED_FORMS} | set(PATTERNS)
    supported.discard('Scope')  # The workspace uses Initial/Final Scope.
    aliases = {'atp': 'Auth to Perform', 'cif': 'Customer Info Form',
               'cer': 'Customer Equip Resp', 'cos': 'Cert of Satisfaction',
               'scope': 'Initial Scope'}
    canonical = {_norm(label): label for label in supported}
    existing = {label for label, _, _ in expected}
    for label in configured:
        if not isinstance(label, str):
            continue
        normalized = _norm(label)
        resolved = aliases.get(normalized) or canonical.get(normalized)
        if resolved and resolved in existing:
            expected = [(name, 'job-specific', 'required') if name == resolved and requirement == 'optional'
                        else (name, group, requirement) for name, group, requirement in expected]
        if resolved and resolved not in existing:
            expected.append((resolved, 'job-specific', 'required'))
            existing.add(resolved)

    rows = []
    for label, group, requirement in expected:
        key = "paperwork_" + _norm(label).replace(" ", "_")
        missing = _matches_issue(label, issues)
        if label == 'Initial Scope':
            missing = missing or _matches_issue('Scope', issues)
        manual = overrides.get(key) if isinstance(overrides.get(key), dict) else {}
        # Preserve existing staff decisions for the initial scope only.
        if label == 'Initial Scope' and not manual and isinstance(overrides.get('paperwork_scope'), dict):
            manual = overrides['paperwork_scope']
        manual_state = str(manual.get("state") or "")
        evidence = (audit.get('form_file_evidence') or {}).get(label, {}) if section == 'EMS' else {}
        confirmation = ((metadata.get('form_confirmations') or {}).get(section) or {}).get(label, {})
        from form_confirmation import verified
        confirmed = (confirmation.get('job_id') == master.get('job_id') and
                     verified(confirmation, audit.get('path') or audit.get('folder')))
        if manual_state == "not_applicable":
            status, source = "not_applicable", "saved job decision"
        elif folder_unavailable:
            status, source = "unknown", "folder unavailable · not verified"
        elif confirmed:
            status, source = 'present', 'File confirmed · signature not verified'
        elif confirmation:
            status, source = 'unknown', 'Confirmed file unavailable or changed · review needed'
        elif label == 'Final Scope' and not final_scope_due and not evidence.get('files'):
            status, source = 'not_due', 'Due at closeout'
        elif evidence.get('checked'):
            status = 'unknown' if evidence.get('files') else 'missing'
            source = 'Suggested file match · confirmation needed' if evidence.get('files') else 'EMS document scan'
        elif group == 'additional form':
            status, source = 'unknown', 'Optional form · file scan not checked'
        elif missing:
            status, source = "missing", "folder audit"
        elif group == 'job-specific':
            status, source = 'unknown', 'Job-specific document scan needed'
        elif label == 'Home Improvement Contract':
            status, source = 'unknown', 'Contract document scan needed'
        elif label in ('Initial Scope', 'Final Scope'):
            # Legacy clean audits cannot distinguish an initial from a final scope.
            status, source = 'unknown', 'Scope document scan needed'
        elif label == IPR_FORM_NAME and not audit_complete:
            status, source = "not_due", "waiting for field evidence"
        elif label == IPR_FORM_NAME and audit_complete and not missing:
            # check_forms only adds IPR once initial photos make it due. A
            # clean result alone therefore cannot prove that report exists.
            status, source = "not_due", "not required by latest audit"
        elif state_farm and label in STATE_FARM_FORMS and label != 'Scope':
            # Legacy audits only checked generic ATP/CIF/CER/COS. No issues
            # from that audit cannot prove these distinct documents exist.
            status, source = 'unknown', 'State Farm form evidence not checked'
        elif group == 'self-pay' and not audit.get('is_self_pay'):
            status, source = 'unknown', 'Self-pay form evidence not checked'
        elif audit_complete:
            status, source = "unknown", "File evidence not verified"
        else:
            status, source = "unknown", "not checked yet"
        if manual_state == 'completed':
            source += ' · previously confirmed complete'
        files = list(evidence.get('files') or []) if evidence.get('checked') and not folder_unavailable else []
        if confirmed:
            confirmed_path = str(Path(audit.get('path') or audit.get('folder')) / confirmation['relative'])
            if confirmed_path not in files:
                files.append(confirmed_path)
        rows.append({
            "key": key, "label": label, "group": group,
            "requirement": requirement, "status": status, "source": source,
            "manual_actor": str(manual.get("actor") or ""),
            "completion_state": manual_state,
            "file_confirmed": bool(confirmed),
            "confirmed_file": confirmation.get('relative') if confirmed else '',
            "manual_at": str(manual.get("at") or ""),
            "files": files,
        })

    counts = {state: sum(1 for row in rows if row["status"] == state)
              for state in ("present", "missing", "unknown", "not_due",
                            "not_applicable")}
    return {
        "items": rows,
        "counts": counts,
        "audit_complete": audit_complete,
        "source": "saved job + folder audit",
        "profile_name": 'State Farm EMS' if state_farm else
                        'Self-pay' if self_pay else
                        'Commercial' if commercial else 'Standard',
    }
