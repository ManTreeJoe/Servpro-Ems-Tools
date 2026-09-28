import pytest
import job_workspace_cache as cache
import job_log_projection as projection


@pytest.fixture
def saved(tmp_path, monkeypatch):
    import paths
    monkeypatch.setattr(paths, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(cache, 'scope', lambda: 'user:IE')
    monkeypatch.setattr(projection, 'request_dismissal_sync', lambda: None)
    rows = [dict(entry_id=eid, source='trello', source_id=source,
                 placement_card_id='card', work_type=source.split(':')[1])
            for eid, source in [('local','comment:Pack Out'),
                                ('remote','comment:Pack Out'),
                                ('keep','comment:EQ placed')]]
    cache.save('card','EMS','Job', {'ok':True,'crm':{'ok':True,
               'canon_key':'job','job_log':rows}})
    return rows


def test_same_source_does_not_show_twice(saved):
    assert len(projection.load('card','EMS')['job_log']) == 2


def test_saved_projection_carries_dismissal_ids_for_ui_merge(saved):
    result = projection.dismiss('card','EMS','local',scope_id=cache.scope())
    assert result['ok']
    loaded = projection.load('card','EMS')
    assert set(loaded.get('job_log_deleted_ids', [])) == {'local', 'remote'}


def test_repeated_dismissal_of_stale_visible_row_is_idempotent(saved):
    assert projection.dismiss('card','EMS','local',scope_id=cache.scope())['ok']
    again = projection.dismiss('card','EMS','local',scope_id=cache.scope())
    assert again['ok'], again
    assert 'local' in again['deleted_ids']


def test_primary_legacy_dismissal_survives_placement_backfill(saved):
    with cache.connect() as conn:
        state = projection._read(conn, cache.scope(), 'card', 'EMS')
        state['include_legacy'] = True
        state['entries']['legacy'] = {'entry_id':'legacy','source':'trello','source_id':'older:Demo'}
        projection._write(conn, cache.scope(), 'card', 'EMS', state)
    assert projection.dismiss('card','EMS','legacy',scope_id=cache.scope())['ok']
    cache.save('card','EMS','Job',{'ok':True,'crm':{'ok':True,'job_log':[
        {'entry_id':'new-id','source':'trello','source_id':'older:Demo','placement_card_id':'card'}]}})
    assert not any(row['source_id']=='older:Demo' for row in projection.load('card','EMS')['job_log'])


def test_legacy_source_suppression_does_not_cross_cards(saved):
    assert projection.dismiss('card','EMS','local',scope_id=cache.scope())['ok']
    cache.save('other','EMS','Job',{'ok':True,'crm':{'ok':True,'job_log':[
        {'entry_id':'other-id','source':'trello','source_id':'comment:Pack Out','placement_card_id':'other'}]}})
    assert projection.load('other','EMS')['job_log'][0]['entry_id'] == 'other-id'


def test_visible_legacy_import_can_be_dismissed_on_designated_primary(saved):
    with cache.connect() as conn:
        state = projection._read(conn, cache.scope(), 'card', 'EMS')
        state['include_legacy'] = True
        state['entries']['legacy'] = {'entry_id':'legacy','source':'trello','source_id':'older:Demo'}
        projection._write(conn, cache.scope(), 'card', 'EMS', state)
    assert any(r['entry_id']=='legacy' for r in projection.load('card','EMS')['job_log'])
    result = projection.dismiss('card','EMS','legacy',scope_id=cache.scope())
    assert result['ok'], result
    assert not any(r['entry_id']=='legacy' for r in projection.load('card','EMS')['job_log'])


def test_legacy_import_cannot_be_dismissed_from_secondary(saved):
    with cache.connect() as conn:
        state = projection._read(conn, cache.scope(), 'card', 'EMS')
        state['include_legacy'] = False
        state['entries']['legacy'] = {'entry_id':'legacy','source':'trello','source_id':'older:Demo'}
        projection._write(conn, cache.scope(), 'card', 'EMS', state)
    assert not projection.dismiss('card','EMS','legacy',scope_id=cache.scope())['ok']


def test_offline_dismiss_persists_before_any_network(saved, monkeypatch):
    import pipeline_web, ems_db
    monkeypatch.setattr(ems_db, 'find_job_by_name', lambda *a: pytest.fail('Network lookup in click'))
    monkeypatch.setattr(projection, 'request_dismissal_sync', lambda: None, raising=False)
    result = pipeline_web.Api().dismiss_job_log_update('Job','local','card','EMS')
    assert result['ok'] and result['pending_sync']
    assert set(result['deleted_ids']) == {'local','remote'}
    assert [r['entry_id'] for r in projection.load('card','EMS')['job_log']] == ['keep']
    cache.save('card','EMS','Job',{'ok':True,'crm':{'ok':True,'canon_key':'job','job_log':saved}})
    assert [r['entry_id'] for r in projection.load('card','EMS')['job_log']] == ['keep']


def test_dismissal_is_scoped(saved, monkeypatch):
    import pipeline_web
    monkeypatch.setattr(cache, 'scope', lambda:'other-user')
    result=pipeline_web.Api().dismiss_job_log_update('Job','local','card','EMS')
    assert not result['ok']


def test_failed_delivery_is_retained_then_shared_tombstone_hides_all_aliases(saved, monkeypatch):
    import ems_db_supabase as db
    missing=db._sb.SupabaseError(404,'{"code":"PGRST205","message":"crm_job_log_entries"}')
    monkeypatch.setattr(db,'_one',lambda *a,**k: (_ for _ in ()).throw(missing))
    projection.dismiss('card','EMS','local',scope_id=cache.scope())
    events = [{'id':i,'payload_json':__import__('json').dumps({'entry_id':row['entry_id'],'after':row})}
              for i,row in enumerate(saved)]
    monkeypatch.setattr(db,'log_event',lambda *a,**k: (_ for _ in ()).throw(TimeoutError()))
    with pytest.raises(TimeoutError):
        projection.sync_dismissals()
    assert projection.load('card','EMS')['job_log_dismissal_pending']
    def deliver(key,kind,*,payload):
        assert key == 'job'
        events.append({'id':20,'payload_json':__import__('json').dumps(payload)})
    monkeypatch.setattr(db,'log_event',deliver)
    projection.sync_dismissals()
    assert not projection.load('card','EMS')['job_log_dismissal_pending']
    monkeypatch.setattr(db,'_rows',lambda *a,**k:list(reversed(events)))
    rows = db._event_job_log_rows('job')
    assert [r['entry_id'] for r in rows] == ['keep']
    assert set(rows.deleted_ids) == {'local','remote'}


def test_local_save_failure_never_reports_success(saved, monkeypatch):
    import sqlite3
    monkeypatch.setattr(projection,'_write',lambda *a: (_ for _ in ()).throw(sqlite3.OperationalError('disk full')))
    result=projection.dismiss('card','EMS','local',scope_id=cache.scope())
    assert not result['ok']
    assert len(projection.load('card','EMS')['job_log']) == 2
    with cache.connect() as conn:
        projection._dismissal_table(conn)
        assert not conn.execute('SELECT * FROM job_log_dismissal_outbox').fetchall()


def test_legacy_saved_log_without_workspace_can_dismiss(saved):
    import json
    with cache.connect() as conn:
        state = projection._read(conn, cache.scope(), 'card', 'EMS')
        state.pop('canon_key', None)
        projection._write(conn, cache.scope(), 'card', 'EMS', state)
        conn.execute('DELETE FROM workspaces')
    result = projection.dismiss('card', 'EMS', 'local', scope_id=cache.scope())
    assert result['ok'] and result['pending_sync']
    assert [r['entry_id'] for r in projection.load('card','EMS')['job_log']] == ['keep']
    with cache.connect() as conn:
        intent = json.loads(conn.execute('SELECT payload FROM job_log_dismissal_outbox').fetchone()[0])
        assert not intent['canon_key']  # Resolve exact card in background, never guess a name.


def test_legacy_dismissal_resolves_exact_card_on_delivery(saved, monkeypatch):
    import ems_db_supabase as db
    with cache.connect() as conn:
        state=projection._read(conn,cache.scope(),'card','EMS')
        state.pop('canon_key',None)
        projection._write(conn,cache.scope(),'card','EMS',state)
        conn.execute('DELETE FROM workspaces')
    assert projection.dismiss('card','EMS','local',scope_id=cache.scope())['ok']
    def links(table, **filters):
        assert table == 'job_links'
        assert filters['link_value'] == 'eq.card'
        return [{'canon_key':'verified-job'}]
    monkeypatch.setattr(db,'_rows',links)
    missing=db._sb.SupabaseError(404,'{"code":"PGRST205","message":"crm_job_log_entries"}')
    monkeypatch.setattr(db,'_one',lambda *a,**k: (_ for _ in ()).throw(missing))
    delivered=[]
    monkeypatch.setattr(db,'log_event',lambda key,*a,**k:delivered.append(key))
    projection.sync_dismissals()
    assert delivered == ['verified-job']


def test_identity_survives_first_dismissal_and_workspace_invalidation(saved):
    import pipeline_web
    with cache.connect() as conn:
        state=projection._read(conn,cache.scope(),'card','EMS')
        state.pop('canon_key',None)
        projection._write(conn,cache.scope(),'card','EMS',state)
    api=pipeline_web.Api()
    assert api.dismiss_job_log_update('Job','local','card','EMS')['ok']
    with cache.connect() as conn:
        assert projection._read(conn,cache.scope(),'card','EMS')['canon_key'] == 'job'
        assert not conn.execute('SELECT * FROM workspaces').fetchall()
    assert api.dismiss_job_log_update('Job','keep','card','EMS')['ok']


def test_ambiguous_card_never_delivers_to_guessed_job(saved,monkeypatch):
    import ems_db_supabase as db
    with cache.connect() as conn:
        state=projection._read(conn,cache.scope(),'card','EMS')
        state.pop('canon_key',None)
        projection._write(conn,cache.scope(),'card','EMS',state)
        conn.execute('DELETE FROM workspaces')
    assert projection.dismiss('card','EMS','local',scope_id=cache.scope())['ok']
    monkeypatch.setattr(db,'_rows',lambda *a,**k:[{'canon_key':'one'},{'canon_key':'two'}])
    monkeypatch.setattr(db,'log_event',lambda *a,**k:pytest.fail('Must not send'))
    with pytest.raises(ValueError,match='ambiguous'):
        projection.sync_dismissals()
    assert projection.load('card','EMS')['job_log_dismissal_pending']
