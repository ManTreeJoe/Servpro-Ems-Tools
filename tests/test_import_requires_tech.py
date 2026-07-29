"""All IMAGE imports must attribute a tech.

do_import blocks companycam / wc_attachments without a tech; sp_copy_to_pics
blocks when no tech can be inferred. Docs imports stay exempt."""
import audit_web


def _api():
    return audit_web.Api.__new__(audit_web.Api)


def test_do_import_blocks_companycam_without_tech(tmp_path, monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "_resolve_client_path", lambda c: str(tmp_path))
    res = api.do_import("X", "companycam",
                        [str(tmp_path / "photos.zip")], "", "", "ems")
    assert res.get("need_tech") is True


def test_do_import_blocks_wc_attachments_without_tech(tmp_path, monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "_resolve_client_path", lambda c: str(tmp_path))
    res = api.do_import("X", "wc_attachments",
                        [str(tmp_path / "wc.zip")], "", "", "ems")
    assert res.get("need_tech") is True


def test_do_import_allows_image_with_tech(tmp_path, monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "_resolve_client_path", lambda c: str(tmp_path))
    # With a tech, it passes the guard (then fails later on the fake zip —
    # the point is it does NOT block for need_tech).
    res = api.do_import("X", "companycam",
                        [str(tmp_path / "photos.zip")], "", "Robert", "ems")
    assert res.get("need_tech") is not True


def test_docs_import_exempt_from_tech(tmp_path, monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "_resolve_client_path", lambda c: str(tmp_path))
    res = api.do_import("X", "docusign",
                        [str(tmp_path / "doc.zip")], "", "", "ems")
    assert res.get("need_tech") is not True


def test_docs_forced_pick_exempt(tmp_path, monkeypatch):
    # wc_attachments but user routed everything to DOCS → paperwork, no tech.
    api = _api()
    monkeypatch.setattr(api, "_resolve_client_path", lambda c: str(tmp_path))
    res = api.do_import("X", "wc_attachments",
                        [str(tmp_path / "wc.zip")], "DOCS", "", "ems")
    assert res.get("need_tech") is not True
