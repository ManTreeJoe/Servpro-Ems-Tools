"""Exercise intake orchestration without creating any external records."""
import audit_web
import companycam_api as cc
import ems_db
import new_loss_intake as nli
import trello_client as tc


def test_completed_intake_publishes_companycam_link_on_created_card(monkeypatch):
    monkeypatch.setattr(cc, 'is_configured', lambda: True)
    monkeypatch.setattr(nli, 'create_new_loss', lambda *a, **k: {
        'ok': True, 'card_id': 'new-card', 'name': 'Test Intake'})
    monkeypatch.setattr(nli, 'create_folder', lambda *a, **k: {'ok': True, 'path': 'test-folder'})
    monkeypatch.setattr(nli, 'create_companycam_project', lambda *a, **k: {
        'ok': True, 'project': {'id': '123456'}, 'pinned': True})
    monkeypatch.setattr(ems_db, 'resolve_and_link', lambda *a, **k: {'canon_key': 'test'})
    attachments = []
    def call(path, *, method='GET', data=None, **kwargs):
        assert path == '/cards/new-card/attachments'
        if method == 'GET': return list(attachments)
        assert method == 'POST'
        attachment = dict(data, id='attachment-1')
        attachments.append(attachment)
        return attachment
    monkeypatch.setattr(tc, '_call', call)
    result = object.__new__(audit_web.Api).create_new_loss({'insured_name': 'Test Intake'})
    assert result['provisioning']['complete']
    assert tc.card_companycam_link({'attachments': attachments}) == 'https://app.companycam.com/projects/123456'
    assert nli.publish_companycam_link('new-card', '123456')['existing']
    assert len(attachments) == 1
    def offline(*args, **kwargs):
        raise OSError('offline')
    monkeypatch.setattr(tc, '_call', offline)
    failed = object.__new__(audit_web.Api).create_new_loss({'insured_name': 'Test Intake'})
    assert failed['ok']  # Card already exists; never invite whole-job recreation.
    assert not failed['provisioning']['complete']
    assert 'companycam_trello_link' in failed['provisioning']['failed']
    assert 'offline' in failed['companycam_trello_link']['error']


def test_ems_residential_is_default_even_when_water_template_arrives_first(monkeypatch):
    monkeypatch.setattr(nli, '_wip_board', lambda: {'id': 'board', 'name': 'WORK IN PROGRESS'})
    def call(path, **kwargs):
        if path.endswith('/lists'): return [{'id': 'templates', 'name': 'TEMPLATES'}]
        return [
            {'id': 'generic-water', 'name': 'Water Commercial', 'isTemplate': True, 'idList': 'templates'},
            {'id': 'ems-residential', 'name': 'EMS - Residential Template', 'isTemplate': True, 'idList': 'templates'},
        ]
    monkeypatch.setattr(tc, '_call', call)
    templates = nli.list_templates()
    assert templates['water']['id'] == 'ems-residential'
    assert object.__new__(audit_web.Api).new_loss_templates()['default_template_id'] == 'ems-residential'


def test_description_link_still_wins_and_unrelated_attachments_are_ignored():
    assert not tc.card_companycam_link({'attachments': [{'url': 'https://evil.example/projects/123'}]})
    assert tc.card_companycam_link({'desc': '**LINKS**\nCompanyCam Link: https://app.companycam.com/projects/original',
        'attachments': [{'url': 'https://app.companycam.com/projects/other'}]}) == 'https://app.companycam.com/projects/original'


def test_customer_and_card_title_are_stored_on_same_linked_job():
    import job_settings
    key = ems_db.upsert_job(display_name='Intake Test - Carrier', metadata={'keep': 'unchanged'})
    ems_db.set_link(key, ems_db.LINK_TRELLO, 'intake-facts-card')
    linked = ems_db.get_job(key)
    result = nli.save_intake_facts(linked, {'insured_name': 'Intake Test', 'address': '123 Test St', 'adjuster_number': '555-0100', 'additional_contacts': 'Tenant'}, 'Intake Test - Carrier')
    assert result['canon_key'] == key
    assert job_settings.stored_values(result)['customer_name'] == 'Intake Test'
    assert result['address'] == '123 Test St'
    assert job_settings.stored_values(result)['adjuster_phone'] == '555-0100'
    assert job_settings.stored_values(result)['addl_contacts'] == 'Tenant'
    metadata = job_settings._meta_of(result)
    assert metadata['keep'] == 'unchanged'
    assert metadata['intake_identity']['job_name'] == 'Intake Test - Carrier'
    assert ems_db.get_link(key, ems_db.LINK_TRELLO) == 'intake-facts-card'
