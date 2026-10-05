"""Open Schedule in the actual DEV shell and verify its iframe assets."""
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
        for _ in range(40):
            time.sleep(0.5)
            ready = window.evaluate_js("typeof findItem === 'function' && !!findItem('run_doc_editor')")
            if ready:
                window.evaluate_js("navigate('run_doc_editor')")
                break
        time.sleep(2)
        print(window.evaluate_js("""JSON.stringify((()=>{
          const f=document.querySelector('iframe[data-panel-key="run_doc_editor"]');
          const d=f?.contentDocument;
          return {src:f?.getAttribute('src'),days:d?.querySelectorAll('.wc-day').length,
            status:d?.querySelector('.preview-note')?.textContent,
            sync:d?.querySelector('#sync-status')?.textContent,
            theme:d?f.contentWindow.getComputedStyle(d.documentElement).getPropertyValue('--surface').trim():null};
        })())"""), flush=True)
        if '--history' in sys.argv:
            for _ in range(60):
                time.sleep(0.5)
                if window.evaluate_js("""(()=>{const d=document.querySelector('iframe[data-panel-key="run_doc_editor"]')?.contentDocument;return d?.querySelector('.preview-note')?.textContent.startsWith('Live drafts');})()"""):
                    break
            window.evaluate_js("""(()=>{const d=document.querySelector('iframe[data-panel-key="run_doc_editor"]').contentDocument;[...d.querySelectorAll('button')].find(b=>b.textContent==='History').click();})()""")
            for _ in range(60):
                time.sleep(0.5)
                if window.evaluate_js("""!!document.querySelector('iframe[data-panel-key="run_doc_editor"]')?.contentDocument?.querySelector('#run-history [data-edit]')"""):
                    break
            print(window.evaluate_js("""JSON.stringify((()=>{const d=document.querySelector('iframe[data-panel-key="run_doc_editor"]').contentDocument;return {historyOpen:d.querySelector('#run-history').open,status:d.querySelector('#run-history [data-status]').textContent,draggableHistory:d.querySelectorAll('#run-history [draggable="true"]').length};})())"""),flush=True)

    window.events.loaded += lambda: threading.Thread(target=inspect, daemon=True).start()
    return window


webview.create_window = create
home_web.main()
