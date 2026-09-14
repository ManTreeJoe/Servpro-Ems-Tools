def test_schedule_uses_canonical_editable_roster(monkeypatch):
    import audit_logic, persistence
    from run_doc_editor_web import Api
    monkeypatch.setattr(audit_logic,'ensure_roster_seeded',lambda:None)
    monkeypatch.setattr(persistence,'get_user_techs',lambda:{'names':['Sam','Alex'],'abbrev':{'S':'Sam','AL':'Alex'}})
    result=Api().get_crew_roster()
    assert result['ok']
    assert result['entries']==[{'name':'Alex','aliases':['AL']},{'name':'Sam','aliases':['S']}]

def test_schedule_roster_failure_is_explicit(monkeypatch):
    import audit_logic
    from run_doc_editor_web import Api
    def fail(): raise OSError('Unreadable')
    monkeypatch.setattr(audit_logic,'ensure_roster_seeded',fail)
    result=Api().get_crew_roster()
    assert not result['ok']
    assert result['entries']==[]
