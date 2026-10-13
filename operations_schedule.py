"""Small, read-only counts from the current shared Schedule, not Run Docs."""
from datetime import date


def summarize(rows, today=None):
    today = today or date.today().isoformat()
    counts = dict(today_visits=0, tbs=0, pending=0, hold=0, needs_link=0,
                  past_visits=0, active_entries=0)
    seen = set()
    issues = []
    for row in rows:
        if row['id'] in seen:
            continue
        seen.add(row['id'])
        payload = row['payload']
        if payload.get('status') != 'active':
            continue
        counts['active_entries'] += 1
        counts['needs_link'] += int(not row.get('job_id'))
        reasons = [] if row.get('job_id') else ['Job link missing']
        queue = payload.get('queue')
        if queue in ('tbs', 'pending', 'hold'):
            counts[queue] += 1
        elif queue == 'scheduled':
            day = date.fromisoformat(payload['date']).isoformat()
            counts['today_visits'] += int(day == today)
            counts['past_visits'] += int(day < today)
            if day < today:
                reasons.append('Past visit still active: ' + day)
        else:
            raise ValueError('Unrecognized Schedule queue')
        if reasons:
            issues.append(dict(id='schedule:' + str(row['id']), category='Schedule',
                title=row.get('entry_title') or 'Schedule entry', severity='review',
                action='Review schedule', detail=' · '.join(reasons), target='run_doc_editor'))
    return dict(ok=True, source='shared_schedule', date=today, issues=issues, **counts)


class OperationsSchedule:
    def load(self):
        try:
            from schedule_store import ScheduleStore
            store = ScheduleStore()
            rows = []
            for offset in range(0, 10000, 500):
                batch = store.request('schedule_visits', params={
                    'department': 'eq.' + store.department,
                    'payload->>status': 'eq.active',
                    'select': 'id,job_id,entry_title,payload', 'order': 'id.asc',
                    'limit': 500, 'offset': offset})
                rows.extend(batch)
                if len(batch) < 500:
                    return summarize(rows)
            raise ValueError('Schedule is too large to summarize completely')
        except Exception as error:
            return dict(ok=False, source='shared_schedule', error=str(error))
