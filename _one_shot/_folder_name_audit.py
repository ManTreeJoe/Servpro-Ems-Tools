"""One-off audit: compare 2026 Jobs folder names against Trello card
names and flag inconsistent formatting.

Convention: folders should be 'Lastname Firstname' (no comma, mixed
case, no carrier suffix). Compare each folder to its best-matching
Trello card name, report anything that diverges. READ ONLY — no
renames performed.
"""
import os
import re
import sys

import trello_client as tc
import config

JOBS_ROOT = os.path.join(
    config.load().get("audit_base", r"X:\IE_Public"), "2026 Jobs")


# ── Pull all in-scope cards (open boards, open lists) ──────────────────────

def pull_all_cards():
    boards = tc.list_boards() or []
    out = []
    for b in boards:
        try:
            cards = tc._call(
                f"/boards/{b['id']}/cards",
                params={"fields": "id,name,closed,idBoard,idList,shortUrl",
                        "filter": "open"}) or []
        except Exception as ex:
            print(f"  ! board {b.get('name', '?')}: {ex}")
            continue
        for c in cards:
            c["_board_name"] = b.get("name", "")
        out.extend(cards)
    return out


# ── Folder vs card matching ─────────────────────────────────────────────────

# Strip carrier suffix and trailing tags from card names so we get the
# bare insured. Card names look like:
#   "Smith, John - State Farm"
#   "Doe Jane & Bob - AAA - $4,500"
#   "Garcia, Aliah & Ryan - Mercury - $48,597.37"
_CARD_TRIM_RE = re.compile(r"\s*[-—–]\s+.*$")
# Strip trailing year suffix from folders ("Smith John 2026").
_YEAR_SUFFIX_RE = re.compile(r"\s+(?:19|20)\d{2}\s*$")
# Words that aren't part of a person name — used to detect commercial /
# property / non-person folders.
_COMMERCIAL_MARKERS = (
    "apartments", "apt", "ranch", "property", "management", "llc",
    "inc", "corp", "company", "service", "services", "restoration",
    "construction", "investments", "partners", "farms", "estate",
    "school", "church", "fire", "loss", "& associates", "& sons",
    "ave", "avenue", "blvd", "boulevard", "st ", "street", "drive",
    "way", "rd", "road", "lane", "ln", "court", "ct", "circle",
    "place", "place", "highway", "hwy", "freeway",
    "7-11", "starbucks", "mcdonald", "subway", "burger",
)


def _norm(s):
    return re.sub(r"[^a-z\s&]", " ", s.lower()).split()


def _looks_commercial(name):
    nl = name.lower()
    if re.search(r"\d", name):
        return True   # addresses have numbers
    if any(m in nl for m in _COMMERCIAL_MARKERS):
        return True
    return False


def _bare_insured_from_card(card_name):
    """Extract just the insured portion from a card title."""
    bare = _CARD_TRIM_RE.sub("", card_name).strip()
    return bare


def _name_tokens(s):
    """Lowercase tokens of the person-name portion only."""
    s = _YEAR_SUFFIX_RE.sub("", s)
    s = re.sub(r",", " ", s)
    return [t for t in _norm(s) if t and t != "&" and len(t) >= 2]


def _build_card_index(cards):
    """Token-set → card mapping for fast folder lookup. Same insured can
    appear on multiple boards; we keep the first hit."""
    index = []
    for c in cards:
        bare = _bare_insured_from_card(c["name"])
        if not bare or _looks_commercial(bare):
            continue
        toks = _name_tokens(bare)
        if len(toks) < 2:
            continue
        index.append((set(toks), bare, c))
    return index


def _find_card_for_folder(folder_name, index):
    """Best-overlap card (by token set) — must overlap on ≥ 2 tokens to
    avoid surnaming false positives ('Smith' alone matches everyone)."""
    f_toks = set(_name_tokens(folder_name))
    if len(f_toks) < 2:
        return None
    best = None
    best_overlap = 0
    for toks, bare, c in index:
        ov = len(f_toks & toks)
        if ov >= 2 and ov > best_overlap:
            best = (bare, c)
            best_overlap = ov
    return best


