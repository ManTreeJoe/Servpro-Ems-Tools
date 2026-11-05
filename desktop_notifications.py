"""Per-user desktop delivery of the existing personal inbox. No background service."""
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone

import paths

_manager = None


def notification_text(text):
    """Readable native-toast excerpt; original comments remain untouched."""
    text = str(text or '')
    text = re.sub(r'\[([^\]\n]+)\]\((?:https?://|mailto:)[^\n)]*\)', r'\1', text)
    for marker in ('**', '__', '~~', '`'):
        text = re.sub(re.escape(marker)+r'(.+?)'+re.escape(marker), r'\1', text)
    text = re.sub(r'(?m)^\s*(?:#{1,6}\s+|>\s*)', '', text)
    text = re.sub(r'\\([<>])', r'\1', text)
    return ' '.join(text.split())


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


def sound_preference(scope, sound=None):
    """Separate per-account/office setting; existing alert opt-in is unchanged."""
    if sound is not None and sound not in ('chime', 'system', 'silent'):
        raise ValueError('Invalid notification sound')
    if not scope:
        return 'silent'
    with sqlite3.connect(paths.data('desktop_notifications.db'), timeout=5) as db:
        db.execute('CREATE TABLE IF NOT EXISTS sounds (scope TEXT PRIMARY KEY, sound TEXT NOT NULL)')
        key = json.dumps(scope)
        if sound is not None:
            db.execute('INSERT OR REPLACE INTO sounds VALUES (?,?)', (key, sound))
        row = db.execute('SELECT sound FROM sounds WHERE scope=?', (key,)).fetchone()
        return row[0] if row else 'chime'


class WindowsDelivery:
    def __init__(self, channel):
        from windows_toasts import InteractableWindowsToaster
        from windows_app_identity import register_notifications
        app_id = register_notifications(channel)
        self.toaster = InteractableWindowsToaster('OneLoss', notifierAUMID=app_id)
        self.last_sound = float('-inf')

    def show(self, title, body, clicked, failed=lambda: None):
        from windows_toasts import Toast, ToastAudio, AudioSource
        toast = Toast([title[:100], notification_text(body)[:240]])
        try:
            sound = sound_preference(identity())
        except Exception:
            sound = 'silent'
        now = time.monotonic()
        quiet = sound == 'silent' or now - self.last_sound < 5
        toast.audio = ToastAudio(
            sound=AudioSource.IM if sound == 'chime' else AudioSource.Default,
            silent=quiet, looping=False)
        toast.on_activated = lambda _: threading.Thread(target=clicked, daemon=True).start()
        toast.on_failed = lambda _: failed()
        self.toaster.show_toast(toast)
        if not quiet:
            self.last_sound = now


