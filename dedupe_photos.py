"""Remove byte-identical duplicate photos from a job folder.

The two CompanyCam import paths name the same photo differently — the zip
export uses `<label>-<N>-<Jul 30 2026 12_03pm>-<4char>.jpg`, the API pull
uses `<label> <tech> <YYYY-MM-DD HH-MM-SS> <id8>.jpg` — and share no common
identifier, so neither can see the other's files. A job imported both ways
holds every photo twice.

Content hash is the only reliable match: both paths download the SAME
original bytes, so identical photos hash identically regardless of name.

    python dedupe_photos.py "X:\\IE_Public\\2026 Jobs\\Johnson,Carmen"
    python dedupe_photos.py <folder> --apply

Dry by default — it prints what it WOULD delete and touches nothing.
`--apply` sends duplicates to the Recycle Bin (not a hard delete), so a
wrong call is undoable from Explorer.

Which copy is kept
------------------
The one whose name carries the most information, in this order:
  1. an API-pull name  (tags + tech + capture time + photo id)
  2. a zip-export name (tags + capture time)
  3. anything else
  4. on a tie, the older file — it was there first
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from collections import defaultdict

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif",
               ".bmp", ".mp4", ".mov"}

# `<label> <tech> 2026-07-30 10-02-05 34233068.jpg`
_API_RE = re.compile(r" \d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2} [0-9a-f]{6,}\.",
                     re.IGNORECASE)
# `<label>-10-Jul 30 2026 12_03pm-icUc.jpg`
_ZIP_RE = re.compile(r"-\d+-\w{3} \d+ \d{4} \d{2}_\d{2}[ap]m-\w{4}\.",
                     re.IGNORECASE)


def _rank(path: str) -> int:
    """Lower is better — how much the filename tells you about the photo."""
    name = os.path.basename(path)
    if _API_RE.search(name):
        return 0
    if _ZIP_RE.search(name):
        return 1
    return 2


def _id_len(path: str) -> int:
    """Length of the trailing id token — longer wins a tie.

    A duplicate pair is usually the SAME photo under a legacy 8-character
    token and its full 10-digit id. Keeping the short one preserves the
    ambiguity that created the duplicate: two photos can share an 8-char
    prefix, so "do we already have this?" stays unanswerable for them.
    Without this the tie fell to mtime, which kept the older short name.
    """
    stem = os.path.splitext(os.path.basename(path))[0]
    tok = stem.rsplit(" ", 1)[-1]
    return len(tok) if tok.isalnum() else 0


def _digest(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def scan(folder: str):
    """{hash: [paths]} for every image under `folder`, size-prefiltered.

    Hashing is the expensive part, so only files that SHARE A SIZE are
    hashed — a unique size cannot have a byte-identical twin.
    """
    by_size = defaultdict(list)
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if os.path.splitext(f)[1].lower() not in _IMAGE_EXTS:
                continue
            p = os.path.join(root, f)
            try:
                by_size[os.path.getsize(p)].append(p)
            except OSError:
                pass
    groups = defaultdict(list)
    hashed = 0
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        for p in paths:
            try:
                groups[_digest(p)].append(p)
                hashed += 1
            except OSError:
                pass
    dupes = {h: sorted(ps, key=lambda p: (_rank(p), -_id_len(p), os.path.getmtime(p)))
             for h, ps in groups.items() if len(ps) > 1}
    total = sum(len(v) for v in by_size.values())
    return dupes, {"images": total, "hashed": hashed}


def _recycle(path: str) -> bool:
    """Recycle Bin, not unlink — a wrong call must be undoable."""
    try:
        from send2trash import send2trash
        send2trash(path)
        return True
    except Exception:
        return False


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folder", help="job folder to scan")
    ap.add_argument("--apply", action="store_true",
                    help="actually remove duplicates (Recycle Bin)")
    args = ap.parse_args(argv)

    folder = os.path.abspath(args.folder)
    if not os.path.isdir(folder):
        print(f"not a folder: {folder}")
        return 2

    print(f"scanning {folder}")
    dupes, stats = scan(folder)
    print(f"  {stats['images']} images, {stats['hashed']} hashed "
          f"(same-size candidates only)")

    if not dupes:
        print("\nNo byte-identical duplicates.")
        return 0

    removable = sum(len(v) - 1 for v in dupes.values())
    freed = 0
    print(f"\n{len(dupes)} photo(s) present more than once — "
          f"{removable} file(s) removable:\n")
    for paths in sorted(dupes.values(), key=lambda ps: ps[0].lower()):
        keep, drop = paths[0], paths[1:]
        print(f"  KEEP {os.path.relpath(keep, folder)}")
        for d in drop:
            try:
                freed += os.path.getsize(d)
            except OSError:
                pass
            print(f"    - {os.path.relpath(d, folder)}")

    print(f"\n{removable} file(s), {freed / 1_048_576:.1f} MB")
    if not args.apply:
        print("\nDry run — nothing removed. Re-run with --apply.")
        return 0

    gone = failed = 0
    for paths in dupes.values():
        for d in paths[1:]:
            if _recycle(d):
                gone += 1
            else:
                failed += 1
    print(f"\nrecycled {gone} file(s)" + (f", {failed} failed" if failed else ""))
    print("They are in the Recycle Bin if this was wrong.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
