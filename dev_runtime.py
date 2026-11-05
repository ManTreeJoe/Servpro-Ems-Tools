"""Fail-closed HTTP fence for the isolated identity pilot, not Main/Trial."""
import sys
from urllib.parse import urlsplit

DEV_HOST = 'erenessjerbkmhhrgpvk.supabase.co'
_installed = False


def check_host(host):
    if str(host or '').lower().rstrip('.') not in {DEV_HOST, 'localhost', '127.0.0.1', '::1'}:
        raise RuntimeError('Isolated Dev blocks connections outside its test database.')


def _audit(event, args):
    if event == 'urllib.Request':
        check_host(urlsplit(args[0]).hostname)
    elif event == 'http.client.connect':
        check_host(args[1])


def install():
    global _installed
    import paths
    if not paths.IS_DEV:
        raise RuntimeError('The Dev network fence requires an isolated profile.')
    if not _installed:
        sys.addaudithook(_audit)
        _installed = True
