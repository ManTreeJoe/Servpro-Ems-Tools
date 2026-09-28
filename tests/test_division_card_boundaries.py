from types import SimpleNamespace
import audit_web
import pytest


@pytest.mark.parametrize('board,expected', [('WORK IN PROGRESS','EMS'),
    ('WORK IN PROGRESS - 2026','EMS'), ('RECON WORK IN PROGRESS','RECON'),
    ('Contents Work In Progress','CONTENTS')])
def test_full_wip_board_names(board, expected):
    import division_cards
    assert division_cards.board_division(board) == expected


def reconcile(hits, opened='', division='EMS', pins=None):
    writes=[]
    api=SimpleNamespace(search_trello=lambda _: hits,
        crm_division_trello_cards=lambda _: {'cards': pins or []},
        pin_crm_division_trello=lambda *a: writes.append(a) or {'ok':True})
    result=audit_web.Api.reconcile_crm_division_trello_cards(api,'Fixture',opened,division)
    return result,writes


def hit(card,board,lane='Active'):
    return dict(card_id=card,name='Fixture',board=board,lane=lane,tier='active',score=1)


def test_opened_recon_card_cannot_replace_existing_ems_pin():
    result,writes=reconcile([hit('recon123','Recon'),hit('ems12345','WIP')],
        'recon123','EMS',[dict(division='EMS',card_id='ems12345')])
    assert not any(a[1]=='EMS' for a in writes)
    ems=next(d for d in result['divisions'] if d['division']=='EMS')
    assert ems['card_id']=='ems12345'


def test_unknown_board_is_not_automatically_ems():
    _,writes=reconcile([hit('unknown1','Unclassified')])
    assert writes==[]


def test_board_identity_wins_over_lane_name():
    _,writes=reconcile([hit('estimate','EMS Estimating','Contents question')])
    assert writes==[('Fixture','EMS','estimate')]


@pytest.mark.parametrize('board,actual', [('EMS WIP','EMS'),('Estimating','EMS'),
    ('Contents','CONTENTS'),('Recon','RECON')])
@pytest.mark.parametrize('wanted', ['EMS','CONTENTS','RECON'])
def test_pin_validates_provider_board_before_any_write(monkeypatch, board, actual, wanted):
    import division_cards
    monkeypatch.setattr('trello_client.get_card_lite', lambda _: {'id':'full-card-id','idBoard':'b'})
    monkeypatch.setattr('trello_client.list_boards', lambda: [{'id':'b','name':board}])
    if actual == wanted:
        assert division_cards.validate_pin('short-id',wanted)=='full-card-id'
    else:
        with pytest.raises(ValueError,match='existing pin was not changed'):
            division_cards.validate_pin('short-id',wanted)
        monkeypatch.setattr('ems_db.find_job_by_name', lambda _: pytest.fail('Wrong board reached database'))
        result=audit_web.Api.pin_crm_division_trello(SimpleNamespace(),'Fixture',wanted,'Abcd1234')
        assert not result['ok'] and 'existing pin was not changed' in result['error']


def test_opening_other_ems_placement_preserves_existing_primary():
    _,writes=reconcile([hit('estimate','Estimating'),hit('wip12345','WIP')],
        'estimate','EMS',[dict(division='EMS',card_id='wip12345')])
    assert writes==[]


def test_existing_wrong_division_pin_is_conflict_not_linked():
    result,_=reconcile([hit('recon123','Recon')],pins=[dict(division='EMS',card_id='recon123')])
    ems=next(d for d in result['divisions'] if d['division']=='EMS')
    assert ems['state']=='conflict' and ems['reason']=='saved_pin_wrong_division'


def test_unknown_provider_board_rejected(monkeypatch):
    import division_cards
    monkeypatch.setattr('trello_client.get_card_lite',lambda _: {'idBoard':'b'})
    monkeypatch.setattr('trello_client.list_boards',lambda: [{'id':'b','name':'Other'}])
    with pytest.raises(ValueError,match='Cannot verify'):
        division_cards.validate_pin('card','EMS')


def test_picker_filters_by_board_before_limiting(monkeypatch):
    import pipeline_web
    rows=[hit('recon','Recon'),hit('contents','Contents'),hit('ems','WIP'),hit('est','Estimating')]
    monkeypatch.setattr('card_search.search_local',lambda *a,**k: [])
    monkeypatch.setattr('trello_client.find_accessible_cards_by_name',lambda *a,**k: [])
    monkeypatch.setattr('card_search.merge',lambda *a: rows)
    result=pipeline_web.Api.global_card_search(SimpleNamespace(),'Fixture',24,'EMS')
    assert result['ok'] and {r['card_id'] for r in result['cards']}=={'ems','est'}
