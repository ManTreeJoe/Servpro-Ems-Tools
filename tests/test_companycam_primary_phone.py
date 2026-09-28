import companycam_api as cc


def test_new_loss_multiple_phone_numbers_use_first_contact_number(monkeypatch):
    sent = []
    def provider(path, **kwargs):
        body = kwargs['data']
        phone = body['primary_contact'].get('phone_number', '')
        assert phone == '+19516967284', 'Do not send both customer phone numbers to CompanyCam'
        sent.append(body)
        return {'id': 'fixture', 'name': body['name']}
    monkeypatch.setattr(cc, '_call', provider)
    result = cc.create_project('Fixture', contact_name='Fixture',
                               contact_phone='(951) 696-7284 (951) 541-1084')
    assert result['ok'], result
    assert len(sent) == 1


def test_invalid_phone_does_not_block_project_creation(monkeypatch):
    def provider(path, **kwargs):
        assert 'phone_number' not in kwargs['data']['primary_contact']
        return {'id': 'fixture', 'name': 'Fixture'}
    monkeypatch.setattr(cc, '_call', provider)
    assert cc.create_project('Fixture', contact_name='Fixture', contact_phone='TBD')['ok']
