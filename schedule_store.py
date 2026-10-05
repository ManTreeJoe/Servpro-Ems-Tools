"""User-bound digital schedule adapter. No Word/Trello or offline fallback."""
import base64
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request

import config
import schedule_records
import supabase_client as sb

JOB_FIELDS = 'job_id,display_name,address,phone,email,carrier,claim_number'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Schedule server redirected the request. Save stopped.')


def context():
    url, key = sb.creds()
    user = str((sb.current_user() or {}).get('id') or '')
    department = str(config.active_department() or '')
    if not user or not department:
        raise ValueError('Sign in and select an office to use Schedule.')
    return url, key, user, department


def context_id(values):
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


class ScheduleStore:
    def __init__(self, expected_context=None):
        self.binding = context()
        self.context_id = context_id(self.binding)
        if expected_context and expected_context != self.context_id:
            raise ValueError('Account or office changed. Reopen Schedule before editing.')
        self.url, self.key, self.user, self.department = self.binding
        if urllib.parse.urlparse(self.url).scheme != 'https':
            raise ValueError('Schedule requires HTTPS.')
        self.token = sb.access_token()
        part = self.token.split('.')[1]
        subject = json.loads(base64.urlsafe_b64decode(part + '=' * (-len(part) % 4)))['sub']
        if subject != self.user:
            raise ValueError('Account changed. Sign in again.')
        self.opener = urllib.request.build_opener(_NoRedirect())
        self.check()

    def check(self):
        if context() != self.binding:
            raise ValueError('Account or office changed. Reopen Schedule before editing.')

    def request(self, path, *, params=None, body=None):
        self.check()
        suffix = '?' + urllib.parse.urlencode(params) if params else ''
        req = urllib.request.Request(self.url + '/rest/v1/' + path + suffix,
            data=None if body is None else json.dumps(body).encode(),
            headers={'apikey': self.key, 'Authorization': 'Bearer ' + self.token,
                     'Content-Type': 'application/json'},
            method='GET' if body is None else 'POST')
        try:
            with self.opener.open(req, timeout=20) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as ex:
            raise sb.SupabaseError(ex.code, ex.read(2000).decode('utf-8', 'replace')) from None
        self.check()
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError('Schedule response is too large. Narrow the request.')
        return json.loads(raw) if raw else None

    def load(self):
        result = []
        for offset in range(0, 10000, 500):
            rows = self.request('schedule_visits', params={
                'department': 'eq.' + self.department, 'payload->>status': 'eq.active',
                'select': '*,jobs(' + JOB_FIELDS + ')', 'order': 'position.asc,id.asc',
                'limit': 500, 'offset': offset})
            result.extend(self.row(row) for row in rows)
            if len(rows) < 500:
                return result
        raise ValueError('Schedule exceeds the supported view size; no partial list was shown.')

    @staticmethod
    def job(row):
        return {'id': row['job_id'], 'job_id': row['job_id'],
                'title': row.get('display_name') or 'Unnamed job',
                'address': row.get('address') or '', 'phone': row.get('phone') or '',
                'contact': '', 'insurance': row.get('carrier') or '',
                'claim': row.get('claim_number') or '', 'activities': []}

    @classmethod
    def row(cls, row):
        payload = row['payload']
        return {**cls.job(row.get('jobs') or {'job_id': row['job_id']}), **payload,
                'time': payload['arrival'], 'revision': row['revision'],
                'since': row['queue_entered_at'][:10]}

    def search(self, query):
        # Only literal words enter the PostgREST expression, never operators.
        query = ' '.join(''.join(c if c.isalnum() or c.isspace() else ' ' for c in str(query)[:120]).split())
        if len(query) < 2:
            return []
        pattern = '*' + '*'.join(query.split()) + '*'
        rows = self.request('jobs', params={'department': 'eq.' + self.department,
            'select': JOB_FIELDS, 'or': f'(display_name.ilike.{pattern},address.ilike.{pattern})',
            'order': 'display_name.asc,job_id.asc', 'limit': 30})
        return [self.job(row) for row in rows]

    def save(self, command):
        if not isinstance(command, dict) or command.get('department') != self.department:
            raise ValueError('Office changed. Reopen Schedule.')
        clean = schedule_records.save_command(command.get('visit'), department=self.department,
            expected_revision=command.get('expected_revision'), operation_id=command.get('operation_id'))
        if 'before_id' in command:
            clean['before_id'] = None if command['before_id'] is None else schedule_records.identifier(command['before_id'])
        return self.request('rpc/save_schedule_draft', body={'p_command': clean})


def failure(error):
    if isinstance(error, sb.SupabaseError):
        try:
            code = json.loads(error.body).get('code')
        except (ValueError, AttributeError):
            code = None
        if code == '40001':
            return {'ok': False, 'conflict': True, 'error': 'This visit changed elsewhere. Your edit is still open. Cancel and reopen it to use the latest details.'}
        if code == '23505':
            return {'ok': False, 'conflict': True, 'error': 'This job already has an active visit. Cancel and open that visit instead.'}
        if error.status in (401, 403):
            return {'ok': False, 'error': 'Sign in with access to this office before using Schedule.'}
        return {'ok': False, 'error': 'Schedule could not confirm the request. Retry the same save safely, or cancel and reload to check it.'}
    if isinstance(error, ValueError):
        return {'ok': False, 'error': str(error)}
    return {'ok': False, 'error': 'Schedule connection failed. Your edit has not been cleared. Retry to confirm the save.'}
