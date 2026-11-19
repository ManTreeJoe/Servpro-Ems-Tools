"""Default-off transport policy and a source check against bypass transports."""
import ast
import io
import subprocess
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
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for name in node.names:
                aliases[name.asname or name.name] = f"{node.module}.{name.name}"
        elif isinstance(node, ast.Import):
            for name in node.names:
                aliases[name.asname or name.name] = name.name
    def qualified(node):
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return qualified(node.value) + '.' + node.attr
        return ''
    class Visitor(ast.NodeVisitor):
        owner = '<module>'
        def visit_FunctionDef(self, node):
            previous = self.owner
            self.owner = node.name
            self.generic_visit(node)
            self.owner = previous
        visit_AsyncFunctionDef = visit_FunctionDef
        def visit_Call(self, node):
            name = qualified(node.func)
            if name.startswith(('urllib.', 'requests.', 'httpx.', 'http.')):
                if name.rsplit('.', 1)[-1] in {'urlopen', 'open', 'request', 'send', 'post', 'put', 'delete', 'patch'}:
                    found.append((self.owner, name))
                elif name == 'urllib.request.Request' and any(k.arg == 'method' for k in node.keywords):
                    found.append((self.owner, name))
            self.generic_visit(node)
    Visitor().visit(tree)
    return found


def test_all_desktop_trello_network_calls_use_guarded_transport():
    source = (ROOT / 'trello_client.py').read_text(encoding='utf-8')
    assert direct_transports(source) == [
        ('_guarded_urlopen', 'urllib.request.urlopen'),
        ('_call', 'urllib.request.Request'), ('attach_file', 'urllib.request.Request'),
    ]
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
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8')
    for name in filter(None, tracked.split('\0')):
        rel = Path(name)
        path = ROOT / rel
        if any(part in {'tests', '.git', 'node_modules', 'Output', '__pycache__', '.pytest_cache'} for part in rel.parts): continue
        if path.suffix not in {'.py', '.ts', '.js', '.mjs', '.sql', '.cjs', '.html', '.ps1'}: continue
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

@pytest.mark.parametrize('source', [
    'from urllib.request import urlopen as send\nclass Client:\n def write(self):\n  send("fixture")',
    'from urllib.request import Request as R\ndef outer():\n def inner():\n  return R("fixture", method="POST")',
    'import requests as r\nclass Client:\n async def write(self):\n  r.post("fixture")',
])
def test_transport_scan_walks_methods_nested_functions_and_aliases(source):
    assert direct_transports(source)


def test_comment_fallback_reports_disabled_before_post(monkeypatch):
    import sys
    from types import SimpleNamespace
    tree = ast.parse((ROOT / 'pipeline_web.py').read_text(encoding='utf-8'))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'post_job_comment')
    namespace = {'pipeline_store': SimpleNamespace(add_activity=lambda *a, **k: None)}
    exec(compile(ast.Module(body=[method], type_ignores=[]), 'pipeline_web.py', 'exec'), namespace)
    monkeypatch.setitem(sys.modules, 'supabase_client', SimpleNamespace(current_user=lambda: {}, actor_name=lambda x: x))
    monkeypatch.delenv('ONELOSS_TRELLO_WRITES_ENABLED', raising=False)
    monkeypatch.setattr(tc, 'post_comment', lambda *a: pytest.fail('Post reached'))
    result = namespace['post_job_comment'](None, 'Fixture', 'fixture-card', 'Fixture comment')
    assert result == {'ok': False, 'posted_trello': False, 'delivery': 'disabled',
                      'error': 'Trello posting is off, nothing was sent'}
