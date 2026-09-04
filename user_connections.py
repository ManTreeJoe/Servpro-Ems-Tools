"""One user-facing connection model for external services.

Screens should not need to know whether a provider uses the Linguar Hub
session, an organization application key, a per-user token, or the Windows
desktop session.  They ask for :func:`statuses` and render the same small
set of states and actions.

CompanyCam is intentionally organization-managed for this private app.  An
administrator configures one Application Key per franchise; employees sign
into Linguar Hub, and CompanyCam writes are attributed to that employee with
``X_COMPANYCAM_USER``.  We do not ask every employee to create or paste a
personal CompanyCam token.
"""
from __future__ import annotations

import os


def _access(value=None) -> dict:
    if value is not None:
        return value
    try:
        import account_access
        return account_access.current_access() or {}
    except Exception as ex:
        return {"signed_in": False, "is_admin": False, "error": str(ex)}


def _config(value=None) -> dict:
    if value is not None:
        return value
    try:
        import config
        return config.load() or {}
    except Exception:
        return {}


def _franchise() -> str:
    try:
        import config
        return (config.active_department() or "").strip()
    except Exception:
        return ""


def _card(provider, name, icon, state, status, detail, *, identity="",
          action="", action_label="", scope="personal", admin_only=False):
    return {
        "provider": provider,
        "name": name,
        "icon": icon,
        "state": state,
        "status": status,
        "detail": detail,
        "identity": identity,
        "action": action,
        "action_label": action_label,
        "scope": scope,
        "admin_only": bool(admin_only),
    }


def statuses(*, access=None, cfg=None, platform_name=None) -> list[dict]:
    """Return fast, side-effect-free connection cards for My Settings.

    This deliberately does not call provider APIs or launch Outlook.  A
    Settings render must stay responsive even when a provider is offline.
    Explicit Test/Open actions can perform slower work afterward.
    """
    access = _access(access)
    cfg = _config(cfg)
    signed_in = bool(access.get("signed_in"))
    email = str(access.get("email") or "").strip().lower()
    display_name = str(access.get("display_name") or "").strip()
    actor = display_name or email
    is_admin = bool(access.get("is_admin"))
    franchise = _franchise() or "this franchise"

    cards = []
    if signed_in:
        cards.append(_card(
            "linguar", "Linguar Hub", "LH", "connected", "Signed in",
            "Your app permissions and activity history use this identity.",
            identity=actor, action="sign_out", action_label="Sign out"))
    else:
        cards.append(_card(
            "linguar", "Linguar Hub", "LH", "sign_in_required",
            "Sign in required", "Sign in once with your SERVPRO work account.",
            action="sign_in", action_label="Sign in"))

    companycam_local = bool(str(cfg.get("companycam_api_token") or "").strip())
    try:
        import companycam_api
        companycam_cloud = bool(signed_in and companycam_api.cloud_gateway_available())
    except Exception:
        companycam_cloud = False
    companycam_ready = companycam_local or companycam_cloud
    if not companycam_ready:
        cards.append(_card(
            "companycam", "CompanyCam", "CC", "admin_required",
            "Office connection needed on this PC",
            (f"An admin must install the {franchise} CompanyCam application key "
             "on this PC. You can still sign into CompanyCam normally; employees "
             "should not paste personal API tokens."),
            action=("admin_setup" if is_admin else "open_companycam"),
            action_label=("Admin setup" if is_admin else "Sign in to CompanyCam"),
            scope="organization", admin_only=True))
    elif not signed_in:
        cards.append(_card(
            "companycam", "CompanyCam", "CC", "sign_in_required",
            "Sign in to identify your work",
            (f"{franchise} is connected. Sign into Linguar Hub so CompanyCam "
             "actions can be recorded under your work email."),
            action="sign_in", action_label="Sign in",
            scope="organization"))
    else:
        cards.append(_card(
            "companycam", "CompanyCam", "CC", "connected",
            "Connected securely by office",
            (f"{franchise} manages the secure connection in Supabase. Actions "
             "are sent to CompanyCam as the signed-in employee."),
            identity=email, action="open_companycam",
            action_label="Open CompanyCam", scope="organization"))

    trello_key = bool(str(cfg.get("trello_api_key") or "").strip())
    trello_token = bool(str(cfg.get("trello_token") or "").strip())
    if trello_key and trello_token:
        cards.append(_card(
            "trello", "Trello", "TR", "connected", "Personal account connected",
            "Trello comments and card changes use the account connected on this PC.",
            identity="Your Trello account", action="connect_trello",
            action_label="Reconnect"))
    elif trello_key:
        cards.append(_card(
            "trello", "Trello", "TR", "disconnected", "Not connected",
            "Sign into Trello and approve Linguar Hub. No token typing is needed.",
            action="connect_trello", action_label="Connect Trello"))
    else:
        cards.append(_card(
            "trello", "Trello", "TR", "admin_required", "Office setup needed",
            "An admin must configure Linguar Hub's Trello application first.",
            action=("admin_setup" if is_admin else ""),
            action_label=("Admin setup" if is_admin else ""), admin_only=True))

    windows = (platform_name or os.name) == "nt"
    cards.append(_card(
        "microsoft", "Microsoft 365", "M", "available" if windows else "unavailable",
        "Uses your Windows Outlook sign-in" if windows else "Desktop Outlook unavailable",
        ("Email tools use the Outlook account already signed into this Windows PC. "
         "Outlook will ask you to sign in normally when needed." if windows else
         "Microsoft 365 desktop access is available in the Windows app."),
        action="open_outlook" if windows else "",
        action_label="Open Outlook" if windows else ""))
    return cards


