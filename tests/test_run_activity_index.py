from datetime import date
import json
import run_activity_index as index


def test_exact_key_only():
    assert index.client_key('Evans, Linda - AAA') == index.client_key('Linda Evans')
    assert index.client_key('Linda') != index.client_key('Linda Evans')


def test_commit_idempotent_scoped(tmp_path, monkeypatch):
    db = tmp_path / 'history.sqlite3'
    row = {'key':'linda evans', 'iso':'2026-09-01', 'raw':'Demo', 'status':'scheduled'}
    assert index.commit([row,row], db, 'ems') == 1
    assert index.commit([row], db, 'ems') == 0
    monkeypatch.setattr(index, 'location', lambda: (db,'ems','unused'))
    assert index.history('Evans, Linda - AAA') == [row]
    assert index.history('Evans') == []
    monkeypatch.setattr(index, 'location', lambda: (db,'other','unused'))
    assert index.history('Linda Evans') == []


def test_scan_date_bounds_claims_and_duplicates(tmp_path, monkeypatch):
    import run_doc
    for name in ['Tuesday 9.1.26.docx','Copy 9.1.26.docx','Wednesday 9.2.26.docx','Old 7.1.26.docx']:
        (tmp_path/name).touch()
    monkeypatch.setattr(run_doc,'_month_search_dirs',lambda *args:[str(tmp_path)])
    def parse(path):
        return ([{'client':'Linda Evans','raw':'Linda Evans: Demo','section':'work'},
                 {'client':'Property','raw':'Property: Demo','unit':'12'}],
                '09-03-2026' if '9.2.26' in path else '09-01-2026')
    monkeypatch.setattr(index,'parse_source',parse)
    result=index.scan(date(2026,9,1),date(2026,9,2),str(tmp_path))
    assert result['documents']==3
    assert len(result['rows'])==1
    assert result['rows'][0]['iso']=='2026-09-01'
    assert len(result['excluded'])==3
    assert result['errors']==[]
