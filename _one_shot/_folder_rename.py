"""Rename 2026 Jobs folders for consistency: 'Lastname Firstname' (no
comma). Read-only by default — pass --apply to actually rename.

Rules:
  1. Remove any commas from the folder name (preserves token order + case).
  2. If the folder's tokens are reversed vs the matching Trello card AND
     that card encodes lastname-first via a comma, swap the folder
     tokens to match.
  3. Skip commercial folders (matched by markers + addresses).
  4. Skip when no card matches (no signal to act on).
  5. Skip when the Trello card has no comma (can't trust its order).
  6. Preserve case — never recase ("ALVAREZ DIANE" stays "ALVAREZ DIANE"
     on rename if only a swap is needed).

Usage:
  python _folder_rename.py            # dry-run (preview pairs)
  python _folder_rename.py --apply    # actually rename
"""
import os
import re
import sys

import config
import trello_client as tc

JOBS_ROOT = os.path.join(
    config.load().get("audit_base", r"X:\IE_Public"), "2026 Jobs")

# ── Reused from the audit script ─────────────────────────────────────────────

_CARD_TRIM_RE = re.compile(r"\s*[-—–]\s+.*$")
_YEAR_SUFFIX_RE = re.compile(r"\s+(?:19|20)\d{2}\s*$")

_COMMERCIAL_MARKERS = (
    "apartments", "apt", "ranch", "property", "management", "llc",
    "inc", "corp", "company", "service", "services", "restoration",
    "construction", "investments", "partners", "farms", "estate",
    "school", "church", "fire", "loss", "& associates", "& sons",
    "ave", "avenue", "blvd", "boulevard", "st ", "street", "drive",
    "way", "rd", "road", "lane", "ln", "court", "ct", "circle",
    "place", "highway", "hwy", "freeway",
    "7-11", "starbucks", "mcdonald", "subway", "burger",
    "greystar", "grocers", "tools", "tool", "bistro", "starbucks",
    "everhome", "metro at",
)


def _looks_commercial(name):
    nl = name.lower()
    if re.search(r"\d", name):
        return True
    if any(m in nl for m in _COMMERCIAL_MARKERS):
        return True
    return False


def _name_tokens(s):
    s = _YEAR_SUFFIX_RE.sub("", s)
    s = re.sub(r"[,\-]", " ", s)
    return [t.lower() for t in re.split(r"\s+", s.strip())
            if t and t != "&" and len(t) >= 2]


def _bare_insured_from_card(card_name):
    return _CARD_TRIM_RE.sub("", card_name).strip()


def pull_all_cards():
    boards = tc.list_boards() or []
    out = []
    for b in boards:
        try:
            cards = tc._call(
                f"/boards/{b['id']}/cards",
                params={"fields": "id,name,closed", "filter": "open"}) or []
        except Exception:
            continue
        out.extend(cards)
    return out


def _build_card_index(cards):
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


# ── Rename target ──────────────────────────────────────────────────────────

def _split_preserving_case(name):
    """Split on whitespace OR comma, preserving each token's original
    case. Returns list of original tokens (in order). Hyphens become
    spaces (so 'HERMINIA-DURAN' becomes ['HERMINIA', 'DURAN'])."""
    if not name:
        return []
    # Normalize hyphens to spaces for token split (rare but real:
    # 'HERMINIA-DURAN'). Don't touch hyphens INSIDE token-like content
    # — these are always between names.
    s = name.replace("-", " ")
    parts = re.split(r"[,\s]+", s)
    return [p for p in parts if p]