def companycam_actor_headers(method="GET", *, access=None) -> dict:
    """Headers that attribute a CompanyCam mutation to the signed-in user.

    Read calls need no attribution.  Missing identity returns no header so
    legacy/offline tools continue to report their normal auth error; the UI
    separately tells the employee to sign in before doing attributed work.
    """
    if str(method or "GET").upper() in {"GET", "HEAD", "OPTIONS"}:
        return {}
    access = _access(access)
    if not access.get("signed_in"):
        return {}
    email = str(access.get("email") or "").strip().lower()
    return {"X_COMPANYCAM_USER": email} if email else {}


def open_target(provider: str) -> str:
    """Browser destination for providers whose normal UI owns sign-in."""
    return {
        "companycam": "https://app.companycam.com/",
        "microsoft": "https://outlook.office.com/mail/",
    }.get(str(provider or "").strip().lower(), "")


def sign_in(email: str, password: str) -> dict:
    """Sign into Linguar Hub and select the shared job backend.

    This is the shared account seam for the legacy Settings screen and the
    Operations workspace.  Passwords are sent directly to Supabase Auth and
    are never persisted in config or returned to either UI.
    """
    email = str(email or "").strip()
    if not email or not password:
        return {"ok": False, "error": "Enter your work email and password."}
    try:
        import supabase_client
        user = supabase_client.sign_in_with_password(email, password)
        import config
        import ems_db
        base = dict(config.load_base() or {})
        config.save({**base, "ems_db_backend": "supabase"})
        ems_db.use_backend("supabase")
        try:
            import cache_bust
            cache_bust.invalidate_all("user signed in")
        except Exception:
            pass
        return {"ok": True, "user": user,
                "message": f"Signed in as {user.get('email') or email}."}
    except Exception as ex:
        status = getattr(ex, "status", 0)
        if status in (400, 401):
            return {"ok": False, "error": "Email or password is incorrect."}
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}


def sign_out() -> dict:
    """End the user session and leave the local fallback available."""
    try:
        import supabase_client
        supabase_client.sign_out()
        import config
        import ems_db
        base = dict(config.load_base() or {})
        config.save({**base, "ems_db_backend": "sqlite"})
        ems_db.use_backend("sqlite")
        try:
            import cache_bust
            cache_bust.invalidate_all("user signed out")
        except Exception:
            pass
        return {"ok": True, "message": "Signed out. Local fallback is available."}
    except Exception as ex:
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}


def begin(provider: str) -> dict:
    """Begin the provider's normal connection flow without exposing keys."""
    provider = str(provider or "").strip().lower()
    if provider == "trello":
        try:
            import trello_auth
            result = trello_auth.authorize()
            if result.get("ok"):
                return {"ok": True, "message": "Trello connected."}
            return result
        except Exception as ex:
            return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
    target = open_target(provider)
    if target:
        return {"ok": True, "url": target,
                "message": f"Opened {provider} sign in."}
    return {"ok": False, "error": "That connection is not available."}
