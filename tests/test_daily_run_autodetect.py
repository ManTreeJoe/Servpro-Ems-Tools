from pathlib import Path

import paths
import run_doc


def test_detects_nested_ie_sharepoint_daily_run(tmp_path, monkeypatch):
    daily = (tmp_path / "OneDrive - servpro10100.com"
             / "Servpro Team Lingurar-Run - Documents" / "EMS Daily Run")
    month = daily / "August"
    month.mkdir(parents=True)
    (month / "Thursday 8.27.26.docx").write_bytes(b"test")
    monkeypatch.setattr(paths.os.path, "expanduser", lambda value: str(tmp_path))

    detected = paths.auto_detect()

    assert Path(detected["runs_dir"]) == daily


def test_run_doc_prefers_detected_current_library(monkeypatch, tmp_path):
    current = tmp_path / "EMS Daily Run"
    current.mkdir()
    monkeypatch.setattr(run_doc.config, "load",
                        lambda: {"runs_dir": r"X:\IE_Public\Daily Run"})
    monkeypatch.setattr(run_doc.paths, "auto_detect",
                        lambda: {"runs_dir": str(current)})
    assert run_doc._runs_dir() == str(current)


def test_run_doc_respects_manually_selected_sharepoint_folder(monkeypatch,
                                                               tmp_path):
    selected = tmp_path / "Samantha SharePoint" / "EMS Daily Run"
    selected.mkdir(parents=True)
    other = tmp_path / "Other detected folder"
    other.mkdir()
    monkeypatch.setattr(run_doc.config, "load",
                        lambda: {"runs_dir": str(selected)})
    monkeypatch.setattr(run_doc.paths, "auto_detect",
                        lambda: {"runs_dir": str(other)})

    assert run_doc._runs_dir() == str(selected)


def test_run_doc_detects_folder_when_selected_folder_is_missing(monkeypatch,
                                                                 tmp_path):
    current = tmp_path / "Current EMS Daily Run"
    current.mkdir()
    monkeypatch.setattr(run_doc.config, "load",
                        lambda: {"runs_dir": str(tmp_path / "missing")})
    monkeypatch.setattr(run_doc.paths, "auto_detect",
                        lambda: {"runs_dir": str(current)})

    assert run_doc._runs_dir() == str(current)
