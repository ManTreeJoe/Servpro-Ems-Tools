import data_backup
from health_web import Api


def test_manual_backup_retains_attempt_for_health(monkeypatch):
    report = {'cloud.json': 'failed: HTTP 403'}
    monkeypatch.setattr(data_backup, '_LAST_REPORT', None)
    monkeypatch.setattr(data_backup, 'run_once', lambda force: report)
    monkeypatch.setattr(data_backup, 'health', lambda: {'ok': False})
    result = Api().run_backup()
    assert result['ok'] is False
    assert data_backup._LAST_REPORT == report


def test_directory_failure_is_not_success(monkeypatch):
    monkeypatch.setattr(data_backup, '_LAST_REPORT', None)
    monkeypatch.setattr(data_backup, 'run_once', lambda force: {'_error': 'Access denied'})
    monkeypatch.setattr(data_backup, 'health', lambda: {'ok': False})
    assert Api().run_backup()['ok'] is False


def test_skipped_export_is_not_verified_success(monkeypatch):
    monkeypatch.setattr(data_backup, '_LAST_REPORT', None)
    monkeypatch.setattr(data_backup, 'run_once', lambda force: {'cloud.json': 'skipped: sign-in required'})
    monkeypatch.setattr(data_backup, 'health', lambda: {'ok': True})
    assert Api().run_backup()['ok'] is False
