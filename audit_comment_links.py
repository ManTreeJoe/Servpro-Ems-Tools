"""Exact-card evidence links. Never edit comments or infer event dates from posts."""
from copy import deepcopy
from datetime import date, datetime
import re
import uuid

TARGETS = {
 'incoming_loss_at': ('Incoming loss received', 'timestamp'),
 'insured_contacted_at': ('Insured contacted', 'timestamp'),
 'on_site_at': ('On-site arrival', 'timestamp'),
 'inspection_at': ('Inspection performed', 'timestamp'),
 'field_note_posted_at': ('Field inspection note', 'timestamp'),
 'initial_note_sent_at': ('Coordinator initial note', 'timestamp'),
 'ems_start': ('EMS work started', 'date'),
 'ems_completed': ('EMS work completed', 'date'),
 'contents_start': ('Contents work started', 'date'),
 'contents_completed': ('Contents work completed', 'date'),
 'ems_ready': ('EMS ready for billing', 'date'),
 'contents_ready': ('Contents ready for billing', 'date'),
 'ems_billed': ('EMS billed', 'date'),
 'contents_billed': ('Contents billed', 'date'),
 'other_billed': ('Recon / other billed', 'date'),
}


def verified_comments(card_id, department):
    import supabase_client as sb
    import config
    import trello_client as tc
    if not re.fullmatch(r'[a-fA-F0-9]{24}', str(card_id)):
        raise ValueError('An exact shared card is required. Refresh the job first.')
    user_id = (sb.current_user() or {}).get('id')
    workspace = str(config.load().get('trello_workspace_id') or '').strip()
    if not user_id or not workspace or department != config.active_department():
        raise ValueError('Sign in and select the correct office before linking audit evidence.')
    # This column-limited read is protected by the source RLS policy, including
    # ALL required memberships on mixed-office boards. Never infer access from
    # a customer name, a cached card, or provider credentials alone.
    sources = sb.rest('GET','hub_trello_sync_sources',params={
        'select':'board_id,reader_department,reader_workspace,enabled',
        'reader_department':'eq.'+department,'reader_workspace':'eq.'+workspace,'enabled':'eq.true'}) or []
    allowed = {s['board_id'] for s in sources if s.get('enabled') is True
               and s.get('reader_department') == department and s.get('reader_workspace') == workspace}
    if not allowed:
        raise ValueError('No authorized boards are available for this office. Check sign-in and board configuration.')
    def current_board():
        card = tc._call('/cards/'+card_id, params={'fields':'id,idBoard,closed'})
        if not isinstance(card, dict) or card.get('id') != card_id or card.get('idBoard') not in allowed:
            raise ValueError('This card is not on an authorized board for the selected office. Refresh the job.')
        return card['idBoard']
    board = current_board()
    # A stale mirror's present=false flag is not proof that a live card is gone.
    # Retrieve provider evidence by the exact ID only after board authorization.
    actions = tc.get_all_comments(card_id)
    result={}
    for a in actions:
        if a.get('type')=='commentCard':
            result[a['id']]={'id':a['id'],'text':a.get('data',{}).get('text',''),
                'author':a.get('memberCreator',{}).get('fullName',''), 'date':a.get('date',''), 'source':'trello'}
    native=sb.rest('GET','job_comment_threads',params={
        'select':'id,body,actor,created_at,provider_id','card_id':'eq.'+card_id}) or []
    for c in native:
        item={'id':c['id'],'text':c['body'],'author':c['actor'],'date':c['created_at'],'source':'oneloss'}
        result[c['id']]=item
        if c.get('provider_id') and c['provider_id'] not in result: result[c['provider_id']]=item
    if (current_board() != board or config.active_department() != department
            or str(config.load().get('trello_workspace_id') or '').strip() != workspace
            or (sb.current_user() or {}).get('id') != user_id):
        raise ValueError('Card or workspace changed while reading. Reopen the audit link menu.')
    return result


class EvidenceLinks:
    def __init__(self, storage, department, resolver=verified_comments):
        self.storage,self.department,self.resolver=storage,department,resolver

    def read(self, card):
        self.resolver(card,self.department)  # enforce exact-card access on reads too
        return deepcopy(self.storage.load_store()['links'].get(card) or {'version':None,'items':{}})

    def change(self, card, comment, target, value, expected, remove=False, previous=None, inspection=None):
        if target not in TARGETS or (previous and previous not in TARGETS): raise ValueError('Unknown audit item.')
        comments=self.resolver(card,self.department)
        store=self.storage.load_store()
        if any(o.get('card_id')==card and o.get('status') not in ('preview','done','superseded') for o in store['operations'].values()):
            raise ValueError('An audit publication needs recovery first. Verify it before changing its evidence links.')
        current=store['links'].get(card) or {'version':None,'items':{}}
        if current['version']!=expected: raise ValueError('Audit links changed on another device. Close and reopen this menu.')
        items=deepcopy(current['items'])
        if remove:
            if (items.get(target) or {}).get('comment_id')!=comment: raise ValueError('This comment is no longer linked here.')
            items[target]=None
        else:
            source=comments.get(comment)
            if not source: raise ValueError('Comment unavailable in the shared snapshot. Refresh comments and retry.')
            if TARGETS[target][1]=='timestamp':
                parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
                if parsed.tzinfo is None: raise ValueError('Include a timezone in the event time.')
            else:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value): raise ValueError('Confirm the actual event date.')
                date.fromisoformat(value)
            if previous and previous!=target:
                if (items.get(previous) or {}).get('comment_id')!=comment: raise ValueError('Previous link changed; refresh.')
                items[previous]=None
            items[target]={'comment_id':comment,'card_id':card,'target':target,'value':value,'comment':source,
                'division':'CONTENTS' if target.startswith('contents_') else 'RECON' if target=='other_billed' else 'EMS' if target.startswith('ems_') else None}
        if inspection is not None:
            if remove or target != 'field_note_posted_at':
                raise ValueError('Inspection time must accompany a field note link.')
            parsed=datetime.fromisoformat(inspection.replace('Z','+00:00'))
            if parsed.tzinfo is None: raise ValueError('Include a timezone in inspection time.')
            occupied=items.get('inspection_at')
            if occupied and occupied.get('comment_id') != comment:
                raise ValueError('Inspection is linked to another comment. Edit or unlink that inspection first.')
            items['inspection_at']={'comment_id':comment,'card_id':card,'target':'inspection_at',
                'value':inspection,'comment':comments[comment],'division':None}
        store['links'][card]={'version':str(uuid.uuid4()),'items':items}
        self.storage.save_store(store)
        return store['links'][card]


def apply_links(fields, links):
    result=deepcopy(fields)
    for key,link in (links or {}).get('items',{}).items():
        if key in TARGETS:
            result[key]=link['value'] if link else ''
            if key=='initial_note_sent_at': result['missed_by']=link['comment'].get('author','') if link else ''
    return result


def call(card_id, command=None):
    import config, persistence
    from logs_audit_storage import SharedAuditStorage
    try:
        dept=config.active_department()
        service=EvidenceLinks(SharedAuditStorage(persistence,dept),dept)
        if command is None: value=service.read(card_id)
        else: value=service.change(card_id,command['comment_id'],command['target'],command.get('value',''),
            command.get('expected'),command.get('remove') is True,command.get('previous'),command.get('inspection'))
        return {'ok':True,'links':value,'targets':TARGETS}
    except ValueError as e: return {'ok':False,'error':str(e)}
    except Exception: return {'ok':False,'error':'Shared audit links unavailable. Your comment was not changed.'}
