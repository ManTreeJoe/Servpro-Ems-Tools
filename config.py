"""Single-source config loader.

Reads `%APPDATA%\\EMS Automation\\config.json` so the user can edit paths
without rebuilding. On first run, seeds it from the bundled default in
RESOURCE_DIR.
"""
import json as _json
import os as _os
import shutil as _shutil

import paths as _paths

_USER_CFG    = _paths.data("config.json")
_DEFAULT_CFG = _paths.resource("config.json")


def _ensure_user_config():
    if _os.path.isfile(_USER_CFG):
        return
    cfg = {}
    if _os.path.isfile(_DEFAULT_CFG):
        try:
            with open(_DEFAULT_CFG, encoding="utf-8") as f:
                cfg = _json.load(f)
        except (OSError, _json.JSONDecodeError) as ex:
            try:
                import ems_log
                ems_log.warn("config", f"default config unreadable: {ex}")
            except Exception:
                pass
            cfg = {}
    # Overlay best-guess paths so coworkers see auto-detected values pre-filled
    cfg.update(_paths.auto_detect())
    try:
        with open(_USER_CFG, "w", encoding="utf-8") as f:
            _json.dump(cfg, f, indent=2)
    except OSError as ex:
        try:
            import ems_log
            ems_log.error("config", f"seed user config write failed: {ex}")
        except Exception:
            pass


# ── Department (multi-account) scoping ───────────────────────────────
# The suite can run against two SERVPRO departments (e.g. Inland Empire
# vs Orange County), each with its own Trello board, file-share roots,
# and franchise identity. Rather than teach all 28 config consumers about
# departments, we scope UNDER load(): the flat base config is the default,
# and the ACTIVE department's non-empty overrides are merged on top. When
# `multi_department_enabled` is off, load() returns the base untouched —
# fully backward-compatible with single-department installs.
#
# Keys a department profile is allowed to override. Everything else
# (Downloads output, Graph/Azure creds, CompanyCam token, feature flags)
# stays global across departments.
DEPT_OVERRIDE_KEYS = (
    # Trello — its own board/workspace (and token, if a separate login)
    "trello_api_key", "trello_token", "trello_workspace_id",
    "trello_boards_exclude", "trello_snapshot_list_id",
    # File-share roots — separate job/photo/run/APA folders
    "audit_base", "snapshot_template", "photos_root",
    "photos_extra_roots", "runs_dir", "apa_monitor_root",
    # Franchise identity — name + office phone on forms / DocuSign
    "franchise_name", "office_phone",
)

# Franchise identity defaults (Inland Empire) used when a config key is
# absent, so nothing breaks on installs whose config.json predates these
# keys. Overridable per-department once multi-dept is on.
_DEFAULT_FRANCHISE_NAME = (
    "L&P Group, Inc. d/b/a SERVPRO of Woodcrest / El Cerrito / Lake Mathews")
_DEFAULT_OFFICE_PHONE = "951-398-3240"


def _is_blank(v):
    """A department override value that should INHERIT the base instead of
    winning: None, empty/whitespace string, or empty list/dict."""
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() == ""
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


def _apply_department(cfg):
    """Overlay the active department's non-empty overrides onto the base
    config. No-op when multi-dept is off or the active profile is missing.
    Operates on (and returns) a fresh dict — never mutates the cache."""
    if not cfg.get("multi_department_enabled"):
        return cfg
    depts = cfg.get("departments") or {}
    active = (cfg.get("active_department") or "").strip()
    prof = depts.get(active)
    if not isinstance(prof, dict):
        return cfg
    merged = dict(cfg)
    for k in DEPT_OVERRIDE_KEYS:
        if k in prof and not _is_blank(prof[k]):
            merged[k] = prof[k]
    return merged


# Module-level cache so each panel init doesn't re-read config.json off the
# share. Invalidates on file mtime change so an external edit (settings
# dialog → save, or a department switch) is picked up next call without a
# process restart. Each load() returned a fresh dict before, so callers
# that mutated the result would silently corrupt the cache — return a deep
# copy to preserve that contract. Saves ~50-200ms per panel construction
# (×11 embedded panels = 0.5-2s of startup time).
_CACHE = None
_CACHE_MTIME = None


def _read_raw():
    """Return the cached raw base config dict (a shared reference — callers
    must not mutate it). Re-reads from disk when the file mtime changes."""
    global _CACHE, _CACHE_MTIME
    _ensure_user_config()
    path = _USER_CFG if _os.path.isfile(_USER_CFG) else _DEFAULT_CFG
    try:
        mtime = _os.path.getmtime(path)
    except OSError:
        mtime = None
    if _CACHE is not None and mtime is not None and mtime == _CACHE_MTIME:
        return _CACHE
    with open(path, encoding="utf-8") as f:
        cfg = _json.load(f)
    _CACHE = cfg
    _CACHE_MTIME = mtime
    return _CACHE


