"""Conservative, inspectable suggestions. No keyword can approve an audit."""
import re
from datetime import date
from logs_audit_evidence import division, timing, billing_facts

LABELS = {
    'ems_start': r'ems (?:physical )?work start(?:ed| date)?',
    'contents_start': r'original contents card start(?:ed| date)?',
    'job_date': r'date rec(?:ei|ie)ved|rec(?:ei|ie)ved date|job rec(?:ei|ie)ved(?: date)?',
    'scope': r'scope being audited|division|job type',
    'ems_estimator': r'ems estimator',
    'contents_estimator': r'contents estimator',
    'inspection_completed_at': r'inspection (?:completed|finished)(?: at)?',
    'initial_note_sent_at': r'initial note sent(?: at)?',
    'missed_by': r'coordinator who missed it',
    'ems_ready': r'ems ready for billing',
    'ems_billed': r'ems billed|ems billing completed',
    'contents_ready': r'contents ready for billing',
    'contents_billed': r'contents billed|contents billing completed',
}
TOPICS = {
    'initial_note': r'initial.*(?:note|inspection)|(?:note|inspection).*initial',
    'job_date': r'date rec(?:ei|ie)ved|rec(?:ei|ie)ved date|job rec(?:ei|ie)ved',
    'file_status': r'workcenter|\bwc\b|file.*(?:closed|open|merge)',
    'ems_estimator': r'estimat', 'contents_estimator': r'contents.*estimat',
    'ems_ready': r'ready.*bill', 'contents_ready': r'contents.*ready.*bill',
    'ems_billed': r'\bbilled\b', 'contents_billed': r'contents.*\bbilled\b',
    'billing_evidence': r'\bbilled\b',
    'payment_notes': r'paid|payment|check.*(?:pick|receiv)|balance',
    'field_notes': r'inspection|moisture|equipment|demolition|drying',
    'estimator_notes': r'estimat|approval|supplement',
    'audit_notes': r'question|missing|hold|clarif|outstanding',
}

def normalize(key, value):
    value = value.strip().strip('*').strip()
    if key in ('inspection_completed_at','initial_note_sent_at'):
        from datetime import datetime
        try:
            # Require explicit date and clock time, never a comment timestamp.
            if not re.match(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}',value): return None
            parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
            return parsed.isoformat()
        except ValueError: return None
    if key.endswith(('_start', '_ready', '_billed')) or key == 'job_date':
        try:
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value): return date.fromisoformat(value).isoformat()
            match = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})', value)
            if match:
                m,d,y = map(int, match.groups())
                return date(y+2000 if y<100 else y,m,d).isoformat()
        except ValueError:
            pass
        return None
    options = {'initial_note': ['Yes','No','N/A'], 'file_status': ['Closed','Open','Needs Merge','N/A'],
               'scope': ['EMS','Contents','EMS + Contents','Recon','Service call / no charge']}
    if key in options: return next((v for v in options[key] if v.lower()==value.lower()),None)
    return value if value and len(value)<100 and value.lower() not in ('unknown','tbd','none','not assigned') else None

