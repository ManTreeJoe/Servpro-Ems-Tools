"""Exact-card Logs audit drafts and explicitly confirmed Trello publication.

Local drafts are not shared. Never infer an audit pass or billing month from
an invoice/payment keyword. Trello identity, comments and checks are evidence.
"""
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
import re
import threading
import uuid

from weekly_review_sources import BOARD, _one
from logs_audit_suggestions import suggest
from logs_audit_evidence import AR_BOARD, timing, candidates, compare

LOCK = threading.RLock()
FIELDS = ('ems_start', 'contents_start', 'job_date', 'ems_estimator', 'contents_estimator', 'initial_note',
          'missed_by', 'file_status', 'ems_ready', 'ems_billed', 'contents_ready',
          'contents_billed', 'estimator_notes', 'audit_notes', 'billing_evidence',
          'payment_notes', 'billed_month', 'destination', 'decision', 'period_start',
          'period_end', 'scope', 'field_notes', 'billing_status', 'billing_conflict',
          'other_billed', 'inspection_completed_at', 'initial_note_sent_at',
          'timing_source', 'ar_resolution')
CHECKS = ('front_checked', 'estimating_checked', 'field_checked', 'billing_checked',
          'identity_checked', 'all_confirmed')
MONTHS = {name: i for i, names in enumerate(
    ('JAN JANUARY','FEB FEBRUARY','MAR MARCH','APR APRIL','MAY','JUN JUNE',
     'JUL JULY','AUG AUGUST','SEP SEPT SEPTEMBER','OCT OCTOBER','NOV NOVEMBER','DEC DECEMBER'),1)
    for name in names.split()}

def month_lane(name):
    words = re.findall(r'[A-Z]+|\d{4}', name.upper())
    months = {MONTHS[w] for w in words if w in MONTHS}
    years = {w for w in words if w.isdigit()}
    if 'BILLED' in words and len(months) == len(years) == 1:
        return f'{next(iter(years))}-{next(iter(months)):02d}'
    return ''

def fingerprint(evidence):
    comments = [a for a in evidence['comments'] if not a['text'].endswith(evidence.get('ignore_marker', '\0'))]
    value = {k:evidence[k] for k in ('card','checklists')}
    value['comments'] = comments
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

