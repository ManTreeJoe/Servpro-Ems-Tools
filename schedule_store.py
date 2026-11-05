"""User-bound digital schedule adapter. No Word/Trello or offline fallback."""
import base64
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request

import config
import job_settings
import schedule_records
import supabase_client as sb

JOB_FIELDS = ','.join(['job_id', 'canon_key', 'display_name', 'metadata_json',
                      *dict.fromkeys(job_settings.COLUMN_FIELDS.values())])


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
        source_boards = None  # Reused only within this load, never across refreshes.
        for offset in range(0, 10000, 500):
            rows = self.request('schedule_visits', params={
                'department': 'eq.' + self.department, 'payload->>status': 'eq.active',
                'select': '*,jobs(' + JOB_FIELDS + ')', 'order': 'position.asc,id.asc',
                'limit': 500, 'offset': offset})
            linked = self.trello_links([r.get('jobs') for r in rows if r.get('jobs')])
            # Batch only description projections; never download photo payloads
            # or issue a full-card request for every visit on each refresh.
            ids = sorted({card for cards in linked.values() for card in cards})
            descriptions = {}
            for start in range(0,len(ids),50):
                if source_boards is None:
                    source_boards = self._source_boards()
                cards = self.card_candidates(ids[start:start+50], descriptions_only=True,
                                             source_boards=source_boards)
                descriptions.update({c['card_id']: c['payload'].get('desc') or '' for c in cards})
            for row in rows:
                cards = linked.get((row.get('jobs') or {}).get('canon_key'), [])
                if row.get('jobs') and cards:
                    row = {**row, 'jobs': {**row['jobs'], '_schedule_desc': [descriptions.get(card, '') for card in cards]}}
                item=self.row(row)
                item['trello_cards']=linked.get((row.get('jobs') or {}).get('canon_key'),[])
                result.append(item)
            if len(rows) < 500:
                return result
        raise ValueError('Schedule exceeds the supported view size; no partial list was shown.')

    @staticmethod
    def job(row, desc=''):
        facts = job_settings.display_values(row, desc)
        sections = {}
        for fid, section, _key, label, _core in job_settings.FIELDS:
            value = str(facts.get(fid) or '').strip()
            if value:
                sections.setdefault(section.title(), []).append({'id': fid, 'label': label, 'value': value})
        return {'id': row['job_id'], 'job_id': row['job_id'],
                'title': row.get('display_name') or 'Unnamed job',
                'facts_base': {k: job_settings.stored_values(row)[k] for k in
                    ('address','customer_name','phone','email','carrier','claim_number')},
                'address': facts['address'], 'phone': facts['phone'],
                'contact': facts['customer_name'], 'insurance': facts['carrier'],
                'email': facts['email'], 'claim': facts['claim_number'], 'activities': [],
                'info_sections': [{'name': name, 'fields': fields} for name, fields in sections.items()]}

    def job_detail(self, job_id):
        if str(job_id).startswith('card:'):
            cards = self.card_candidates([str(job_id)[5:]])
            if len(cards) != 1:
                raise ValueError('This card is no longer available in this office. Search again.')
            result = self.card_job(cards[0])
            payload = cards[0]['payload']
            aliases = {cards[0]['card_id'], *[payload.get(k) for k in ('shortLink','shortUrl','url')]}
            values = '('+','.join(json.dumps(v) for v in sorted(v for v in aliases if v))+')'
            links = self.request('job_links', params={
                'link_value': 'in.'+values, 'link_type': 'in.(trello_card,trello_card_contents,trello_card_recon)',
                'select': 'canon_key', 'limit': 100})
            keys = {link['canon_key'] for link in links}
            if len(keys)>1:
                raise ValueError('This card has multiple job links. Reconcile them before scheduling.')
            if keys:
                jobs = self.request('jobs', params={'canon_key': 'eq.'+keys.pop(), 'select': JOB_FIELDS+',department', 'limit': 1})
                if not jobs or jobs[0].get('department') not in (None,self.department):
                    raise ValueError('This job is not available in this office.')
                # Keep the selected reference until save; preview must not enroll
                # a legacy unscoped job or overwrite its canonical facts.
                result = {**self.job(jobs[0], payload.get('desc') or ''), 'id': job_id, 'job_id': job_id,
                          'trello_cards': [cards[0]['card_id']]}
            return result
        job_id = schedule_records.identifier(job_id)
        rows = self.request('jobs', params={'department': 'eq.' + self.department,
            'job_id': 'eq.' + job_id, 'select': JOB_FIELDS, 'limit': 1})
        if not rows:
            raise ValueError('This job is no longer available in this office.')
        result = self.job(rows[0])
        result['trello_cards'] = self.trello_links(rows).get(rows[0]['canon_key'], [])
        if result['trello_cards']:
            cards = self.card_candidates(result['trello_cards'])
            result.update(self.job(rows[0], [card['payload'].get('desc') or '' for card in cards]))
        return result

    @classmethod
    def row(cls, row):
        payload = row['payload']
        job = row.get('jobs') or {'job_id': row['job_id'], 'metadata_json':json.dumps({'settings': row.get('details') or {}})}
        return {**cls.job(job, job.get('_schedule_desc','')), **payload,
                'time': payload['arrival'], 'revision': row['revision'],
                'since': row['queue_entered_at'][:10],
                'entry_title': row.get('entry_title') or '', 'source_key': row.get('source_key'),
                'confirmed': row.get('confirmed_revision', 0) == row['revision'],
                'confirmed_at': row.get('confirmed_at'),
                'title': (row.get('jobs') or {}).get('display_name') or row.get('entry_title') or 'Unlinked entry',
                'needs_link': not row['job_id']}

    def jobs(self):
        result=[]
        for offset in range(0,10000,500):
            rows=self.request('jobs',params={'department':'eq.'+self.department,
                'select':JOB_FIELDS,'order':'job_id.asc','limit':500,'offset':offset})
            result.extend(rows)
            if len(rows)<500:return result
        raise ValueError('Too many jobs for automatic matching; no import was saved.')

    def trello_links(self, jobs):
        keys=sorted({j.get('canon_key') for j in jobs if j.get('canon_key')})
        result={}
        for start in range(0,len(keys),50):
            values='('+','.join(json.dumps(key) for key in keys[start:start+50])+')'
            for offset in range(0,5000,500):
                rows=self.request('job_links',params={'canon_key':'in.'+values,'link_type':'in.(trello_card,trello_card_contents,trello_card_recon)',
                    'select':'canon_key,link_value','order':'canon_key.asc,link_value.asc','offset':offset,'limit':500})
                for row in rows:
                    if re.fullmatch(r'[a-fA-F0-9]{24}',row['link_value'] or ''):
                        result.setdefault(row['canon_key'],[]).append(row['link_value'])
                if len(rows)<500:break
        return result

    def import_entries(self, entries):
        clean=[{k:v for k,v in c.items() if k not in ('match_reason','review_note')} for c in entries]
        return self.request('rpc/import_schedule_entries',body={'p_department':self.department,'p_entries':clean})

    def search(self, query):
        import card_search
        # Only literal words enter the PostgREST expression, never operators.
        query = ' '.join(''.join(c if c.isalnum() or c.isspace() else ' ' for c in str(query)[:120]).split())
        if len(query) < 2:
            return []
        pattern = '*' + max(query.split(), key=len) + '*'
        # Separators vary by carrier; prefilter loosely, then verify the
        # normalized identifier below (never fuzzy-match claim numbers).
        claim_pattern = '*' + '*'.join(''.join(card_search.tokens(query))) + '*'
        rows = self.request('jobs', params={'department': 'eq.' + self.department,
            'select': JOB_FIELDS, 'or': f'(display_name.ilike.{pattern},address.ilike.{pattern},claim_number.ilike.{claim_pattern})',
            'order': 'display_name.asc,job_id.asc', 'limit': 400})
        jobs = [self.job(row) for row in rows if
                card_search.match_score(query, row.get('display_name')) or
                card_search.match_score(query, job_settings.stored_values(row)['address']) or
                card_search.claim_score(query, job_settings.stored_values(row)['claim_number'])]
        found = card_search.global_search(query, limit=30)
        self.check()
        if not found.get('ok'):
            raise ValueError('Job search is temporarily unavailable. Please retry.')
        cards = self.card_candidates([c['card_id'] for c in found['cards']])
        # Deduplicate by exact provider links, never by display name.
        matched_ids = {job['job_id'] for job in jobs}
        linked = self.trello_links([r for r in rows if r['job_id'] in matched_ids])
        known = {cid for ids in linked.values() for cid in ids}
        jobs.extend(self.card_job(c) for c in cards if c['card_id'] not in known)
        # Keep legacy placeholders available, but don't lead with an empty
        # record when the actual job has saved customer/property information.
        return sorted(jobs, key=lambda job: (-card_search.match_score(query, job['title']),
            not bool(job['info_sections'])))[:30]

    def _source_boards(self):
        sources = self.request('hub_trello_sync_sources', params={
            'reader_department': 'eq.'+self.department, 'enabled': 'eq.true', 'select': 'board_id'})
        return {s['board_id'] for s in sources}

    def card_candidates(self, ids, descriptions_only=False, *, source_boards=None):
        ids = sorted({cid for cid in ids if re.fullmatch(r'[a-f0-9]{24}', str(cid))})
        if not ids:
            return []
        boards = self._source_boards() if source_boards is None else source_boards
        rows = self.request('hub_trello_mirror_cards', params={
            'card_id': 'in.('+','.join(ids)+')', 'present': 'eq.true',
            'select': 'card_id,board_id,description:payload->>desc' if descriptions_only else 'card_id,board_id,payload', 'limit': 60})
        if descriptions_only:
            rows = [{**r, 'payload': {'desc': r.get('description') or ''}} for r in rows]
        return [r for r in rows if r['board_id'] in boards]

    @classmethod
    def card_job(cls, card):
        facts = job_settings.from_card(card['payload'].get('desc') or '')
        result = cls.job({'job_id': 'card:'+card['card_id'],
            'display_name': card['payload'].get('name'),
            'metadata_json': json.dumps({'settings': facts})})
        result['trello_cards'] = [card['card_id']]
        return result

    def save(self, command):
        if not isinstance(command, dict) or command.get('department') != self.department:
            raise ValueError('Office changed. Reopen Schedule.')
        record = dict(command.get('visit') or {})
        card_id = str(record.get('job_id') or '')
        card_id = card_id[5:] if card_id.startswith('card:') else None
        if card_id is not None:
            if not re.fullmatch(r'[a-f0-9]{24}', card_id):
                raise ValueError('Invalid selected card. Search again.')
            record['job_id'] = None
        unlinked = record.get('job_id') is None
        if unlinked: record['job_id']='00000000-0000-4000-8000-000000000000'
        clean = schedule_records.save_command(record, department=self.department,
            expected_revision=command.get('expected_revision'), operation_id=command.get('operation_id'))
        if 'before_id' in command:
            clean['before_id'] = None if command['before_id'] is None else schedule_records.identifier(command['before_id'])
        if unlinked: clean['visit']['job_id']=None
        clean.update(contract_version=2,entry_title=schedule_records.text(command.get('entry_title',''),300,required=unlinked),source_key=command.get('source_key'))
        if clean['source_key'] is not None: clean['source_key']=schedule_records.text(clean['source_key'],160,required=True)
        if 'job_facts' in command:
            clean['job_facts'] = command['job_facts']
            imported = {}
            if card_id:
                cards = self.card_candidates([card_id])
                if len(cards) != 1:
                    raise ValueError('Selected card is no longer available in this office.')
                imported = job_settings.from_card(cards[0]['payload'].get('desc') or '')
            # Database validates field allowlist, original values and office;
            # the visit and shared job update commit or roll back together.
            return self.request('rpc/save_schedule_with_facts', body={
                'p_command': clean, 'p_card': card_id, 'p_imported': imported})
        if card_id:
            cards = self.card_candidates([card_id])
            if len(cards) != 1:
                raise ValueError('Selected card is no longer available in this office.')
            facts = job_settings.from_card(cards[0]['payload'].get('desc') or '')
            return self.request('rpc/save_schedule_card_entry', body={
                'p_command': clean, 'p_card': card_id, 'p_facts': facts})
        return self.request('rpc/save_schedule_entry', body={'p_command': clean})


def failure(error):
    if isinstance(error, sb.SupabaseError):
        try:
            code = json.loads(error.body).get('code')
        except (ValueError, AttributeError):
            code = None
        if code == '40001':
            return {'ok': False, 'conflict': True, 'error': 'This visit changed elsewhere. Your edit is still open. Cancel and reopen it to use the latest details.'}
        if code == '23505':
            return {'ok': False, 'conflict': True, 'error': 'This visit or imported source already exists. Your edit is still open. Reload Schedule to check the existing entry.'}
        if error.status in (401, 403):
            return {'ok': False, 'error': 'Sign in with access to this office before using Schedule.'}
        return {'ok': False, 'error': 'Schedule could not confirm the request. Retry the same save safely, or cancel and reload to check it.'}
    if isinstance(error, ValueError):
        return {'ok': False, 'error': str(error)}
    return {'ok': False, 'error': 'Schedule connection failed. Your edit has not been cleared. Retry to confirm the save.'}
