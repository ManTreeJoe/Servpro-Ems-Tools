import pytest
import ems_db_supabase as db
import supabase_client as sb


@pytest.mark.parametrize('matching_link', [True, False])
def test_rejected_alias_link_uses_only_verified_existing_owner(monkeypatch, matching_link):
    writes = []
    denial = sb.SupabaseError(403, '{"code":"42501"}')
    def rest(method, table, **kw):
        writes.append(kw['body']['canon_key'])
        if writes[-1] == 'janette patterson':
            raise denial
    monkeypatch.setattr(db._sb, 'rest', rest)
    monkeypatch.setattr(db, 'get_job', lambda key: None)
    monkeypatch.setattr(db, 'find_job_by_name', lambda name: pytest.fail('Recovery must not run a broad name search'))
    def exact_rows(table, **kw):
        if table == 'job_aliases':
            assert kw['alias_canon'] == 'eq.janette patterson'
            return [{'canon_key':'patterson, janette'}]
        assert table == 'job_links' and kw['link_value'] == 'eq.card-id'
        return [{'canon_key':'patterson, janette' if matching_link else 'different job'}]
    monkeypatch.setattr(db, '_rows', exact_rows)
    if matching_link:
        db.set_link('janette patterson', 'trello_card', 'card-id')
        assert writes == ['janette patterson', 'patterson, janette']
    else:
        with pytest.raises(sb.SupabaseError):
            db.set_link('janette patterson', 'trello_card', 'card-id')
        assert writes == ['janette patterson']


def test_existing_canonical_job_denial_is_never_redirected(monkeypatch):
    def denied(*a, **kw):
        raise sb.SupabaseError(403, '{"code":"42501"}')
    monkeypatch.setattr(db._sb, 'rest', denied)
    monkeypatch.setattr(db, 'get_job', lambda key: {'canon_key':key})
    monkeypatch.setattr(db, 'find_job_by_name', lambda *a: pytest.fail('Redirected a real permission failure'))
    with pytest.raises(sb.SupabaseError):
        db.set_link('canonical job', 'trello_card', 'card-id')


def test_replay_acknowledges_verified_alias_only_after_shared_write(monkeypatch, tmp_path):
    import ems_db_offline as off
    monkeypatch.setattr(off, 'QUEUE_PATH', str(tmp_path / 'queue.jsonl'))
    off._queue_append('set_link', ['janette patterson','trello_card','card-id'], {})
    writes = []
    def rest(method, table, **kw):
        writes.append(kw['body']['canon_key'])
        if writes[-1] == 'janette patterson':
            raise sb.SupabaseError(403, '{"code":"42501"}')
    monkeypatch.setattr(db._sb, 'rest', rest)
    monkeypatch.setattr(db, 'get_job', lambda key: None)
    monkeypatch.setattr(db, 'find_job_by_name', lambda name: {'canon_key':'patterson, janette'})
    monkeypatch.setattr(db, '_rows', lambda *a, **kw: [{'canon_key':'patterson, janette'}])
    result = off.flush_queue()
    assert result['sent'] == 1 and result['pending'] == 0
    assert writes == ['janette patterson','patterson, janette']
