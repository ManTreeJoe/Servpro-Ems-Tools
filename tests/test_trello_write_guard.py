"""Default-off transport policy and a source check against bypass transports."""
import ast
import io
from pathlib import Path
import urllib.request
import pytest
import trello_client as tc
from trello_write_guard import require_write_enabled, TrelloWritesDisabled

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize('value', [None, '', 'false', '1', 'TRUE', 'yes'])
@pytest.mark.parametrize('method', ['POST', 'PUT', 'PATCH', 'DELETE', 'post'])
def test_mutations_require_exact_operator_opt_in(monkeypatch, value, method):
    monkeypatch.delenv('ONELOSS_TRELLO_WRITES_ENABLED', raising=False)
    if value is not None: monkeypatch.setenv('ONELOSS_TRELLO_WRITES_ENABLED', value)
    monkeypatch.setattr(tc, '_creds', lambda: pytest.fail('Credentials read before denial'))
    with pytest.raises(TrelloWritesDisabled): tc._call('/cards', method=method)


def test_opt_in_still_cannot_write_in_isolated_dev(monkeypatch):
    monkeypatch.setenv('ONELOSS_TRELLO_WRITES_ENABLED', 'true')
    monkeypatch.setenv('LINGUAR_CHANNEL', 'dev')
    with pytest.raises(TrelloWritesDisabled): require_write_enabled('POST')


def test_final_transport_catches_multipart_or_direct_bypass(monkeypatch):
    monkeypatch.delenv('ONELOSS_TRELLO_WRITES_ENABLED', raising=False)
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: pytest.fail('Network reached'))
    with pytest.raises(TrelloWritesDisabled):
        tc._guarded_urlopen(urllib.request.Request('https://api.trello.com/1/cards/x/attachments',
                                                 data=b'fake'), timeout=1)


@pytest.mark.parametrize('method', ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE'])
def test_explicit_opt_in_and_reads_use_fake_transport(monkeypatch, method):
    monkeypatch.setenv('LINGUAR_CHANNEL', 'trial')
    if method not in ('GET', 'HEAD'): monkeypatch.setenv('ONELOSS_TRELLO_WRITES_ENABLED', 'true')
    else: monkeypatch.delenv('ONELOSS_TRELLO_WRITES_ENABLED', raising=False)
    calls = []
    monkeypatch.setattr(urllib.request, 'urlopen', lambda req, **kw: calls.append(req.get_method()) or io.BytesIO(b'{}'))
    tc._guarded_urlopen(urllib.request.Request('https://api.trello.com/1/cards', method=method), timeout=1)
    assert calls == [method]


def direct_transports(source):
    tree = ast.parse(source)
    found = []
    for func in [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        for node in ast.walk(func):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {'urlopen', 'open', 'request', 'send', 'post', 'put', 'delete', 'patch'}:
                    name = ast.unparse(node.func)
                    if name.startswith(('urllib.', 'requests.', 'httpx.', 'http.')):
                        found.append((func.name, name))
    return found


def test_all_desktop_trello_network_calls_use_guarded_transport():
    source = (ROOT / 'trello_client.py').read_text(encoding='utf-8')
    assert direct_transports(source) == [('_guarded_urlopen', 'urllib.request.urlopen')]
    tree = ast.parse(source)
    guarded = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_guarded_urlopen')
    text = ast.unparse(guarded)
    assert text.index('require_write_enabled(method)') < text.index('urllib.request.urlopen')


def test_architecture_check_rejects_new_direct_post():
    assert direct_transports('def bypass():\n    return requests.post("https://api.trello.com/1/cards")')


def test_new_trello_endpoint_requires_reviewed_transport():
    # Catch new provider literals/imported API_BASE usage anywhere in source.
    # This is a regression tripwire, not a security boundary against obfuscation.
    allowed = {'trello_client.py', 'supabase/functions/trello-sync/core.ts',
               'supabase/functions/comment-parent/core.mjs'}
    unexpected = []
    for path in ROOT.rglob('*'):
        rel = path.relative_to(ROOT)
        if any(part in {'tests', '.git', 'node_modules', 'Output', '__pycache__', '.pytest_cache'} for part in rel.parts): continue
        if path.suffix not in {'.py', '.ts', '.js', '.mjs'}: continue
        source = path.read_text(encoding='utf-8', errors='replace')
        if ('api.trello.com' in source or 'trello_client.API_BASE' in source or
                'from trello_client import API_BASE' in source):
            if rel.as_posix() not in allowed: unexpected.append(rel.as_posix())
    assert unexpected == []


def test_public_create_and_post_cannot_reach_transport(monkeypatch):
    monkeypatch.delenv('ONELOSS_TRELLO_WRITES_ENABLED', raising=False)
    monkeypatch.setattr(tc, '_creds', lambda: pytest.fail('Credentials accessed'))
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **kw: pytest.fail('Network reached'))
    with pytest.raises(TrelloWritesDisabled): tc.create_card('fixture-list', 'Fixture')
    assert tc.post_comment('fixture-card', 'Fixture note') is None
