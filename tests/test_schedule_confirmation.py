from copy import deepcopy
from unittest.mock import Mock

import pytest
import schedule_confirmation as sc

CARD = 'a' * 24
BASE = {'id': 'visit', 'job_id': 'job', 'revision': 3, 'date': '2026-10-05',
        'queue': 'scheduled', 'group': 'Work To Be Performed', 'title': 'Test job',
        'activities': [{'label': 'Demo', 'people': ['Sam']}], 'trello_cards': [CARD]}
BOARD = {'board_id': 'wip', 'name': 'WORK IN PROGRESS', 'lists': [
    {'id': 'old', 'name': 'TBS MITIGATION'}, {'id': 'work', 'name': 'WORK IN PROGRESS'},
    {'id': 'monitor', 'name': 'MONITOR'}, {'id': 'recon', 'name': 'RECONSTRUCTION'},
    {'id': 'closed', 'name': 'OLD', 'closed': True}]}


def store(visits=None, placements=None, mirrors=None, boards=None):
    s = Mock(department='IE')
    s.load.return_value = visits if visits is not None else [deepcopy(BASE)]
    s.request.side_effect = lambda table, **kw: {
        'app_job_boards': boards if boards is not None else [deepcopy(BOARD)],
        'app_card_placements': placements if placements is not None else [
            {'card_id': CARD, 'board_id': 'wip', 'list_id': 'old', 'state': 'active', 'version': 2}],
        'hub_trello_mirror_cards': mirrors or []}[table]
    return s


def test_preview_is_read_only_and_uses_current_placement():
    s = store()
    review = sc.preview(s, '2026-10-05')
    card = review['entries'][0]['cards'][0]
    assert card['version'] == 2
    assert card['suggested_list'] == 'work'
    assert [x['id'] for x in card['lanes']] == ['old', 'work', 'monitor']
    assert all('body' not in call.kwargs for call in s.request.call_args_list)


def test_monitor_extra_does_not_move_card():
    v = deepcopy(BASE)
    v['activities'].append({'label': 'Monitor', 'people': []})
    assert sc.preview(store([v]), v['date'])['entries'][0]['cards'][0]['suggested_list'] == 'old'
    v['group'] = 'Monitor'
    assert sc.preview(store([v]), v['date'])['entries'][0]['cards'][0]['suggested_list'] == 'monitor'


@pytest.mark.parametrize('name', ['ESTIMATING', 'RECON WORK IN PROGRESS', 'THE LOGS - EMS'])
def test_unsupported_board_not_offered(name):
    board = {**BOARD, 'name': name}
    assert sc.preview(store(boards=[board]), BASE['date'])['entries'][0]['cards'] == []


def test_archive_unlinked_and_other_day():
    s = store([deepcopy(BASE), {**BASE, 'date': '2026-10-06'}, {**BASE, 'queue': 'tbs'}],
              placements=[{'card_id': CARD, 'state': 'archived', 'board_id': 'wip', 'list_id': 'old'}])
    assert len(sc.preview(s, BASE['date'])['entries']) == 1
    assert sc.preview(s, BASE['date'])['entries'][0]['cards'] == []
    s = store([{**BASE, 'job_id': None, 'trello_cards': []}])
    assert 'Link this entry' in sc.preview(s, BASE['date'])['entries'][0]['note']


def test_mirror_fallback_and_multiple_candidates():
    s = store(placements=[], mirrors=[{'card_id': CARD, 'board_id': 'wip', 'present': True,
                                       'payload': {'idList': 'old', 'name': 'Mirror card'}}])
    assert sc.preview(s, BASE['date'])['entries'][0]['cards'][0]['version'] == 0
    v = {**BASE, 'trello_cards': [CARD, 'b' * 24]}
    ps = [{'card_id': cid, 'board_id': 'wip', 'list_id': 'old', 'state': 'active', 'version': 1}
          for cid in v['trello_cards']]
    assert 'Choose the card' in sc.preview(store([v], ps), v['date'])['entries'][0]['note']


def test_wrong_office_rejected():
    with pytest.raises(ValueError, match='Office changed'):
        sc.confirm(store(), {'department': 'OTHER'})
