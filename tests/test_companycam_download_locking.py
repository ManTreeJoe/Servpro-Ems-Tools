import os

import companycam_api as cc


def test_replace_download_retries_windows_share_lock(tmp_path, monkeypatch):
    temp = tmp_path / "photo.jpg.part.unique"
    final = tmp_path / "photo.jpg"
    temp.write_bytes(b"photo")
    real_replace = os.replace
    attempts = {"count": 0}

    def flaky_replace(src, dst):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise PermissionError(32, "file in use")
        return real_replace(src, dst)

    monkeypatch.setattr(cc.os, "replace", flaky_replace)
    monkeypatch.setattr(cc.time, "sleep", lambda _seconds: None)
    assert cc._replace_download(str(temp), str(final)) == str(final)
    assert final.read_bytes() == b"photo"
    assert attempts["count"] == 3


def test_replace_download_accepts_photo_finished_by_other_pull(tmp_path):
    temp = tmp_path / "photo.jpg.part.other"
    final = tmp_path / "photo.jpg"
    temp.write_bytes(b"duplicate")
    final.write_bytes(b"complete")
    assert cc._replace_download(str(temp), str(final)) == str(final)
    assert final.read_bytes() == b"complete"
    assert not temp.exists()


def test_failed_photo_does_not_advance_project_watermark(tmp_path, monkeypatch):
    photo = {"id": "3494721263", "captured_at": 100,
             "original_url": "https://example.test/photo.jpg",
             "creator_name": "Marco C", "tags": [],
             "processing_status": "processed"}
    monkeypatch.setattr(cc, "new_photos", lambda *_a, **_k: [photo])
    monkeypatch.setattr(cc, "_download", lambda *_a, **_k:
                        (_ for _ in ()).throw(PermissionError(32, "in use")))
    monkeypatch.setattr(cc, "route_photo", lambda *_a, **_k: {
        "division": "EMS", "stage_label": "Demo", "room": "",
        "stage": "Demo", "box": "", "parts": []})
    monkeypatch.setattr(cc, "_photo_filename", lambda *_a: "photo 3494721263.jpg")
    monkeypatch.setattr(cc, "_walk_all", lambda _roots: [])
    seen = []
    import persistence
    monkeypatch.setattr(persistence, "set_companycam_seen",
                        lambda *args, **kwargs: seen.append((args, kwargs)))

    result = cc.pull_new_photos("project", str(tmp_path), since_epoch=None)
    assert result["failed"] == 1
    assert result["watermark_advanced"] is False
    assert seen == []
