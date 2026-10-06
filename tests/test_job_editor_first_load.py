import pytest
import job_settings as js
import job_saved_data
import trello_client as tc
from job_settings_api import JobSettingsApi


def wire(monkeypatch, record, fail=False):
    monkeypatch.setattr(job_saved_data, 'resolve', lambda *a: ({'canon_key':'verified'}, 'EMS'))
    monkeypatch.setattr(js, '_record', lambda *a: record)
    def fetch(card):
        assert card == 'exact-card'
        if fail:
            raise RuntimeError('offline')
        return {'desc':'**CUSTOMER INFORMATION**\nCustomer Name: Fixture\nAddress: Test address\n**Scope**\nKitchen:\nWork'}
    monkeypatch.setattr(tc, 'get_card_lite', fetch)
    monkeypatch.setattr(js, '_persist', lambda *a, **k: pytest.fail('opening editor must not persist'))


def test_first_editor_load_populates_from_verified_card(monkeypatch):
    wire(monkeypatch, {'metadata':{}})
    result = JobSettingsApi().job_settings_load('Fixture', '', 'exact-card')
    assert result['ok']
    assert result['values']['customer_name'] == 'Fixture'
    assert result['values']['scope_initial'] == 'Kitchen:\nWork'


@pytest.mark.parametrize('meta', [{'settings':{'customer_name':''}}, {'trello_base':{'customer_name':'Old'}}])
def test_intentional_blank_is_not_reinitialized(monkeypatch, meta):
    wire(monkeypatch, {'metadata':meta})
    monkeypatch.setattr(tc, 'get_card_lite', lambda *a: pytest.fail('initialized fields must stay database-first'))
    result = JobSettingsApi().job_settings_load('Fixture', '', 'exact-card')
    assert result['ok'] and result['values']['customer_name'] == ''


def test_failed_first_load_does_not_open_empty_successful_editor(monkeypatch):
    wire(monkeypatch, {'metadata':{}}, fail=True)
    result = JobSettingsApi().job_settings_load('Fixture', '', 'exact-card')
    assert not result['ok']


def test_populated_record_does_not_fetch_provider(monkeypatch):
    wire(monkeypatch, {'phone':'555','metadata':{}})
    monkeypatch.setattr(tc, 'get_card_lite', lambda *a: pytest.fail('stored data is available'))
    assert JobSettingsApi().job_settings_load('Fixture', '', 'exact-card')['values']['phone'] == '555'


def test_first_save_keeps_untouched_preview_fields_and_explicit_clear(monkeypatch):
    record = {'metadata':{}}
    wire(monkeypatch, record)
    preview = JobSettingsApi().job_settings_load('Fixture', '', 'exact-card')
    monkeypatch.setattr(js, '_persist', lambda key, child, values, meta: record.update(metadata=meta.copy()))
    writes = []
    monkeypatch.setattr(tc, 'update_card_desc', lambda cid, desc: writes.append(desc) or True)
    result = js.save('verified', {'customer_name':''}, card_desc=preview['card_desc'],
                     edited_only=True, exact_card_id='exact-card')
    assert result['ok']
    reopened = JobSettingsApi().job_settings_load('Fixture', '', 'exact-card')
    assert reopened['values']['customer_name'] == ''
    assert reopened['values']['address'] == 'Test address'
    assert reopened['values']['scope_initial'] == 'Kitchen:\nWork'
    assert result['wrote_to_card'] == ['customer_name']
    assert len(writes) == 1
