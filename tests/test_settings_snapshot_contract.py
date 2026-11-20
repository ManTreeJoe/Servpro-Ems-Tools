"""Pin the actual workbook-directory contract; no filesystem writes."""
import os
import settings_web
import snapshots_excel


def test_snapshot_controls_match_workbook_directory_reader(monkeypatch):
    default = next(row for row in settings_web.FIELDS if row[0] == 'snapshots_root')
    override = next(row for row in settings_web.DEPT_FIELDS if row[0] == 'snapshots_root')
    assert default[1:3] == override[1:3] == ('Snapshots folder', 'dir')
    monkeypatch.setattr(snapshots_excel, '_root', None)
    import config
    monkeypatch.setattr(config, 'load', lambda: {'snapshots_root': 'synthetic-folder'})
    assert snapshots_excel.workbook_path(2026) == os.path.join('synthetic-folder', 'Snapshots 2026.xlsx')
