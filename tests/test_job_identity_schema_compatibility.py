import pytest

import pipeline_store as store


@pytest.mark.parametrize('extra', [{}, {'client_id': 'client-1', 'claim_id': 'claim-1'}])
def test_identity_graph_works_without_optional_job_columns(monkeypatch, extra):
    calls = []
    job = {'job_id': 'job-1', 'canon_key': 'smith, jane', **extra}

    def rest(method, table, *, params=None, **kwargs):
        calls.append((method, table, params))
        assert method == 'GET'
        if table == 'jobs':
            if params.get('select') != '*':
                requested = set(params['select'].split(','))
                if requested - set(job):
                    raise store._sb.SupabaseError(400, '{"code":"42703","message":"column jobs.client_id does not exist"}')
            return [job]
        assert table == 'job_aliases'
        return [{'alias_canon': 'jane smith', 'canon_key': 'smith, jane'}]

    monkeypatch.setattr(store._sb, 'rest', rest)
    index = store._job_identity_index()
    for title in ('Smith, Jane', 'Jane Smith'):
        result = store.resolve_card_identity(title, index)
        assert result == {'status': 'linked', 'job_id': 'job-1',
                          'client_id': extra.get('client_id'),
                          'claim_id': extra.get('claim_id')}
    assert len(calls) == 2
