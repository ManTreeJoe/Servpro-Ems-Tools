import pytest
import ems_db_supabase as db


def test_duplicate_card_owners_never_select_oldest(monkeypatch):
    monkeypatch.setattr(db._sb, 'rest', lambda *a, **k: [
        {'canon_key': 'empty placeholder'}, {'canon_key': 'populated job'}])
    monkeypatch.setattr(db, 'get_job', lambda key: {'canon_key': key})
    with pytest.raises(ValueError, match='multiple jobs'):
        db.find_job_by_link('trello_card', 'card')


def test_single_card_owner_still_resolves(monkeypatch):
    monkeypatch.setattr(db._sb, 'rest', lambda *a, **k: [{'canon_key': 'job'}])
    monkeypatch.setattr(db, 'get_job', lambda key: {'canon_key': key})
    assert db.find_job_by_link('trello_card', 'card') == {'canon_key': 'job'}


def test_sqlite_mirror_rejects_duplicate_owners(tmp_path, monkeypatch):
    import ems_db_sqlite as local
    monkeypatch.setattr(local, 'DB_PATH', str(tmp_path / 'links.db'))
    local._init_schema()
    first = local.upsert_job(display_name='Empty Placeholder')
    second = local.upsert_job(display_name='Populated Job')
    local.set_link(first, 'trello_card', 'card')
    assert local.find_job_by_link('trello_card', 'card')['canon_key'] == first
    local.set_link(second, 'trello_card', 'card')
    with pytest.raises(ValueError, match='multiple jobs'):
        local.find_job_by_link('trello_card', 'card')
