"""Main posting hotfix: scratch outbox only; every provider call is blocked."""
import json
import urllib.request

import pytest

import job_workflow as workflow
import pipeline_web
import pipeline_store


SCOPE = {'version': 1, 'user_id': 'user-a', 'department': 'IE',
         'project': 'https://fixture.invalid', 'workspace': 'workspace-a',
         'trello_identity': 'credential-fingerprint'}


@pytest.fixture
def queue(monkeypatch, tmp_path):
    monkeypatch.setattr(workflow, 'DB_PATH', str(tmp_path / 'outbox.db'))
    monkeypatch.setattr(workflow, 'delivery_scope', lambda: dict(SCOPE))
    def forbidden(*args, **kwargs):
        pytest.fail('Live network call forbidden')
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', forbidden)
    monkeypatch.setattr('trello_client.post_comment', forbidden)
    monkeypatch.setattr('trello_client.update_comment', forbidden)
    monkeypatch.setattr('trello_client.delete_comment', forbidden)
    monkeypatch.setattr(workflow, 'acknowledge', acknowledge_scratch)
    monkeypatch.setattr(pipeline_store, 'pending_trello_changes', lambda: {
        'ok': True, 'mode': 'direct', 'queue_reason': 'schema_missing',
        'cards': [], 'comments': []})
    return workflow.queue_job_log('job', {'entry_id': 'entry'}, 'card', 'text')['operation_key']


def acknowledge_scratch(key, *, external_id=''):
    with workflow._connect() as conn:
        conn.execute("UPDATE trello_outbox SET status='complete',comment_id=? WHERE operation_key=?",
                     (external_id, key))


def row(key):
    with workflow._connect() as conn:
        return dict(conn.execute('SELECT * FROM trello_outbox WHERE operation_key=?', (key,)).fetchone())


def test_missing_optional_tables_deliver_once(queue, monkeypatch):
    calls = []
    monkeypatch.setattr('trello_client.post_comment', lambda *args: calls.append(args) or {'id': 'comment'})
    api = pipeline_web.Api()
    assert api._push_pending_trello()['job_logs'] == 1
    assert api._push_pending_trello()['job_logs'] == 0
    assert calls == [('card', 'text')]
    assert row(queue)['status'] == 'complete'


@pytest.mark.parametrize('failure', [
    {'ok': True, 'mode': 'direct', 'queue_reason': 'workspace_unscoped'},
    {'ok': False, 'error': 'HTTP 401 unauthorized'},
    {'ok': False, 'error': 'HTTP 403 permission denied'},
    {'ok': False, 'error': 'timeout'},
    {'ok': True, 'mode': 'direct', 'queue_reason': 'unknown'},
])
def test_scope_or_permission_failure_never_reads_outbox(queue, monkeypatch, failure):
    monkeypatch.setattr(pipeline_store, 'pending_trello_changes', lambda: failure)
    monkeypatch.setattr(workflow, 'pending', lambda: pytest.fail('Outbox must remain untouched'))
    pipeline_web.Api()._push_pending_trello()
    assert row(queue)['status'] == 'pending'


@pytest.mark.parametrize('field', ['user_id', 'department', 'project', 'workspace', 'trello_identity'])
def test_changed_owner_cannot_deliver(queue, monkeypatch, field):
    monkeypatch.setattr(workflow, 'delivery_scope', lambda: {**SCOPE, field: 'other'})
    assert pipeline_web.Api()._push_pending_trello()['job_logs'] == 0
    assert row(queue)['status'] == 'pending'


def test_legacy_origin_is_held_without_guessing(queue):
    with workflow._connect() as conn:
        conn.execute('UPDATE trello_outbox SET payload_json=? WHERE operation_key=?',
                     (json.dumps({'text': 'historic'}), queue))
    assert not pipeline_web.Api()._push_pending_trello()['ok']
    assert row(queue)['status'] == 'held'


