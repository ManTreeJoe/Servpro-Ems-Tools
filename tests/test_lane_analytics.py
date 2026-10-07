from datetime import datetime, timezone
from lane_analytics import timeline, queues
from lane_analytics import IE_EST_BOARD, IE_LOGS_BOARD, IE_ESTIMATOR_LANES


def event(identity, day, lane, kind='updateCard', board='wip'):
    return dict(id=identity, date=f'2026-10-{day:02d}T00:00:00Z', type=kind,
                data=dict(board=dict(id=board, name=board), listAfter=dict(id=lane, name=lane)))


def test_returns_and_comments_do_not_reset_lane_clock():
    first = event('1', 1, 'wip')
    result = timeline([event('3', 4, 'wip'), first, first, event('2', 2, 'hold'),
                       event('4', 5, 'wip', kind='commentCard')],
                      dict(idBoard='wip', idList='wip'), datetime(2026,10,7,tzinfo=timezone.utc))
    assert [p['seconds'] for p in result['periods']] == [86400, 2*86400, 3*86400]
    assert result['current_seconds'] == 3*86400


def test_unknown_current_entry_is_not_last_activity():
    assert timeline([], dict(idBoard='wip', idList='hold', dateLastActivity='2026-10-01'))['current_seconds'] is None
    result = timeline([event('1', 1, 'wip')],dict(idBoard='wip',idList='other'))
    assert result['periods'][0]['seconds'] is None


def test_cross_board_without_lane_stops_old_clock():
    move = dict(id='2',type='moveCardFromBoard',date='2026-10-03T00:00:00Z',
                data=dict(boardTarget=dict(id='logs',name='Logs')))
    result = timeline([event('1',1,'Juan',board='est'),move],dict(idBoard='logs',idList='preserved'))
    assert result['periods'][0]['seconds'] == 2*86400
    assert result['current_seconds'] is None


def test_queues_keep_empty_lanes_and_do_not_use_proxy_days():
    result = queues(dict(boards=[dict(key='wip',board_id='b',name='WIP',lanes=[
        dict(list_id='l',name='TBS',cards=[dict(card_id='c',name='Job',days_in_lane=99)]),
        dict(list_id='e',name='Empty',cards=[])])]))
    assert len(result['lanes']) == 2
    assert result['lanes'][0]['cards'] == [dict(id='c',name='Job')]


def test_estimating_ends_on_logs_arrival_not_billed_and_reopens():
    lane = sorted(IE_ESTIMATOR_LANES)[0]
    events = [event('1',1,lane,board=IE_EST_BOARD),
              event('2',3,'preserved',kind='moveCardToBoard',board=IE_LOGS_BOARD),
              event('3',4,'billed',board=IE_LOGS_BOARD),
              event('4',5,lane,kind='moveCardToBoard',board=IE_EST_BOARD)]
    result = timeline(events,dict(idBoard=IE_EST_BOARD,idList=lane),datetime(2026,10,7,tzinfo=timezone.utc))
    assert [c['seconds'] for c in result['estimator_cycles']] == [2*86400,2*86400]
    assert result['estimator_cycles'][0]['ended'].startswith('2026-10-03')


def test_history_requires_allowed_card_and_paginates(monkeypatch):
    from lane_analytics import read_history
    import trello_client as tc
    calls=[]
    cid='a'*24
    monkeypatch.setattr(tc,'_call',lambda path,params: calls.append(params.copy()) or (
        [event(str(i),2,'lane') for i in range(1000)] if not params.get('before') else []))
    monkeypatch.setattr(tc,'get_card_lite',lambda *a,**kw:dict(idBoard='wip',idList='lane'))
    assert not read_history(cid,set())['ok']
    assert calls == []
    assert read_history(cid,{cid})['complete']
    assert calls[1]['before']=='999'