def _compute_target(folder_name, card):
    """Return the target folder name (or None if no rename needed).
    Applies: comma removal, name flip when card has a comma. Preserves
    case in every token of the original folder."""
    folder_clean = _YEAR_SUFFIX_RE.sub("", folder_name).strip()
    has_comma_or_hyphen = ("," in folder_clean) or ("-" in folder_clean)

    tokens = _split_preserving_case(folder_clean)
    if len(tokens) < 2:
        return None
    folder_first_lower = tokens[0].lower()

    # If the card name has a comma, that gives us authoritative lastname
    # = before the comma. Compare to the folder's first token.
    card_name = card["name"]
    bare = _bare_insured_from_card(card_name)
    if "," in bare:
        # Lastname = part before first comma
        canonical_lastname = bare.split(",", 1)[0].strip().lower()
    else:
        canonical_lastname = None   # don't trust

    rebuilt: list[str]
    if (canonical_lastname is not None
            and folder_first_lower != canonical_lastname):
        # Find the token in the folder that matches the canonical
        # lastname, move it to the front. Preserve all other tokens
        # in their original order.
        idx = next((i for i, t in enumerate(tokens)
                    if t.lower() == canonical_lastname), None)
        if idx is None:
            # Folder doesn't contain the canonical lastname token — skip
            # (can happen with hyphenated surnames, multi-word lastnames).
            rebuilt = tokens
        else:
            rebuilt = [tokens[idx]] + tokens[:idx] + tokens[idx + 1:]
    else:
        rebuilt = tokens

    # Final assembly: tokens joined by single space, plus any '&' that
    # appeared in the original folder is preserved IF it appears between
    # rebuilt tokens. Reconstructing & ordering precisely is brittle, so
    # we re-thread '&' from the original folder where we can.
    target = " ".join(rebuilt)
    # Re-insert '&' if the original had one — find the '&' position in
    # the original token sequence and insert at the equivalent index.
    if "&" in folder_clean:
        # Reconstruct from original to keep '&' anchoring stable: walk
        # original tokens (including '&'), substitute the swapped order
        # of NON-& tokens.
        orig_tokens_with_amp = [t for t in re.split(r"\s+", folder_clean)
                                  if t]
        non_amp_indices = [i for i, t in enumerate(orig_tokens_with_amp)
                           if t != "&"]
        if len(non_amp_indices) == len(rebuilt):
            new_seq = list(orig_tokens_with_amp)
            for i, idx in enumerate(non_amp_indices):
                new_seq[idx] = rebuilt[i]
            target = " ".join(new_seq)

    # Strip any commas that were in the original.
    target = target.replace(",", "")

    # Collapse double spaces.
    target = re.sub(r"\s+", " ", target).strip()

    # Skip if no real change. We only emit a rename when comma removal
    # OR token-order swap actually changes the string. Case is preserved
    # by tokenization (we never call .title() / .upper() / .lower() on
    # rebuilt tokens), so a case-only diff is impossible from this code
    # path — no need to filter for it explicitly.
    if target == folder_clean.strip():
        return None
    return target


# ── Main ───────────────────────────────────────────────────────────────────

def main(apply: bool = False):
    if not os.path.isdir(JOBS_ROOT):
        print(f"Folder not found: {JOBS_ROOT}")
        return 1
    print(f"Scanning {JOBS_ROOT}")
    print("Pulling Trello cards...")
    cards = pull_all_cards()
    index = _build_card_index(cards)
    print(f"  {len(index)} indexed person-name cards")

    folders = sorted(
        e.name for e in os.scandir(JOBS_ROOT)
        if e.is_dir(follow_symlinks=False))

    plans = []
    skipped_commercial = 0
    skipped_nomatch = 0
    skipped_nocomma = 0

    for folder in folders:
        if _looks_commercial(folder):
            skipped_commercial += 1
            continue
        match = _find_card_for_folder(folder, index)
        if match is None:
            skipped_nomatch += 1
            continue
        bare, card = match
        target = _compute_target(folder, card)
        if target is None or target == folder:
            continue
        # Skip rename if the only diff is case
        if target.lower() == folder.lower():
            continue
        plans.append((folder, target, card["name"]))

    print()
    print(f"=== {len(plans)} planned renames ===")
    print()
    for old, new, card_name in plans:
        print(f"  '{old}' -> '{new}'")
        print(f"     (card: '{card_name}')")
    print()
    print(f"Skipped: {skipped_commercial} commercial / "
          f"{skipped_nomatch} no card match")

    if not plans:
        return 0

    if not apply:
        print("\n(dry-run) Re-run with --apply to actually rename.")
        return 0

    # Apply renames.
    print("\nApplying renames...")
    success = 0
    failed = []
    for old, new, _ in plans:
        old_path = os.path.join(JOBS_ROOT, old)
        new_path = os.path.join(JOBS_ROOT, new)
        if os.path.exists(new_path):
            failed.append((old, new, "destination already exists"))
            continue
        try:
            os.rename(old_path, new_path)
            success += 1
            print(f"  OK  '{old}' -> '{new}'")
        except OSError as ex:
            failed.append((old, new, str(ex)))
            print(f"  FAIL  '{old}' -> '{new}': {ex}")
    print()
    print(f"Renamed: {success} | Failed: {len(failed)}")
    return 0 if not failed else 2


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    sys.exit(main(apply=apply))
