import audit_web


def _api():
    return object.__new__(audit_web.Api)


def test_new_loss_defaults_to_folder_trello_and_companycam(monkeypatch):
    import companycam_api as cc
    import ems_db
    import new_loss_intake as nli

    monkeypatch.setattr(cc, "is_configured", lambda: True)
    monkeypatch.setattr(nli, "create_new_loss", lambda *a, **k: {
        "ok": True, "card_id": "card-1", "name": "Doe, Jane - AAA",
        "url": "https://trello.example/card-1", "template": "Water",
        "list": "New Loss",
    })
    monkeypatch.setattr(nli, "create_folder", lambda *a, **k: {
        "ok": True, "path": r"X:\IE_Public\2026 Jobs\Doe, Jane",
        "mode": "new_client",
    })
    cc_calls = []
    monkeypatch.setattr(nli, "create_companycam_project", lambda *a, **k: (
        cc_calls.append(k) or {
            "ok": True, "created": True, "pinned": True,
            "project": {"id": "cc-1"},
        }))
    linked = {}
    monkeypatch.setattr(ems_db, "resolve_and_link", lambda name, **kwargs: (
        linked.update(name=name, **kwargs) or {"canon_key": "doe, jane"}))

    result = _api().create_new_loss({"insured_name": "Doe, Jane"})

    assert result["ok"] is True
    assert result["provisioning"]["complete"] is True
    assert cc_calls[0]["confirm_create"] is True
    assert linked["trello_card"] == "card-1"
    assert linked["folder_path"].endswith("Doe, Jane")
    assert linked["companycam_project"] == "cc-1"


def test_new_loss_stops_before_creating_anything_without_companycam(monkeypatch):
    import companycam_api as cc
    import new_loss_intake as nli

    monkeypatch.setattr(cc, "is_configured", lambda: False)
    monkeypatch.setattr(nli, "create_new_loss", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("Trello card created before provisioning preflight")))

    result = _api().create_new_loss({"insured_name": "Doe, Jane"})

    assert result["ok"] is False
    assert "CompanyCam" in result["error"]


def test_new_loss_ui_does_not_offer_partial_provisioning():
    source = (audit_web.ASSETS_DIR + "\\app.js")
    with open(source, encoding="utf-8") as handle:
        js = handle.read()
    block = js[js.index("function openNewLossModal()"):js.index("// ── Client Memory modal")]
    assert "nl-make-companycam" not in block
    assert "CompanyCam project" in block
    assert "true,                                   // make_companycam" in block
