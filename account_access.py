"""One account-access decision for every Linguar Hub screen.

The bootstrap owner, Supabase RPC shape, offline behavior and normalization
used to leak into each caller.  This module is the single interface: callers
ask for ``current_access()`` and never interpret identity or RPC failures.
"""
from __future__ import annotations

OWNER_EMAIL = "nathan@servpro10100.com"
KNOWN_CAPABILITIES = ("docusketch",)
_LAST_ACCESS = None


class SupabaseAccessAdapter:
    """Production adapter at the external Supabase seam."""

    @staticmethod
    def current_user():
        import supabase_client
        return supabase_client.current_user() or {}

    @staticmethod
    def access():
        import supabase_client
        return supabase_client.rpc("my_app_access") or {}


def current_access(adapter=None) -> dict:
    """Return normalized identity, owner/admin and franchise readiness.

    Signed-in identity survives a temporary RPC/network failure.  The owner
    fallback is intentionally evaluated here—not independently by screens.
    """
    global _LAST_ACCESS
    supplied_adapter = adapter is not None
    adapter = adapter or SupabaseAccessAdapter()
    error = ""
    try:
        user = adapter.current_user() or {}
    except Exception as ex:
        user = {}
        error = f"Sign-in status unavailable: {ex}"
    email = str(user.get("email") or "").strip().lower()
    signed_in = bool(user.get("id") or email)
    owner = signed_in and email == OWNER_EMAIL
    raw = {}
    if signed_in:
        try:
            raw = adapter.access() or {}
        except Exception as ex:
            error = f"Could not check franchise access: {ex}"
    departments = []
    for value in raw.get("departments") or []:
        key = str(value or "").strip().upper()
        if key and key not in departments:
            departments.append(key)
    raw_capabilities = raw.get("capabilities")
    capabilities_configured = isinstance(raw_capabilities, (dict, list, tuple))
    if isinstance(raw_capabilities, dict):
        capabilities = {key: bool(raw_capabilities.get(key))
                        for key in KNOWN_CAPABILITIES}
    else:
        enabled = {str(value or "").strip().lower()
                   for value in (raw_capabilities or [])}
        capabilities = {key: key in enabled for key in KNOWN_CAPABILITIES}
    if owner or raw.get("is_admin"):
        capabilities = {key: True for key in KNOWN_CAPABILITIES}
    result = {
        "ok": True,
        "identity": user,
        "email": email,
        "display_name": str(user.get("display_name") or "").strip(),
        "signed_in": signed_in,
        "is_owner": owner,
        "is_admin": bool(owner or raw.get("is_admin")),
        "departments": departments,
        "capabilities": capabilities,
        "capabilities_configured": capabilities_configured,
        "error": error,
    }
    if not supplied_adapter:
        _LAST_ACCESS = dict(result)
    return result


def cached_access() -> dict:
    """Last normalized access result without database or network I/O.

    Cold Job Workspace paint uses this and lets its background refresh call
    :func:`current_access`. An absent snapshot is represented explicitly so
    the UI never guesses that a regular employee has a restricted tool.
    """
    if _LAST_ACCESS:
        return {**_LAST_ACCESS,
                "capabilities": dict(_LAST_ACCESS.get("capabilities") or {})}
    return {
        "ok": True, "identity": {}, "email": "", "display_name": "",
        "signed_in": False, "is_owner": False, "is_admin": False,
        "departments": [],
        "capabilities": {key: False for key in KNOWN_CAPABILITIES},
        "capabilities_configured": False, "error": "",
    }
