"""Identify a file's true type from its leading bytes (magic number) and
repair a missing file extension.

WHY: CompanyCam's web export — and some email / browser downloads — hand
back files with NO extension. A signed authorization PDF arrives in
Downloads named plain `Servpro Authorization` (no `.pdf`). Two things
break:
  1. Windows can't open it by double-click — with no extension there's
     no associated program, so Explorer shrugs.
  2. The suite's Downloads scans skip it — every scan filters by
     extension (`.pdf`, `.zip`), so an extensionless PDF is invisible
     to scope / document / photo import.

`ensure_extension()` sniffs the real type from the first bytes and
appends the correct suffix, so the file opens normally in Windows AND
shows up in the importers. Only ever ADDS a suffix to a file that has
NONE — it never rewrites an existing extension, so it can't mangle a
deliberately-named file. Positively-identified types only; anything it
can't recognize is left untouched.
"""
import os
import zipfile


# HEIF/HEIC brand codes that appear right after the `ftyp` box marker
# (bytes 4-8). iPhone photos pulled through CompanyCam are commonly HEIC.
_HEIF_BRANDS = {
    b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx",
    b"hevm", b"hevs", b"mif1", b"msf1", b"heif",
}


def sniff_extension(path):
    """Return the dotted extension (e.g. ``.pdf``) that matches the file's
    magic bytes, or ``""`` when the type isn't recognized. Never reads
    more than the first 32 bytes off disk (plus a light zip peek for
    Office formats)."""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
    except OSError:
        return ""
    if len(head) < 4:
        return ""

    # ── Documents / images by fixed-offset signature ──────────────
    if head.startswith(b"%PDF-"):
        return ".pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return ".tif"
    if head.startswith(b"BM"):
        return ".bmp"
    # RIFF-based: WEBP (RIFF....WEBP)
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return ".webp"
    # ISO-BMFF `ftyp` box → HEIC/HEIF (brand at bytes 8-12)
    if head[4:8] == b"ftyp" and head[8:12] in _HEIF_BRANDS:
        return ".heic"

    # ── ZIP container: could be a plain .zip or an OOXML Office doc ──
    if head.startswith(b"PK\x03\x04"):
        return _zip_or_office(path)

    return ""


def _zip_or_office(path):
    """A ZIP local-file header could be a real .zip OR an Office/OpenXML
    document (docx/xlsx/pptx are zips). Peek the archive's member names to
    tell them apart; fall back to ``.zip`` on any read error."""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
    except (zipfile.BadZipFile, OSError):
        return ".zip"
    joined = "\n".join(names)
    if "word/" in joined:
        return ".docx"
    if "xl/" in joined:
        return ".xlsx"
    if "ppt/" in joined:
        return ".pptx"
    return ".zip"


def _dedupe_target(path):
    """Return `path` if free, else `path` with ` (2)`, ` (3)`… inserted
    before the extension so a rename never clobbers an existing file."""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while True:
        cand = f"{stem} ({n}){ext}"
        if not os.path.exists(cand):
            return cand
        n += 1


def ensure_extension(path):
    """If `path` has NO extension but its bytes identify a known type,
    rename it to add the correct suffix. Returns the (possibly new) path.

    A no-op — returns `path` unchanged — when the file already has any
    extension, when the type isn't recognized, or on any OS error. Only
    ever adds a suffix; never rewrites or removes one."""
    try:
        if not os.path.isfile(path):
            return path
        # splitext ext is "" only when the name carries no dot-suffix at
        # all — exactly the CompanyCam case. Leave every other file alone.
        if os.path.splitext(path)[1]:
            return path
        ext = sniff_extension(path)
        if not ext:
            return path
        target = _dedupe_target(path + ext)
        os.rename(path, target)
        try:
            import ems_log
            ems_log.info("file_signature",
                         f"added extension: {os.path.basename(path)} -> "
                         f"{os.path.basename(target)}")
        except Exception:
            pass
        return target
    except OSError:
        return path


def repair_directory(dir_path):
    """Add the correct extension to every extensionless-but-identifiable
    file directly inside `dir_path` (non-recursive). Returns a list of
    ``{"old": <old name>, "new": <new name>, "path": <new full path>}``
    for each file renamed — empty when nothing needed fixing."""
    repaired = []
    if not dir_path or not os.path.isdir(dir_path):
        return repaired
    try:
        with os.scandir(dir_path) as it:
            entries = [e for e in it if e.is_file(follow_symlinks=False)]
    except OSError:
        return repaired
    for e in entries:
        if os.path.splitext(e.name)[1]:
            continue
        new_path = ensure_extension(e.path)
        if new_path != e.path:
            repaired.append({
                "old":  e.name,
                "new":  os.path.basename(new_path),
                "path": new_path,
            })
    return repaired


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    if os.path.isdir(target):
        fixed = repair_directory(target)
        if not fixed:
            print("Nothing to fix — every file already has an extension "
                  "(or wasn't a recognized type).")
        for r in fixed:
            print(f"{r['old']}  ->  {r['new']}")
    else:
        print(sniff_extension(target) or "(unrecognized)")
