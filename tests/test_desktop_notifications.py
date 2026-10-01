from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import desktop_notifications as dn


def item(n, now, **extra):
    return dict(id=str(n), created_at=now.isoformat(), kind='mention', **extra)


def test_baseline_modes_read_muted_and_duplicates():
    now = datetime.now(timezone.utc)
    gate = dn.FreshItems()
    key = ('user', 'office', 'jobs')
    old = item(1, now - timedelta(seconds=5))
    assert gate.take(key, [old], now) == []
    fresh = item(2, now)
    assert gate.take(key, [fresh, old], now) == [fresh]
    assert gate.take(key, [fresh, old], now) == []
    assert gate.take(key, [item(3, now, muted=True), item(4, now, read_at='read')], now) == []
    assert gate.take(('other', 'office', 'jobs'), [item(5, now)], now) == []
    assert gate.take(('other', 'office', 'mentions'), [item(6, now)], now) == []
    comment = item(7, now); comment['kind'] = 'comment'
    assert gate.take(('other', 'office', 'mentions'), [comment], now) == []


def test_resume_does_not_flood_old_notifications():
    now = datetime.now(timezone.utc)
    gate = dn.FreshItems()
    key = ('user', 'office', 'jobs')
    gate.take(key, [], now - timedelta(hours=2))
    assert gate.take(key, [item(1, now - timedelta(hours=1))], now) == []


def test_preferences_scoped_and_validated(tmp_path, monkeypatch):
    monkeypatch.setattr(dn.paths, 'data', lambda _: str(tmp_path / 'prefs.db'))
    assert dn.preferences(('a', 'IE')) == 'off'
    assert dn.preferences(('a', 'IE'), 'jobs') == 'jobs'
    assert dn.preferences(('b', 'IE')) == 'off'
    assert dn.preferences(('a', 'OC')) == 'off'
    import pytest
    with pytest.raises(ValueError): dn.preferences(('a', 'IE'), 'anything')


def test_click_rechecks_identity(monkeypatch):
    monkeypatch.setattr(dn, 'identity', lambda: ('new-user', 'IE'))
    manager = dn.Manager(SimpleNamespace(), 'Dev')
    manager.open_item(('old-user', 'IE'), {'id': '1'})


def test_click_opens_exact_comment_and_marks_read(monkeypatch):
    import personal_notifications as pn
    calls, scripts = [], []
    scope = ('user', 'IE')
    monkeypatch.setattr(dn, 'identity', lambda: scope)
    row = {'id':'1', 'card_id':'card', 'comment_id':'comment'}
    def call(action, **data):
        calls.append((action, data))
        return {'ok':True, 'items':[row]}
    monkeypatch.setattr(pn, 'call', call)
    api = SimpleNamespace(_window=SimpleNamespace(evaluate_js=scripts.append), focus_window=lambda:None,
        _subs={'notifications':SimpleNamespace(notification_job=lambda c, a: {'ok':True, 'cardId':c, 'commentId':a})})
    dn.Manager(api, 'Dev').open_item(scope, row)
    assert '"commentId": "comment"' in scripts[0]
    assert calls[-1] == ('read', {'id':'1', 'read':True})


def test_poll_failure_does_not_establish_baseline(monkeypatch):
    import personal_notifications as pn
    monkeypatch.setattr(dn, 'identity', lambda: ('user', 'IE'))
    monkeypatch.setattr(dn, 'preferences', lambda _: 'jobs')
    monkeypatch.setattr(pn, 'call', lambda *a, **kw: {'ok':False})
    manager = dn.Manager(None, 'Dev')
    manager.poll()
    assert manager.fresh.key is None
    assert manager.error
    monkeypatch.setattr(pn, 'call', lambda *a, **kw: {'ok':True,'items':[item(1,datetime.now(timezone.utc))]})
    monkeypatch.setattr(manager, 'send', lambda *a: (_ for _ in ()).throw(AssertionError('Old item toasted')))
    manager.poll()
    assert manager.fresh.key == ('user', 'IE', 'jobs')
    assert manager.error == ''


def test_disabled_does_not_fetch(monkeypatch):
    import personal_notifications as pn
    monkeypatch.setattr(dn, 'identity', lambda: ('user', 'IE'))
    monkeypatch.setattr(dn, 'preferences', lambda _: 'off')
    monkeypatch.setattr(pn, 'call', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Disabled fetched')))
    dn.Manager(None, 'Dev').poll()
