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
import datetime as _dt
import os
import re
import zipfile
from collections import Counter

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
    # Contents work goes to PICS/Contents. audit_logic has routed the
    # run-doc's Contents / Pack-out / Pack-in activities there all
    # along (see its `priority` table), but the TAG path never knew
    # the word — so a photo tagged "Contents" in CompanyCam became a
    # ROOM folder called Contents instead, one level down and outside
    # the stage the audit looks in. Pack-out/in absorb to Contents
    # here for the same reason they do there.
    ("post contents",     "Contents"),
    ("pack out",          "Contents"),
    ("pack-out",          "Contents"),
    ("packout",           "Contents"),
    ("pack in",           "Contents"),
    ("pack-in",           "Contents"),
    ("packin",            "Contents"),
    ("contents",          "Contents"),
    ("reinspection",      "Reinspection"),
    ("reinspect",         "Reinspection"),
    ("initial inspection", "Initial"),
    ("mold",              "Mold"),
    ("demo",              "Demo"),
    # Both are real stages and both are live CompanyCam tags, but this list
    # didn't know them — so a photo tagged "Monitor" became a ROOM folder
    # from CompanyCam while the Workcenter import (import_grouping) filed
    # the same word as a STAGE. Added 2026-07-30 to reconcile the two.
    ("monitor",           "Monitor"),
    ("equipment",         "Equipment"),
    ("initial",           "Initial"),
    ("inspection",        "Initial"),
    ("post",              "Post"),
]

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".jfif",
               ".webp", ".gif", ".bmp"}
# CompanyCam exports sometimes include clips. Keep them in the same stage
# container but tucked into a "Videos" subfolder (user rule, 2026-07-01) so
# they don't clutter the photo grid. Previously these were dropped entirely.
_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm",
               ".3gp", ".3g2", ".mts", ".m2ts", ".wmv", ".mpg",
               ".mpeg", ".hevc", ".flv"}
_MEDIA_EXTS = _IMAGE_EXTS | _VIDEO_EXTS
_VIDEO_SUBFOLDER = "Videos"


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
# CompanyCam's trailing "-<N>-<Mon DD YYYY HH_MMam>-<rand>" stamp. The
# label (room + optional stage tags) is whatever precedes it. An UNTAGGED
# photo is named just "<N>-<date>-<rand>.jpg" — the whole stem IS the
# stamp, so stripping it leaves an empty label (→ no room subfolder).
# Anchored at end so a room that happens to contain digits ("Room 2")
# isn't mis-split.
_CC_STAMP_RE = re.compile(
    r'-?\d+-[A-Za-z]{3} \d{1,2} \d{4} \d{1,2}_\d{2}[ap]m-\w+$',
    re.IGNORECASE)
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
      "Master Bath-19-…"                → ("Master Bath", "")
      "1-Jun 17 2026 05_08pm-GJrY"      → ("", "")   # fully untagged"""
    base = os.path.basename((filename or "").replace("\\", "/"))
    stem = os.path.splitext(base)[0]
    # Strip CompanyCam's trailing "-<N>-<date>-<rand>" stamp; the label is
    # what's left. A fully-untagged photo's whole stem is the stamp, so
    # the label comes back empty (→ no room subfolder).
    label = _CC_STAMP_RE.sub("", stem).strip()
    if label == stem:        # stamp didn't match — fall back to old split
        m = _LABEL_RE.match(base)
        label = (m.group(1) if m else stem).strip()
    return room_stage_from_label(label)


def room_stage_from_label(label):
    """(room, stage) from a photo's joined tag text.

    Split out of `parse_room_stage` so the API pull can share it. The zip
    export bakes tags INTO the filename; the API returns them as a list
    from GET /photos/{id}/tags. Same tags, two transports — they have to
    classify identically, or one job pulled both ways ends up in two
    different folder layouts.
    """
    label = (label or "").strip()
    for kw, folder in _STAGE_RULES:        # most-specific first
        mm = re.search(r'\b' + re.escape(kw) + r'\b', label, re.IGNORECASE)
        if mm:
            room = (label[:mm.start()] + " " + label[mm.end():])
            room = " ".join(room.replace("-", " ").split()).strip(" -")
            return _safe_folder(room), folder
    return _safe_folder(label), ""


