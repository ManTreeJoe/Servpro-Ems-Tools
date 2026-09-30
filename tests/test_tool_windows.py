from types import SimpleNamespace
from urllib.parse import urlparse,parse_qs
import pytest
import tool_windows


class Event:
    def __iadd__(self,callback):self.callback=callback;return self


@pytest.fixture
def manager(monkeypatch):
    import home_web,webview
    created=[]
    class Api:
        def __init__(self,tool_keys=None):self.keys=tool_keys
        def attach(self,window):self.window=window
    def create(**kwargs):
        window=SimpleNamespace(events=SimpleNamespace(closed=Event()),restore=lambda:None,show=lambda:None,evaluate_js=lambda text:None,options=kwargs)
        created.append(window);return window
    monkeypatch.setattr(home_web,'HomeApi',Api)
    monkeypatch.setattr(webview,'create_window',create)
    owner=SimpleNamespace(_window=SimpleNamespace(get_current_url=lambda:'http://127.0.0.1:1234/home_web_assets/index.html'))
    return tool_windows.ToolWindows(owner),created


def test_duplicate_tool_reuses_window_and_close_does_not_touch_main(manager):
    registry,created=manager
    assert registry.open('notifications')['ok']
    assert registry.open('notifications')['existing']
    assert len(created)==1
    assert urlparse(created[0].options['url']).path=='/home_web_assets/popout.html'
    assert created[0].options['js_api'].keys=={'notifications'}
    created[0].events.closed.callback()
    assert registry.open('notifications')['ok'] and len(created)==2


def test_card_keeps_exact_context_and_independent_api(manager):
    registry,created=manager
    registry.open('pipeline',{'cardId':'a'*24,'client':'Name & detail','division':'Contents','commentId':'b'*24})
    query=parse_qs(urlparse(created[0].options['url']).query)
    assert query['cardId']==['a'*24] and query['commentId']==['b'*24]
    assert query['client']==['Name & detail']
    assert registry.open('pipeline',{'cardId':'a'*24})['existing']
    registry.open('pipeline')
    assert len(created)==2 and created[0].options['js_api'] is not created[1].options['js_api']


def test_invalid_tool_or_card_does_not_create_window(manager):
    registry,created=manager
    assert not registry.open('../../outside')['ok']
    assert not registry.open('pipeline',{'cardId':'bad/path'})['ok']
    assert not registry.open('notifications',{'cardId':'a'*24})['ok']
    assert not created
