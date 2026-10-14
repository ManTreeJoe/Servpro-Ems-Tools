import json
import pytest
import app_error_reports as reports


def test_diagnostic_has_no_raw_customer_or_secret_text():
    shaped = reports.shape('pipeline', 'open_job', 'PGRST205 crm_pipeline_cards (cached) password=secret Sam customer@email.com')
    serialized = json.dumps(shaped)
    assert 'secret' not in serialized and 'customer@' not in serialized and 'Sam' not in serialized
    assert shaped['code'] == 'PGRST205'
    assert shaped['table_name'] == 'crm_pipeline_cards'
    assert shaped['cached'] is True


def test_api_wrapper_keeps_original_result_and_records_action(monkeypatch):
    calls = []
    monkeypatch.setattr(reports, 'report', lambda *args: calls.append(args))
    value = {'ok':False,'error':'PGRST205'}
    wrapped = reports.instrument('pipeline','save',lambda: value)
    assert wrapped() is value
    assert calls == [('pipeline','save','PGRST205')]


def test_api_wrapper_preserves_exception(monkeypatch):
    calls=[]
    monkeypatch.setattr(reports,'report',lambda *args: calls.append(args))
    def fail(): raise ValueError('failed')
    with pytest.raises(ValueError): reports.instrument('pipeline','save',fail)()
    assert calls[0][:2] == ('pipeline','save')


def test_unsigned_does_not_send(monkeypatch):
    monkeypatch.setattr(reports.sb,'current_user',lambda: None)
    assert reports.report('pipeline','save','error') is False


def test_native_bridge_keeps_named_arguments():
    import inspect
    class Api:
        def save(self, card_id, complete=False): return {'ok':True}
    wrapped = reports.instrument('pipeline','save',Api().save)
    assert inspect.getfullargspec(wrapped).args[1:] == ['card_id','complete']
    assert inspect.getfullargspec(wrapped).defaults == (False,)


def test_ambiguous_job_reference_has_actionable_safe_code():
    shaped = reports.shape('pipeline', 'visible_error',
        'Card: private-card\nValueError: This reference is linked to multiple jobs. Reconcile the links before editing.')
    assert shaped['code'] == 'reference_multiple_jobs'
    assert 'private-card' not in json.dumps(shaped)
