import companycam_api as cc
import companycam_web_api as web


def test_pull_adds_requested_tags_then_downloads(monkeypatch, tmp_path):
    api = object.__new__(web.CompanyCamApi)
    monkeypatch.setattr(web.CompanyCamApi, "_cc_resolve", lambda self, client, card="": ("p1", client))
    monkeypatch.setattr(web.CompanyCamApi, "_cc_pics_dir", lambda self, client: str(tmp_path))
    monkeypatch.setattr(web.CompanyCamApi, "_cc_contents_dir", lambda self, client: "")
    monkeypatch.setattr(web.CompanyCamApi, "_cc_docs_dir", lambda self, client: "")
    tagged = []
    monkeypatch.setattr(cc, "add_photo_tags", lambda pid, tags: tagged.append((pid, tags)) or {"ok": True})
    monkeypatch.setattr(cc, "pull_new_photos", lambda *args, **kwargs: {"downloaded": 2, "skipped": 0})

    result = api.companycam_pull_assigned("Doe, Jane", [{
        "photo_ids": ["1", "2"], "stage": "Demo", "tech": "FB",
        "tags": ["Mold", "Kitchen", "mold"],
    }])

    assert result["ok"] and result["pulled"] == 2 and result["tagged"] == 2
    assert tagged == [("1", ["Mold", "Kitchen"]), ("2", ["Mold", "Kitchen"])]
