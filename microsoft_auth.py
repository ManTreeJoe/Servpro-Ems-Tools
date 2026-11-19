"""Desktop Microsoft OAuth with PKCE and a loopback-only return listener."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import secrets
import socket
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import webbrowser

PORT = 43821
CALLBACK_PATH = '/auth/microsoft/callback'
REDIRECT = f'http://127.0.0.1:{PORT}{CALLBACK_PATH}'
_flight = threading.Lock()
_cancel = threading.Event()


def cancel():
    _cancel.set()


def _challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')


def _listener():
    class LoopbackServer(HTTPServer):
        allow_reuse_address = False

        def server_bind(self):
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(2)
            return connection, address

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Authorization codes must never enter HTTP logs.

        def do_GET(self):
            parsed = urlsplit(self.path)
            params = parse_qs(parsed.query)
            codes = params.get('code', [])
            valid_host = self.headers.get('Host') == f'127.0.0.1:{PORT}'
            valid = valid_host and parsed.path == CALLBACK_PATH
            valid = valid and len(codes) == 1 and 0 < len(codes[0]) <= 4096
            if valid and 'error' not in params:
                self.server.code = codes[0]
                status, message = 200, 'Return to OneLoss to finish signing in. You can close this tab.'
            elif valid_host and parsed.path == CALLBACK_PATH and 'error' in params:
                self.server.denied = True
                status, message = 400, 'Microsoft sign-in was cancelled or denied. Return to OneLoss to try again.'
            else:
                status, message = 404, 'This address is not a OneLoss sign-in return.'
            data = message.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = LoopbackServer(('127.0.0.1', PORT), Callback)
    server.timeout = 0.25
    server.code, server.denied = None, False
    return server


def sign_in(email='', *, timeout=180):
    """Return a validated user; preserve any prior session on failed/cancelled login."""
    import supabase_client as sb
    email = str(email or '').strip()
    if email and '@' not in email:
        raise ValueError('Use a valid work email or leave it blank to choose your Microsoft account.')
    if not _flight.acquire(blocking=False):
        raise ValueError('Microsoft sign-in is already open. Finish or cancel that attempt first.')
    _cancel.clear()
    token = None
    saved = False
    try:
        original_creds = sb.creds()
        base = original_creds[0]
        parsed = urlsplit(base)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Microsoft sign-in requires a configured HTTPS OneLoss server.')
        settings = sb._raw('GET', '/auth/v1/settings') or {}
        if settings.get('external', {}).get('azure') is not True:
            raise ValueError('Microsoft sign-in is not enabled for this OneLoss server. Ask your administrator.')
        try:
            server = _listener()
        except OSError:
            raise ValueError('The OneLoss sign-in return address is in use. Close another sign-in attempt and retry.') from None
        with server:
            verifier = secrets.token_urlsafe(48)
            params = {'provider': 'azure', 'scopes': 'email', 'redirect_to': REDIRECT,
                      'code_challenge': _challenge(verifier), 'code_challenge_method': 's256'}
            try:
                opened = webbrowser.open(base + '/auth/v1/authorize?' + urlencode(params), new=2)
            except Exception:
                opened = False
            if not opened:
                raise ValueError('Could not open your browser. Check your default browser and try again.')
            deadline = time.monotonic() + timeout
            while not server.code and not server.denied and not _cancel.is_set() and time.monotonic() < deadline:
                server.handle_request()
            if _cancel.is_set():
                raise ValueError('Microsoft sign-in cancelled. You can try again.')
            if server.denied:
                raise ValueError('Microsoft sign-in was cancelled or denied. You can try again.')
            if not server.code:
                raise ValueError('Microsoft sign-in timed out. Close the browser tab and try again.')
            if sb.creds() != original_creds:
                raise ValueError('The OneLoss server changed during sign-in. Please try again.')
            payload = sb._raw('POST', '/auth/v1/token', params={'grant_type': 'pkce'},
                              body={'auth_code': server.code, 'code_verifier': verifier}) or {}
        token = payload.get('access_token')
        if not token or not payload.get('refresh_token'):
            raise ValueError('Microsoft did not return a complete OneLoss session. Try again.')
        user = sb._raw('GET', '/auth/v1/user', token=token) or {}
        if email and str(user.get('email') or '').casefold() != email.casefold():
            raise ValueError('That Microsoft account does not match the work email entered. Choose the correct account and retry.')
        if not user.get('id') or not user.get('email') or not user.get('email_confirmed_at') or not any(
                i.get('provider') == 'azure' for i in user.get('identities', [])):
            raise ValueError('Microsoft identity could not be verified. Contact your administrator.')
        with sb._LOCK:
            with sb._cross_process_session_lock():
                if _cancel.is_set() or sb.creds() != original_creds:
                    raise ValueError('Sign-in was cancelled or the server changed. Try again.')
                sb._store_session({**payload, 'user': user})
                saved = True
        return user
    except (ValueError, sb.NotConfigured):
        raise
    except Exception:
        raise ValueError('Microsoft sign-in could not finish. Check your connection and retry; ask your administrator if it continues.') from None
    finally:
        if token and not saved:
            try:
                if sb.creds() == original_creds:
                    sb._raw('POST', '/auth/v1/logout', params={'scope': 'local'}, body={}, token=token)
            except Exception:
                pass
        _flight.release()
