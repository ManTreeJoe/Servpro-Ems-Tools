import pytest
import job_log_records as records


def test_sections_read_fresh_exact_card_and_keep_distinct_entries(monkeypatch):
    import job_log_projection
    monkeypatch.setattr(job_log_projection, 'load', lambda *a: {'job_log': []})
    calls = []
    def refresh(card, division):
        calls.append((card, division))
        return {'ok': True, 'crm': {'job_log': [
            {'entry_id': 'crew', 'status':'completed', 'work_type':'Demo + Monitor',
             'technicians':'Demo: ME | Monitor: FB'},
            {'entry_id':'sub1', 'status':'completed', 'work_party':'subcontractor', 'subcontractor':'Titan'},
            {'entry_id':'sub2', 'status':'completed', 'work_party':'subcontractor', 'subcontractor':'Titan'},
            {'entry_id':'future', 'status':'scheduled'},
            {'entry_id':'deleted', 'status':'completed', 'deleted':True},
        ]}}
    monkeypatch.setattr(job_log_projection, 'refresh_saved', refresh)
    result = records.snapshot_sections('Fixture', 'exact-card', 'Contents')
    assert calls == [('exact-card', 'Contents')]
    assert [r['entry_id'] for r in result['logs']] == ['crew']
    assert result['logs'][0]['techs'] == 'Demo: ME | Monitor: FB'
    assert [r['entry_id'] for r in result['subs']] == ['sub1', 'sub2']


def test_refresh_failure_not_silently_replaced_with_cached_rows(monkeypatch):
    import job_log_projection
    monkeypatch.setattr(job_log_projection, 'load', lambda *a: {'job_log':[{'status':'completed'}]})
    monkeypatch.setattr(job_log_projection, 'refresh_saved', lambda *a: {'ok':False, 'error':'Offline'})
    with pytest.raises(RuntimeError, match='Offline'):
        records.snapshot_sections('Fixture','card')


def test_prefill_uses_saved_sections_even_when_trello_unavailable(monkeypatch):
    import snapshot_web, trello_client
    monkeypatch.setattr(trello_client, 'get_card', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('offline')))
    monkeypatch.setattr(records, 'snapshot_sections', lambda *a: {
        'logs':[{'entry_id':'crew'}], 'subs':[{'entry_id':'sub'}], 'job_log_source':'saved'})
    result = snapshot_web.Api().prefill_from_trello_card('card','Fixture','EMS')
    assert result['logs'] == [{'entry_id':'crew'}]
    assert result['subs'] == [{'entry_id':'sub'}]
