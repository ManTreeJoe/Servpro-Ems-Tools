from concurrent.futures import ThreadPoolExecutor
import threading
import time
import pytest
import trello_mirror_reader as reader


@pytest.mark.parametrize('distinct_cards', [False, True])
def test_concurrent_same_card_uses_one_rpc(monkeypatch, distinct_cards):
    monkeypatch.setattr(reader, '_FAILURES', {})
    monkeypatch.setattr(reader.sb, 'current_user', lambda: {'id':'fixture'})
    monkeypatch.setattr(reader.config, 'load', lambda: {'trello_workspace_id':'workspace'})
    monkeypatch.setattr(reader.config, 'active_department', lambda:'IE')
    monkeypatch.setattr(reader.cache, 'scope', lambda:'fixture-scope')
    gate=threading.Barrier(4)
    local=threading.local()
    def barrier():
        if not getattr(local,'arrived',False):
            local.arrived=True
            gate.wait(timeout=2)
        return 0
    monkeypatch.setattr(reader,'_barrier',barrier)
    calls=[]
    def rpc(*args):
        calls.append(args)
        time.sleep(.15)
        return {'card':{'id':'card'}}
    monkeypatch.setattr(reader.sb,'rpc',rpc)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda i:reader._read(str(i) if distinct_cards else 'card'),range(4)))
    assert len(calls)==(4 if distinct_cards else 1)
    assert all(r[0]['card']['id']=='card' for r in results)
    results[0][0]['card']['id']='mutated'
    assert results[1][0]['card']['id']=='card'


def test_failed_shared_request_is_not_left_stuck(monkeypatch):
    calls=[]
    def rpc(*args):
        calls.append(args)
        if len(calls)==1:
            raise TimeoutError('fixture')
        return {'ready':True}
    monkeypatch.setattr(reader.sb,'rpc',rpc)
    with pytest.raises(TimeoutError):
        reader._shared_read('scope','IE','workspace','card')
    assert reader._shared_read('scope','IE','workspace','card')=={'ready':True}
    assert not reader._INFLIGHT


def test_different_users_never_share_inflight_payload(monkeypatch):
    gate=threading.Barrier(2)
    calls=[]
    def rpc(*args):
        calls.append(args)
        gate.wait(timeout=2)
        return {'ready':True}
    monkeypatch.setattr(reader.sb,'rpc',rpc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda scope:reader._shared_read(scope,'IE','workspace','card'),['user-a','user-b']))
    assert len(calls)==2
