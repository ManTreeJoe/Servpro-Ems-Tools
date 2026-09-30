"""One native window per tool or exact card, with independent panel APIs."""
import re
import json
import threading
from urllib.parse import urlencode, urljoin


class ToolWindows:
    def __init__(self, owner):
        self.owner = owner
        self.windows = {}
        self.lock = threading.RLock()

    def open(self, tool, context=None):
        import home_web
        import webview
        context = context if isinstance(context, dict) else {}
        allowed = set(home_web.SUB_MODULES) | {'daily_run'}
        if tool not in allowed:
            return {'ok': False, 'error': 'This tool cannot be opened in a separate window.'}
        card = str(context.get('cardId') or '')
        if card and (tool != 'pipeline' or not re.fullmatch(r'[a-fA-F0-9]{24}|[a-zA-Z0-9]{8}', card)):
            return {'ok': False, 'error': 'Choose a saved job card first.'}
        key = ('card', card) if card else ('tool', tool)
        with self.lock:
            existing = self.windows.get(key)
            if existing:
                existing.restore(); existing.show()
                if card and context.get('commentId'):
                    payload=json.dumps({'cardId':card,'commentId':str(context['commentId'])[:100]})
                    existing.evaluate_js("document.getElementById('tool').contentWindow.postMessage("+payload+",location.origin)")
                return {'ok': True, 'existing': True}
            base = self.owner._window.get_current_url()
            if not base or not base.startswith(('http://127.0.0.1:', 'http://localhost:')):
                return {'ok': False, 'error': 'Pop-outs need the running desktop app.'}
            params = {'tool': tool}
            for name in ('cardId', 'client', 'division', 'commentId'):
                if context.get(name):
                    params[name] = str(context[name])[:300]
            api = home_web.HomeApi(tool_keys={'audit' if tool == 'daily_run' else tool})
            api._popouts = self
            title = next((name for _, rows in home_web.NAV_GROUPS for k, _, name in rows if k == tool), tool.replace('_', ' ').title())
            if card:
                title = str(context.get('client') or 'Job')[:100]
            window = webview.create_window(
                title=f'{title} · {home_web._window_title()}',
                url=urljoin(base, '/home_web_assets/popout.html')+'?'+urlencode(params),
                js_api=api, width=1280, height=860, min_size=(760, 560), confirm_close=True)
            api.attach(window)
            self.windows[key] = window
            def closed():
                with self.lock:
                    if self.windows.get(key) is window:
                        self.windows.pop(key, None)
            window.events.closed += closed
            return {'ok': True, 'existing': False}
