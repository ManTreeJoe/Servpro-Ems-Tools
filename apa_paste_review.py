"""Resumable APA table review. Searches Trello; never writes to Trello.

Queue identity is source job + claim + division + requirement, never name alone.
Human confirmation is required for every added or existing entry.
"""
import csv
import hashlib
import json
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from docx import Document
import apa_logic as apa
from apa_digital_archive import scope_key


def normalize(value):
    return re.sub(r'[^a-z0-9]', '', str(value).casefold())


def name_key(value):
    return sorted(re.findall(r'[a-z]+', str(value).casefold()))


def item_key(text):
    return ' '.join(apa.wrap_item(text).get('text',text).casefold().split())


def saved_link(text):
    import paths
    db=Path(paths.DATA_DIR)/'apa_paste_review'/(scope_key(apa._apa_root())+'.sqlite3')
    if not db.exists(): return None
    with sqlite3.connect(db) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='links'").fetchone(): return None
        found=conn.execute('SELECT data FROM links WHERE item_key=?',(item_key(text),)).fetchone()
    return json.loads(found[0]) if found else None


def repin_saved_link(text, card_id):
    link = saved_link(text)
    if not link:
        return False
    import paths
    db = Path(paths.DATA_DIR)/'apa_paste_review'/(scope_key(apa._apa_root())+'.sqlite3')
    link['card_id'] = card_id
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE links SET data=? WHERE item_key=?',
                     (json.dumps(link), item_key(text)))
    return True


def parse_table(text):
    rows, errors, seen = [], [], set()
    for number, line in enumerate(str(text).splitlines(), 1):
        if not line.strip(): continue
        if '\t' in line:
            cells = next(csv.reader([line], delimiter='\t'))
        elif '|' in line:
            cells = [v.strip() for v in line.strip().strip('|').split('|')]
        else:
            errors.append(f'Line {number}: paste the full table, not just a name.'); continue
        cells = [c.strip() for c in cells]
        if not cells or re.fullmatch(r'[- :]+', cells[0] or ''): continue
        if not cells[0].isdigit():
            if any(word in cells[0].casefold() for word in ('job','id','number')): continue
            errors.append(f'Line {number}: missing numeric job ID.'); continue
        if len(cells) < 8:
            errors.append(f'Line {number}: expected at least eight columns.'); continue
        requirement = cells[7]
        kinds = re.findall(r'\b(initial|final) job\b', requirement, re.I)
        kind = kinds[0].lower() if len(set(k.lower() for k in kinds)) == 1 else ''
        division = 'contents' if 'contents' in cells[4].casefold() or cells[3].upper().endswith(':CON') else 'water' if cells[4].casefold() == 'water' else cells[4].casefold()
        if not kind or not cells[1] or not cells[3]:
            errors.append(f'Line {number}: customer, claim, or Initial/Final Job requirement is missing.'); continue
        identity = '|'.join((cells[0], normalize(cells[3]), division, kind))
        if identity in seen: continue
        seen.add(identity)
        rows.append({'key':identity,'job_id':cells[0],'customer':cells[1],
            'received':cells[2],'claim':cells[3],'division':division,'carrier':cells[5],
            'due':cells[6],'requirement':kind,'requirement_text':requirement,'source_row':cells})
    if len(rows)>250: raise ValueError('Review up to 250 rows per batch.')
    return rows, errors


def routing(row, suggested):
    if row['requirement']=='initial':
        return apa.SEC_INITIAL_UPLOADS, 'AARON' if row['division']=='contents' else ''
    if row['division']=='contents': return 'PABLO', ''
    return suggested.get('suggested_section') or '', suggested.get('suggested_sub') or ''


def doc_revision(path):
    p=Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else 'missing'


def read_sections(path):
    if Path(path).exists(): Document(path)  # Fail closed; legacy parser masks errors.
    return apa.parse_existing_doc(path)


