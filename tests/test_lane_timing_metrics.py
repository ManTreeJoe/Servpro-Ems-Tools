from datetime import datetime, timezone
from lane_analytics import timeline, IE_SNAPSHOT, IE_EST_BOARD, IE_ESTIMATOR_LANES, IE_LOGS_BOARD


def move(i, day, board, lane, name=None):
    return dict(id=str(i),type='updateCard',date=f'2026-10-{day:02d}T00:00:00Z',
                data=dict(board=dict(id=board,name=board),listAfter=dict(id=lane,name=name or lane)))


def test_snapshot_cycles_include_repeated_visits_and_unknown_open_end():
    estimator = sorted(IE_ESTIMATOR_LANES)[0]
    events = [move(1,1,IE_EST_BOARD,IE_SNAPSHOT),move(2,2,IE_EST_BOARD,estimator),
              move(3,3,IE_EST_BOARD,IE_SNAPSHOT)]
    result = timeline(events,dict(idBoard=IE_EST_BOARD,idList=IE_SNAPSHOT),datetime(2026,10,5,tzinfo=timezone.utc))
    assert [c['seconds'] for c in result['snapshot_cycles']] == [86400,172800]
    result = timeline(events,dict(idBoard='elsewhere',idList='missing'))
    assert result['snapshot_cycles'][-1]['seconds'] is None


def test_waiting_returns_and_unknown_are_separate_from_known_total():
    events = [move(1,1,'wip','hold','ON HOLD'),move(2,2,'wip','work'),move(3,3,'wip','hold','ON HOLD')]
    result = timeline(events,dict(idBoard='wip',idList='unrecorded'))
    assert result['waiting_lanes'][0] == dict(board='wip',lane='ON HOLD',seconds=86400,visits=2,unknown_visits=1)


def test_logs_without_assignment_does_not_join_snapshot_to_reopened_work():
    estimator = sorted(IE_ESTIMATOR_LANES)[0]
    events = [move(1,1,IE_EST_BOARD,IE_SNAPSHOT),move(2,2,IE_LOGS_BOARD,'received'),
              move(3,3,IE_EST_BOARD,estimator)]
    result = timeline(events,dict(idBoard=IE_EST_BOARD,idList=estimator))
    assert result['snapshot_cycles'][0]['seconds'] is None
    assert result['snapshot_cycles'][0]['ended'] is None


def test_logs_arrivals_without_estimator_and_internal_lane_changes():
    events = [move(1,1,IE_LOGS_BOARD,'received'),move(2,2,IE_LOGS_BOARD,'billed')]
    result = timeline(events,dict(idBoard=IE_LOGS_BOARD,idList='billed'),datetime(2026,10,5,tzinfo=timezone.utc))
    assert len(result['logs_arrivals']) == 1
    assert result['logs_age_seconds'] == 4*86400
    assert result['estimator_cycles'] == []
    events += [move(3,3,'wip','work'),move(4,4,IE_LOGS_BOARD,'received')]
    result = timeline(events,dict(idBoard=IE_LOGS_BOARD,idList='received'),datetime(2026,10,5,tzinfo=timezone.utc))
    assert len(result['logs_arrivals']) == 2
    assert result['logs_age_seconds'] == 86400
