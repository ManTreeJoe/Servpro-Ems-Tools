from pathlib import Path
import datetime as dt
import json
import pytest
import apa_logic as apa
import apa_web
import paths
import trello_client as tc
from apa_paste_review import Review, parse_table, routing
from apa_digital_archive import archive_month, snapshot


def table(job='101',division='Contents',kind='Initial',name='LINDA SAMPLE',claim='000123:CON'):
    return '\t'.join([job,name,'9/12/2026 2:03:00 PM',claim,division,'Example Insurance',
                      '9/18/2026 8:55:42 AM',f'({kind} Job must be uploaded and self-audited within compliance days).'])


@pytest.fixture
def env(tmp_path,monkeypatch):
    root=tmp_path/'apa';(root/'2026'/'September').mkdir(parents=True)
    monkeypatch.setattr(paths,'DATA_DIR',str(tmp_path/'data'))
    monkeypatch.setattr(apa,'_apa_root',lambda:str(root))
    monkeypatch.setattr(apa,'_persisted_section_order',lambda:list(apa._DEFAULT_SECTION_ORDER))
    api=apa_web.Api()
    monkeypatch.setattr(tc,'find_cards_by_name',lambda *a,**k:[{'card_id':'card1','name':'Sample, Linda - Contents', 'board':'Contents','list_name':'PABLO'}])
    monkeypatch.setattr(tc,'get_card_lite',lambda *a,**k:{'name':'Sample, Linda - Contents','desc':'Claim Number: 000123:CON','idBoard':'b','idList':'l'})
    monkeypatch.setattr(api,'suggest_apa_routing',lambda *a,**k:{'suggested_section':'KIM','suggested_sub':''})
    return Review(api),api,root


def test_table_parser_preserves_divisions_initial_final_leading_zeroes():
    raw=table()+'\n'+table('102','Water','Final',claim='000123')+'\n'+table()
    rows,errors=parse_table(raw)
    assert not errors and len(rows)==2
    assert rows[0]['claim']=='000123:CON'
    assert rows[0]['key']!=rows[1]['key']
    md='| '+table().replace('\t',' | ')+' |\n| --- | --- |'
    assert len(parse_table(md)[0])==1
    assert parse_table('not a table')[1]
    assert routing(rows[0],{})==(apa.SEC_INITIAL_UPLOADS,'AARON')
    assert routing(dict(rows[0],requirement='final'),{})==('PABLO','')
    assert routing(dict(rows[1],requirement='initial'),{})==(apa.SEC_INITIAL_UPLOADS,'')


def ready(review,text=None):
    batch=review.start(text or table(),'2026-09-16')['batch']
    info=review.inspect(batch['id'],0)
    review.choose(batch['id'],0,'card1')
    return batch,info


def test_queue_selected_date_resume_retry_and_contents_tag(env):
    review,api,root=env;b,info=ready(review)
    assert review.recent('2026-09-16')['batch']['id']==b['id']
    with pytest.raises(ValueError,match='Confirm'):review.commit(b['id'],0,'add')
    result=review.commit(b['id'],0,'add',apa.SEC_INITIAL_UPLOADS,'AARON',confirmed=True)
    assert result['batch']['rows'][0]['state']=='added'
    review.commit(b['id'],0,'add',apa.SEC_INITIAL_UPLOADS,'AARON',confirmed=True)
    parsed=apa.parse_existing_doc(apa.doc_path_for_today(dt.date(2026,9,16)))
    assert len(parsed[apa.SEC_INITIAL_UPLOADS])==1
    assert 'Contents [000123:CON]-AARON-pending' in parsed[apa.SEC_INITIAL_UPLOADS][0][0]
    assert not Path(apa.doc_path_for_today(dt.date(2026,9,18))).exists()
    assert list((Path(paths.DATA_DIR)/'apa_digital_archive').rglob('snapshot.json'))


def test_same_name_water_is_explicitly_distinct(env):
    review,api,root=env;b,_=ready(review)
    review.commit(b['id'],0,'add',apa.SEC_INITIAL_UPLOADS,'AARON',confirmed=True)
    water=table('102','Water','Final',claim='000123')
    w,info=ready(review,water)
    assert len(info['row']['existing'])==1
    with pytest.raises(ValueError,match='already has'):review.commit(w['id'],0,'add','KIM',confirmed=True)
    review.commit(w['id'],0,'add','KIM',confirmed=True,distinct=True)
    parsed=apa.parse_existing_doc(apa.doc_path_for_today(dt.date(2026,9,16)))
    assert sum(map(len,parsed.values()))==2


