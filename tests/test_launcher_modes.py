"""Source contract tests: no application imports, profiles, UI or providers."""
import ast
from pathlib import Path
from types import SimpleNamespace
import pytest

SOURCE = Path(__file__).parents[1] / 'tools' / 'launch_notification_shell.py'


def launcher(env=None, modules=None, frozen=False, fence_error=False):
    events = []
    fake_os = SimpleNamespace(environ=dict(env or {}))
    fake_sys = SimpleNamespace(modules=modules or {}, frozen=frozen, path=[], argv=[])
    def load(name, *args, **kwargs):
        if name == 'dev_runtime':
            def install():
                events.append(('fence', fake_os.environ.copy()))
                if fence_error:
                    raise RuntimeError('fence unavailable')
            return SimpleNamespace(install=install)
        if name == 'home_web':
            events.append(('import_home', fake_os.environ.copy()))
            return SimpleNamespace(main=lambda: events.append(('launch', {})))
        raise AssertionError('Unexpected import: ' + name)
    import builtins
    scope = {'os': fake_os, 'sys': fake_sys, 'Path': Path, '__file__': str(SOURCE),
             '__builtins__': dict(vars(builtins), __import__=load)}
    tree = ast.parse(SOURCE.read_text())
    # Execute the actual functions with an import trap; never execute app modules.
    tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    exec(compile(tree, str(SOURCE), 'exec'), scope)
    return scope, fake_os.environ, events


@pytest.mark.parametrize('mode', ['Dev', 'IsolatedDev'])
@pytest.mark.parametrize('inherited', ['main', 'trial', 'dev', 'typo', ''])
def test_dev_overrides_inherited_channel_and_fences_before_home(mode, inherited):
    code, env, events = launcher({'LINGUAR_CHANNEL': inherited, 'ONELOSS_DEV_LIVE': '1'})
    code['main']([mode])
    assert env['LINGUAR_CHANNEL'] == 'dev'
    assert env['LINGUAR_DEV_MODE'] == '1'
    assert 'ONELOSS_DEV_LIVE' not in env
    assert [e[0] for e in events] == ['fence', 'import_home', 'launch']
    assert all(e[1]['LINGUAR_CHANNEL'] == 'dev' for e in events[:2])


def test_main_is_explicit_and_clears_inherited_dev_flags():
    code, env, events = launcher({'LINGUAR_CHANNEL': 'dev', 'LINGUAR_DEV_MODE': '1'})
    code['main'](['Main'])
    assert env == {'LINGUAR_CHANNEL': 'main'}
    assert [e[0] for e in events] == ['import_home', 'launch']


@pytest.mark.parametrize('args', [[], ['typo'], ['main'], ['Dev', 'Main'], ['Trial']])
def test_invalid_mode_cannot_import_application(args):
    code, env, events = launcher()
    with pytest.raises(SystemExit): code['main'](args)
    assert not env and not events


def test_fence_failure_never_falls_back():
    code, env, events = launcher(fence_error=True)
    with pytest.raises(RuntimeError, match='fence unavailable'): code['main'](['Dev'])
    assert env['LINGUAR_CHANNEL'] == 'dev'
    assert [e[0] for e in events] == ['fence']


@pytest.mark.parametrize('module', ['paths', 'config', 'home_web'])
def test_loaded_application_state_refuses_retargeting(module):
    code, env, events = launcher(modules={module: object()})
    with pytest.raises(RuntimeError, match='precede'): code['main'](['Dev'])
    assert not env and not events


def test_frozen_launcher_refused():
    code, env, events = launcher(frozen=True)
    with pytest.raises(SystemExit): code['main'](['Dev'])
    assert not env and not events
