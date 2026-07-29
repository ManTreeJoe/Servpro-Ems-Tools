"""CompanyCam photo pull + new-photo check.

Network + disk-download are mocked; these pin: original-uri extraction,
the 'new since watermark' filter (incl. skipping still-processing photos),
capture-time filenames, dedup on re-run, and the per-project high-water
mark advancing (never rewinding)."""
import os

import companycam_api as cc
import persistence


def _photo(pid, captured_at, status="processed", url=None):
    return {
        "id": pid,
        "captured_at": captured_at,
        "processing_status": status,
        "uris": [
            {"type": "thumbnail", "uri": f"https://x/{pid}/t.jpg"},
            {"type": "web", "uri": f"https://x/{pid}/w.jpg"},
            {"type": "original", "uri": url or f"https://x/{pid}/o.jpg"},
        ],
    }


def _isolate(monkeypatch):
    monkeypatch.setattr(persistence, "_CACHE", {}, raising=False)
    monkeypatch.setattr(persistence, "_CACHE_MTIME", None, raising=False)
    monkeypatch.setattr(persistence, "_save",
                        lambda state: persistence.__dict__.update(
                            _CACHE=state, _CACHE_MTIME=None))
    monkeypatch.setattr(persistence, "_load", lambda: persistence._CACHE)


def test_original_uri_preferred():
    assert cc._original_uri(_photo("a", 100)) == "https://x/a/o.jpg"
    # Falls back to web when no original.
    p = {"uris": [{"type": "web", "uri": "https://x/w.jpg"}]}
    assert cc._original_uri(p) == "https://x/w.jpg"


def test_new_photos_filters_by_watermark(monkeypatch):
    monkeypatch.setattr(cc, "list_project_photos", lambda *a, **k: [
        _photo("old", 100), _photo("mid", 200), _photo("new", 300),
    ])
    got = cc.new_photos("proj", since_epoch=200)
    assert [p["id"] for p in got] == ["new"]          # strictly after 200
    assert cc.count_new_photos("proj", since_epoch=None) == 3  # all


def test_new_photos_skips_unprocessed(monkeypatch):
    monkeypatch.setattr(cc, "list_project_photos", lambda *a, **k: [
        _photo("ready", 300, status="processed"),
        _photo("wait", 400, status="processing"),
    ])
    got = cc.new_photos("proj", since_epoch=None)
    assert [p["id"] for p in got] == ["ready"]


def test_filename_carries_capture_and_id():
    p = cc._shape_photo(_photo("a1b2c3d4e5", 1_750_000_000))
    fn = cc._photo_filename(p)
    assert fn.startswith("CC ") and fn.endswith(".jpg")
    assert "a1b2c3d4" in fn                            # short id token


def test_pull_downloads_and_advances_watermark(monkeypatch, tmp_path):
    _isolate(monkeypatch)
    monkeypatch.setattr(cc, "list_project_photos", lambda *a, **k: [
        _photo("p1", 100), _photo("p2", 250),
    ])
    saved = []
    def _fake_dl(url, dest, **k):
        with open(dest, "wb") as fh:
            fh.write(b"jpg")
        saved.append(dest)
        return dest
    monkeypatch.setattr(cc, "_download", _fake_dl)

    res = cc.pull_new_photos("proj", str(tmp_path), since_epoch=None, job="Smith")
    assert res["ok"] and res["downloaded"] == 2 and res["skipped"] == 0
    assert res["latest"] == 250
    assert all(os.path.isfile(f) for f in res["files"])
    # Watermark advanced to newest capture.
    assert persistence.get_companycam_seen("proj")["last_captured_at"] == 250

    # Re-run with auto watermark → nothing new, no re-download.
    res2 = cc.pull_new_photos("proj", str(tmp_path), job="Smith")
    assert res2["downloaded"] == 0


def test_pull_dedups_on_rerun(monkeypatch, tmp_path):
    _isolate(monkeypatch)
    monkeypatch.setattr(cc, "list_project_photos",
                        lambda *a, **k: [_photo("p1", 100)])
    monkeypatch.setattr(cc, "_download",
                        lambda url, dest, **k: open(dest, "wb").write(b"x"))
    # First pull downloads; second (watermark disabled, same since) skips by name.
    cc.pull_new_photos("proj", str(tmp_path), since_epoch=None,
                       advance_watermark=False)
    res = cc.pull_new_photos("proj", str(tmp_path), since_epoch=None,
                             advance_watermark=False)
    assert res["downloaded"] == 0 and res["skipped"] == 1


def test_watermark_never_rewinds(monkeypatch):
    _isolate(monkeypatch)
    persistence.set_companycam_seen("proj", 500, job="Smith")
    persistence.set_companycam_seen("proj", 200)      # older — must not win
    assert persistence.get_companycam_seen("proj")["last_captured_at"] == 500
