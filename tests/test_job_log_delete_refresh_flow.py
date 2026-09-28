import pytest
import job_workspace_cache as cache
import job_log_projection as projection
import pipeline_web


@pytest.fixture
def loaded(tmp_path, monkeypatch):
    import paths
    monkeypatch.setattr(paths, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(cache, 'scope', lambda: 'fixture:IE')
    monkeypatch.setattr(projection, 'request_dismissal_sync', lambda: None)
    entry = dict(entry_id='local-id', source='trello', source_id='comment:Pack Out',
                 placement_card_id='card', work_type='Pack Out', work_date='2026-09-10')
    cache.save('card','EMS','Fixture',dict(ok=True,crm=dict(ok=True,canon_key='fixture',job_log=[entry])))
    return entry


def test_delete_visible_entry_does_not_need_remote_uuid(loaded, monkeypatch):
    import ems_db
    monkeypatch.setattr(ems_db, 'find_job_by_name', lambda _: {'canon_key':'fixture'})
    monkeypatch.setattr(ems_db, 'list_job_log_entries', lambda _: [{**loaded,'entry_id':'shared-id'}])
    result = pipeline_web.Api().delete_job_log_update('Fixture','local-id','card','EMS')
    assert result['ok'], result
    assert result['pending_sync']
    cache.save('card','EMS','Fixture',dict(ok=True,crm=dict(ok=True,job_log=[
        loaded, {**loaded,'entry_id':'shared-id'}])))
    assert projection.load('card','EMS')['job_log'] == []
    again = pipeline_web.Api().delete_job_log_update('Fixture','local-id','card','EMS')
    assert again['ok']


def test_delete_manual_entry_is_durable_without_trello(loaded):
    with cache.connect() as conn:
        projection.merge(conn,cache.scope(),'card','EMS',dict(ok=True,job_log=[
            dict(entry_id='manual',source='pc_only',placement_card_id='card')]))
    result = pipeline_web.Api().delete_job_log_update('Fixture','manual','card','EMS')
    assert result['ok'], result
    with cache.connect() as conn:
        projection.merge(conn,cache.scope(),'card','EMS',dict(ok=True,job_log=[
            dict(entry_id='manual',source='pc_only',placement_card_id='card')]))
    assert all(r['entry_id'] != 'manual' for r in projection.load('card','EMS')['job_log'])


def test_snapshot_cannot_recreate_deleted_cached_activity(loaded, monkeypatch):
    from job_log_records import snapshot_rows
    import ems_db
    result = pipeline_web.Api().delete_job_log_update('Fixture','local-id','card','EMS')
    assert result['ok']
    monkeypatch.setattr(ems_db, 'find_job_by_name', lambda _: pytest.fail('Snapshot ignored saved deletion'))
    assert snapshot_rows('Fixture','card') == []


def test_native_reader_suppresses_shared_aliases():
    from job_log_records import visible_rows
    row = dict(entry_id='remote',source='trello',source_id='comment:Pack Out',placement_card_id='card')
    deleted = {**row,'entry_id':'local','deleted':True}
    result = visible_rows([row,{**row,'entry_id':'other','placement_card_id':'other-card'}],[deleted])
    assert [r['entry_id'] for r in result] == ['other']
    assert set(result.deleted_ids) == {'local','remote'}


def test_reimport_does_not_reparse_a_deleted_comment(tmp_path, monkeypatch):
    import ems_db, ems_db_sqlite as db, audit_web, snapshot_logic
    monkeypatch.setattr(db,'DB_PATH',str(tmp_path/'entries.db'))
    db._init_schema()
    key = db.upsert_job(display_name='Fixture')
    row = db.save_job_log_entry(key,dict(work_date='2026-09-10',work_type='Pack Out',
        source='trello',source_id='comment:Pack Out',trello_comment_id='comment',placement_card_id='card'))
    assert db.delete_job_log_entry(key,row['entry_id'],preserve_source=True)
    assert row['entry_id'] in db.list_job_log_entries(key).deleted_ids
    monkeypatch.setattr(ems_db,'find_job_by_name',db.find_job_by_name)
    monkeypatch.setattr(ems_db,'list_job_log_entries',db.list_job_log_entries)
    monkeypatch.setattr(ems_db,'save_job_log_entry',lambda *a: pytest.fail('Recreated deleted comment'))
    monkeypatch.setattr(snapshot_logic,'extract_job_log',lambda *a: pytest.fail('Reparsed already imported comment'))
    result = audit_web.Api().import_crm_job_log_comments('Fixture',[{'id':'comment','data':{'text':'Packout wording changed'}}],'card')
    assert result['ok'] and result['imported'] == 0, result


def test_explicit_refresh_preserves_cleanup_and_accepts_new_rows(loaded, monkeypatch):
    import ems_db
    assert pipeline_web.Api().delete_job_log_update('Fixture','local-id','card','EMS')['ok']
    monkeypatch.setattr(ems_db,'list_job_log_entries',lambda _: [
        {**loaded,'entry_id':'other-alias'},
        dict(entry_id='new',source='pc_only',placement_card_id='card')])
    result = pipeline_web.Api().refresh_saved_job_log('card','EMS')
    assert result['ok']
    assert [r['entry_id'] for r in result['crm']['job_log']] == ['new']
