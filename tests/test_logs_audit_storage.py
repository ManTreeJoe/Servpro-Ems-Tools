from copy import deepcopy
import pytest
from logs_audit_storage import SharedAuditStorage


class Local:
    def __init__(self, data=None): self.data = data or {}
    def get(self, key): return deepcopy(self.data)


class Database:
    def __init__(self): self.revision, self.rows, self.history = 0, {}, []
    def __call__(self, name, args):
        assert name == 'logs_audit_store' and args['p_department'] == 'IE'
        if 'p_changes' in args:
            if args['p_expected'] != self.revision: raise ValueError('40001')
            self.revision += 1
            for c in args['p_changes']:
                self.rows[c['kind'], c['id']] = deepcopy(c['payload'])
                self.history.append(deepcopy(c))
        return {'revision': self.revision, 'records': [
            {'kind': k, 'id': i, 'payload': deepcopy(v)} for (k, i), v in self.rows.items()]}


def test_shared_read_conflict_and_nested_snapshot_token():
    db = Database()
    a, b = [SharedAuditStorage(Local(), 'IE', db) for _ in range(2)]
    first, stale = a.load_store(), b.load_store()
    first['drafts']['card1'] = {'fields': {'ems_estimator': 'Mark L'}}
    a.save_store(first)
    assert b.load_store()['drafts'] == first['drafts']
    stale['drafts']['card1'] = {'fields': {'ems_estimator': 'Aaron'}}
    with pytest.raises(ValueError, match='Another reviewer'): b.save_store(stale)
    assert db.rows['drafts', 'card1']['fields']['ems_estimator'] == 'Mark L'
    first['operations']['op1'] = {'status': 'posting'}
    a.save_store(first)  # successful writes advance this snapshot's token
    assert db.revision == 2


def test_legacy_import_once_preserves_conflicts_and_tombstones():
    db = Database()
    db.rows['drafts', 'existing'] = {'fields': {'ems_estimator': 'Shared'}}
    db.rows['operations', 'canceled'] = None
    local = Local({'drafts': {'existing': {'fields': {'ems_estimator': 'Old'}},
                             'new': {'fields': {'ems_estimator': 'Zac'}}},
                   'operations': {'canceled': {'card_id': 'new'}, 'old': {'card_id': 'existing'}}})
    original = deepcopy(local.data)
    a = SharedAuditStorage(local, 'IE', db)
    store = a.load_store()
    assert store['drafts']['existing']['fields']['ems_estimator'] == 'Shared'
    assert store['drafts']['new']['fields']['ems_estimator'] == 'Zac'
    assert not store['operations']
    assert local.data == original
    assert next(v for (k, _), v in db.rows.items() if k == 'legacy') == original
    rev = db.revision
    a.load_store()
    assert db.revision == rev


def test_failed_database_has_no_local_success_fallback():
    def broken(*args): raise OSError('network failure with sensitive details')
    with pytest.raises(ValueError, match='Shared audit database unavailable') as error:
        SharedAuditStorage(Local(), 'IE', broken).load_store()
    assert 'sensitive' not in str(error.value)


def test_canceled_preview_remains_tombstoned():
    db = Database(); a = SharedAuditStorage(Local(), 'IE', db)
    store = a.load_store(); store['operations']['op'] = {'status': 'preview'}
    a.save_store(store)
    del store['operations']['op']; a.save_store(store)
    assert not a.load_store()['operations']
    assert db.rows['operations', 'op'] is None


def test_legacy_evidence_null_sentinel_roundtrips_without_invalid_postgres_json():
    import json
    db = Database(); a = SharedAuditStorage(Local(), 'IE', db)
    store = a.load_store()
    store['drafts']['card'] = {'evidence': {'ignore_marker': '\0'}, 'revision': 'unchanged'}
    a.save_store(store)
    assert '\\u0000' not in json.dumps(db.rows['drafts', 'card'])
    assert a.load_store()['drafts'] == store['drafts']
