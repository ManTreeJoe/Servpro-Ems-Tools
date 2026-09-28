from datetime import datetime, timezone, timedelta
import pytest

import trello_mirror_reader as reader


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    reader._FAILURES.clear()
    import paths
    monkeypatch.setattr(paths, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(reader.cache, 'scope', lambda: 'user-ie')
    monkeypatch.setattr(reader.sb, 'current_user', lambda: {'id': 'user'})
    monkeypatch.setattr(reader.config, 'load', lambda: {'trello_workspace_id': 'workspace'})
    monkeypatch.setattr(reader.config, 'active_department', lambda: 'IE')
    monkeypatch.setattr(reader.sb, 'rpc', lambda *args: None)


def snapshot(**changes):
    return {'ready': True, 'safe_after': datetime.now(timezone.utc).isoformat(),
            'card': {'id': 'card', 'actions': [], 'checklists': [], 'attachments': []}, **changes}


def test_complete_saved_card_avoids_trello(monkeypatch):
    monkeypatch.setattr(reader.sb, 'rpc', lambda *args: snapshot())
    monkeypatch.setattr('trello_client.get_card', lambda *args: pytest.fail('No live card request expected'))
    assert reader.get_card('card')['_hub_source'] == 'server_mirror'


@pytest.mark.parametrize('value', [None, {}, snapshot(ready=False), snapshot(card={'id':'other'}),
                                     snapshot(safe_after='invalid')])
def test_missing_partial_stale_or_foreign_snapshot_falls_back(monkeypatch, value):
    # Invalid safe-after is rejected even without a prior write.
    monkeypatch.setattr(reader.sb, 'rpc', lambda *args: value)
    monkeypatch.setattr('trello_client.get_card', lambda *args: {'id':'live'})
    monkeypatch.setattr('trello_client.get_all_comments', lambda *args: [{'id':'comment','type':'commentCard'}])
    assert reader.get_card('card') == {'id':'live','actions':[{'id':'comment','type':'commentCard'}],
                                      '_comments_complete':True}


def test_write_barrier_survives_read_and_blocks_old_snapshot(monkeypatch):
    old = snapshot()
    reader.mark_write()
    monkeypatch.setattr(reader.sb, 'rpc', lambda *args: old)
    assert reader.card('card') is None
    new = snapshot(safe_after=(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat())
    monkeypatch.setattr(reader.sb, 'rpc', lambda *args: new)
    assert reader.card('card')


def test_scope_switch_during_read_is_discarded(monkeypatch):
    def rpc(*args):
        monkeypatch.setattr(reader.cache, 'scope', lambda: 'user-oc')
        return snapshot()
    monkeypatch.setattr(reader.sb, 'rpc', rpc)
    assert reader.card('card') is None


def test_concurrent_write_during_read_rejects_old_snapshot(monkeypatch):
    old = snapshot()
    def rpc(*args):
        reader.mark_write()
        return old
    monkeypatch.setattr(reader.sb, 'rpc', rpc)
    assert reader.card('card') is None


def test_rpc_uses_active_scope_and_signout_never_reads(monkeypatch):
    calls=[]
    monkeypatch.setattr(reader.sb, 'rpc', lambda *args: calls.append(args))
    reader.card('card')
    assert calls[0][1] == {'p_department':'IE','p_workspace':'workspace','p_card_id':'card'}
    monkeypatch.setattr(reader.sb, 'current_user', lambda: None)
    reader.card('card')
    assert len(calls) == 1


def test_board_requires_all_rows_ready(monkeypatch):
    rows=[{'ready':True,'safe_after':datetime.now(timezone.utc).isoformat()}]
    monkeypatch.setattr(reader.sb, 'rpc', lambda *args: {'boards':rows})
    assert reader.boards() == rows
    rows.append({'ready':False})
    assert reader.boards() is None


def test_pipeline_comments_uses_saved_card(monkeypatch):
    import pipeline_web
    monkeypatch.setattr(reader.sb, 'rpc', lambda *args: snapshot())
    monkeypatch.setattr('trello_client.get_card', lambda *args: pytest.fail('Live card fetch'))
    monkeypatch.setattr('trello_client.get_member_me', lambda: {})
    monkeypatch.setattr('pipeline_store.add_activities', lambda *args: None)
    monkeypatch.setattr('pipeline_store.list_activity', lambda *args: [])
    assert pipeline_web.Api().refresh_job_comments('card') == {'ok':True,'comments':[]}


def test_board_cache_not_shared_across_users(monkeypatch):
    import pipeline_store
    monkeypatch.setattr(reader.cache, 'scope', lambda: 'first-user')
    assert pipeline_store._cache_scope() == 'first-user'
    monkeypatch.setattr(reader.cache, 'scope', lambda: 'second-user')
    assert pipeline_store._cache_scope() == 'second-user'


def test_board_shapes_saved_snapshot_without_trello(monkeypatch):
    import pipeline_web as p
    monkeypatch.setattr(p, 'BOARD_SPECS', [('wip','WORK IN PROGRESS')])
    monkeypatch.setattr(reader, 'boards', lambda: [{
        'board': {'id':'board','name':'WORK IN PROGRESS'}, 'saved_at':'2026-09-18',
        'lists':[{'id':'lane','name':'Active','pos':1}],
        'cards':[{'id':'card','name':'Synthetic job','idList':'lane','pos':1,
                  'badges':{'checkItems':5,'checkItemsChecked':2}}]}])
    monkeypatch.setattr('trello_client._call', lambda *args, **kw: pytest.fail('Live board request'))
    result=p._server_board_payload()
    assert result['source']=='server_mirror'
    assert result['boards'][0]['lanes'][0]['cards'][0]['checklist']=={'done':2,'total':5}


def test_complete_mirror_does_not_resurrect_deleted_comments(monkeypatch):
    import pipeline_web as p
    monkeypatch.setattr(reader.sb, 'rpc', lambda *args: snapshot())
    monkeypatch.setattr('trello_client.get_member_me', lambda: {})
    monkeypatch.setattr('pipeline_store.add_activities', lambda *args: None)
    monkeypatch.setattr('pipeline_store.list_activity', lambda *args: [
        {'source':'trello','external_id':'deleted','body':'Old deleted note'},
        {'source':'linguar','activity_key':'pending','body':'New unsent note'}])
    result=p.Api().refresh_job_comments('card')
    assert [c['id'] for c in result['comments']]==['pending']


def test_server_projection_migration_is_service_only_and_complete_only():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    sql = (root / 'supabase' / 'migrations' /
           '20260921170000_trello_application_projection.sql').read_text(
               encoding='utf-8')
    assert 'c.comments_revision is distinct from p_revision' in sql
    assert 'c.details_revision is distinct from p_revision' in sql
    assert 'grant execute on function public.hub_trello_project_card' in sql
    assert 'to service_role' in sql
    assert 'from public, anon, authenticated' in sql
    assert 'source = \'trello\'' in sql
    optional_sql = (root / 'supabase' / 'migrations' /
                    '20260921171000_trello_projection_optional_target.sql').read_text(
                        encoding='utf-8')
    assert "to_regclass('public.crm_pipeline_cards') is null" in optional_sql
    assert "to_regclass('public.crm_pipeline_activity') is null" in optional_sql


def test_failed_mirror_read_backs_off_instead_of_repeating_for_each_card(monkeypatch):
    calls = []
    def broken(*args):
        calls.append(args)
        raise reader.sb.SupabaseError(500, 'fixture server failure')
    monkeypatch.setattr(reader.sb, 'rpc', broken)
    for card in ['a', 'b', 'c']:
        assert reader.card(card) is None
    assert len(calls) == 1


def test_mirror_recovers_after_backoff_and_does_not_block_another_scope(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(reader.time, 'monotonic', lambda: now[0])
    def broken(*args):
        raise reader.sb.SupabaseError(500, 'fixture failure')
    monkeypatch.setattr(reader.sb, 'rpc', broken)
    assert reader.card('card') is None
    calls = []
    monkeypatch.setattr(reader.sb, 'rpc', lambda *a: calls.append(a) or snapshot())
    assert reader.card('card') is None
    assert calls == []
    monkeypatch.setattr(reader.cache, 'scope', lambda: 'another-user')
    assert reader.card('card')
    monkeypatch.setattr(reader.cache, 'scope', lambda: 'user-ie')
    now[0] += 16
    assert reader.card('card')
    assert reader._FAILURES == {}


def test_incomplete_snapshot_does_not_start_failure_backoff(monkeypatch):
    monkeypatch.setattr(reader.sb, 'rpc', lambda *a: snapshot(ready=False))
    assert reader.card('card') is None
    monkeypatch.setattr(reader.sb, 'rpc', lambda *a: snapshot())
    assert reader.card('card')
