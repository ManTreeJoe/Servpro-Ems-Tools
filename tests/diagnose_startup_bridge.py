"""Isolated native bridge diagnostic; no OneLoss API, credentials or data."""
import sys
import time
import re
import tempfile
from pathlib import Path
import webview

direct = '--direct' in sys.argv
shell_root = '--shell-root' in sys.argv
shell_html = None
if shell_root:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import home_web
    with tempfile.TemporaryDirectory(prefix='oneloss-startup-') as folder:
        home_web.ROOT_INDEX_HTML = str(Path(folder) / 'root.html')
        home_web._ensure_root_index()
        shell_html = Path(home_web.ROOT_INDEX_HTML).read_text(encoding='utf-8')
    shell_html = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', shell_html, flags=re.I)
    shell_html = re.sub(r'<link\b[^>]*>', '', shell_html, flags=re.I)
class Api:
    def health_state(self):
        time.sleep(0.5)
        return {'ok': True}

def app(environ, start_response):
    start_response('200 OK', [('Content-Type', 'text/html')])
    if environ['PATH_INFO'] == '/' and not direct and not shell_root:
        return [b'<meta http-equiv="refresh" content="0; url=/shell">']
    probe = '''<script>
window.readyCount=0;window.doneCount=0;
window.addEventListener('pywebviewready',()=>{
 readyCount++;pywebview.api.health_state().then(()=>doneCount++);
});
</script>'''
    return [((shell_html or '<!doctype html><title>Bridge diagnostic</title>') + probe).encode()]

window = webview.create_window('Isolated bridge diagnostic', app, js_api=Api(), hidden=True)
def inspect():
    time.sleep(4)
    result = window.evaluate_js('({ready:window.readyCount,completed:window.doneCount})')
    print(result, flush=True)
    global passed
    passed = result == {'ready': 1, 'completed': 1}
    window.destroy()
passed = False
webview.start(inspect)
if (direct or shell_root) and not passed:
    raise SystemExit(1)
