"""CompanyCam photo-export zip import.

CompanyCam's web export drops a zip in Downloads named
`photos-<YYYY-MM-DD>-<rand>.zip`. The zip's single top-level folder is the
CompanyCam PROJECT name (== our client, e.g. "David Smith") — the filename
itself carries NO client, so we read the project from inside.

Photos are named "<Room> [Stage]-<N>-<Mon DD YYYY HH_MMam>-<rand>.jpg",
e.g. "Kitchen Post-1-Jun 15 2026 12_03pm-yZ87.jpg". The optional stage tag
(Post / Demo / Mold / Initial / Reinspect / …) drives which PICS/<stage>
subfolder a photo lands in; room-only photos fall back to a dated
"CompanyCam <date>" folder.

Because the user downloads MANY exports for the same date (one per job),
the date alone can't identify a zip — the random suffix disambiguates the
file and the top-folder project name identifies the job. So discovery
reads each zip's project name and surname-matches it to the target client.
"""
import os
import re
import zipfile

# photos-2026-06-15-d4X7.zip  → captures the date for the folder label.
COMPANYCAM_ZIP_RE = re.compile(
    r'^photos-(?P<date>\d{4}-\d{2}-\d{2})-\w+\.zip$', re.IGNORECASE)

# CompanyCam tag (found anywhere in a photo's name) → PICS subfolder.
# Ordered MOST-SPECIFIC first so multi-word tags win over their parts
# ("post mold prep" before "mold prep"/"post"; "initial inspection"
# before "initial"/"inspection"; "reinspection" before "inspection").
# Folder names match what audit_logic.check_photos looks for, so the
# next audit pass auto-resolves the stage.
#
# CompanyCam exports join a photo's tags into the filename label in no
# fixed order — "Garage Initial Inspection", "Initial Inspection Master
# Bath", "Kitchen Post" — so the stage tag can lead, trail, or sit in
# the middle. parse_room_stage matches it ANYWHERE (whole-word) and the
# leftover words are the room.
_STAGE_RULES = [
    ("post mold prep",    "Post Mold Prep"),
    ("mold prep",         "Mold Prep"),
    ("post mold",         "Post Mold"),
    ("mold after",        "Post Mold"),
    ("abatement",         "Abatement"),
    ("reinspection",      "Reinspection"),
    ("reinspect",         "Reinspection"),
    ("initial inspection", "Initial"),
    ("mold",              "Mold"),
    ("demo",              "Demo"),
    ("initial",           "Initial"),
    ("inspection",        "Initial"),
    ("post",              "Post"),
]

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif", ".bmp"}


def stage_for_name(name):
    """Stage folder detected from a photo's filename, or "" when the photo
    is room-only (no stage tag). Whole-word match so "reinspection" isn't
    mistaken for "inspection" and a room like "Compost Area" isn't read
    as a Post tag."""
    low = (name or "").lower()
    for kw, folder in _STAGE_RULES:
        if re.search(r'\b' + re.escape(kw) + r'\b', low):
            return folder
    return ""


# "Kitchen Post-1-Jun 15 2026 02_13pm-nCFi.jpg" → label "Kitchen Post".
_LABEL_RE = re.compile(r'^(.*?)-\d+-')
# Characters Windows won't allow in a folder name.
_BAD_PATH = re.compile(r'[<>:"/\\|?*]+')


def _safe_folder(s):
    s = _BAD_PATH.sub(" ", (s or "")).strip().rstrip(".")
    return " ".join(s.split())  # collapse whitespace


def parse_room_stage(filename):
    """Split a CompanyCam photo name into (room, stage). The name is
    "<label>-<N>-<date>-<rand>.ext" where <label> is the photo's joined
    CompanyCam tags. A stage tag (Post / Demo / Mold Prep / Initial
    Inspection / …) may LEAD, TRAIL, or sit in the MIDDLE; whatever
    words remain after removing it are the room. Examples:
      "Kitchen Post-1-…"                → ("Kitchen", "Post")
      "Garage Initial Inspection-10-…"  → ("Garage", "Initial")
      "Initial Inspection Master Bath-…"→ ("Master Bath", "Initial")
      "Initial Inspection-1-…"          → ("", "Initial")
      "Master Bath-19-…"                → ("Master Bath", "")"""
    base = os.path.basename((filename or "").replace("\\", "/"))
    m = _LABEL_RE.match(base)
    label = (m.group(1) if m else os.path.splitext(base)[0]).strip()
    for kw, folder in _STAGE_RULES:        # most-specific first
        mm = re.search(r'\b' + re.escape(kw) + r'\b', label, re.IGNORECASE)
        if mm:
            room = (label[:mm.start()] + " " + label[mm.end():])
            room = " ".join(room.replace("-", " ").split()).strip(" -")
            return _safe_folder(room), folder
    return _safe_folder(label), ""


