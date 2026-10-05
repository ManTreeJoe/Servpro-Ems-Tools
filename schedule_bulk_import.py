"""Conservative Run matching. No fuzzy match silently becomes an identity."""
import re
from uuid import NAMESPACE_URL, uuid5


def words(value):
    return re.findall(r'[a-z0-9]+', str(value or '').casefold())


def name_words(value):
    value = re.split(r'\s*-\s*', value or '')[0]
    return set(words(re.sub(r'\([^)]*\)', '', value)))


def match_job(raw, jobs):
    name = name_words(raw.split(':')[0])
    evidence = []
    names = {j['job_id'] for j in jobs if len(name)>=2 and name == name_words(j.get('display_name'))}
    if names:
        evidence.append(names)
    raw_words = ' ' + ' '.join(words(raw)) + ' '
    addresses = set()
    for job in jobs:
        tokens = words(job.get('address'))
        if len(tokens)>=3 and tokens[0].isdigit() and (' '+' '.join(tokens[:3])+' ') in raw_words:
            addresses.add(job['job_id'])
    if addresses:
        evidence.append(addresses)
    if not evidence:
        return None, 'No unique name/address match'
    candidates = set.intersection(*evidence)
    if len(candidates)!=1:
        return None, 'Ambiguous or conflicting job matches'
    return next(iter(candidates)), 'Unique name/address match'


def commands(preview, jobs):
    entries, skipped = [], []
    for row in preview['visits']:
        if row['struck']:
            skipped.append({'text': row['raw_text'], 'reason': 'Crossed out in source'})
            continue
        raw = row['raw_text']
        if len(raw)>3800:
            raise ValueError('A Run line exceeds 3,800 characters. Shorten that line before importing; no entries were saved.')
        jid, reason = match_job(raw, jobs)
        queue, group = row.get('queue'), row.get('group')
        date = row.get('proposed_date')
        review = ''
        if not queue:
            queue, group, date = 'hold', 'On Hold', None
            review = 'Original section needs review: '+str(row['section'])
        elif queue=='scheduled' and not date:
            queue, group = 'tbs', 'TBS Mitigation'
            review = 'Upcoming date needs review; original line retained below.'
        labels = []
        if row['section']=='monitor' or re.search(r'\bmonitor\b',raw,re.I):
            labels.append('Monitor')
        for pattern,label in [(r'\bdemo\b','Demo'),(r'\breinspection\b','Reinspection'),
                              (r'\binitial inspection\b','Initial inspection'),
                              (r'\b(?:equipment|eq) pickup\b','Equipment pickup'),
                              (r'\bpackout\b','Packout')]:
            if re.search(pattern,raw,re.I): labels.append(label)
        if not labels: labels=['Work to be reviewed']
        title=raw.split(':')[0].strip()[:300] or raw[:300]
        note=raw+'\nSource: '+preview['source_filename'][:100]
        if review: note+='\n'+review
        if len(note)>4000: raise ValueError('Imported notes exceed the schedule limit; no entries were saved.')
        entries.append({'contract_version':2,'department':preview['workspace'],
            'operation_id':str(uuid5(NAMESPACE_URL,'bulk-save:'+row['source_row_key'])),
            'expected_revision':0,'entry_title':title,'source_key':row['source_row_key'],
            'visit':{'id':row['draft_id'],'job_id':jid,'queue':queue,'group':group,'date':date,
                     'arrival':'','activities':[{'label':label,'people':[]} for label in labels],
                     'equipment':'','access':'','notes':note,'status':'active'},
            'match_reason':reason,'review_note':review})
    if len(entries)>500: raise ValueError('Import supports at most 500 Run lines at a time.')
    return entries, skipped
