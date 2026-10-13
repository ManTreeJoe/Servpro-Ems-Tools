"""Launch DEV and report only layout/asset health from the real WebView."""
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['LINGUAR_DEV_MODE'] = '1'
import webview
import home_web

original_create = webview.create_window


def create(*args, **kwargs):
    window = original_create(*args, **kwargs)
    def inspect():
        time.sleep(3)
        result = window.evaluate_js("""JSON.stringify({
          sheets:Array.from(document.querySelectorAll('link[rel=stylesheet]')).map(el=>({
            path:new URL(el.href).pathname,loaded:!!el.sheet,
            rules:el.sheet?.cssRules.length,firstRule:el.sheet?.cssRules[0]?.cssText})),
          shellDisplay:getComputedStyle(document.querySelector('.shell')).display,
          sidebarWidth:document.querySelector('.sidebar')?.getBoundingClientRect().width,
          scripts:Array.from(document.scripts).filter(el=>el.src).map(el=>new URL(el.src).pathname),
          shellReady:typeof window.pywebview?.api?.nav==='function'
        })""")
        print(result, flush=True)
        import json
        health = json.loads(result) if isinstance(result, str) else result
        if not (150 < health.get('sidebarWidth', 0) < 400):
            print('FAIL: desktop shell layout is not ready', flush=True)
        else:
            print('PASS: desktop shell layout is ready', flush=True)
        if '--test-notification' in sys.argv:
            import desktop_notifications
            print('Desktop test:', desktop_notifications.test_notification(), flush=True)
    window.events.loaded += lambda: threading.Thread(target=inspect, daemon=True).start()
    return window


webview.create_window = create
home_web.main()
