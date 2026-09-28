from pathlib import Path

import audit_web
import clipboard_files
import pipeline_web


def _job_with_pics(tmp_path: Path) -> Path:
    job = tmp_path / "Exact Job Folder"
    stage = job / "EMS" / "PICS" / "Initial"
    stage.mkdir(parents=True)
    (stage / "photo.jpg").write_bytes(b"photo")
    return job


def test_xa_uses_current_local_pin_instead_of_stale_workspace_path(tmp_path, monkeypatch):
    job = _job_with_pics(tmp_path)
    monkeypatch.setattr(audit_web.persistence, "get_folder_path", lambda _client: str(job))
    result = audit_web.Api().list_pics_stages("Customer", str(tmp_path / "old folder"))
    assert result["ok"], result
    assert result["job_path"] == str(job)


def test_xa_real_staging_opens_folder_with_selected_files(tmp_path, monkeypatch):
    job = _job_with_pics(tmp_path)
    monkeypatch.setattr(audit_web.persistence, "get_folder_path", lambda _client: str(job))
    opened = []
    monkeypatch.setattr(clipboard_files.os, "startfile", lambda path: opened.append(path))
    result = audit_web.Api().copy_pics_to_clipboard("Customer", "Initial", str(job))
    assert result["ok"], result
    assert opened == [result["folder"]]
    assert (Path(result["folder"]) / "photo.jpg").read_bytes() == b"photo"


def test_xa_reports_explorer_failure_and_keeps_staged_files(tmp_path, monkeypatch):
    job = _job_with_pics(tmp_path)
    def fail_open(path):
        raise OSError("Explorer unavailable")
    monkeypatch.setattr(clipboard_files.os, "startfile", fail_open)
    result = audit_web.Api().copy_pics_to_clipboard("Customer", "Initial", str(job))
    assert not result["ok"], result
    assert "Explorer unavailable" in result["error"]
    assert (Path(result["folder"]) / "photo.jpg").exists()


def test_xa_stage_uses_the_exact_folder_already_pinned_to_the_job(tmp_path, monkeypatch):
    job = _job_with_pics(tmp_path)
    monkeypatch.setattr(audit_web.persistence, "get_folder_path", lambda _client: "")

    result = audit_web.Api().list_pics_stages(
        "Customer name does not match folder", str(job))

    assert result["ok"] is True
    assert result["job_path"] == str(job)
    assert [stage["name"] for stage in result["stages"]] == ["Initial"]


def test_xa_copy_keeps_using_the_same_exact_folder(tmp_path, monkeypatch):
    job = _job_with_pics(tmp_path)
    monkeypatch.setattr(audit_web.persistence, "get_folder_path", lambda _client: "")
    captured = {}

    def fake_stage(paths, **kwargs):
        captured["paths"] = list(paths)
        return {"ok": True, "count": len(paths), "folder": "staged"}

    monkeypatch.setattr(clipboard_files, "stage_files_in_temp", fake_stage)
    result = audit_web.Api().copy_pics_to_clipboard(
        "Customer name does not match folder", "Initial", str(job))

    assert result["ok"] is True
    assert captured["paths"] == [str(job / "EMS" / "PICS" / "Initial" / "photo.jpg")]


def test_pipeline_xa_stage_contract_passes_the_linked_folder_path():
    js = Path("pipeline_web_assets/app.js").read_text(encoding="utf-8")
    assert "list_pics_stages(client, jobPath)" in js
    assert "copy_pics_to_clipboard(client, button.dataset.stage || \"\", jobPath)" in js

    api = pipeline_web.Api()
    audit = type("Audit", (), {
        "list_pics_stages": lambda self, client, path: {"client": client, "path": path},
        "copy_pics_to_clipboard": lambda self, client, stage, path: {
            "client": client, "stage": stage, "path": path},
    })()
    api._audit = audit
    assert api.list_pics_stages("Customer", "X:/exact") == {
        "client": "Customer", "path": "X:/exact"}
    assert api.copy_pics_to_clipboard("Customer", "Initial", "X:/exact") == {
        "client": "Customer", "stage": "Initial", "path": "X:/exact"}


def test_xa_stage_surfaces_a_companycam_pdf_saved_directly_in_pics(tmp_path, monkeypatch):
    job = tmp_path / "De La O Nicholas"
    pics = job / "EMS" / "PICS"
    pics.mkdir(parents=True)
    report = pics / "De La O _companycam_report.pdf"
    report.write_bytes(b"pdf")
    monkeypatch.setattr(audit_web.persistence, "get_folder_path", lambda _client: "")
    captured = {}

    def fake_stage(paths, **kwargs):
        captured["paths"] = list(paths)
        return {"ok": True, "count": len(paths), "folder": "staged"}

    monkeypatch.setattr(clipboard_files, "stage_files_in_temp", fake_stage)
    api = audit_web.Api()
    listed = api.list_pics_stages("De La O, Nicholas - AAA", str(job))
    assert [(row["name"], row["count"]) for row in listed["stages"]] == [
        ("(root)", 1)]

    copied = api.copy_pics_to_clipboard(
        "De La O, Nicholas - AAA", "(root)", str(job))
    assert copied["ok"] is True
    assert captured["paths"] == [str(report)]
