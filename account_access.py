"""One account-access decision for every Linguar Hub screen.

The bootstrap owner, Supabase RPC shape, offline behavior and normalization
used to leak into each caller.  This module is the single interface: callers
ask for ``current_access()`` and never interpret identity or RPC failures.
"""
from __future__ import annotations

OWNER_EMAIL = "nathan@servpro10100.com"


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
    return {
        "ok": True,
        "identity": user,
        "email": email,
        "display_name": str(user.get("display_name") or "").strip(),
        "signed_in": signed_in,
        "is_owner": owner,
        "is_admin": bool(owner or raw.get("is_admin")),
        "departments": departments,
        "error": error,
    }
