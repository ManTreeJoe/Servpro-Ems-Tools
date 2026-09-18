"""Background completion must reach a Snapshot frame opened after Jobs."""
import subprocess
from pathlib import Path
import web_event
import pytest


@pytest.mark.parametrize('route', ['shared', 'companycam'])
@pytest.mark.parametrize('event_name', ['companycam:pull-progress', 'companycam:pull-done'])
def test_completion_reaches_warm_snapshot_frame(monkeypatch, route, event_name):
    scripts = []
    class Window:
        def evaluate_js(self, script):
            scripts.append(script)
    if route == 'shared':
        web_event.event(Window(), event_name, {'client': 'Test job', 'ok': True})
    else:
        import webview
        import companycam_web_api
        monkeypatch.setattr(webview, 'windows', [Window()])
        companycam_web_api.CompanyCamApi()._cc_emit(
            event_name, {'client': 'Test job', 'ok': True})
    setup = '''
const assert = require('node:assert/strict');
const received = {home:[], jobs:[], snapshot:[]};
global.CustomEvent = function(name, options){this.type=name;this.detail=options.detail;};
global.window = {dispatchEvent:e=>received.home.push(e)};
const jobs = {contentWindow:{dispatchEvent:e=>received.jobs.push(e)}};
const snapshot = {contentWindow:{dispatchEvent:e=>received.snapshot.push(e)}};
const inaccessible = {get contentWindow(){throw Error('unavailable frame')}};
global.document = {getElementById:()=>jobs,querySelectorAll:()=>[jobs,inaccessible,snapshot]};
'''
    result = subprocess.run(['node', '-e', setup + scripts[0] +
        "for (const events of Object.values(received)) {assert.equal(events.length,1);assert.equal(events[0].detail.client,'Test job');}"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_delivered_completion_clears_snapshot_watchdog():
    source = (Path(__file__).resolve().parents[1] / 'web_shared/audit_detail.js').read_text(encoding='utf-8')
    watcher = source[source.index('  const _ccWatching = new Set();'):source.index('  function ccOfferAlternate(')]
    scripts = []
    class Window:
        def evaluate_js(self, script):
            scripts.append(script)
    web_event.event(Window(), 'companycam:pull-done', {'client': 'Test job', 'ok': True, 'pulled': 14})
    setup = '''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const timers = new Map(); let nextTimer = 1; const statuses = [];
const target = new EventTarget(); let done = 0; let audited = 0;
target.Progress = {done:()=>done++,fail:()=>assert.fail('unexpected failure')};
const panel = vm.createContext({window:target,Set,
  setTimeout:fn=>{const id=nextTimer++;timers.set(id,fn);return id;},
  clearTimeout:id=>timers.delete(id),
  setStatus:(_ctx,text)=>statuses.push(text)});
'''
    script = setup + '\nvm.runInContext(' + __import__('json').dumps(watcher) + ', panel);\n' + '''
panel.ctx = {reauditAndRerender:()=>audited++};
vm.runInContext("watchCcPull('Test job', ctx)",panel);
assert.equal(timers.size,1);
global.window = new EventTarget();
global.document = {querySelectorAll:()=>[{contentWindow:new EventTarget()},{contentWindow:target}]};
''' + scripts[0] + '''
assert.equal(timers.size,0,'completion must cancel the false timeout');
assert.equal(done,1); assert.equal(audited,1);
assert.match(statuses.at(-1),/Pulled 14 photos/);
vm.runInContext("assertClean = !_ccWatching.has('Test job')",panel);
assert.equal(panel.assertClean,true);
'''
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
