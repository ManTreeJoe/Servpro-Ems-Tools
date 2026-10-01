"""Per-user desktop delivery of the existing personal inbox. No background service."""
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

import paths

_manager = None


def identity():
    import supabase_client as sb
    import config
    user = (sb.current_user() or {}).get('id')
    return (user, config.active_department()) if user else None


def preferences(scope, mode=None):
    if not scope:
        return 'off'
    with sqlite3.connect(paths.data('desktop_notifications.db'), timeout=5) as db:
        db.execute('CREATE TABLE IF NOT EXISTS preferences (scope TEXT PRIMARY KEY, mode TEXT NOT NULL)')
        key = json.dumps(scope)
        if mode is not None:
            if mode not in ('off', 'mentions', 'jobs'):
                raise ValueError('Invalid notification setting')
            db.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)', (key, mode))
        row = db.execute('SELECT mode FROM preferences WHERE scope=?', (key,)).fetchone()
        return row[0] if row else 'off'


class FreshItems:
    """First successful fetch is a quiet baseline, also after account/settings changes."""
    def __init__(self):
        self.key = None
        self.seen = set()
        self.floor = float('-inf')

    def take(self, key, items, now=None):
        now = now or datetime.now(timezone.utc)
        ids = {str(i['id']) for i in items}
        def timestamp(item):
            try:
                return datetime.fromisoformat(item['created_at'].replace('Z', '+00:00')).timestamp()
            except (ValueError, KeyError, TypeError):
                return float('-inf')
        if key != self.key:
            self.key, self.seen = key, ids
            self.floor = max((timestamp(i) for i in items), default=now.timestamp())
            return []
        fresh = []
        for item in items:
            at = timestamp(item)
            age = now.timestamp() - at
            if (str(item['id']) not in self.seen and at >= self.floor
                    and -60 <= age <= 300 and not item.get('read_at') and not item.get('muted')
                    and item.get('kind') in ('mention', 'comment')
                    and (key[-1] == 'jobs' or item['kind'] == 'mention')):
                fresh.append(item)
        self.seen = (self.seen | ids)
        if len(self.seen) > 2000:
            self.seen = ids
        self.floor = max([self.floor] + [timestamp(i) for i in items])
        return fresh


class WindowsDelivery:
    def __init__(self, channel):
        from windows_toasts import InteractableWindowsToaster
        import winreg
        app_id = 'OneLoss.Desktop.' + channel
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, 'Software\\Classes\\AppUserModelId\\' + app_id) as key:
            winreg.SetValueEx(key, 'DisplayName', 0, winreg.REG_SZ, 'OneLoss' + (' — DEV' if channel == 'Dev' else ''))
            winreg.SetValueEx(key, 'IconUri', 0, winreg.REG_SZ, paths.resource('linguar_hub.ico'))
        self.toaster = InteractableWindowsToaster('OneLoss', notifierAUMID=app_id)

    def show(self, title, body, clicked, failed=lambda: None):
        from windows_toasts import Toast
        toast = Toast([title[:100], body[:240]])
        toast.on_activated = lambda _: threading.Thread(target=clicked, daemon=True).start()
        toast.on_failed = lambda _: failed()
        self.toaster.show_toast(toast)


class Manager:
    def __init__(self, api, channel):
        self.api, self.channel = api, channel
        self.stop_event = threading.Event()
        self.fresh = FreshItems()
        self.delivery = None
        self.error = ''
        self.lock = threading.Lock()
        self.started = False

    def start(self):
        with self.lock:
            if self.started:
                return
            self.started = True
            threading.Thread(target=self.run, daemon=True, name='desktop-notifications').start()

    def stop(self):
        self.stop_event.set()

    def send(self, title, body, clicked):
        with self.lock:
            if self.delivery is None:
                self.delivery = WindowsDelivery(self.channel)
            self.delivery.show(title, body, clicked, self.delivery_failed)

    def delivery_failed(self):
        self.error = 'Windows rejected a desktop alert. Check Windows notification permissions.'

    def open_item(self, scope, item):
        if self.stop_event.is_set() or identity() != scope:
            return
        from personal_notifications import call
        result = call('inbox', filter='all', unread=False)
        # Recheck account and access before navigating from a possibly stale OS toast.
        if identity() != scope or not result.get('ok'):
            return
        current = next((i for i in result.get('items', []) if i['id'] == item['id']), None)
        if not current:
            self.open_inbox()
            return
        context = self.api._subs['notifications'].notification_job(current['card_id'], current.get('comment_id', ''))
        if identity() != scope:
            return
        if context.get('ok'):
            self.api._window.evaluate_js('window.postMessage(' + json.dumps({'type': 'linguar-open-job', **context}) + ',location.origin)')
            self.api.focus_window()
            call('read', id=current['id'], read=True)
        else:
            self.open_inbox()

    def open_inbox(self):
        self.api._window.evaluate_js('window.postMessage({type:"ems-navigate",key:"notifications"},location.origin)')
        self.api.focus_window()

    def poll(self):
        scope = identity()
        mode = preferences(scope)
        if mode == 'off' or not scope:
            self.fresh = FreshItems()
            return
        from personal_notifications import call
        result = call('inbox', filter='all', unread=False)
        if not result.get('ok'):
            self.error = 'Your personal inbox could not connect. Desktop alerts will retry.'
            return
        if identity() != scope or preferences(scope) != mode:
            return
        items = self.fresh.take((*scope, mode), result.get('items', []))
        self.error = ''
        # Bound bursts; the rest remain available in the inbox.
        for item in items[:3]:
            if self.stop_event.is_set() or identity() != scope or preferences(scope) != mode:
                break
            title = ('You were mentioned · ' if item['kind'] == 'mention' else 'New job comment · ') + item.get('client', 'OneLoss')
            self.send(title, item.get('actor', 'Teammate') + ': ' + item.get('body', ''),
                      lambda item=item: self.open_item(scope, item))

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.poll()
            except Exception:
                self.error = 'Desktop alerts are unavailable. Try a test notification or check Windows notification settings.'
            self.stop_event.wait(30)


def install(api, channel):
    global _manager
    _manager = Manager(api, channel)
    return _manager


def settings(mode=None):
    try:
        scope = identity()
        if not scope:
            return {'ok': False, 'error': 'Sign in to OneLoss to configure your desktop alerts.'}
        return {'ok': True, 'mode': preferences(scope, mode), 'available': os.name == 'nt' and _manager is not None,
                'error': _manager.error if _manager else ''}
    except Exception:
        return {'ok': False, 'error': 'Desktop alert settings could not be saved. Try again.'}


def test_notification():
    if _manager is None or os.name != 'nt':
        return {'ok': False, 'error': 'Open Notifications in the main Windows app to test desktop alerts.'}
    try:
        _manager.send('OneLoss test notification', 'Desktop alerts are connected. Click to open your inbox.', _manager.open_inbox)
        return {'ok': True}
    except Exception:
        return {'ok': False, 'error': 'Windows could not send the test. Check notification permissions and Do not disturb.'}
