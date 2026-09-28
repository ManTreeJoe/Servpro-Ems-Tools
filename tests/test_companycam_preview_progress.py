import companycam_api as cc


def test_photo_tech_summary_arrives_before_folder_and_tag_checks(monkeypatch):
    events = []
    monkeypatch.setattr(cc, "list_project_photos", lambda _: [
        {"id": "123456789", "creator_name": "Alex Tech", "captured_at": 1700000000}])
    def folder_check(_):
        assert events and events[0]["phase"] == "photos"
        assert events[0]["shoots"][0]["tech"]
        return False
    monkeypatch.setattr(cc.os.path, "isdir", folder_check)
    def tags(*args):
        assert events[0]["total"] == 1
        return ["Initial"]
    monkeypatch.setattr(cc, "photo_tags", tags)
    monkeypatch.setattr(cc, "flush_tag_cache", lambda: None)
    result = cc.plan_pull("project", "folder", progress_cb=events.append)
    assert result["ok"] and result["groups"][0]["stage"]
    assert any(e["phase"] == "tags" and e["done"] == 1 for e in events)