@pytest.mark.parametrize('outcome', ['timeout', 'missing_id'])
def test_uncertain_send_is_never_reposted(queue, monkeypatch, outcome):
    calls = []
    def post(*args):
        calls.append(args)
        if outcome == 'timeout':
            raise TimeoutError('Unknown delivery outcome')
        return {}
    monkeypatch.setattr('trello_client.post_comment', post)
    api = pipeline_web.Api()
    assert not api._push_pending_trello()['ok']
    assert row(queue)['status'] == 'needs_review'
    api._push_pending_trello()
    assert len(calls) == 1


def test_context_changes_after_claim_are_held(queue, monkeypatch):
    original = workflow.claim_delivery
    def claim(key, scope):
        result = original(key, scope)
        monkeypatch.setattr(workflow, 'delivery_scope', lambda: {**SCOPE, 'user_id': 'other'})
        return result
    monkeypatch.setattr(workflow, 'claim_delivery', claim)
    assert not pipeline_web.Api()._push_pending_trello()['ok']
    assert row(queue)['status'] == 'needs_review'


def test_queue_refuses_scope_changed_during_save(queue, monkeypatch):
    monkeypatch.setattr(workflow, 'delivery_scope', lambda: {**SCOPE, 'department': 'OC'})
    result = workflow.queue_job_log('job', {'entry_id': 'new'}, 'card', 'text', SCOPE)
    assert not result['queued']


def test_claim_is_atomic_and_requires_matching_origin(queue):
    assert not workflow.claim_delivery(queue, {**SCOPE, 'user_id': 'other'})
    assert workflow.claim_delivery(queue, SCOPE)
    assert not workflow.claim_delivery(queue, SCOPE)


def test_real_scope_captures_routing_without_secrets(monkeypatch):
    import config
    import supabase_client as sb
    monkeypatch.setattr(config, 'load', lambda: {'trello_workspace_id': 'workspace',
                      'trello_api_key': 'secret-key', 'trello_token': 'secret-token'})
    monkeypatch.setattr(config, 'active_department', lambda: 'IE')
    monkeypatch.setattr(config, 'is_multi_dept', lambda: True)
    monkeypatch.setattr(sb, 'current_user', lambda: {'id': 'owner'})
    monkeypatch.setattr(sb, 'creds', lambda: ('https://fixture.invalid/', 'publishable'))
    scope = workflow.delivery_scope()
    assert scope['department'] == 'IE' and scope['user_id'] == 'owner'
    assert 'secret' not in json.dumps(scope)
    monkeypatch.setattr(sb, 'current_user', lambda: {})
    assert workflow.delivery_scope() == {}


def test_save_captures_origin_before_database_work(queue, monkeypatch):
    import audit_web
    import ems_db
    monkeypatch.setattr(ems_db, 'find_job_by_name', lambda _: {'canon_key': 'job'})
    def save(key, entry):
        monkeypatch.setattr(workflow, 'delivery_scope', lambda: {**SCOPE, 'user_id': 'other'})
        return {**entry, 'entry_id': 'new'}
    monkeypatch.setattr(ems_db, 'save_job_log_entry', save)
    result = audit_web.Api().save_crm_job_log('Job', {'work_type': 'Monitor'}, 'card')
    assert result['ok'] and not result['pending_sync']
    with workflow._connect() as conn:
        assert conn.execute("SELECT count(*) FROM trello_outbox WHERE entry_id='new'").fetchone()[0] == 0


def test_new_log_choice_is_preserved(queue, monkeypatch):
    import audit_web
    import ems_db
    monkeypatch.setattr(ems_db, 'find_job_by_name', lambda _: {'canon_key': 'job'})
    monkeypatch.setattr(ems_db, 'save_job_log_entry', lambda key, entry: {**entry, 'entry_id': 'new'})
    api = audit_web.Api()
    result = api.save_crm_job_log('Job', {'work_type': 'Monitor', 'post_to_trello': False}, 'card')
    assert result['ok'] and not result['pending_sync']
    assert result['entry']['source'] == 'pc_only'
    result = api.save_crm_job_log('Job', {'work_type': 'Monitor'}, 'card')
    assert result['ok'] and result['pending_sync']
    assert json.loads(row('job-log:new')['payload_json'])['origin_scope'] == SCOPE
