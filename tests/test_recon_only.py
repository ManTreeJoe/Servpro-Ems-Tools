"""Recon-only jobs (RECON is the sole subfolder) aren't EMS's business and
must be kept off the Snapshots sheet."""
import snapshots_excel as sx


def _job(tmp_path, name, subdirs):
    d = tmp_path / name
    d.mkdir()
    for s in subdirs:
        (d / s).mkdir()
    return str(d)


def test_recon_sole_folder_is_recon_only(tmp_path):
    assert sx._is_recon_only(_job(tmp_path, "j", ["RECON"])) is True


def test_recon_case_and_name_variants(tmp_path):
    for i, nm in enumerate(("recon", "Recon", "RECON", "Reconstruction")):
        assert sx._is_recon_only(_job(tmp_path, f"job{i}", [nm])) is True, nm


def test_recon_plus_ems_work_is_not_recon_only(tmp_path):
    # EMS work often lives in root PICS/DOCS/CONTENTS with no "EMS" folder.
    for extra in ("PICS", "DOCS", "CONTENTS", "EMS", "Photos"):
        job = _job(tmp_path, f"j_{extra}", ["RECON", extra])
        assert sx._is_recon_only(job) is False, extra


def test_multi_unit_with_recon_is_not_recon_only(tmp_path):
    job = _job(tmp_path, "keystone",
               ["RECON", "Highland Village Unit 168", "Villa Vallerto OC"])
    assert sx._is_recon_only(job) is False


def test_no_recon_folder_not_flagged(tmp_path):
    assert sx._is_recon_only(_job(tmp_path, "j", ["EMS", "PICS"])) is False


def test_empty_or_missing_path_fail_open(tmp_path):
    assert sx._is_recon_only(_job(tmp_path, "empty", [])) is False
    assert sx._is_recon_only(str(tmp_path / "does_not_exist")) is False
    assert sx._is_recon_only("") is False


def test_delete_row_everywhere(tmp_path, monkeypatch):
    # Round-trip: write two rows, delete one by name across sheets.
    monkeypatch.setattr(sx, "workbook_path",
                        lambda y=None: str(tmp_path / "Snapshots.xlsx"))
    monkeypatch.setattr(sx, "_resolve_od_path", lambda r: "")  # no network
    yr = 2026
    wb, path = sx._ensure_workbook(yr)
    sx._apply_one(wb, yr, {"client": "Keep Me", "path": ""})
    sx._apply_one(wb, yr, {"client": "Drop Me", "path": ""})
    assert sx._delete_row_everywhere(wb, yr, "Drop Me") >= 1
    wb.save(path)
    names = [r.get("Name") for r in (sx.read_jobs(yr) or [])]
    assert "Keep Me" in names and "Drop Me" not in names


def test_sync_skips_recon_only(tmp_path, monkeypatch):
    # A recon-only job must not be written to the sheet on sync.
    monkeypatch.setattr(sx, "workbook_path",
                        lambda y=None: str(tmp_path / "Snapshots.xlsx"))
    monkeypatch.setattr(sx, "_is_recon_only", lambda p: p == "RECONPATH")
    monkeypatch.setattr(sx, "_resolve_od_path",
                        lambda r: "RECONPATH" if r.get("client") == "Recon Job"
                        else "")
    yr = 2026
    wb, _path = sx._ensure_workbook(yr)
    sx._apply_one(wb, yr, {"client": "Recon Job", "path": ""})
    sx._apply_one(wb, yr, {"client": "Ems Job", "path": ""})
    names = []
    for base in sx._ALL_SHEETS:
        title = sx._sheet_name(base, yr)
        if title in wb.sheetnames:
            ws = wb[title]
            for r in range(2, (ws.max_row or 1) + 1):
                v = ws.cell(r, sx._COL_INDEX["Name"]).value
                if v:
                    names.append(v)
    assert "Ems Job" in names and "Recon Job" not in names
