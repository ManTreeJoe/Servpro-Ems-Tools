def test_schedule_uses_canonical_editable_roster(monkeypatch):
    import audit_logic, persistence
    import config
    monkeypatch.setattr(config, 'active_department', lambda: 'OC')
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


def test_approved_ie_roster_deduplicates_without_mutating_local_data():
    from copy import deepcopy
    from scheduling_roster import entries
    local = {'names': ['Jose', 'Jose M', 'Vicente', 'Vince', 'Aaron', 'New hire'],
             'abbrev': {'JL': 'Jose', 'AP': 'Aaron', 'NH': 'New hire'}}
    before = deepcopy(local)
    roster = {p['name']: p['aliases'] for p in entries('IE', local)}
    assert local == before
    assert len(roster) == 34
    assert roster['Jose Diaz'] == ['Jose']
    assert roster['Jose Manuel'] == ['Jose M']
    assert roster['Johnny'] == ['JL']
    assert roster['Aaron P'] == ['Aaron', 'AP']
    assert roster['Vince'] == ['Vicente']
    assert roster['New hire'] == ['NH']
    assert 'Jose' not in roster and 'Vicente' not in roster
    assert 'Rafa' in roster and 'Mike' in roster


def test_approved_aliases_have_exactly_one_owner():
    from scheduling_roster import entries
    roster = entries('IE', {})
    tokens = [s.casefold() for p in roster for s in [p['name'], *p['aliases']]]
    assert len(tokens) == len(set(tokens))
    assert {p['name']: p['aliases'] for p in roster}['Mario Nevarez'] == ['Mario N', 'Nevarez']
    assert {p['name']: p['aliases'] for p in roster}['Maricruz'] == ['Cruz', 'M.Cruz']
    roster[0]['aliases'].append('do not persist')
    assert 'do not persist' not in str(entries('IE', {}))


def test_ie_api_returns_approved_people(monkeypatch):
    import audit_logic, persistence, config
    from run_doc_editor_web import Api
    monkeypatch.setattr(config, 'active_department', lambda: 'IE')
    monkeypatch.setattr(audit_logic, 'ensure_roster_seeded', lambda: None)
    monkeypatch.setattr(persistence, 'get_user_techs', lambda: {'names': [], 'abbrev': {}})
    result = Api().get_crew_roster()
    assert result['ok'] and len(result['entries']) == 33
    assert all(set(p) == {'name', 'aliases'} for p in result['entries'])