# ── Format checks ──────────────────────────────────────────────────────────

def _canonical_from_card(bare):
    """Convert card-bare ('Smith, John' or 'Smith John & Jane') into the
    folder convention 'Lastname Firstname'. The card may already have
    the names in canonical order — we just normalize comma + casing."""
    s = _YEAR_SUFFIX_RE.sub("", bare).strip()
    # Comma-form: "Smith, John" or "Smith, John & Jane"
    if "," in s:
        parts = [p.strip() for p in s.split(",", 1)]
        last, rest = parts[0], parts[1] if len(parts) > 1 else ""
        s = f"{last} {rest}".strip()
    # Title case (preserve & in joint names)
    pieces = []
    for w in s.split():
        if w == "&":
            pieces.append("&")
        else:
            pieces.append(w.capitalize())
    return " ".join(pieces).strip()


def _format_issues(folder, canonical):
    """Compare folder name to canonical 'Lastname Firstname' form. Returns
    a list of issue codes — empty when the folder already matches."""
    issues = []
    f = _YEAR_SUFFIX_RE.sub("", folder).strip()
    c = canonical.strip()
    if f == c:
        return issues
    # Same set of tokens but different ordering → swap
    if set(_name_tokens(f)) == set(_name_tokens(c)):
        if "," in folder:
            issues.append("comma")
        if folder.upper() == folder and folder.lower() != folder:
            issues.append("uppercase")
        if " ".join(_name_tokens(f)) != " ".join(_name_tokens(c)):
            issues.append("name_order")
        # Title-case mismatch (e.g. "Smith JOHN")
        if (set(folder.split()) != set(canonical.split())
                and not issues):
            issues.append("casing")
        return issues
    # Different token set entirely — folder might have year suffix or
    # unit number we want to keep, or might be missing a name.
    f_toks = set(_name_tokens(f))
    c_toks = set(_name_tokens(c))
    if c_toks - f_toks:
        issues.append("missing_token")
    if f_toks - c_toks:
        issues.append("extra_token")
    return issues


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    if not os.path.isdir(JOBS_ROOT):
        print(f"Folder not found: {JOBS_ROOT}")
        return 1
    print(f"Scanning {JOBS_ROOT}")

    print("Pulling Trello cards across all in-scope boards...")
    cards = pull_all_cards()
    print(f"  {len(cards)} open cards")
    index = _build_card_index(cards)
    print(f"  {len(index)} indexed (person-name cards only)")

    folders = sorted(
        e.name for e in os.scandir(JOBS_ROOT)
        if e.is_dir(follow_symlinks=False))
    print(f"  {len(folders)} folders in 2026 Jobs")

    proposed = []
    no_match = []
    commercial = []

    for folder in folders:
        if _looks_commercial(folder):
            commercial.append(folder)
            continue
        match = _find_card_for_folder(folder, index)
        if match is None:
            no_match.append(folder)
            continue
        bare, card = match
        canonical = _canonical_from_card(bare)
        issues = _format_issues(folder, canonical)
        if issues:
            proposed.append({
                "folder":    folder,
                "canonical": canonical,
                "card":      card["name"],
                "board":     card["_board_name"],
                "issues":    issues,
            })

    print()
    print(f"=== {len(proposed)} folder(s) with format issues ===")
    print()
    by_issue = {}
    for p in proposed:
        for code in p["issues"]:
            by_issue.setdefault(code, []).append(p)
    for code, items in sorted(by_issue.items(),
                                 key=lambda kv: -len(kv[1])):
        print(f"--- {code.upper()} ({len(items)}) ---")
        for p in items[:25]:
            print(f"  '{p['folder']:40s}' -> '{p['canonical']}'")
            print(f"     card: '{p['card']}' [{p['board']}]")
        if len(items) > 25:
            print(f"  ... {len(items) - 25} more")
        print()

    print(f"=== {len(no_match)} folder(s) with no Trello card match ===")
    for n in no_match[:20]:
        print(f"  {n}")
    if len(no_match) > 20:
        print(f"  ... {len(no_match) - 20} more")
    print()
    print(f"=== {len(commercial)} folder(s) skipped as commercial/address ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
