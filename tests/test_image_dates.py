"""EXIF capture-date stamping for dateless imported photos (image_dates).

Locks the behavior the import 'when were these taken?' dialog relies on:
- a screenshot PNG with no EXIF is detected as undated
- stamping converts it to JPEG with an EXIF capture date that reads back
- an already-dated JPEG is left alone (not in find_undated)
"""
import datetime
from PIL import Image
import image_dates as idt


def _png(path, size=(8, 8)):
    Image.new("RGB", size, (120, 60, 30)).save(path, "PNG")
    return path


def test_screenshot_png_is_undated_then_stamped(tmp_path):
    p = _png(str(tmp_path / "image.png"))
    assert idt.has_capture_date(p) is False
    assert idt.find_undated(str(tmp_path)) == [p]

    n = idt.stamp_dates([p], datetime.date(2026, 6, 9), recycle=False)
    assert n == 1
    out = tmp_path / "image.jpg"
    assert out.exists()
    ex = Image.open(str(out)).getexif()
    taken = ex.get_ifd(0x8769).get(0x9003) or ex.get(0x0132)
    assert taken.startswith("2026:06:09")


def test_already_dated_jpeg_is_skipped(tmp_path):
    p = str(tmp_path / "shot.jpg")
    img = Image.new("RGB", (8, 8), (10, 20, 30))
    exif = img.getexif()
    exif.get_ifd(0x8769)[0x9003] = "2026:01:02 03:04:05"
    img.save(p, "JPEG", exif=exif)

    assert idt.has_capture_date(p) is True
    assert p not in idt.find_undated(str(tmp_path))


def test_stamp_folder_recurses(tmp_path):
    sub = tmp_path / "Kitchen"
    sub.mkdir()
    _png(str(sub / "a.png"))
    _png(str(tmp_path / "b.png"))
    n = idt.stamp_folder(str(tmp_path), datetime.date(2026, 6, 4),
                         recycle=False)
    assert n == 2