def date_from_zip_name(filename):
    """The YYYY-MM-DD embedded in the zip filename, or "".

    NOTE: CompanyCam names the zip with the EXPORT date (the day you
    download it — usually today), NOT the photo capture date. Use
    `date_from_photos` for the real shoot date; keep this only as a
    last-resort fallback."""
    m = COMPANYCAM_ZIP_RE.match(os.path.basename(filename or ""))
    return m.group("date") if m else ""


# The capture date baked into each photo's filename stamp
# ("… -1-Jun 17 2026 05_08pm-GJrY.jpg").
_STAMP_DATE_RE = re.compile(
    r'-?\d+-([A-Za-z]{3} \d{1,2} \d{4}) \d{1,2}_\d{2}[ap]m-\w+',
    re.IGNORECASE)


# Full capture DATETIME baked into a photo's filename stamp
# ("Demo-1-Jun 30 2026 01_04pm-j78D.jpg" → 2026-06-30 13:04).
_STAMP_DT_RE = re.compile(
    r'-?\d+-([A-Za-z]{3} \d{1,2} \d{4} \d{1,2}_\d{2}[ap]m)-\w+',
    re.IGNORECASE)


def capture_datetime(name):
    """Parse the capture datetime from a CompanyCam photo filename, or None.
    'Demo-1-Jun 30 2026 01_04pm-j78D.jpg' → datetime(2026, 6, 30, 13, 4)."""
    m = _STAMP_DT_RE.search(os.path.basename(name or ""))
    if not m:
        return None
    stamp = m.group(1).replace("_", ":")   # "01_04pm" → "01:04pm"
    for fmt in ("%b %d %Y %I:%M%p", "%b %d %Y %I:%M %p"):
        try:
            return _dt.datetime.strptime(stamp, fmt)
        except ValueError:
            continue
    return None


def _apply_capture_time(path, name):
    """Set the file's modified/accessed time to the capture datetime parsed
    from its CompanyCam filename, so Explorer/OneDrive show the real shoot
    date instead of the import time. Best-effort — silently no-ops when the
    name has no parseable stamp."""
    cdt = capture_datetime(name)
    if cdt is None:
        return
    try:
        ts = cdt.timestamp()
        os.utime(path, (ts, ts))
    except (OSError, OverflowError, ValueError):
        pass


def retime_folder(folder):
    """Retro-fix an already-imported folder: walk it and set each photo's
    modified time from its filename's capture stamp. Returns the count of
    files updated. Use to repair imports done before this timestamping."""
    fixed = 0
    for root, _dirs, files in os.walk(folder or ""):
        for f in files:
            if capture_datetime(f) is None:
                continue
            _apply_capture_time(os.path.join(root, f), f)
            fixed += 1
    return fixed