def suggest(evidence):
    sources = [{'id':'description','title':'Card description','text':evidence['card'].get('desc','')}]
    sources += [{'id':a['id'],'title':f"{a.get('date','')[:10]} · {a.get('author','')}", 'text':a['text']}
                for a in evidence['comments'] if '[LH logs audit ' not in a['text']]
    sources += [{'id':'checklist:'+c.get('id',str(i)), 'title':'Checklist · '+c.get('name',''),
                 'text':'\n'.join(('Complete: ' if x.get('state')=='complete' else 'Incomplete: ')+x['name'] for x in c.get('checkItems',[]))}
                for i,c in enumerate(evidence['checklists'])]
    result = {}
    for key in set(LABELS)|set(TOPICS):
        candidates=[]; refs=[]
        for source in sources:
            # Job Date is the intake date in the card description, not a
            # comment/checklist date, inspection date, or Trello creation date.
            if key == 'job_date' and source['id'] != 'description':
                continue
            plain=source['text'].replace('**','')
            if key == 'job_date':
                plain=re.sub(r'(?m)^\s*(?:[-*#>]\s*)+', '', plain).replace('__','')
            matches=list(re.finditer(r'(?im)^\s*(?:'+LABELS[key]+r')\s*:\s*([^\n]+)',plain)) if key in LABELS and not source['id'].startswith('checklist:') else []
            if matches or (key in TOPICS and re.search(TOPICS[key],plain,re.I)):
                refs.append(source)
            for match in matches:
                val=normalize(key,match.group(1))
                if val is not None: candidates.append({'value':val,'source_id':source['id']})
        values={c['value'] for c in candidates}
        result[key]={'value':next(iter(values)) if len(values)==1 else None,
                     'conflict':len(values)>1,'candidates':candidates,'sources':refs}
        if key in ('field_notes','estimator_notes','payment_notes','billing_evidence') and refs:
            # These are quoted notes, not a classification or pass. Retain the
            # original wording (including negatives, partial balances, plans).
            excerpts=[]
            for source in refs:
                lines=[line for line in source['text'].splitlines() if re.search(TOPICS[key],line,re.I)]
                excerpts.append(source['title']+'\n'+'\n'.join(lines))
            result[key]['value']='Source notes — verify applicability:\n\n'+'\n\n'.join(excerpts)
    # Operational authorship is evidence; mentions and copied email recipients
    # are not ownership. Never default Contents to a particular employee.
    for comment in evidence['comments']:
        text=comment['text']
        if '[LH logs audit ' in text: continue
        plain=text.replace('**','')
        audit=bool(re.search(r'(?im)^\s*#*\s*(?:contents\s+)?est\s*audit\b',plain))
        invoice=bool(re.search(r'(?im)^\s*(?:i am |i\s+)?requesting\s+(?:an?\s+)?(?:contents\s+)?invoice\b',plain))
        contents=division(evidence['card'])=='contents' or bool(re.search(r'(?im)^\s*#*\s*contents\s+est\s*audit\b|requesting\s+(?:an?\s+)?contents\s+invoice',plain))
        ownership=bool(re.search(r'(?i)\bI(?:\s+have|\x27ve)?\s+(?:picked up|grabbed|taken|am handling)\s+(?:the\s+)?contents\s+(?:job|card|estimate)\b',plain))
        source=next((s for s in sources if s['id']==comment['id']),None)
        if not source: continue
        if (audit or invoice or ownership) and comment.get('author'):
            key='contents_estimator' if contents or ownership else 'ems_estimator'
            target=result[key]
            target['candidates'].append({'value':comment['author'],'source_id':comment['id']})
            if source not in target['sources']: target['sources'].append(source)
            values={c['value'] for c in target['candidates']}
            target.update(value=next(iter(values)) if len(values)==1 else None,conflict=len(values)>1)
        if audit:
            target=result['estimator_notes']
            if source not in target['sources']: target['sources'].append(source)
        if re.search(r'\btonia\b',comment.get('author',''),re.I):
            target=result['billing_evidence']
            if source not in target['sources']: target['sources'].append(source)
    for key in ('estimator_notes','billing_evidence'):
        refs=result[key]['sources']
        if refs: result[key]['value']='Source notes — verify applicability:\n\n'+'\n\n'.join(s['title']+'\n'+s['text'] for s in refs)
    result['file_status']['value']=None
    result['file_status']['manual']=True
    scoped=division(evidence['card'])
    if scoped and result['scope']['value'] is None and not result['scope']['conflict']:
        result['scope'].update(value={'ems':'EMS','contents':'Contents','recon':'Recon'}[scoped],sources=[{'id':'card','title':'Card title / division','text':evidence['card'].get('name','')+'\n'+evidence['card'].get('desc','')}])
    for fact in billing_facts(evidence):
        if fact['status']!='Billed' or fact['division'] not in ('ems','contents'): continue
        target=result[fact['division']+'_billed']
        target['candidates'].append({'value':fact['date'],'source_id':fact['source']['id']})
        source=next((s for s in sources if s['id']==fact['source']['id']),None)
        if source and source not in target['sources']:target['sources'].append(source)
        values={c['value'] for c in target['candidates']}
        target.update(value=next(iter(values)) if len(values)==1 else None,conflict=len(values)>1)
    clock=timing(result['inspection_completed_at']['value'],result['initial_note_sent_at']['value'])
    result['initial_note'].update(value=clock['status'] if clock['status'] in ('Yes','No') else None,
        sources=result['inspection_completed_at']['sources']+result['initial_note_sent_at']['sources']+result['initial_note']['sources'])
    return result
