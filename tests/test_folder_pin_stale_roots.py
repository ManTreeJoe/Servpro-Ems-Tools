import config
import ems_db_common as common
import persistence


def test_existing_pin_resolves_when_root_cache_was_empty_at_startup(monkeypatch, tmp_path):
    root = tmp_path / 'office'
    folder = root / '2026 Jobs' / 'Evans Linda'
    folder.mkdir(parents=True)
    monkeypatch.setattr(common, '_DEPT_ROOTS_CACHE', [])
    monkeypatch.setattr(config, 'list_departments', lambda: [{'key':'IE'}])
    monkeypatch.setattr(config, 'load_for', lambda dept: {'audit_base': str(root)} if dept == 'IE' else {})
    monkeypatch.setattr(persistence, '_load', lambda: {'folder_paths': {
        'evans, linda': 'linguar-folder://IE/2026%20Jobs/Evans%20Linda'}})
    assert persistence.get_folder_path('Evans, Linda - AAA') == str(folder)


def test_unknown_department_never_uses_active_office(monkeypatch):
    monkeypatch.setattr(config, 'list_departments', lambda: [{'key':'IE'}])
    monkeypatch.setattr(common, '_DEPT_ROOTS_CACHE', [])
    monkeypatch.setattr(config, 'load_for', lambda dept: {})
    assert common.resolve_portable_folder_path('linguar-folder://UNKNOWN/Job') == ''
