from intake_names import names


def test_destinations():
    result = names({'insured_name': 'Lawrence Stidham', 'carrier': 'AAA'})
    assert result['trello'] == 'Stidham, Lawrence - AAA'
    assert result['folder'] == 'Stidham Lawrence'
    assert result['companycam'] == 'Lawrence Stidham'


def test_compound_surname_and_self_pay():
    result = names({'insured_name': 'De La O, Nicholas', 'carrier': 'selfpay'})
    assert result['trello'] == 'De La O, Nicholas - Self Pay'
    assert result['folder'] == 'De La O Nicholas'
    assert result['companycam'] == 'Nicholas De La O'


def test_explicit_parts_and_business():
    assert names({'first_name': 'Mary Ann', 'last_name': 'Van Buren'})['companycam'] == 'Mary Ann Van Buren'
    assert names({'insured_name': 'Example Business', 'customer_type': 'business'})['folder'] == 'Example Business'


def test_folder_parent_is_untouched():
    from new_loss_intake import _file_under
    assert _file_under({'insured_name': 'Jane Doe'}) == ('Doe Jane', False)
    assert _file_under({'insured_name': 'Jane Doe'}, 'Existing Parent') == ('Existing Parent', True)


def test_companycam_uses_person_name_but_pins_original_identity(monkeypatch):
    import new_loss_intake as n
    import companycam_api as cc
    import ems_db
    seen = {}
    monkeypatch.setattr(cc, 'is_configured', lambda: True)
    monkeypatch.setattr(ems_db, 'find_job_by_name', lambda name: None)
    monkeypatch.setattr(cc, 'find_project', lambda name, **kw: {'ok': True, 'match': None})
    def create(name, **kw):
        seen['name'] = name
        return {'ok': True, 'project': {'id': 'test'}}
    monkeypatch.setattr(cc, 'create_project', create)
    monkeypatch.setattr(n, '_pin_companycam', lambda name, *a, **kw: seen.update(identity=name) or True)
    result = n.create_companycam_project({'insured_name': 'Jane Doe'}, card_name='Doe, Jane - AAA', confirm_create=True)
    assert result['ok']
    assert seen == {'name': 'Jane Doe', 'identity': 'Doe, Jane - AAA'}
