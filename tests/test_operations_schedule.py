from datetime import date
from operations_schedule import summarize, OperationsSchedule
from operations_hub import OperationsHub


def row(id, queue='scheduled', day='2026-10-12', job='j', status='active'):
    return dict(id=id, job_id=job, payload=dict(queue=queue, date=day, status=status))


def test_counts_are_entries_not_jobs_and_exclude_inactive():
    result = summarize([row('a'), row('b'), row('a'), row('c', 'tbs', job=None),
                        row('d', 'pending'), row('e', 'hold'),
                        row('f', day='2026-10-11'), row('g', status='completed'),
                        row('h', status='canceled')], '2026-10-12')
    assert result['today_visits'] == 2
    assert result['active_entries'] == 6
    assert result['tbs'] == result['pending'] == result['hold'] == result['needs_link'] == result['past_visits'] == 1


def test_unavailable_is_not_zero(monkeypatch):
    import schedule_store
    def unavailable():
        raise ValueError('Sign in')
    monkeypatch.setattr(schedule_store, 'ScheduleStore', unavailable)
    result = OperationsSchedule().load()
    assert not result['ok'] and 'today_visits' not in result


def test_compact_paged_office_scoped_reads(monkeypatch):
    import schedule_store
    calls = []
    class Store:
        department = 'IE'
        def request(self, path, params):
            calls.append((path, params))
            return [row(str(i)) for i in range(500)] if params['offset'] == 0 else []
    monkeypatch.setattr(schedule_store, 'ScheduleStore', Store)
    assert OperationsSchedule().load()['active_entries'] == 500
    assert [p['offset'] for _, p in calls] == [0, 500]
    assert all(p['department'] == 'eq.IE' and p['select'] == 'id,job_id,entry_title,payload' for _, p in calls)


def test_schedule_combines_reasons_and_deduplicates_entries():
    entry = dict(row('a', day='2026-10-11', job=None), entry_title='Example')
    result = summarize([entry, entry], '2026-10-12')
    assert len(result['issues']) == 1
    assert result['issues'][0]['title'] == 'Example'
    assert 'Job link missing' in result['issues'][0]['detail']
    assert 'Past visit still active' in result['issues'][0]['detail']


def test_attention_union_and_recon():
    jobs = OperationsHub._flatten_jobs([dict(key='recon', lanes=[dict(name='Work', cards=[
        dict(card_id='a', overdue=True, stall='warn', due=date.today().isoformat()+'T12:00:00Z')])])])
    overview = OperationsHub._overview(jobs, [])
    assert overview['needs_attention'] == overview['due_today'] == overview['divisions']['RECON'] == 1


def test_bootstrap_never_loads_dispatch_and_keeps_due_dates_separate():
    from tests.test_operations_hub import FakePipeline, FakeClients, FakeData
    class Dispatch:
        def load(self, jobs):
            raise AssertionError('Operations must not read Run Docs')
    class Schedule:
        def load(self): return dict(ok=True, today_visits=9)
    hub = OperationsHub(FakePipeline(), FakeClients(), FakeData(), dispatch=Dispatch(), schedule=Schedule())
    result = hub.bootstrap()
    assert result['schedule']['today_visits'] == 9
    assert result['overview']['due_today'] == 0
    assert 'dispatch' not in result
    # A successful empty board response must clear the previous counts.
    hub._pipeline.board_view = lambda *_: dict(ok=True, boards=[])
    assert hub.bootstrap(True)['overview']['active_jobs'] == 0