class Manager:
    def __init__(self, api, channel):
        self.api, self.channel = api, channel
        self.stop_event = threading.Event()
        self.fresh = FreshItems()
        self.trello_fresh = FreshItems()
        self.delivery = None
        self.error = ''
        self.trello_error = ''
        self.lock = threading.Lock()
        self.started = False
        self.alert_targets = {}

    def present_in_app(self, scope, item, title, body):
        if self.api is None:
            return
        import uuid
        token = str(uuid.uuid4())
        with self.lock:
            self.alert_targets[token] = (scope, dict(item))
            while len(self.alert_targets) > 100:
                self.alert_targets.pop(next(iter(self.alert_targets)))
        self.api._window.evaluate_js('window.OneLossNotice?.show(' + json.dumps({
            'kind':'notification', 'panel':'Notifications', 'title':title,
            'msg':body, 'alertToken':token}) + ')')

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
        if item.get('source') == 'trello':
            import trello_alerts
            if trello_alerts.account_key() != item.get('account_key'):
                return
            current = next((i for i in trello_alerts.fetch() if i['id']==item['id']), None)
            if not current or identity() != scope:
                return
            context = self.api._subs['notifications'].notification_job(current['card_id'], current.get('comment_id',''))
            if context.get('ok') and identity() == scope and trello_alerts.account_key() == item['account_key']:
                self.api._window.evaluate_js('window.postMessage(' + json.dumps({'type':'linguar-open-job', **context, 'fromNotifications':True}) + ',location.origin)')
                self.api.focus_window()
                import trello_client as tc
                tc.mark_notification_read(current['notification_id'], True)
            else:
                self.open_inbox()
            return
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
            self.api._window.evaluate_js('window.postMessage(' + json.dumps({'type': 'linguar-open-job', **context, 'fromNotifications':True}) + ',location.origin)')
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
            self.trello_fresh = FreshItems()
            return
        self.poll_trello(scope, mode)
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
            self.present_in_app(scope, item, title, item.get('actor', 'Teammate') + ': ' + item.get('body', ''))
            self.send(title, item.get('actor', 'Teammate') + ': ' + item.get('body', ''),
                      lambda item=item: self.open_item(scope, item))

    def poll_trello(self, scope, mode):
        if self.api is None:
            return
        import trello_alerts
        from personal_notifications import call
        try:
            account = trello_alerts.account_key()
            rows = trello_alerts.fetch()
            if identity()!=scope or preferences(scope)!=mode or trello_alerts.account_key()!=account:
                return
            fresh = self.trello_fresh.take((*scope, account, mode), rows)
            self.trello_error = ''
            for item in fresh[:3]:
                # Reuse the account-access and mute boundary; Trello membership
                # never grants access to a OneLoss card.
                access = call('members', card_id=item['card_id'])
                if not access.get('ok') or access.get('muted'):
                    continue
                if identity()!=scope or preferences(scope)!=mode or trello_alerts.account_key()!=account:
                    return
                item['account_key'] = account
                title = ('Mention · ' if item['kind']=='mention' else 'Comment · ') + item['client']
                body = item['actor'] + ': ' + item['body']
                self.present_in_app(scope, item, title, body)
                self.send(title, body, lambda item=item:self.open_item(scope,item))
        except Exception:
            # Independent of the native inbox: a provider failure must not
            # reset the baseline or block native delivery.
            self.trello_error = 'Trello alerts could not refresh. They will retry.'

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


def settings(mode=None, sound=None):
    try:
        scope = identity()
        if not scope:
            return {'ok': False, 'error': 'Sign in to OneLoss to configure your desktop alerts.'}
        if sound is not None and sound not in ('chime', 'system', 'silent'):
            raise ValueError('Invalid notification sound')
        return {'ok': True, 'mode': preferences(scope, mode), 'sound': sound_preference(scope, sound), 'available': os.name == 'nt' and _manager is not None,
                'error': (_manager.error or _manager.trello_error) if _manager else ''}
    except Exception:
        return {'ok': False, 'error': 'Desktop alert settings could not be saved. Try again.'}


def test_notification():
    if _manager is None or os.name != 'nt':
        return {'ok': False, 'error': 'Open Notifications in the main Windows app to test desktop alerts.'}
    try:
        _manager.send('OneLoss test notification', 'Test alert from OneLoss. Click to open your inbox.', _manager.open_inbox)
        return {'ok': True}
    except Exception:
        return {'ok': False, 'error': 'Windows could not send the test. Check notification permissions and Do not disturb.'}


def open_alert(token):
    if _manager is None:
        return {'ok':False, 'error':'Reopen Notifications to find this alert.'}
    with _manager.lock:
        target = _manager.alert_targets.get(str(token))
    if not target or _manager.stop_event.is_set() or identity() != target[0]:
        return {'ok':False, 'error':'This alert expired or the account changed. Open Notifications.'}
    try:
        _manager.open_item(*target)
        return {'ok':True}
    except Exception:
        return {'ok':False, 'error':'The notification could not open. Try again from Notifications.'}
