"""Canonical Trello board taxonomy — which boards hold LIVE work.

Search hits from every included board used to come back in Trello's own
relevance order, so a card from THE LOGS (1,388 archived jobs) or the AR
BOARD (1,092 billing cards) could outrank the job the office is actually
working right now. Those two boards alone are more cards than everything
else combined, so the noise wins by sheer volume.

Two tiers, and the rule is "is somebody working this job today":

  ACTIVE   — live production work. Shown first.
  ARCHIVE  — finished, billing, or collections. Shown after, under a
             divider, but never hidden: pinning an old job is exactly
             when you need to find it.

An UNRECOGNISED board is treated as ACTIVE on purpose. A board nobody
classified is far more likely to be new live work than a new archive,
and burying it would be silent. Add it below when it shows up.
"""
import re

ACTIVE = "active"
ARCHIVE = "archive"

# Matched on a normalised name (casefolded, runs of non-alphanumerics
# collapsed) because the real board names are inconsistent — "AR  BOARD"
# carries a double space, and "RECON CLOSEOUT/COLLECTIONS" a slash.
_ARCHIVE_PATTERNS = (
    r"^the logs",              # THE LOGS - EMS       (completed jobs)
    r"^ar board$",             # AR  BOARD            (receivables)
    r"closeout|collections",   # RECON CLOSEOUT/COLLECTIONS
    r"billing|disputes",       # EMS BILLING DISPUTES
)

# Order within the ACTIVE tier — the board the office lives in comes
# first. Anything unlisted sorts after these but still ahead of ARCHIVE.
_ACTIVE_ORDER = (
    r"work in progress",
    r"disaster response",
    r"estimating",
    r"commercial",
    r"contents",
)


def normalize(name):
    """Board name → comparable key. 'AR  BOARD' and 'ar board' match."""
    return re.sub(r"[^a-z0-9]+", " ", (name or "").casefold()).strip()


def tier(board_name):
    """ACTIVE or ARCHIVE for a board name. Unknown boards are ACTIVE."""
    key = normalize(board_name)
    if not key:
        return ACTIVE
    for pat in _ARCHIVE_PATTERNS:
        if re.search(pat, key):
            return ARCHIVE
    return ACTIVE


def is_active(board_name):
    return tier(board_name) == ACTIVE


def sort_key(board_name):
    """(tier_rank, board_rank) — sort search hits with this.

    Stable within a rank, so Trello's own relevance ordering survives
    inside a board rather than being replaced by an alphabetical one.
    """
    key = normalize(board_name)
    if tier(board_name) == ARCHIVE:
        return (1, len(_ACTIVE_ORDER))
    for i, pat in enumerate(_ACTIVE_ORDER):
        if re.search(pat, key):
            return (0, i)
    return (0, len(_ACTIVE_ORDER))      # unknown active board


def classify(board_names):
    """[{name, tier, active}] in display order — powers the filter UI."""
    return [
        {"name": n, "tier": tier(n), "active": is_active(n)}
        for n in sorted(set(board_names or ()), key=lambda b: (sort_key(b), b))
    ]
