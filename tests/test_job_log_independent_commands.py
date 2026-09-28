import pytest


def test_edit_never_queues_a_trello_write(monkeypatch):
    import audit_web, ems_db, job_workflow
    entry = {'entry_id': 'e', 'source': 'trello', 'source_id': 'c:Demo',
             'trello_comment_id': 'c', 'placement_card_id': 'card'}
    monkeypatch.setattr(ems_db, 'find_job_by_name', lambda _: {'canon_key': 'job'})
    monkeypatch.setattr(ems_db, 'list_job_log_entries', lambda _: [entry])
    monkeypatch.setattr(ems_db, 'save_job_log_entry', lambda key, row: row)
    monkeypatch.setattr(job_workflow, 'queue_job_log', lambda *a: pytest.fail('Edit posted to Trello'))
    assert audit_web.Api().save_crm_job_log('Job', entry, 'card')['ok']


def test_delete_only_selected_log_and_preserves_comment(monkeypatch):
    import audit_web, ems_db, job_workflow, trello_client
    entries = [{'entry_id': key, 'source': 'trello', 'source_id': 'c:' + key,
                'trello_comment_id': 'c', 'placement_card_id': 'card'} for key in ('a', 'b')]
    calls = []
    monkeypatch.setattr(ems_db, 'find_job_by_name', lambda _: {'canon_key': 'job'})
    monkeypatch.setattr(ems_db, 'list_job_log_entries', lambda _: entries)
    monkeypatch.setattr(trello_client, 'delete_owned_comment', lambda *a: pytest.fail('Deleted source comment'))
    monkeypatch.setattr(ems_db, 'delete_job_log_entry', lambda key, entry, **kw: calls.append((entry, kw)) or True)
    monkeypatch.setattr(job_workflow, 'cancel_job_log_delivery', lambda *a: None)
    result = audit_web.Api().delete_crm_job_log('Job', 'a', 'card')
    assert result['ok'] and result['deleted_ids'] == ['a']
    assert result['entries'] == [entries[1]]
    assert calls == [('a', {'preserve_source': True})]


def test_pending_does_not_dispatch_legacy_comment_mutations(tmp_path, monkeypatch):
    import job_workflow as workflow
    monkeypatch.setattr(workflow, 'DB_PATH', str(tmp_path / 'queue.db'))
    with workflow._connect() as conn:
        conn.execute("INSERT INTO trello_outbox (operation_key,operation_type,job_key,entry_id,payload_json,created_at,updated_at) VALUES ('old','comment.update','j','e','{}','now','now')")
    assert workflow.pending() == []


def test_sqlite_delete_survives_reopen_and_reimport(tmp_path, monkeypatch):
    import ems_db_sqlite as db
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'logs.db'))
    db._init_schema()
    key = db.upsert_job(display_name='Independent log fixture')
    source = {'work_date': '2026-09-23', 'work_type': 'Demo',
              'source': 'trello', 'source_id': 'comment:Demo', 'placement_card_id': 'card'}
    saved = db.save_job_log_entry(key, source)
    assert db.delete_job_log_entry(key, saved['entry_id'], preserve_source=True)
    assert db.list_job_log_entries(key) == []
    # Each public call opens a fresh connection; neither stale edit nor an
    # explicit repeated import may resurrect the durable tombstone.
    assert db.save_job_log_entry(key, source)['deleted']
    assert db.save_job_log_entry(key, {**saved, 'note': 'stale'})['deleted']
    assert db.list_job_log_entries(key) == []
    assert db.job_log_history(saved['entry_id'])