def date_from_photos(zip_path):
    """The photo CAPTURE date (YYYY-MM-DD) read from the export's photo
    filename stamps — the REAL shoot date, unlike the zip name (which is
    the export/download date, i.e. today). Returns the most common date
    across the photos, or "" when none parse."""
    counts = Counter()
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                name = os.path.basename(info.filename.replace("\\", "/"))
                m = _STAMP_DATE_RE.search(name)
                if not m:
                    continue
                try:
                    d = _dt.datetime.strptime(m.group(1), "%b %d %Y")
                except ValueError:
                    continue
                counts[d.strftime("%Y-%m-%d")] += 1
    except Exception:
        return ""
    return counts.most_common(1)[0][0] if counts else ""


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
    """Extract a CompanyCam zip's photos into the job's PICS folder.
    Each photo's stage container is PICS/<stage>/[<Tech date>/]. The
    <stage> is the user-picked `force_subfolder` when given, else the
    photo's own tag (Post / Demo / …), else a dated "CompanyCam <date>"
    fallback.

    Per-room organization is decided PER stage container by the whole
    batch (user rule, 2026-06-19):
      • If a container's photos all share ONE room — or carry no room
        label at all — they land FLAT in the container (no per-room and
        no per-photo subfolders). "Flatten if the label is all the same."
      • If a container holds 2+ DISTINCT rooms, each photo goes into its
        own PICS/<stage>/[<Tech date>/]<room>/ subfolder. "Organize when
        they have room labels."

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
        # Pass 1: resolve each photo's stage container + room. Defer the
        # room-subfolder decision until we've seen the whole batch.
        entries = []   # {info, name, container, room, key, stage}
        for info in z.infolist():
            if info.is_dir():
                continue
            name = os.path.basename(info.filename.replace("\\", "/"))
            ext = os.path.splitext(name)[1].lower()
            if not name or ext not in _MEDIA_EXTS:
                continue
            is_video = ext in _VIDEO_EXTS
            room, tag = parse_room_stage(name)
            stage = forced or tag            # "" when untagged
            if stage:
                container = os.path.join(pics_root, stage)
                if tech_box:
                    container = os.path.join(container, tech_box)
                key = stage
            else:
                # Untagged: the tech box (or generic CompanyCam box) is
                # the container itself.
                container = os.path.join(pics_root, tech_box or fallback)
                key = tech_box or fallback
            entries.append({"info": info, "name": name, "container": container,
                            "room": room, "key": key, "stage": stage,
                            "is_video": is_video})

        # Single dominant stage → fold untagged stragglers into it.
        # When every TAGGED photo in the export shares ONE stage (e.g. all
        # "Post") but a few photos came in with no stage tag, route those
        # untagged photos into the SAME stage container rather than a
        # separate "<Tech> <date>" / "CompanyCam <date>" folder at the
        # PICS root. Otherwise one export splits into two same-named
        # tech-box folders — one under PICS/Post, a duplicate at the root
        # (the Munoz Joshua 06-19 case). Skipped when a stage was forced
        # (every photo already shares it) or when the export genuinely
        # spans 2+ stages (then untagged stays at the root, ambiguous).
        # (2026-06-19)
        if not forced:
            tagged_stages = {e["stage"] for e in entries if e["stage"]}
            if len(tagged_stages) == 1:
                only = next(iter(tagged_stages))
                only_container = os.path.join(pics_root, only)
                if tech_box:
                    only_container = os.path.join(only_container, tech_box)
                for e in entries:
                    if not e["stage"]:
                        e["container"] = only_container
                        e["key"] = only

        # Per-container distinct rooms → only split into per-room
        # subfolders when a container has 2+ of them.
        rooms_by_container = {}
        for e in entries:
            # Videos land in a flat Videos subfolder, so their room label
            # shouldn't drive the photos' per-room split decision.
            if e["room"] and not e["is_video"]:
                rooms_by_container.setdefault(
                    e["container"], set()).add(e["room"])
        multi_room = {c for c, rs in rooms_by_container.items()
                      if len(rs) >= 2}

        # De-dup against photos ALREADY on disk anywhere under pics_root.
        # CompanyCam filenames carry a unique token, so a matching basename
        # is the SAME photo re-exported — which happens when a project is
        # imported twice in a day (photos trickled in at different times).
        # Skip those instead of writing "name (2).jpg" duplicates, so the
        # two imports combine into one clean set. (user rule 2026-07-01)
        existing_names = set()
        for _root, _dirs, _files in os.walk(pics_root):
            for _f in _files:
                existing_names.add(_f.lower())

        # Pass 2: write each photo to its final folder.
        for e in entries:
            name = e["name"]
            if name.lower() in existing_names:
                continue   # already imported (same-day re-run) — combine
            if e["is_video"]:
                # Same stage container, but nested in a Videos subfolder.
                dest_dir = os.path.join(e["container"], _VIDEO_SUBFOLDER)
            else:
                dest_dir = e["container"]
                if e["room"] and e["container"] in multi_room:
                    dest_dir = os.path.join(dest_dir, e["room"])
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, name)
            if os.path.exists(dest):
                stem, ext = os.path.splitext(name)
                k = 2
                while os.path.exists(
                        os.path.join(dest_dir, f"{stem} ({k}){ext}")):
                    k += 1
                dest = os.path.join(dest_dir, f"{stem} ({k}){ext}")
            with z.open(e["info"]) as src, open(dest, "wb") as dst:
                dst.write(src.read())
            # Stamp the file's date from its filename's capture time so
            # Explorer / OneDrive sort by when the photo was actually taken,
            # not when it was imported.
            _apply_capture_time(dest, name)
            existing_names.add(name.lower())
            landed[e["key"]] = landed.get(e["key"], 0) + 1
    return landed


def summarize_landed(landed):
    """Short summary for the post-import toast, busiest folder first."""
    if not landed:
        return "(no photos extracted)"
    return ", ".join(f"{k} ({v})" for k, v in
                     sorted(landed.items(), key=lambda kv: -kv[1]))
