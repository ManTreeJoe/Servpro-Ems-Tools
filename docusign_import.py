"""DocuSign Final-Paperwork zip import — mirrors the Workcenter import
flow for completed signed paperwork that comes back from DocuSign.

A DocuSign export landing in Downloads as `<Client>_Final_Paperwork.zip`
typically bundles the four signed forms — Certificate of Satisfaction,
Customer Information Form, Authorization to Perform / Direction of
Payment, plus a Summary — using SERVPRO's template ID prefixes
(28531 / 28501 / 28000 / etc.) as filename heads.

This module locates those zips, classifies each PDF inside by template
ID (with a regex fallback so a re-export with the template-name renamed
still classifies), and extracts them into the job's EMS/DOCS folder so
the audit's missing-form checks pass on the next run.
"""
import os
import re
import zipfile


# Matches the DocuSign export zip however it's named:
#   "Smith paperwork.zip"            (the actual current template)
#   "Sanchez_Final_Paperwork.zip"    (older underscore form)
#   "Doe Jane_Final_Paperwork.zip"   (multi-word client)
#   "Garcia Final Paperwork.zip" / "Smith paperwork (2).zip"
# The separator before "paperwork" can be a space / underscore / hyphen,
# the word "final" is optional, and downloaded copies often pick up a
# Windows-style "(1)" / "(2)" suffix.
DOCUSIGN_ZIP_RE = re.compile(
    r'^(?P<client>.+?)[ _-]+(?:final[ _-]+)?paperwork(?:\s*\(\d+\))?\.zip$',
    re.IGNORECASE)


# Form classifier — SERVPRO template ID prefix the DocuSign packet uses.
# Keep IDs canonical so a new form added to the template bundle is a
# single-line edit instead of regex spelunking. The id-less fallback
# below uses the same name patterns audit_logic.REQUIRED_FORMS uses so
# classifier output always matches what the audit looks for.
_FORM_BY_TEMPLATE_ID = {
    "28000": "ATP",   # Auth to Perform Services + Direction of Payment
    "28001": "ATP",
    "28501": "CIF",   # Customer Information Form
    "28510": "CER",   # Customer Equipment Responsibility (commercial)
    "28531": "CoS",   # Certificate of Satisfaction
    "28540": "Scope",
}

# Stable display order for `summarize_landed` — the user reads it left to
# right after an import, so keep the most-common signed forms first.
_LANDED_ORDER = ("ATP", "CIF", "CER", "CoS", "Scope", "Summary", "Other")


def classify_pdf(name):
    """Return the form kind for a DocuSign filename — one of
    "ATP" / "CIF" / "CER" / "CoS" / "Scope" / "Summary" / "Other"."""
    n = (name or "").strip()
    if not n:
        return "Other"
    low = n.lower()
    if low == "summary.pdf" or low.startswith("summary"):
        return "Summary"
    # Template ID is the leading 4-6 digit number — e.g. "28531_-_..."
    m = re.match(r'^(\d{4,6})[_\-\s]', n)
    if m:
        tag = _FORM_BY_TEMPLATE_ID.get(m.group(1))
        if tag:
            return tag
    # Fallback — regex by name fragment (mirrors audit_logic.REQUIRED_FORMS)
    if re.search(r'cert.*satisf', low):
        return "CoS"
    if re.search(r'customer.*info', low):
        return "CIF"
    if re.search(r'auth.*perform', low):
        return "ATP"
    if re.search(r'customer.*equip|equip.*resp', low):
        return "CER"
    if re.search(r'\bscope\b', low):
        return "Scope"
    return "Other"


def _surname_key(client_hint):
    """Return the lowercase surname portion of a client hint for zip
    matching. Handles "Last, First" and "First Last" inputs; returns
    "" when we can't extract a usable surname token."""
    raw = (client_hint or "").strip()
    if not raw:
        return ""
    # "Last, First" — take everything before the first comma.
    if "," in raw:
        head = raw.split(",", 1)[0]
    else:
        # "First Last" — take the last word as the surname.
        parts = raw.split()
        head = parts[-1] if parts else ""
    head = head.strip().lower()
    return head if len(head) >= 2 else ""


def find_docusign_zips(downloads_dir, client_hint=None):
    """Return DocuSign Final-Paperwork zips found in `downloads_dir`,
    newest-mtime first. When `client_hint` is supplied, zips whose
    `<client>` portion matches the surname sort to the top so the
    user's most likely target is at index 0."""
    try:
        names = [
            f for f in os.listdir(downloads_dir)
            if DOCUSIGN_ZIP_RE.match(f)
            and os.path.isfile(os.path.join(downloads_dir, f))
        ]
    except OSError:
        return []

    by_mtime = sorted(
        names,
        key=lambda f: os.path.getmtime(os.path.join(downloads_dir, f)),
        reverse=True)

    surname = _surname_key(client_hint)
    if not surname:
        return by_mtime

    matches, others = [], []
    for fn in by_mtime:
        m = DOCUSIGN_ZIP_RE.match(fn)
        if m and m.group("client").lower().startswith(surname):
            matches.append(fn)
        else:
            others.append(fn)
    return matches + others


def import_zip(zip_path, target_dir):
    """Extract `zip_path` into `target_dir`, classifying every PDF by
    form kind. Returns `{form_kind: [extracted_filenames, ...]}` so the
    caller can show "ATP, CIF, CoS imported" and cross off the matching
    audit rows in one pass.

    Filenames are taken from the zip entry's basename — any nested
    directory structure inside the zip is flattened so the audit's
    REQUIRED_FORMS regexes find the files at the DOCS root.
    """
    if not zip_path or not os.path.isfile(zip_path):
        raise FileNotFoundError(zip_path)
    os.makedirs(target_dir, exist_ok=True)

    landed = {}
    with zipfile.ZipFile(zip_path, "r") as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            name = os.path.basename(info.filename)
            if not name:
                continue
            target = os.path.join(target_dir, name)
            with z.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())
            kind = classify_pdf(name)
            landed.setdefault(kind, []).append(name)
    return landed


def summarize_landed(landed):
    """Short human-readable count summary for the post-import toast.
    Returns "(no files extracted)" when nothing landed."""
    if not landed:
        return "(no files extracted)"
    parts = []
    for k in _LANDED_ORDER:
        if k in landed and landed[k]:
            parts.append(f"{k}: {len(landed[k])}")
    # Catch anything outside the canonical order so a new template ID
    # doesn't silently disappear from the summary.
    for k, v in landed.items():
        if k not in _LANDED_ORDER and v:
            parts.append(f"{k}: {len(v)}")
    return ", ".join(parts) if parts else "(no files extracted)"


# Map from classified form kind → the audit row text it satisfies.
# Used by the audit wiring to cross off ALL rows resolved by a single
# zip import (not just the row whose button was clicked) — same
# behavior the WC import has via post_action_card_rewalk.
FORM_AUDIT_LABELS = {
    "ATP":   "Auth to Perform",
    "CIF":   "Customer Info Form",
    "CER":   "Customer Equip Resp",
    "CoS":   "Cert of Satisfaction",
    "Scope": "Scope",
}
