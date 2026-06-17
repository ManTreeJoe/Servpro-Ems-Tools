"""Stamp an EXIF capture date onto imported photos that lack one.

CompanyCam (and most photo systems) date a photo by its EXIF
DateTimeOriginal, NOT the file's modified date. Screenshots, pasted
PNGs, and some downloads carry no EXIF date, so they upload with the
wrong (upload-day) date. These helpers detect dateless images in a
folder and stamp a chosen date — converting PNG/HEIC to JPEG, because
PNG/HEIC EXIF isn't reliably read by CompanyCam — so the date sticks.

Used by the import flow: after a WC / pick-a-file / SP import lands
photos with no date, the UI asks "when were these taken?" and calls
`stamp_dates` with the answer.
"""
import os
import datetime

from PIL import Image

try:                       # HEIC support (same backend the WC importer uses)
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pass

_DT_TAG   = 0x0132   # DateTime
_EXIF_IFD = 0x8769
_DTO_TAG  = 0x9003   # DateTimeOriginal
_DTD_TAG  = 0x9004   # DateTimeDigitized

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp",
              ".tif", ".tiff", ".heic", ".heif")


def has_capture_date(path):
    """True when the image already carries an EXIF capture date
    (DateTime or DateTimeOriginal) — i.e. nothing to fix."""
    try:
        ex = Image.open(path).getexif()
        return bool(ex.get(_DT_TAG) or ex.get_ifd(_EXIF_IFD).get(_DTO_TAG))
    except Exception:
        return False


def find_undated(folder):
    """Absolute paths of images under `folder` (recursive) with no EXIF
    capture date."""
    out = []
    if not folder or not os.path.isdir(folder):
        return out
    for root, _dirs, files in os.walk(folder):
        for f in files:
            if os.path.splitext(f)[1].lower() in IMAGE_EXTS:
                p = os.path.join(root, f)
                if not has_capture_date(p):
                    out.append(p)
    return out


def _uniq(path):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{stem} ({n}){ext}"):
        n += 1
    return f"{stem} ({n}){ext}"


def _recycle(path):
    try:
        from send2trash import send2trash
        send2trash(path)
        return True
    except Exception:
        pass
    bdir = os.path.join(os.path.dirname(path), "_originals")
    try:
        os.makedirs(bdir, exist_ok=True)
        os.replace(path, os.path.join(bdir, os.path.basename(path)))
        return True
    except Exception:
        return False


def stamp_dates(paths, when, *, recycle=True):
    """Stamp EXIF capture date = `when` on each image in `paths`,
    converting it to JPEG. `when` is a `datetime.date` (each file keeps
    its own time-of-day) or a full `datetime.datetime` (used verbatim).
    Originals are recycled (Recycle Bin, else moved to an `_originals`
    subfolder) unless `recycle=False`. Returns the count stamped.
    """
    is_dt = isinstance(when, datetime.datetime)
    base = when.date() if is_dt else when
    done = 0
    for p in paths:
        if not os.path.isfile(p):
            continue
        if is_dt:
            dt = when
        else:
            try:
                mt = datetime.datetime.fromtimestamp(os.path.getmtime(p))
                h, m, s = mt.hour, mt.minute, mt.second
            except OSError:
                h, m, s = 12, 0, 0
            dt = datetime.datetime(base.year, base.month, base.day, h, m, s)
        dtstr = dt.strftime("%Y:%m:%d %H:%M:%S")
        try:
            img = Image.open(p)
            img.load()
        except Exception:
            continue
        rgb = img.convert("RGB")
        exif = img.getexif()
        exif[_DT_TAG] = dtstr
        ifd = exif.get_ifd(_EXIF_IFD)
        ifd[_DTO_TAG] = dtstr
        ifd[_DTD_TAG] = dtstr
        out = _uniq(os.path.join(
            os.path.dirname(p),
            os.path.splitext(os.path.basename(p))[0] + ".jpg"))
        try:
            rgb.save(out, "JPEG", quality=95, exif=exif)
        except Exception:
            img.close()
            continue
        img.close()
        if recycle and os.path.normcase(out) != os.path.normcase(p):
            _recycle(p)
        done += 1
    return done


def stamp_folder(folder, when, *, recycle=True):
    """Convenience: stamp every dateless image under `folder`."""
    return stamp_dates(find_undated(folder), when, recycle=recycle)
