"""Exercise real entry dispatch without starting GUI or touching a user profile."""
import ast
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest


class ReachedEmployeeGate(Exception):
    pass


def entry(monkeypatch, allowed=True, another_main=False):
    source=Path(__file__).resolve().parents[1]/'home_web.py'
    tree=ast.parse(source.read_text(encoding='utf-8'))
    function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='main')
    calls=[]
    def claim():calls.append('claim');return not another_main
    def access():
        calls.append('access')
        if not allowed:raise PermissionError('Not approved')
        return {'access_state':'approved'}
    def gate():raise ReachedEmployeeGate()
    monkeypatch.setitem(sys.modules,'employee_access',SimpleNamespace(require_access=access))
    monkeypatch.setitem(sys.modules,'quickimport_web',SimpleNamespace(main=lambda:calls.append('quickimport')))
    def recovery(on_authenticated):
        calls.append('recovery')
        on_authenticated()
    monkeypatch.setitem(sys.modules,'emergency_admin',SimpleNamespace(main=recovery))
    namespace={'_claim_single_instance':claim,'_show_already_running':lambda:calls.append('already-running'),
        '_ensure_root_index':gate}
    exec(compile(ast.Module(body=[function],type_ignores=[]),str(source),'exec'),namespace)
    return namespace['main'],calls


def test_quickimport_without_access_opens_employee_gate(monkeypatch):
    main,calls=entry(monkeypatch,allowed=False)
    with pytest.raises(ReachedEmployeeGate):main(['--quickimport'])
    assert calls==['claim','access']


def test_approved_quickimport_still_opens_its_tool(monkeypatch):
    main,calls=entry(monkeypatch)
    main(['--quickimport'])
    assert calls==['claim','access','quickimport']


def test_recovery_reuses_main_lock_after_authentication(monkeypatch):
    main,calls=entry(monkeypatch)
    with pytest.raises(ReachedEmployeeGate):main(['--emergency-admin'])
    assert calls==['claim','recovery']


def test_recovery_cannot_replace_session_while_another_main_is_open(monkeypatch):
    main,calls=entry(monkeypatch,another_main=True)
    main(['--emergency-admin'])
    assert calls==['claim','already-running']
