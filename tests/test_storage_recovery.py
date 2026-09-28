import pytest
import job_drafts
import job_workspace_cache as cache
import ems_db_sqlite as db


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    import paths, supabase_client
    monkeypatch.setattr(paths, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(supabase_client, 'current_user', lambda: {'id': 'test-user'})
    monkeypatch.setattr(cache, 'scope', lambda: 'account-a')
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'jobs.db'))
    db._init_schema()
    return tmp_path


def test_atomic_outbox_commits_both_and_nested_calls(isolated):
    def change():
        key = db.upsert_job(display_name='Atomic test')
        db.set_link(key, 'trello_card', 'exact-card')
        return key
    key = db._with_outbox({'fn': 'fixture'}, change)
    assert db.get_link(key, 'trello_card') == 'exact-card'
    assert db._outbox_entries()[0]['fn'] == 'fixture'


def test_local_failure_after_nested_commit_rolls_back_everything(isolated):
    def change():
        db.upsert_job(display_name='Must roll back')
        raise RuntimeError('Simulated process interruption before outbox insertion')
    with pytest.raises(RuntimeError):
        db._with_outbox({'fn': 'fixture'}, change)
    assert db.find_job_by_name('Must roll back') is None
    assert db._outbox_entries() == []


def test_outbox_insert_failure_rolls_back_local_change(isolated):
    with db._connect() as connection:
        db._outbox_table(connection)
        connection.execute("CREATE TRIGGER reject_intent BEFORE INSERT ON offline_outbox BEGIN SELECT RAISE(ABORT, 'disk failure fixture'); END")
        connection.commit()
    with pytest.raises(Exception, match='disk failure fixture'):
        db._with_outbox({'fn': 'fixture'}, lambda: db.upsert_job(display_name='Not committed'))
    assert db.find_job_by_name('Not committed') is None


def test_draft_survives_reopen_but_not_scope_or_card_switch(isolated, monkeypatch):
    initial = job_drafts.exchange('ems-card', 'EMS', 'comment')
    saved = job_drafts.exchange('ems-card', 'EMS', 'comment', payload={'text': 'Unsent'}, version=initial['version'], scope=initial['scope'])
    assert job_drafts.exchange('ems-card', 'EMS', 'comment')['payload']['text'] == 'Unsent'
    assert job_drafts.exchange('contents-card', 'CONTENTS', 'comment')['payload'] is None
    monkeypatch.setattr(cache, 'scope', lambda: 'account-b')
    assert job_drafts.exchange('ems-card', 'EMS', 'comment')['payload'] is None
    with pytest.raises(ValueError, match='changed'):
        job_drafts.exchange('ems-card', 'EMS', 'comment', payload=None, version=saved['version'], scope=saved['scope'])


def test_cleared_draft_cannot_be_resurrected_by_late_write(isolated):
    saved = job_drafts.exchange('card', 'EMS', 'job-log', payload={'note':'work'}, version=0)
    job_drafts.exchange('card', 'EMS', 'job-log', payload=None, version=saved['version'])
    with pytest.raises(ValueError, match='another window'):
        job_drafts.exchange('card', 'EMS', 'job-log', payload={'note':'stale'}, version=saved['version'])
    assert job_drafts.exchange('card', 'EMS', 'job-log')['payload'] is None


def test_signed_out_drafts_are_rejected(isolated, monkeypatch):
    import supabase_client
    monkeypatch.setattr(supabase_client, 'current_user', lambda: None)
    with pytest.raises(ValueError, match='Sign in'):
        job_drafts.exchange('card', 'EMS', 'comment')