def date_from_zip_name(filename):
    """The YYYY-MM-DD embedded in the zip filename, or ""."""
    m = COMPANYCAM_ZIP_RE.match(os.path.basename(filename or ""))
    return m.group("date") if m else ""


def project_name_from_zip(zip_path):
    """The CompanyCam project name = the zip's single top-level folder
    (== our client). Returns "" if it can't be read."""
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            tops = set()
            for n in z.namelist():
                n = n.replace("\\", "/")
                if "/" in n:
                    tops.add(n.split("/", 1)[0].strip())
            tops.discard("")
            if len(tops) == 1:
                return next(iter(tops))
            if tops:
                # Unusual multi-project export — pick deterministically.
                return sorted(tops)[0]
    except Exception:
        pass
    return ""


def _surname(client_hint):
    raw = (client_hint or "").strip()
    if not raw:
        return ""
    head = raw.split(",", 1)[0] if "," in raw else (raw.split()[-1]
                                                     if raw.split() else "")
    head = head.strip().lower()
    return head if len(head) >= 2 else ""


def find_companycam_zips(downloads_dir, client_hint=None):
    """Every CompanyCam export zip in `downloads_dir`, each as
    {filename, path, project, date}. Newest-mtime first; zips whose
    project name matches the client's surname float to the top so the
    most likely target for THIS job is first."""
    try:
        names = [f for f in os.listdir(downloads_dir)
                 if COMPANYCAM_ZIP_RE.match(f)
                 and os.path.isfile(os.path.join(downloads_dir, f))]
    except OSError:
        return []
    names.sort(
        key=lambda f: os.path.getmtime(os.path.join(downloads_dir, f)),
        reverse=True)
    out = []
    for f in names:
        path = os.path.join(downloads_dir, f)
        out.append({
            "filename": f, "path": path,
            "project":  project_name_from_zip(path),
            "date":     date_from_zip_name(f),
        })
    surname = _surname(client_hint)
    if not surname:
        return out
    match = [e for e in out if surname in (e["project"] or "").lower()]
    rest  = [e for e in out if surname not in (e["project"] or "").lower()]
    return match + rest


def import_zip(zip_path, pics_root, *, date_label="", force_subfolder="",
               tech=""):
    """Extract a CompanyCam zip's photos into the job's PICS folder,
    keeping CompanyCam's per-room organization. Each photo lands in
    PICS/<stage>/[<Tech date>/]<room>/. The <stage> is the user-picked
    `force_subfolder` when given, else the photo's own tag (Post / Demo /
    …), else a dated "CompanyCam <date>" fallback. The <room> is parsed
    from the filename ("Kitchen Post-1-…" → "Kitchen").

    `tech`: CompanyCam exports carry NO photographer, so the importer is
    told who shot the batch. When provided, a "<Tech> <date>" folder
    attributes the photos — inserted under the stage for tagged photos,
    or as the top container for untagged ones (replacing the generic
    "CompanyCam <date>"). Flattens the project top folder. Collision-safe.
    Returns {stage: count} aggregated for the toast."""
    if not zip_path or not os.path.isfile(zip_path):
        raise FileNotFoundError(zip_path)
    dlabel = (date_label or "").strip()
    fallback = ("CompanyCam " + dlabel).strip() or "CompanyCam"
    forced = (force_subfolder or "").strip()
    tech = _safe_folder(tech)
    tech_box = (f"{tech} {dlabel}".strip()) if tech else ""
    landed = {}
    with zipfile.ZipFile(zip_path, "r") as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            name = os.path.basename(info.filename.replace("\\", "/"))
            if not name or os.path.splitext(name)[1].lower() not in _IMAGE_EXTS:
                continue
            room, tag = parse_room_stage(name)
            stage = forced or tag            # "" when untagged
            if stage:
                dest_dir = os.path.join(pics_root, stage)
                if tech_box:
                    dest_dir = os.path.join(dest_dir, tech_box)
                landed_key = stage
            else:
                # Untagged: the tech box (or generic CompanyCam box) is
                # the container itself.
                dest_dir = os.path.join(pics_root, tech_box or fallback)
                landed_key = tech_box or fallback
            if room:
                dest_dir = os.path.join(dest_dir, room)
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, name)
            if os.path.exists(dest):
                stem, ext = os.path.splitext(name)
                k = 2
                while os.path.exists(
                        os.path.join(dest_dir, f"{stem} ({k}){ext}")):
                    k += 1
                dest = os.path.join(dest_dir, f"{stem} ({k}){ext}")
            with z.open(info) as src, open(dest, "wb") as dst:
                dst.write(src.read())
            landed[landed_key] = landed.get(landed_key, 0) + 1
    return landed


def summarize_landed(landed):
    """Short summary for the post-import toast, busiest folder first."""
    if not landed:
        return "(no photos extracted)"
    return ", ".join(f"{k} ({v})" for k, v in
                     sorted(landed.items(), key=lambda kv: -kv[1]))
