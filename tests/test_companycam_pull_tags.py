import companycam_api as cc
import companycam_web_api as web


def test_import_keeps_project_found_by_preview_when_lookup_later_fails(monkeypatch, tmp_path):
    api = web.CompanyCamApi()
    monkeypatch.setattr(api, "_cc_resolve", lambda *args: ("project-found", "Silvia Fenney"))
    monkeypatch.setattr(api, "_cc_pics_dir", lambda *args: str(tmp_path))
    monkeypatch.setattr(api, "_cc_contents_dir", lambda *args: "")
    monkeypatch.setattr(api, "_cc_docs_dir", lambda *args: "")
    monkeypatch.setattr(api, "_suggest_stages_from_run_doc", lambda *args: None)
    monkeypatch.setattr(cc, "plan_pull", lambda *a, **k: {"ok": True, "groups": [], "missing": 1})
    plan = api.companycam_plan_pull("Silvia Fenney")
    monkeypatch.setattr(api, "_cc_resolve", lambda *args: ("", ""))
    pulled = []
    monkeypatch.setattr(cc, "pull_new_photos", lambda pid, *a, **k:
                        pulled.append(pid) or {"downloaded": 1})
    result = api.companycam_pull_assigned("Silvia Fenney", [{"photo_ids": ["photo1"]}],
                                          project_id=plan.get("project_id", ""))
    assert result["ok"], result
    assert pulled == ["project-found"]


def test_pull_adds_requested_tags_then_downloads(monkeypatch, tmp_path):
    import companycam_stage_tags
    monkeypatch.setattr(companycam_stage_tags, 'approved_stage_tags', lambda: {'Initial': 'Initial Inspection', 'Demo': 'Demo'})
    api = object.__new__(web.CompanyCamApi)
    monkeypatch.setattr(web.CompanyCamApi, "_cc_resolve", lambda self, client, card="": ("p1", client))
    monkeypatch.setattr(web.CompanyCamApi, "_cc_pics_dir", lambda self, client: str(tmp_path))
    monkeypatch.setattr(web.CompanyCamApi, "_cc_contents_dir", lambda self, client, pics="": "")
    monkeypatch.setattr(web.CompanyCamApi, "_cc_docs_dir", lambda self, client, pics="": "")
    tagged = []
    monkeypatch.setattr(cc, "add_photo_tags", lambda pid, tags: tagged.append((pid, tags)) or {"ok": True})
    monkeypatch.setattr(cc, "pull_new_photos", lambda *args, **kwargs: {"downloaded": 2, "skipped": 0})

    result = api.companycam_pull_assigned("Doe, Jane", [{
        "photo_ids": ["1", "2"], "stage": "Demo", "tech": "FB",
    }])

    assert result["ok"] and result["pulled"] == 2 and result["tagged"] == 2
    assert tagged == [("1", ["Demo"]), ("2", ["Demo"])]

    tagged.clear()
    rejected = api.companycam_pull_assigned('Doe, Jane', [{
        'photo_ids': ['1'], 'stage': 'Initial', 'tags': ['Custom tag'],
    }])
    assert not rejected['ok']
    assert not tagged

    result = api.companycam_pull_assigned('Doe, Jane', [{
        'photo_ids': ['1'], 'stage': 'Initial',
    }])
    assert result['ok']
    assert tagged == [('1', ['Initial Inspection'])]
