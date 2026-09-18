"""Pure evidence rules: no timestamps or identities inferred from names alone."""
import re
from datetime import datetime

AR_BOARD = '63c6ea7513fb8f018df6b605'  # Existing IE AR board used by office reviews.

def timing(completed, sent):
    if not completed or not sent:
        return {'status':'Unverified','minutes':None,'reason':'Inspection completion and initial-note sent times are required.'}
    try:
        if not all(re.match(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}',v) for v in (completed,sent)):
            raise ValueError('Explicit clock times required')
        start=datetime.fromisoformat(completed.replace('Z','+00:00'))
        end=datetime.fromisoformat(sent.replace('Z','+00:00'))
        minutes=(end-start).total_seconds()/60
    except (ValueError,TypeError):
        return {'status':'Unverified','minutes':None,'reason':'Use comparable timestamps with the same timezone basis.'}
    if minutes<0:
        return {'status':'Unverified','minutes':minutes,'reason':'Note precedes inspection completion; review the evidence.'}
    return {'status':'Yes' if minutes<=60 else 'No','minutes':round(minutes,1),'reason':'Due within 60 minutes after inspection completion.'}

def identifiers(card):
    text=card.get('desc','').replace('**','')
    return {re.sub(r'[^A-Z0-9]','',m.group(1).upper()) for m in re.finditer(
        r'(?im)^\s*(?:claim|job)\s*(?:number|no\.?|#)\s*:?\s*([A-Za-z0-9-]{5,})',text)}

def division(card):
    text=card.get('name','')+'\n'+card.get('desc','')
    match=re.search(r'(?im)^\s*(?:division|job type)\s*:\s*(EMS|Contents|Recon)\b',text)
    if not match: match=re.match(r'(?i)^\s*(EMS|Contents|Recon)\s*[-:]',text)
    return match.group(1).lower() if match else None

def candidates(card, others, saved_id=None):
    tokens=lambda s:set(re.findall(r'[a-z]{3,}',s.lower()))-set('ems contents recon water fire mold aaa mercury insurance state farm self pay property management apartments'.split())
    matches=[]
    for other in others:
        same_id=bool(identifiers(card)&identifiers(other))
        same_division=division(card) is not None and division(card)==division(other)
        unit=lambda c:set(re.findall(r'(?i)\b(?:unit|apt|apartment)\s*#?\s*([a-z0-9-]+)',c.get('name','')+' '+c.get('desc','')))
        units_ok=unit(card)==unit(other)
        linked=bool(other.get('shortUrl') and other['shortUrl'] in card.get('desc',''))
        saved=other['id']==saved_id
        name=bool(tokens(card.get('name',''))&tokens(other.get('name','')))
        if not (saved or linked or same_id or name): continue
        reason='Saved confirmed link' if saved else 'Exact card link' if linked else 'Claim/job number + division' if same_id and same_division and units_ok else 'Possible match — confirm identity, division and unit'
        matches.append({'card':other,'reason':reason,'strong':saved or linked or (same_id and same_division and units_ok)})
    return sorted(matches,key=lambda m:(not m['strong'],m['card'].get('name','')))

def billing_facts(evidence):
    """Only explicit dated statements; retain every source, not a latest-wins guess."""
    facts=[]
    for comment in evidence.get('comments',[]):
        if '[LH logs audit ' in comment['text']: continue
        for line in comment['text'].replace('**','').splitlines():
            m=re.search(r'(?i)\b(?:(EMS|Contents|Recon)\s+)?(?:billed|billing completed)\s*(?:on\s+|:\s*)?(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\b',line)
            if m and not re.search(r'(?i)\b(not|never|will|should|would|could|to be)\b',line[:m.end()]):
                raw=m.group(2)
                try:
                    dt=datetime.fromisoformat(raw) if '-' in raw else datetime.strptime(raw,'%m/%d/%Y' if len(raw.split('/')[-1])==4 else '%m/%d/%y')
                except ValueError: continue
                facts.append({'status':'Billed','date':dt.date().isoformat(),'division':(m.group(1) or division(evidence.get('card',{})) or 'unspecified').lower(),'source':comment})
            elif re.search(r'(?i)\b(?:not (?:yet )?billed|still not billed|has not been billed)\b',line):
                facts.append({'status':'Not billed','date':None,'division':division(evidence.get('card',{})) or 'unspecified','source':comment})
    return facts

def compare(logs, ar):
    left,right=billing_facts(logs),billing_facts(ar)
    conflicts=[]
    for a in left:
        for b in right:
            if a['division']!=b['division'] and 'unspecified' not in (a['division'],b['division']): continue
            if a['status']!=b['status'] or (a['date'] and b['date'] and a['date']!=b['date']):
                conflicts.append({'logs':a,'ar':b})
    return {'logs_facts':left,'ar_facts':right,'conflicts':conflicts,
            'summary':'Conflicting billing evidence — resolve or use Questions.' if conflicts else 'No explicit conflict detected. Review both sources; this is not a billing confirmation.'}
