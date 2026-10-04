"""Launch an isolated, sample-only calendar UI; no application API attached."""
from pathlib import Path
import sys
import json
import webview

if __name__ == "__main__":
    page = Path(__file__).resolve().parents[1] / "run_doc_editor_web_assets" / "calendar_preview.html"
    window = webview.create_window("OneLoss — Calendar TEST PREVIEW (sample data)", str(page), width=1400, height=900)
    result = {}
    if "--check" in sys.argv:
        def check():
            result.update(window.evaluate_js("""({
                theme: getComputedStyle(document.documentElement).getPropertyValue('--surface').trim(),
                sheets: Array.from(document.querySelectorAll('link[rel=stylesheet]')).map(x=>({url:x.href,loaded:!!x.sheet})),
                days: document.querySelectorAll('.wc-day').length
            })"""))
            print(json.dumps(result), flush=True)
            window.destroy()
        window.events.loaded += check
    webview.start(http_server=True)
    if "--check" in sys.argv:
        sys.exit(0 if result.get('theme') and result.get('days') == 7 and all(x['loaded'] for x in result.get('sheets', [])) else 1)
