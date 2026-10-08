import trello_client as tc
from pipeline_web import _job_info_sections


def categories(job, labels):
    sections = _job_info_sections(job, trello_card={'labels': labels})
    fields = {f['id']: f['value'] for s in sections for f in s['fields']}
    return fields.get('loss_categories', '')


def test_real_trello_other_labels():
    assert tc.card_loss_type({'labels': [
        {'name': 'OTHER - BIO'}, {'name': 'OTHER - CLEANING'},
        {'name': 'OTHER - SMOKE'}, {'name': 'OTHER - ODOR'},
        {'name': 'OTHER - BOARD UP'}, {'name': 'OTHER - VEHICLE'},
    ]}) == 'Smoke, Bio, Cleaning, Odor, Board Up, Vehicle'


def test_carrier_and_operational_labels_are_not_loss_types():
    assert tc.card_loss_type({'labels': ['STILLWATER', 'Team Lead', 'Fire department pending',
                                        'READY TO BILL', 'AAA', 'PACK OUT']}) == ''


def test_existing_aliases_and_multiple_types():
    assert tc.card_loss_type({'labels': ['Water Damage', 'Mold Job', 'WATER']}) == 'Water, Mold'


def test_exact_card_labels_supply_unset_category():
    assert categories({}, ['OTHER - BIO', 'OTHER - CLEANING']) == 'Bio, Cleaning'


def test_saved_choice_and_clear_are_never_overwritten():
    for value in ['Fire', '']:
        job = {'metadata': {'settings': {'loss_categories': value}}}
        assert categories(job, ['WATER', 'OTHER - BIO']) == value