class LogsAudit:
    def __init__(self, client, storage, location):
        self.client, self.storage, self.location = client, storage, location

    def _key(self):
        if self.location() != 'IE':
            raise ValueError('This Logs board is configured for IE only. OC needs its own verified board mapping.')
        return 'logs_audit_form_v1_IE'

    def _store(self):
        return deepcopy(self.storage.get(self._key()) or {'drafts':{}, 'operations':{}})

    def _save(self, store):
        key = self._key()
        self.storage.set_value(key, store)
        # Legacy persistence logs some disk errors instead of raising. Never
        # post a comment unless the recovery intent actually reached disk.
        state_path = getattr(self.storage, '_STATE_PATH', None)
        if state_path:
            with open(state_path, encoding='utf-8') as source:
                persisted = json.load(source)
            if persisted.get(key) != store:
                raise ValueError('Audit save was not verified on disk. No further Trello action was attempted. Check storage and retry.')

    def _source(self):
        self._key()
        board = _one(self.client.list_boards(), BOARD)
        lanes = self.client._call(f"/boards/{board['id']}/lists", params={'filter':'open','fields':'name,closed,idBoard'})
        source = _one(lanes, 'TO BE PRESERVED')
        return board, source, lanes

    def queue(self):
        board, source, lanes = self._source()
        cards = self.client._call(f"/lists/{source['id']}/cards", params={'filter':'open','fields':'name,idBoard,idList,closed,shortUrl'})
        if not isinstance(cards,list): raise ValueError('Could not read the source queue.')
        for c in cards:
            if c.get('idBoard') != board['id'] or c.get('idList') != source['id'] or c.get('closed'):
                raise ValueError('Queue changed while reading. Refresh it.')
        store = self._store()
        return {'ok':True, 'cards':cards, 'drafts':{k:{'fields':v['fields'],'saved_at':v['saved_at']} for k,v in store['drafts'].items()},
                'operations':list(store['operations'].values()), 'source':source['name']}

    def _evidence(self, card_id, board_id, allowed_lanes, marker='\0', allow_closed=False):
        if not re.fullmatch(r'[a-zA-Z0-9]+', str(card_id)): raise ValueError('Invalid card ID.')
        card = self.client._call(f'/cards/{card_id}', params={'fields':'name,desc,idBoard,idList,closed,shortUrl'})
        if card.get('idBoard') != board_id or (allowed_lanes is not None and card.get('idList') not in allowed_lanes) or (card.get('closed') and not allow_closed):
            raise ValueError('Card left the expected source/destination. Refresh before continuing.')
        comments, before, seen = [], None, set()
        for _ in range(100):
            params = {'filter':'commentCard','limit':1000}
            if before: params['before'] = before
            page = self.client._call(f'/cards/{card_id}/actions',params=params)
            if not isinstance(page,list): raise ValueError('Comment history unavailable; audit is incomplete.')
            for a in page:
                if a['id'] not in seen:
                    seen.add(a['id'])
                    comments.append({'id':a['id'],'date':a.get('date',''),
                        'author':a.get('memberCreator',{}).get('fullName',''), 'text':a.get('data',{}).get('text','')})
            if len(page)<1000: break
            if page[-1]['id']==before: raise ValueError('Comment pagination did not advance.')
            before=page[-1]['id']
        else: raise ValueError('Comment history exceeded limit. Do not mark audited.')
        checklists=self.client._call(f'/cards/{card_id}/checklists',params={'checkItems':'all'})
        if not isinstance(checklists,list): raise ValueError('Checklists could not be read.')
        result={'card':card,'comments':comments,'checklists':checklists,'ignore_marker':marker}
        result['revision']=fingerprint(result)
        return result

    def ar_candidates(self, card_id):
        board,source,_=self._source()
        evidence=self._evidence(card_id,board['id'],{source['id']})
        cards=self.client._call(f'/boards/{AR_BOARD}/cards',params={'filter':'all','fields':'name,desc,idBoard,idList,closed,shortUrl'})
        if not isinstance(cards,list) or any(c.get('idBoard')!=AR_BOARD for c in cards):
            raise ValueError('AR index could not be verified.')
        saved=self._store().get('ar_links',{}).get(card_id)
        matches=candidates(evidence['card'],cards,saved)
        return {'ok':True,'candidates':matches,'saved_id':saved,'searched_count':len(cards)}

    def ar_review(self, card_id, ar_id, confirmed=False):
        with LOCK:
            board,source,_=self._source()
            logs=self._evidence(card_id,board['id'],{source['id']})
            ar=self._evidence(ar_id,AR_BOARD,None,allow_closed=True)
            if confirmed is True:
                store=self._store();store.setdefault('ar_links',{})[card_id]=ar_id;self._save(store)
            return {'ok':True,'evidence':ar,'comparison':compare(logs,ar)}

    def _linked_ar(self, card_id):
        ar_id=self._store().get('ar_links',{}).get(card_id)
        return self._evidence(ar_id,AR_BOARD,None,allow_closed=True) if ar_id else None

    def _verify_ar(self, snapshot, card_id):
        expected=(snapshot or {}).get('card',{}).get('id')
        if self._store().get('ar_links',{}).get(card_id)!=expected:
            raise ValueError('AR link changed. Save and review the audit again.')
        if snapshot:
            current=self._evidence(snapshot['card']['id'],AR_BOARD,None,allow_closed=True)
            if current['revision']!=snapshot['revision']:
                raise ValueError('Linked AR evidence changed. Reopen and review before publishing.')

    def inspect(self, card_id, period_start=None, period_end=None):
        board, source, lanes=self._source()
        evidence=self._evidence(card_id,board['id'],{source['id']})
        draft=self._store()['drafts'].get(card_id)
        previous=(draft or {}).get('evidence',{})
        old_comments={a['id']:a for a in previous.get('comments',[])}
        changes={'comments':[a['id'] for a in evidence['comments'] if old_comments.get(a['id'])!=a],
                 'removed_comments':sorted(set(old_comments)-{a['id'] for a in evidence['comments']}),
                 'description':bool(previous) and previous['card'].get('desc')!=evidence['card'].get('desc'),
                 'checklists':bool(previous) and previous.get('checklists')!=evidence['checklists']}
        carried=False
        if draft and period_start and period_end:
            carried=(draft['fields']['period_start'],draft['fields']['period_end'])!=(period_start,period_end)
            if carried:
                draft['fields'].update(period_start=period_start,period_end=period_end)
                draft['fields'].update({key:False for key in CHECKS})
        ar=self._linked_ar(card_id)
        if draft and (draft['revision']!=evidence['revision'] or
                      (draft.get('ar') or {}).get('revision')!=(ar or {}).get('revision')):
            draft['fields'].update({k:False for k in CHECKS})
        suggestions=suggest(evidence)
        for key,suggestion in suggestions.items():
            saved=(draft or {}).get('fields',{}).get(key)
            suggestion['differs_from_saved']=bool(saved and (suggestion.get('conflict') or
                (suggestion.get('value') is not None and suggestion['value']!=saved)))
        return {'ok':True, 'evidence':evidence, 'ar':ar, 'ar_comparison':compare(evidence,ar) if ar else None, 'changes':changes, 'carried_forward':carried, 'suggestions':suggestions, 'draft':draft,
                'lanes':[dict(l,month=month_lane(l['name'])) for l in lanes
                         if month_lane(l['name']) or l['name'].strip().upper()=='QUESTIONS']}

    def save(self, card_id, revision, fields):
        with LOCK:
            board, source, _=self._source()
            evidence=self._evidence(card_id,board['id'],{source['id']})
            if evidence['revision']!=revision: raise ValueError('Trello evidence changed. Reopen and review the latest notes.')
            store=self._store()
            ar=self._linked_ar(card_id)
            for op in store['operations'].values():
                if op['card_id']!=card_id or op['status'] in ('done','superseded'):
                    continue
                # A posted audit can be overtaken by another person's evidence.
                # Retain its history, but allow a newly inspected review to start
                # a separate, explicitly confirmed operation. Never retry an
                # uncertain POST or move merely because the form was saved.
                posted=any(note['text']==op['comment'] for note in evidence['comments'])
                changed=(fingerprint(dict(evidence,ignore_marker=op['marker']))!=op['revision'] or
                         (op.get('ar') or {}).get('revision')!=(ar or {}).get('revision'))
                if op['status']=='preview' or not posted or not changed:
                    raise ValueError('This card has a pending publication. Resolve/retry it before editing.')
                op.update(status='superseded',superseded_at=datetime.now(timezone.utc).isoformat(),
                          superseded_reason='Fresh review of changed evidence; prior comment retained without moving.')
            clean={k:str(fields.get(k,'')).strip()[:10000] for k in FIELDS}
            clean.update({k:fields.get(k) is True for k in CHECKS})
            clock=timing(clean['inspection_completed_at'],clean['initial_note_sent_at'])
            clean['initial_note']=clock['status'] if clock['status'] in ('Yes','No') else ''
            for key in ('ems_start','contents_start','job_date','ems_ready','ems_billed','contents_ready','contents_billed','other_billed','period_start','period_end'):
                if clean[key]: date.fromisoformat(clean[key])
            for prefix in ('ems','contents'):
                a,b=clean[prefix+'_ready'],clean[prefix+'_billed']
                if a and b and a>b: raise ValueError('Billing completion cannot precede ready-for-billing date.')
                start=clean[prefix+'_start']
                if start and b and start>b: raise ValueError('Billing completion cannot precede the work/card start date.')
                clean[prefix+'_days']=(date.fromisoformat(b)-date.fromisoformat(start)).days if start and b else None
            if clean['period_start'] and clean['period_end'] and clean['period_start']>clean['period_end']:
                raise ValueError('Invalid review period.')
            prior=store['drafts'].get(card_id)
            draft={'fields':clean,'revision':revision,'evidence':evidence,'ar':ar,'timing':clock,'suggestions':suggest(evidence),
                   'saved_at':datetime.now(timezone.utc).isoformat(), 'version':str(uuid.uuid4()),
                   'history':[*((prior or {}).get('history',[])), *([{k:v for k,v in prior.items() if k!='history'}] if prior else [])]}
            store['drafts'][card_id]=draft
            self._save(store)
            return {'ok':True,'draft':draft}

    def preview(self,card_id):
        with LOCK:
            board, source, lanes=self._source()
            store=self._store(); draft=store['drafts'].get(card_id)
            if not draft: raise ValueError('Save the audit form first.')
            f=draft['fields']
            if not all(f.get(k) for k in CHECKS): raise ValueError('Confirm identity and each department review, then confirm the full form.')
            if not f['period_start'] or not f['period_end'] or f['scope'] not in ('EMS','Contents','EMS + Contents','Recon','Service call / no charge'):
                raise ValueError('Choose review period and audited scope.')
            if f['decision'] not in ('billed','questions','hold'): raise ValueError('Choose billed, Questions, or leave in place.')
            lane=source if f['decision']=='hold' else next((l for l in lanes if l['id']==f['destination']),None)
            if not lane: raise ValueError('Select an available destination.')
            if f['decision']!='questions' and draft.get('ar') and compare(draft['evidence'],draft['ar'])['conflicts'] and not f.get('ar_resolution'):
                raise ValueError('Resolve the Logs/AR conflict with a recorded explanation, or choose Questions.')
            if f['decision']=='billed':
                if f.get('billing_status')!='Billed' or f.get('billing_conflict'):
                    raise ValueError('Confirm explicit billing and resolve conflicting billing evidence, or choose Questions.')
                required={'EMS':['ems_billed'],'Contents':['contents_billed'],
                          'EMS + Contents':['ems_billed','contents_billed']}.get(f['scope'],['other_billed'])
                if any(not f.get(key) for key in required):
                    raise ValueError('Record the explicit billed date for every division on this card. Unknown dates belong in Questions.')
                expected=max(f[key] for key in required)[:7]
                if f['billed_month']!=expected:
                    raise ValueError('Use the month of the last represented division billed.')
                if not re.fullmatch(r'\d{4}-\d{2}',f['billed_month']) or month_lane(lane['name'])!=f['billed_month']:
                    raise ValueError('Destination must match the confirmed billed month.')
                if not f['billing_evidence']: raise ValueError('Record explicit billed evidence, not invoice creation alone.')
            elif f['decision']=='questions':
                if lane['name'].strip().upper()!='QUESTIONS' or not (f['audit_notes'] or f.get('billing_conflict')):
                    raise ValueError('Questions requires an open-action note and the Questions lane.')
            elif f.get('billing_status')!='Not billed' or f.get('billing_conflict'):
                raise ValueError('Leave in place is for clearly not-billed work. Unclear or conflicting billing belongs in Questions.')
            current=self._evidence(card_id,board['id'],{source['id']})
            self._verify_ar(draft.get('ar'),card_id)
            if current['revision']!=draft['revision']: raise ValueError('Evidence changed. Reopen the card and review it before publishing.')
            # Identity of the connected Trello account, not a user-supplied name.
            actor=self.client._call('/members/me',params={'fields':'id,fullName,username'})
            if not actor.get('id'): raise ValueError('Could not verify the connected Trello user.')
            op_id=hashlib.sha256((card_id+draft['version']).encode()).hexdigest()[:24]
            if op_id in store['operations']: return {'ok':True,'operation':store['operations'][op_id]}
            marker=f'[LH logs audit {op_id}]'
            comment='\n'.join([
                f"Logs audit reviewed {date.today().isoformat()} — {actor.get('fullName') or actor['username']}",
                f"Period: {f['period_start']} through {f['period_end']}; scope: {f['scope']}",
                f"Front: initial note on time: {f['initial_note'] or 'Unknown'}; missed by: {f['missed_by'] or 'Not recorded'}; WC/file: {f['file_status'] or 'Unknown'}",
                f"EMS estimator: {f['ems_estimator'] or 'Not recorded'}; ready: {f['ems_ready'] or 'Not recorded'}; billed: {f['ems_billed'] or 'Not recorded'}; days: {f['ems_days'] if f['ems_days'] is not None else 'Unknown'}",
                f"Contents estimator: {f['contents_estimator'] or 'Not applicable / not recorded'}; ready: {f['contents_ready'] or 'Not recorded'}; billed: {f['contents_billed'] or 'Not recorded'}; days: {f['contents_days'] if f['contents_days'] is not None else 'Unknown'}",
                f"Field review: {f['field_notes'] or 'Reviewed by user'}",
                f"Estimator findings: {f['estimator_notes'] or 'None recorded'}",
                f"Billing evidence: {f['billing_evidence'] or 'Unresolved'}",
                f"Billing status: {f.get('billing_status') or 'Unknown'}; conflict: {f.get('billing_conflict') or 'None recorded'}; other scope billed: {f.get('other_billed') or 'N/A'}",
                f"Initial note timing: {draft.get('timing',{}).get('status','Unverified')}; inspection completed: {f.get('inspection_completed_at') or 'Unknown'}; note sent: {f.get('initial_note_sent_at') or 'Unknown'}; source: {f.get('timing_source') or 'Not recorded'}",
                f"AR card: {(draft.get('ar') or {}).get('card',{}).get('shortUrl') or 'No confirmed AR link'}; resolution: {f.get('ar_resolution') or 'None recorded'}",
                f"Payment: {f['payment_notes'] or 'Not verified; payment is not required for billed-month filing'}",
                f"Open actions: {f['audit_notes'] or 'None confirmed by reviewer'}",
                f"User confirmed review. Destination: {lane['name']}",marker])
            operation={'id':op_id,'card_id':card_id,'name':current['card']['name'],'board_id':board['id'],
                'source':source['id'],'destination':lane['id'],'destination_name':lane['name'],
                'revision':draft['revision'],'actor_id':actor['id'],'comment':comment,'marker':marker,'status':'preview',
                'period_start':f['period_start'],'period_end':f['period_end'],'decision':f['decision'],'ar':draft.get('ar')}
            store['operations'][op_id]=operation; self._save(store)
            return {'ok':True,'operation':operation}

    def publish(self, op_id, confirmed=False):
        if confirmed is not True: raise ValueError('Explicit confirmation is required.')
        with LOCK:
            store=self._store(); op=store['operations'].get(op_id)
            if not op: raise ValueError('Preview not found in this workspace.')
            if op['status']=='superseded':
                raise ValueError('This audit was superseded by a fresh review. Preview and confirm the new review instead.')
            if op['status']=='done': return {'ok':True,'operation':op}
            self._verify_ar(op.get('ar'),op['card_id'])
            actor=self.client._call('/members/me',params={'fields':'id'})
            if actor.get('id')!=op['actor_id']: raise ValueError('Connected Trello account changed. Review again.')
            _,_,lanes=self._source()
            if not any(l['id']==op['destination'] and l['name']==op['destination_name'] for l in lanes):
                raise ValueError('Destination changed. Do not publish this preview.')
            evidence=self._evidence(op['card_id'],op['board_id'],{op['source'],op['destination']},op['marker'])
            found=any(a['text']==op['comment'] for a in evidence['comments'])
            if evidence['card']['idList']==op['destination'] and op['source']!=op['destination']:
                if not found: raise ValueError('Card moved without this audit comment. Review manually.')
                op['status']='done';self._save(store);return {'ok':True,'operation':op}
            if fingerprint(evidence)!=op['revision']: raise ValueError('Card evidence changed since confirmation. Re-review required.')
            if not found:
                if op['status']=='posting': raise ValueError('Prior comment result is uncertain. Refresh/retry after Trello settles; do not duplicate the comment.')
                op['status']='posting';self._save(store)
                # No automatic POST retries after ambiguous errors.
                result=self.client._call(f"/cards/{op['card_id']}/actions/comments",method='POST',data={'text':op['comment']},_max_retries=0)
                if not isinstance(result,dict) or not result.get('id'): raise ValueError('Comment result uncertain. Retry will reconcile before moving.')
            op['status']='comment_posted';self._save(store)
            # Recheck after posting: another person's new finding must not be moved away.
            self._verify_ar(op.get('ar'),op['card_id'])
            evidence=self._evidence(op['card_id'],op['board_id'],{op['source']},op['marker'])
            if fingerprint(evidence)!=op['revision']: raise ValueError('New evidence arrived after posting. Move paused for review.')
            if op['source']==op['destination']:
                op['status']='done';op['completed_at']=datetime.now(timezone.utc).isoformat();self._save(store)
                return {'ok':True,'operation':op}
            op['status']='moving';self._save(store)
            self.client._call(f"/cards/{op['card_id']}",method='PUT',data={'idList':op['destination']},_max_retries=0)
            verified=self.client._call(f"/cards/{op['card_id']}",params={'fields':'idList,idBoard'})
            if verified.get('idList')!=op['destination'] or verified.get('idBoard')!=op['board_id']:
                raise ValueError('Move not verified. Retry to check actual Trello state.')
            op['status']='done';op['completed_at']=datetime.now(timezone.utc).isoformat();self._save(store)
            return {'ok':True,'operation':op}

    def cancel_preview(self, op_id):
        with LOCK:
            store=self._store(); op=store['operations'].get(op_id)
            if not op or op['status']!='preview':
                raise ValueError('Only an unpublished preview can be discarded. A started publication must be reconciled.')
            del store['operations'][op_id];self._save(store)
            return {'ok':True}

    def create_month_lane(self, month, confirmed=False):
        if confirmed is not True:
            raise ValueError('Explicit approval is required to create a lane.')
        if not re.fullmatch(r'\d{4}-\d{2}',str(month)):
            raise ValueError('Choose a valid billed month.')
        chosen=date.fromisoformat(month+'-01')
        with LOCK:
            board,_,lanes=self._source()
            existing=[l for l in lanes if month_lane(l['name'])==month]
            if len(existing)>1: raise ValueError('Multiple lanes match this month. Resolve the duplicate lanes before continuing.')
            if existing: return {'ok':True,'lane':existing[0]}
            store=self._store();attempts=store.setdefault('lane_creations',{})
            key=board['id']+':'+month
            if key in attempts:
                raise ValueError('Previous creation result is uncertain. Check Trello before trying to create another lane.')
            name=chosen.strftime('%B %Y').upper()+' - BILLED'
            attempts[key]={'name':name,'status':'creating'};self._save(store)
            lane=self.client._call('/lists',method='POST',data={'idBoard':board['id'],'name':name,'pos':'bottom'},_max_retries=0)
            if not isinstance(lane,dict) or not lane.get('id'):
                raise ValueError('Lane creation was not verified. Check Trello before retrying.')
            attempts[key].update(status='done',id=lane['id']);self._save(store)
            return {'ok':True,'lane':lane}
