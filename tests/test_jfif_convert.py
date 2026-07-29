"""convert_heic_in_dir also normalizes JFIF → JPEG (plain Pillow, no
pillow_heif needed)."""
import os

from PIL import Image

from wc_zip_import import convert_heic_in_dir


def _make_jfif(path):
    # A real JPEG written under a .jfif extension (how some phones save).
    Image.new("RGB", (8, 8), (120, 30, 200)).save(path, "JPEG")


def test_jfif_converted_to_jpg(tmp_path):
    src = tmp_path / "Image.jfif"
    _make_jfif(str(src))
    n = convert_heic_in_dir(str(tmp_path))
    assert n == 1
    assert (tmp_path / "Image.jpg").is_file()
    assert not src.exists()


def test_jfif_in_subfolder(tmp_path):
    sub = tmp_path / "RQ 7-8-26"
    sub.mkdir()
    _make_jfif(str(sub / "a.jfif"))
    _make_jfif(str(sub / "b.jfif"))
    assert convert_heic_in_dir(str(tmp_path)) == 2
    assert (sub / "a.jpg").is_file() and (sub / "b.jpg").is_file()


def test_existing_jpg_not_clobbered(tmp_path):
    _make_jfif(str(tmp_path / "photo.jfif"))
    Image.new("RGB", (4, 4), (0, 0, 0)).save(str(tmp_path / "photo.jpg"), "JPEG")
    convert_heic_in_dir(str(tmp_path))
    # Original photo.jpg survives; the converted one gets a suffix.
    assert (tmp_path / "photo.jpg").is_file()
    assert (tmp_path / "photo (2).jpg").is_file()


def test_plain_jpg_untouched(tmp_path):
    Image.new("RGB", (4, 4), (1, 2, 3)).save(str(tmp_path / "keep.jpg"), "JPEG")
    assert convert_heic_in_dir(str(tmp_path)) == 0
    assert (tmp_path / "keep.jpg").is_file()


def test_webp_converted_to_jpg(tmp_path):
    # CompanyCam / browsers often save .webp; normalize to .jpg like jfif.
    src = tmp_path / "shot.webp"
    Image.new("RGB", (8, 8), (10, 200, 90)).save(str(src), "WEBP")
    n = convert_heic_in_dir(str(tmp_path))
    assert n == 1
    assert (tmp_path / "shot.jpg").is_file()
    assert not src.exists()
