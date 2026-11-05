"""Card-owned insurance facts. Never inherit an EMS claim into Contents/Recon.

Rollout is explicit and Dev-only until all readers and sync callers are migrated.
The shared jobs columns remain a legacy projection, not the scoped write target.
"""
import os
import re

FIELDS=frozenset(('carrier','claim_number','adjuster_name','adjuster_email',
                  'adjuster_phone','deductible','agent_name','inspection_fee'))

def enabled():
    return os.environ.get('LINGUAR_CHANNEL','').lower()=='dev' and os.environ.get('ONELOSS_CARD_INSURANCE')=='1'

def card_key(value):
    value=str(value or '').strip()
    match=re.search(r'/c/([A-Za-z0-9]+)',value)
    value=match.group(1) if match else value
    if not re.fullmatch(r'[A-Za-z0-9]{8}|[a-fA-F0-9]{24}',value):
        raise ValueError('An exact linked Trello card is required for insurance information.')
    return value.lower()

def scope(job,card_id):
    import ems_db
    key=card_key(card_id)
    types={'trello_card':'EMS','trello_card_contents':'Contents','trello_card_recon':'Recon'}
    sections=set()
    for link in ems_db.get_links(job['canon_key']) or []:
        if link.get('link_type') not in types:continue
        try:linked=card_key(link.get('link_value'))
        except ValueError:continue
        if linked==key:sections.add(types[link['link_type']])
    if len(sections)!=1:
        raise ValueError('This card needs one verified work section before editing insurance information.')
    if not job.get('job_id'):raise ValueError('A permanent job ID is required.')
    return {'job_id':job['job_id'],'card_key':key,'section':sections.pop()}

def read(job,card_id):
    import supabase_client as db
    owner=scope(job,card_id)
    rows=db.rest('GET','job_card_insurance',params={'job_id':'eq.'+owner['job_id'],'card_key':'eq.'+owner['card_key']})
    if len(rows)>1:raise ValueError('Ambiguous insurance record')
    return rows[0] if rows else dict(owner,values={},baseline={},revision=0,pending=False)

def overlay(shared,record):
    # A missing scoped value is unknown, never an inherited other-section claim.
    result=dict(shared)
    for field in FIELDS:result[field]=(record.get('values') or {}).get(field,'')
    return result

def write(job,card_id,patch,expected_revision):
    import supabase_client as db
    owner=scope(job,card_id)
    if expected_revision is None:raise ValueError('Reopen Job info before saving section insurance.')
    if set(patch)-FIELDS:raise ValueError('Unsupported insurance field')
    if any(not isinstance(v,str) for v in patch.values()):raise ValueError('Insurance fields must be text')
    return db.rpc('save_job_card_insurance',{'p_job':owner['job_id'],'p_card':owner['card_key'],
        'p_section':owner['section'],'p_patch':patch,'p_revision':expected_revision})

def load_editor(job,card_id,shared,*,fetch_missing=False):
    import job_settings as js
    record=read(job,card_id)
    values=overlay(shared,record)
    if not record['revision'] and fetch_missing:
        card=source_card(card_id)
        if card_key(card.get('id'))!=card_key(card_id):raise ValueError('Could not verify exact insurance card')
        parsed=js.from_card(card.get('desc') or '')
        values.update({f:parsed.get(f,'') for f in FIELDS})
    return values,{'job_id':record['job_id'],'card_key':record['card_key'],
                   'section':record['section'],'revision':record['revision'],
                   'initial_values':{f:values[f] for f in FIELDS} if not record['revision'] else {}},record['pending']

def source_card(card_id):
    """Dev reads its saved snapshot only; never fall through to live Trello."""
    import supabase_client as db
    if enabled():
        rows=db.rest('GET','hub_trello_mirror_cards',params={
            'select':'payload','card_id':'eq.'+card_key(card_id),'limit':'2'})
        if len(rows)!=1:
            raise ValueError('This card has no unique Dev snapshot. Insurance was not borrowed from another card.')
        card=rows[0].get('payload') or {}
    else:
        import trello_client as tc
        card=tc.get_card_lite(card_id) or {}
    if card_key(card.get('id'))!=card_key(card_id):
        raise ValueError('Could not verify exact insurance card')
    return card

def project(job,card,shared):
    record=read(job,card['id'])
    if not record['revision']:
        import job_settings as js
        if 'desc' not in card:
            card=source_card(card['id'])
        record=dict(record,values={f:v for f,v in js.from_card(card.get('desc') or '').items() if f in FIELDS})
    return overlay(shared,record)

def save_editor(job,card_id,patch,context):
    owner=scope(job,card_id)
    if not context or any(context.get(k)!=v for k,v in owner.items()):
        raise ValueError('Reopen this card before saving its insurance details.')
    if context.get('revision')==0:
        patch={**{k:v for k,v in (context.get('initial_values') or {}).items() if k in FIELDS},**patch}
    return write(job,card_id,patch,context.get('revision'))