def load_base():
    """Return the flat BASE config (a fresh copy), WITHOUT department
    overlay. Use for Settings save + department switching so writes never
    bake an active department's overrides into the base."""
    return _json.loads(_json.dumps(_read_raw()))


def load():
    """Return the effective config dict: base with the active department's
    overrides merged on top. Cached by file mtime; returns a fresh deep
    copy so callers can safely mutate it."""
    cfg = _json.loads(_json.dumps(_read_raw()))
    return _apply_department(cfg)


def save(cfg):
    """Persist the user's edited config to %APPDATA%\\EMS Automation\\config.json."""
    global _CACHE, _CACHE_MTIME
    _os.makedirs(_os.path.dirname(_USER_CFG), exist_ok=True)
    tmp = _USER_CFG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump(cfg, f, indent=2)
    _os.replace(tmp, _USER_CFG)
    # Invalidate so the next load() picks up the new mtime. Safer than
    # writing the dict directly into the cache — avoids drift if save()
    # ever transforms the input.
    _CACHE = None
    _CACHE_MTIME = None


def user_config_path():
    return _USER_CFG


# ── Department accessors ─────────────────────────────────────────────
def is_multi_dept():
    """True when multiple-department mode is enabled."""
    try:
        return bool(load_base().get("multi_department_enabled", False))
    except Exception:
        return False


def active_department():
    """Key of the active department (e.g. 'IE'), or '' when multi-dept is
    off / unset."""
    try:
        base = load_base()
        if not base.get("multi_department_enabled"):
            return ""
        return (base.get("active_department") or "").strip()
    except Exception:
        return ""


def list_departments():
    """Ordered list of {key, label} for every configured department.
    Empty when none are set up. Insertion order (IE before OC) is
    preserved from the JSON."""
    try:
        depts = load_base().get("departments") or {}
    except Exception:
        return []
    out = []
    for k, v in depts.items():
        label = ""
        if isinstance(v, dict):
            label = (v.get("label") or "").strip()
        out.append({"key": k, "label": label or k})
    return out


def set_active_department(name):
    """Switch the active department and persist it. Operates on the BASE
    config so no overrides get baked in. Returns True on success."""
    name = (name or "").strip()
    base = load_base()
    depts = base.get("departments") or {}
    if name and name not in depts:
        return False
    base["active_department"] = name
    save(base)
    return True


def ensure_departments_scaffold():
    """Create the default IE + OC department profiles the first time
    multi-dept is turned on. IE inherits the current base values (empty
    overrides), OC is blank for the user to fill in Settings. Idempotent —
    never clobbers existing profiles. Returns the (possibly updated) base
    config dict, already saved if it changed."""
    base = load_base()
    depts = base.get("departments")
    changed = False
    if not isinstance(depts, dict):
        depts = {}
        changed = True
    if "IE" not in depts:
        # IE = the current single-department setup; empty overrides mean
        # it inherits every base value (which is IE today).
        depts["IE"] = {"label": "Inland Empire"}
        changed = True
    if "OC" not in depts:
        depts["OC"] = {"label": "Orange County"}
        changed = True
    if not (base.get("active_department") or "").strip():
        base["active_department"] = "IE"
        changed = True
    if changed:
        base["departments"] = depts
        save(base)
    return base


# ── Franchise identity (per-department once multi-dept is on) ─────────
def franchise_name():
    """Legal franchise name shown on forms / DocuSign requests."""
    try:
        return (load().get("franchise_name") or "").strip() \
            or _DEFAULT_FRANCHISE_NAME
    except Exception:
        return _DEFAULT_FRANCHISE_NAME


def office_phone():
    """Office phone shown on DocuSign / customer-facing messages."""
    try:
        return (load().get("office_phone") or "").strip() \
            or _DEFAULT_OFFICE_PHONE
    except Exception:
        return _DEFAULT_OFFICE_PHONE


def is_alpha_enabled():
    """True when alpha (Workcenter integration) features should appear.

    Single-source check used by the launcher banner, audit row buttons,
    and any module that lazy-imports `workcenter_client`. Defaults to
    False so a fresh install behaves like main.
    """
    try:
        return bool(load().get("enable_workcenter_alpha", False))
    except Exception:
        return False


def is_sort_files_visible():
    """True when the Sort Files tool should appear in the launcher's
    top tool strip. Hidden by default — Sort Files runs as a Desktop
    .bat the user already has, so the launcher entry is redundant for
    most installs. Settings panel exposes a checkbox to opt back in.
    """
    try:
        return bool(load().get("show_sort_files", False))
    except Exception:
        return False


def is_new_job_visible():
    """True when the New EMS Job tool should appear in the launcher's
    top tool strip. Hidden by default — job creation is exposed as a
    "+ New Job" button inside the Audit and Snapshot tools where the
    workflow naturally needs it, so a top-level launcher entry is
    redundant. Settings panel exposes a checkbox to opt back in.
    """
    try:
        return bool(load().get("show_new_job", False))
    except Exception:
        return False
