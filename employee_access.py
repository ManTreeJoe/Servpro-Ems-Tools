"""Employee admission is decided by the server, never by email or local settings."""
from __future__ import annotations
import time
_ADMISSION = (0.0, None, None)
_RECOVERY_MODE = False


def enter_recovery():
    global _RECOVERY_MODE, _ADMISSION
    _RECOVERY_MODE = True
    _ADMISSION = (0.0, None, None)


def status(client=None):
    if client is None:
        import supabase_client as client
    user = client.current_user() or {}
    if not user.get("id"):
        return {"ok": True, "access_state": "signed_out"}
    try:
        access = client.rpc("my_app_access")
        if not isinstance(access, dict) or not access.get("approval_enabled"):
            return {"ok": False, "access_state": "unavailable",
                    "error": "Employee access setup is not ready. Contact your administrator."}
        if access.get("access_state") == "approved" and access.get("auth_mode") != "microsoft":
            recovery = (_RECOVERY_MODE and access.get("auth_mode") == "emergency"
                        and access.get("is_admin") is True)
            if not recovery:
                return {"ok": True, "access_state": "microsoft_required", "is_admin": False,
                        "can_edit": False, "departments": [], "email": user.get("email", "")}
        return {**access, "ok": True, "email": user.get("email", "")}
    except Exception:
        return {"ok": False, "access_state": "unavailable",
                "error": "We could not verify access. Check your connection and try again."}


def require_access():
    global _ADMISSION
    import supabase_client
    user_id = (supabase_client.current_user() or {}).get("id")
    stamp, prior_id, access = _ADMISSION
    if user_id != prior_id or access is None or time.monotonic() - stamp > 5:
        access = status()
        _ADMISSION = (time.monotonic(), user_id, access)
    if access.get("access_state") != "approved":
        raise PermissionError("Sign in with Microsoft and wait for administrator approval.")
    return access


def admin_snapshot():
    import supabase_client
    try:
        return {"ok": True, **supabase_client.rpc("employee_admin_snapshot")}
    except Exception:
        return {"ok": False, "error": "Could not load employee access. Administrator access is required."}


def decide(user_id, action, role, departments, revision):
    import supabase_client
    try:
        result = supabase_client.rpc("employee_decide_user", {
            "p_user_id": user_id, "p_action": action, "p_role": role,
            "p_departments": departments, "p_revision": revision})
        return {"ok": True, "result": result}
    except Exception:
        return {"ok": False, "error": "Change was not confirmed. Reload access before trying again."}
