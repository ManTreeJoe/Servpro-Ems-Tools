"""
Canonical stage taxonomy for the EMS Automation suite.

The franchise's job stages (Initial Inspection, Mold Prep, Demo, …) appear
in three different flows:

  • run_audit_gui    — maps a SharePoint folder name to the pics subfolder
                       (most-specific match wins; loose regexes accept tags
                       like "EQ pics" mixed in).
  • daily_photos_gui — parses run-doc lines, strict regexes (no bare
                       "initial" — that would over-match field shorthand).
  • job_notes_gui    — parses free-form user notes, loose regexes.

Stage labels and their pics subfolder names live HERE. Detection regexes
for each consumer stay with that consumer because the input shapes need
different strictness; consolidating them caused over-matches in earlier
revisions. If you add a stage, update STAGES below and add the regex
in each consumer.
"""
import re

# (label, needs_photos, pics_subfolder)
# Order is the canonical timeline order shown in the UI.
# NOTE: Initial Inspection's pics subfolder is plain "Initial" (no
# " pics" suffix) — this is the user-preferred name for the folder
# techs are about to drop initial photos into. Audits match on the
# substring 'initial' (audit_logic.check_photos) so existing folders
# named "Initial pics" still satisfy the check.
STAGES = [
    ("Initial Inspection", True,  "Initial"),
    ("Mold Prep",          True,  "Mold Prep pics"),
    ("Post Mold Prep",     True,  "Post Mold Prep pics"),
    ("Demo",               True,  "Demo pics"),
    ("Post",               True,  "Post pics"),
    ("Monitor",            False, ""),
    ("Teardown",           True,  "Post pics"),
    ("Mold Clearance",     False, ""),
    ("Recon",              False, ""),
    ("Reinspection",       True,  "Reinspection pics"),
]

LABELS         = [s[0] for s in STAGES]
NEEDS_PHOTOS   = {label: needs for label, needs, _ in STAGES}
PICS_SUBFOLDER = {label: sub for label, _, sub in STAGES if sub}


# SharePoint folder name → stage label.
# Order is most-specific → least so "Post Mold Prep" wins over plain
# "Mold Prep" or "Post". Bare "mold" without "clear" falls through to
# Mold Prep (raw mold work in our process is the prep stage).
_SP_FOLDER_PATTERNS = [
    # Post Mold Prep accepts three folder-naming conventions seen in
    # the wild: "Post Mold Prep", bare "Post Mold", and "Mold After".
    # All three resolve to the same stage / pics subfolder.
    ("Post Mold Prep", re.compile(
        r"\bpost\s*mold(?:\s*prep)?\b|\bmold\s*after\b", re.IGNORECASE)),
    ("Mold Prep",      re.compile(r"\bmold\s*prep\b",        re.IGNORECASE)),
    ("Post",           re.compile(r"\bpost(\s+demo)?\b",     re.IGNORECASE)),
    ("Demo",           re.compile(r"\bdemo\b",               re.IGNORECASE)),
    ("Reinspection",   re.compile(r"\breinspection\b",       re.IGNORECASE)),
    ("Initial Inspection",
     re.compile(r"\b(initial(\s+inspection)?|inspection)\b", re.IGNORECASE)),
    ("Mold Prep",      re.compile(r"\bmold\b(?!\s*clear)",   re.IGNORECASE)),
]


def detect_sp_folder_stage(name):
    """Return the canonical stage label for a SharePoint folder name, or ''."""
    if not name:
        return ""
    for label, pat in _SP_FOLDER_PATTERNS:
        if pat.search(name):
            return label
    return ""


def detect_sp_folder_subfolder(name):
    """Return the pics subfolder name (e.g. 'Demo pics') for a SharePoint
    folder name, or '' when no stage keyword is found."""
    return PICS_SUBFOLDER.get(detect_sp_folder_stage(name), "")