def test_existing_confirmation_does_not_change_status_or_move(env):
    review,api,root=env
    path=apa.doc_path_for_today(dt.date(2026,9,16))
    apa.write_doc(path,dt.date(2026,9,16),{'PABLO':[('LINDA SAMPLE - Example Insurance - Contents-uploaded',False)]})
    before=Path(path).read_bytes();b,info=ready(review)
    result=review.commit(b['id'],0,'existing',existing_index=0,confirmed=True)
    assert result['batch']['rows'][0]['state']=='confirmed existing'
    assert Path(path).read_bytes()==before


def test_stale_review_blocked_network_errors_and_skip(env,monkeypatch):
    review,api,root=env;b,_=ready(review)
    apa.write_doc(apa.doc_path_for_today(dt.date(2026,9,16)),dt.date(2026,9,16),{'KIM':[('Other job',False)]})
    with pytest.raises(ValueError,match='changed'):review.commit(b['id'],0,'add',apa.SEC_INITIAL_UPLOADS,'AARON',confirmed=True)
    monkeypatch.setattr(tc,'find_cards_by_name',lambda *a,**k: (_ for _ in ()).throw(OSError('offline')))
    with pytest.raises(OSError):review.inspect(b['id'],0)
    assert review.load(b['id'])['rows'][0]['state']=='pending'
    assert review.commit(b['id'],0,'skip',confirmed=True)['batch']['rows'][0]['state']=='skipped'


def test_month_backup_preserves_raw_and_before_after(env):
    review,api,root=env;day=dt.date(2026,9,16);path=apa.doc_path_for_today(day)
    apa.write_doc(path,day,{'KIM':[('One',True)]});old=Path(path).read_bytes()
    apa.write_doc(path,day,{'KIM':[('Two',False)]})
    report=archive_month(root,'2026-09')
    assert report['copied']==1 and not report['failures'] and not report['unreadable']
    raws=list((Path(paths.DATA_DIR)/'apa_digital_archive').rglob('original.docx'))
    assert any(p.read_bytes()==old for p in raws)
    records=[json.loads(p.read_text()) for p in (Path(paths.DATA_DIR)/'apa_digital_archive').rglob('snapshot.json')]
    assert any(any('One' in r['text'] for r in d['paragraphs']) for d in records)


def test_backup_failure_blocks_overwrite(env,monkeypatch):
    review,api,root=env;day=dt.date(2026,9,16);path=apa.doc_path_for_today(day)
    apa.write_doc(path,day,{'KIM':[('Keep',False)]});old=Path(path).read_bytes()
    import apa_digital_archive
    monkeypatch.setattr(apa_digital_archive,'snapshot',lambda *a,**kw: (_ for _ in ()).throw(OSError('backup full')))
    with pytest.raises(OSError):apa.write_doc(path,day,{'KIM':[('New',False)]})
    assert Path(path).read_bytes()==old


def test_review_links_survive_status_and_support_repin(env):
    from apa_paste_review import saved_link
    review,api,_=env;b,_=ready(review)
    result=review.commit(b['id'],0,'add',apa.SEC_INITIAL_UPLOADS,'AARON',confirmed=True)
    text=result['batch']['rows'][0]['confirmed_entry']['text']
    changed=text.removesuffix('pending')+'uploaded'
    assert saved_link(changed)['card_id']=='card1'
    assert api.pin_trello_for_item(changed,'card2')['ok']
    assert saved_link(text)['card_id']=='card2'


def test_research_requires_fresh_card_selection(env):
    review,_,_=env;b,_=ready(review)
    review.inspect(b['id'],0)
    with pytest.raises(ValueError,match='Select and review'):
        review.commit(b['id'],0,'add',apa.SEC_INITIAL_UPLOADS,'AARON',confirmed=True)


def test_initial_and_final_for_same_water_job_keep_separate_links(env):
    from apa_paste_review import saved_link
    review, _, _ = env
    initial, _ = ready(review, table('102', 'Water', 'Initial', claim='000123'))
    added = review.commit(initial['id'], 0, 'add', apa.SEC_INITIAL_UPLOADS, confirmed=True)
    initial_text = added['batch']['rows'][0]['confirmed_entry']['text']
    final, _ = ready(review, table('102', 'Water', 'Final', claim='000123'))
    added = review.commit(final['id'], 0, 'add', 'KIM', confirmed=True, distinct=True)
    final_text = added['batch']['rows'][0]['confirmed_entry']['text']
    assert initial_text != final_text
    assert saved_link(initial_text)['requirement'] == 'initial'
    assert saved_link(final_text)['requirement'] == 'final'
    assert saved_link(initial_text)['source_job_id'] == '102'