class Review:
    def __init__(self, api):
        import paths
        self.api=api
        self.root=str(Path(apa._apa_root()).resolve())
        self.scope=scope_key(self.root)
        folder=Path(paths.DATA_DIR)/'apa_paste_review';folder.mkdir(parents=True,exist_ok=True)
        self.db=folder/(self.scope+'.sqlite3')
        with self.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS batches (id TEXT PRIMARY KEY, day TEXT NOT NULL, data TEXT NOT NULL)')
            conn.execute('CREATE TABLE IF NOT EXISTS links (item_key TEXT PRIMARY KEY, data TEXT NOT NULL)')

    def connect(self):
        return sqlite3.connect(self.db, timeout=15)

    def load(self, batch_id):
        with self.connect() as conn:
            found=conn.execute('SELECT data FROM batches WHERE id=?',(batch_id,)).fetchone()
        if not found: raise ValueError('Queue not found in this workspace.')
        return json.loads(found[0])

    def store(self, batch):
        with self.connect() as conn:
            conn.execute('INSERT OR REPLACE INTO batches VALUES (?,?,?)',
                         (batch['id'],batch['day'],json.dumps(batch)))

    def start(self, text, day):
        date.fromisoformat(day)
        rows, errors=parse_table(text)
        if errors: return {'ok':False,'error':'\n'.join(errors),'parsed':len(rows)}
        if not rows: raise ValueError('No job rows found. Paste the entire APA Monitor table.')
        batch_id=hashlib.sha256((day+json.dumps(rows,sort_keys=True)).encode()).hexdigest()[:24]
        try: batch=self.load(batch_id)
        except ValueError:
            batch={'id':batch_id,'day':day,'rows':[dict(r,state='pending') for r in rows],
                   'created_at':datetime.now(timezone.utc).isoformat()}
            self.store(batch)
        return {'ok':True,'batch':batch}

    def recent(self, day):
        with self.connect() as conn:
            found=conn.execute('SELECT data FROM batches WHERE day=? ORDER BY rowid DESC LIMIT 1',(day,)).fetchone()
        return {'ok':True,'batch':json.loads(found[0]) if found else None}

    def inspect(self, batch_id, index, query=''):
        import trello_client as tc
        batch=self.load(batch_id);row=batch['rows'][int(index)]
        day=date.fromisoformat(batch['day']);path=apa.doc_path_for_today(day)
        revision=doc_revision(path);sections=read_sections(path)
        if doc_revision(path)!=revision: raise ValueError('APA changed while loading. Review this row again.')
        existing=[]
        for lane, items in sections.items():
            for position,(text,highlight) in enumerate(items):
                base=text.split(' - ')[0]
                if name_key(base)==name_key(row['customer']):
                    existing.append({'lane':lane,'index':position,'text':text,'highlighted':highlight,
                        'division_hint':'contents' if 'contents' in text.casefold() else 'not labeled Contents'})
        # Search per row; failures are surfaced rather than interpreted as no match.
        queries=[query.strip()] if query.strip() else [row['claim'].split(':')[0], row['customer']]
        cards={}
        for q in queries:
            for hit in tc.find_cards_by_name(q, max_results=20):
                card_id=hit.get('card_id')
                if card_id: cards[card_id]=hit
        hits=list(cards.values())
        for hit in hits:
            hit['match_note']='Review claim and division; search result is not verified.'
        row['candidates']=hits;row['existing']=existing;row['revision']=revision
        row.pop('selection', None)
        self.store(batch)
        return {'ok':True,'row':row,'lanes':self.api.section_list(),'revision':revision}

    def choose(self, batch_id, index, card_id):
        import trello_client as tc
        batch=self.load(batch_id);row=batch['rows'][int(index)]
        hit=next((h for h in row.get('candidates',[]) if h['card_id']==card_id),None)
        if not hit: raise ValueError('Search and select a card from this row first.')
        card=tc.get_card_lite(card_id,fields='name,desc,idBoard,idList,closed')
        if not card or card.get('closed'): raise ValueError('Selected card is unavailable or archived.')
        suggestion=self.api.suggest_apa_routing(card_id,hit.get('list_name',''),card.get('name',''))
        lane,sub=routing(row,suggestion)
        claim=(tc.parse_card_desc(card.get('desc','')) or {}).get('claim','')
        row['selection']={'card_id':card_id,'name':card.get('name',''),'description':card.get('desc',''),
            'board':hit.get('board',''),'trello_lane':hit.get('list_name',''),
            'lane':lane,'sub':sub,'claim_from_card':claim}
        self.store(batch)
        return {'ok':True,'selection':row['selection']}

    def commit(self,batch_id,index,action,lane='',sub='',existing_index=None,confirmed=False,distinct=False):
        if confirmed is not True: raise ValueError('Confirm the reviewed card and entry first.')
        # Serialize confirmations per queue database. This does not claim to lock other PCs.
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            found=conn.execute('SELECT data FROM batches WHERE id=?',(batch_id,)).fetchone()
            if not found: raise ValueError('Queue not found.')
            batch=json.loads(found[0]);row=batch['rows'][int(index)]
            if row['state']!='pending': return {'ok':True,'batch':batch}
            if action=='skip': row['state']='skipped'
            else:
                if action not in ('add','existing'): raise ValueError('Unknown review action.')
                selection=row.get('selection')
                if not selection: raise ValueError('Select and review a Trello card first.')
                path=apa.doc_path_for_today(date.fromisoformat(batch['day']))
                if doc_revision(path)!=row.get('revision'):
                    raise ValueError('APA changed. Reload this row before confirming; nothing was added.')
                sections=read_sections(path)
                if action=='existing':
                    candidates=row.get('existing',[])
                    if existing_index is None: raise ValueError('Select the existing APA entry to confirm.')
                    chosen=candidates[int(existing_index)]
                    if sections[chosen['lane']][chosen['index']][0]!=chosen['text']:
                        raise ValueError('Existing entry changed. Review again.')
                    row['state']='confirmed existing';row['confirmed_entry']=chosen
                    # Confirm presence only; never mark uploaded or change a reviewed item silently.
                else:
                    if row.get('existing') and distinct is not True:
                        raise ValueError('This customer already has APA entries. Confirm an existing entry, or explicitly distinguish the other claim/division first.')
                    expected,expected_sub=routing(row,{'suggested_section':lane,'suggested_sub':sub})
                    if (lane,sub)!=(expected,expected_sub):
                        raise ValueError('Initial/Contents routing must follow the approved rule.')
                    order=apa._persisted_section_order()
                    if lane not in order: raise ValueError('Destination lane is not configured.')
                    # Keep source identity in the stable text (before the
                    # mutable sub/status suffix) so initial/final links cannot
                    # collide even when the claim and destination are equal.
                    text=row['customer']+' - '+row['carrier']
                    text+=f" [{row['requirement'].title()} #{row['job_id']}]"
                    if row['division']=='contents': text+=' - Contents'
                    text+=' ['+row['claim']+']'
                    if sub: text+='-'+sub
                    text+='-pending'
                    if any(t==text for items in sections.values() for t,h in items):
                        raise ValueError('This exact entry already exists. Reload and confirm it instead.')
                    sections.setdefault(lane,[]).append((text,True))
                    payload=[{'name':name,'items':[{'text':t,'highlighted':h} for t,h in items]} for name,items in sections.items()]
                    result=self.api.save_doc(batch['day'],payload)
                    if not result.get('ok'): raise ValueError(result.get('error','APA save failed.'))
                    row['state']='added';row['confirmed_entry']={'lane':lane,'text':text}
                row['confirmed_at']=datetime.now(timezone.utc).isoformat()
                link={'card_id':selection['card_id'],'source_job_id':row['job_id'],
                      'claim':row['claim'],'division':row['division'],
                      'requirement':row['requirement'] if action=='add' else '',
                      'confirmed_at':row['confirmed_at']}
                conn.execute('INSERT OR REPLACE INTO links VALUES (?,?)',
                    (item_key(row['confirmed_entry']['text']),json.dumps(link)))
            conn.execute('UPDATE batches SET data=? WHERE id=?',(json.dumps(batch),batch_id))
        return {'ok':True,'batch':batch}
