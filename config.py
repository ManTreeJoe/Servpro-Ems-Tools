"""Single-source config loader.

Reads `%APPDATA%\\Linguar Hub\\config.json` so the user can edit paths
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
    # Franchise-owned WORKBOOKS. Both pointed at IE's share for every
    # franchise, so OC's Snapshot panel listed IE's jobs and the dispute
    # tracker was one shared file — the two franchises reading and
    # writing each other's records without any sign of it.
    "snapshots_root", "dispute_tracker_path",
    "disputes_board_short_link",
    # Franchise identity — name + office phone on forms / DocuSign
    "franchise_name", "office_phone",
    # CompanyCam — each office has its own account. Without this every
    # department fell through to the BASE token, so OC's projects were
    # created in IE's CompanyCam (reported 2026-08-20).
    "companycam_api_token",
)

# The subset of DEPT_OVERRIDE_KEYS that answers "WHICH FRANCHISE is this?".
# Two departments sharing a value here is never legitimate — it means one
# department is silently operating on the other's Trello workspace or file
# share. Inheriting one from the base is equally dangerous: the base is
# editable from the global Settings form, so a single stray save can
# redirect every department that inherits it. `check_department_integrity`
# reports both cases; keep this list to keys where a collision is provably
# a bug (not merely unusual).
DEPT_IDENTITY_KEYS = (
    "trello_workspace_id",   # which Trello workspace = which franchise
    "audit_base",            # which job-folder share
    "runs_dir",              # which daily-run share
    # Which CompanyCam ACCOUNT. IE is company 1478909 and OC is 1489448 —
    # separate orgs — so two offices sharing this value means one is
    # creating projects in the other's account. That is exactly what was
    # happening before the key became department-scoped: OC inherited the
    # base token and its projects landed in IE's CompanyCam.
    "companycam_api_token",
)


# Franchise-owned DATA where a blank override does NOT mean "inherit".
# Everywhere else blank-inherits is right: OC leaves `trello_token` empty
# because it genuinely uses IE's account. But a blank RECORD path means
# this franchise has none of its own YET, and inheriting hands it IE's
# records to read and write. Blank here resolves to the franchise's own
# default instead - a fresh, empty, editable workbook - and a blank board
# link simply turns that franchise's sync off until a board exists.
DEPT_NO_INHERIT_KEYS = (
    "dispute_tracker_path",
    "disputes_board_short_link",
    "snapshots_root",
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


def _apply_department(cfg, dept=None):
    """Overlay a department's non-empty overrides onto the base config.
    `dept` defaults to the active department. No-op when multi-dept is off
    or the profile is missing. Operates on (and returns) a fresh dict —
    never mutates the cache."""
    if not cfg.get("multi_department_enabled"):
        return cfg
    depts = cfg.get("departments") or {}
    active = (dept if dept is not None
              else (cfg.get("active_department") or "")).strip()
    prof = depts.get(active)
    if not isinstance(prof, dict):
        return cfg
    merged = dict(cfg)
    for k in DEPT_OVERRIDE_KEYS:
        if k in prof and not _is_blank(prof[k]):
            merged[k] = prof[k]
    # Records are not inherited. Only the franchise that owns the base
    # values keeps them; everyone else falls through to their own
    # default rather than opening IE's workbook.
    if active != base_department(cfg):
        for k in DEPT_NO_INHERIT_KEYS:
            if _is_blank(prof.get(k, "")):
                merged[k] = ""
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


def load_for(dept):
    """Effective config as it would resolve if `dept` were the active
    department. Used by the integrity check (and any cross-department
    guard) to compare franchises without switching."""
    cfg = _json.loads(_json.dumps(_read_raw()))
    return _apply_department(cfg, dept=dept)


def save(cfg):
    """Persist the user's edited config to %APPDATA%\\Linguar Hub\\config.json."""
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
def base_department(cfg=None):
    """Key of the franchise that owns the flat base values.

    This used to be derived as "whichever franchise is active", which
    made the base move every time you switched offices - and with it,
    which franchise was allowed to inherit records. It is an explicit,
    stored key now; unset, it falls back to the first franchise defined,
    never to the active one."""
    try:
        base = cfg if isinstance(cfg, dict) else load_base()
    except Exception:
        return ""
    explicit = (base.get("base_department") or "").strip()
    depts = base.get("departments") or {}
    if explicit and explicit in depts:
        return explicit
    return next(iter(depts), "")


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


def _norm_identity(key, value):
    """Comparable form of an identity value. Paths are case- and
    separator-insensitive on Windows; ids compare as lowercased text."""
    s = ("" if value is None else str(value)).strip()
    if not s:
        return ""
    if key in ("audit_base", "runs_dir"):
        return _os.path.normcase(_os.path.normpath(s))
    return s.lower()


def check_department_integrity():
    """Report configuration states that let one franchise act on another's
    data. Returns a list of {level, key, dept, message} dicts — empty when
    the setup is sound. Never raises.

    Two failure modes, both of which have actually happened:

    * **collision** — two departments resolve to the SAME identity value
      (e.g. both point at the same Trello workspace). Whichever department
      inherited it is silently working in the other's franchise: every card
      lookup returns either nothing or, worse, the wrong franchise's cards.
    * **inherited** — a department has no explicit value and falls back to
      the base. The base is writable from the global Settings form, so this
      is a collision waiting to happen; it is what caused the first one.

    Cheap and offline (no API calls), so it is safe to run on every
    Settings open and at startup.
    """
    out = []
    try:
        base = load_base()
    except Exception as ex:
        return [{"level": "error", "key": "", "dept": "",
                 "message": f"config unreadable: {ex}"}]
    if not base.get("multi_department_enabled"):
        return out
    depts = base.get("departments") or {}
    if not isinstance(depts, dict) or len(depts) < 2:
        return out

    resolved = {}          # dept -> {key: effective value}
    for dk in depts:
        try:
            eff = load_for(dk)
        except Exception:
            continue
        resolved[dk] = {k: eff.get(k) for k in DEPT_IDENTITY_KEYS}

    for key in DEPT_IDENTITY_KEYS:
        seen = {}
        for dk, vals in resolved.items():
            prof = depts.get(dk) if isinstance(depts.get(dk), dict) else {}
            explicit = not _is_blank(prof.get(key))
            norm = _norm_identity(key, vals.get(key))
            if not norm:
                out.append({
                    "level": "error", "key": key, "dept": dk,
                    "message": (f"{dk} has no {key} — nothing identifies "
                                f"which franchise it operates on."),
                })
                continue
            if not explicit:
                out.append({
                    "level": "warn", "key": key, "dept": dk,
                    "message": (f"{dk} inherits {key} from the base config. "
                                f"Set it explicitly in Settings → Departments "
                                f"so a global save can't redirect {dk}."),
                })
            seen.setdefault(norm, []).append(dk)
        for norm, owners in seen.items():
            if len(owners) > 1:
                out.append({
                    "level": "error", "key": key, "dept": ", ".join(owners),
                    "message": (f"{' and '.join(owners)} both resolve to the "
                                f"SAME {key} ({norm!r}). One of them is "
                                f"operating on the other franchise's data."),
                })
    return out


def add_department(key, label=""):
    """Create an office profile. Idempotent; returns (ok, error).

    Offices are not a fixed pair. An install might be only IE, only OC,
    or a new LA — the scaffold seeded exactly IE+OC, so anyone else got
    two departments they did not want and no way to make the one they
    did.

    A new profile starts EMPTY, i.e. inheriting the base, so nothing is
    silently pointed at another office's share. The Settings form is
    where its own paths, Trello and CompanyCam token go in.
    """
    key = (key or "").strip().upper()
    if not key:
        return False, "office code required"
    if not key.replace("_", "").isalnum():
        return False, "office code must be letters/numbers"
    base = load_base()
    depts = base.get("departments")
    if not isinstance(depts, dict):
        depts = {}
    if key in depts:
        return False, f"{key} already exists"
    depts[key] = {"label": (label or "").strip() or key}
    base["departments"] = depts
    if not (base.get("active_department") or "").strip():
        base["active_department"] = key
    if len(depts) > 1:
        base["multi_department_enabled"] = True
    save(base)
    return True, ""


def remove_department(key):
    """Delete an office profile. Returns (ok, error).

    Refuses the ACTIVE office and the last remaining one: removing either
    leaves the app resolving paths through a profile that no longer
    exists, which reads as "everything inherited the base" — the silent
    cross-franchise wiring this file's other guards exist to prevent.
    """
    key = (key or "").strip().upper()
    base = load_base()
    depts = base.get("departments") or {}
    if key not in depts:
        return False, f"{key} is not an office"
    if len(depts) <= 1:
        return False, "that is the only office"
    if key == (base.get("active_department") or "").strip():
        return False, "switch to another office first"
    depts.pop(key, None)
    base["departments"] = depts
    if len(depts) <= 1:
        base["multi_department_enabled"] = False
    save(base)
    return True, ""


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
        # IE = the current single-department setup. Copy the base identity
        # values in EXPLICITLY rather than leaving the profile empty to
        # inherit them: the base is writable from the global Settings form,
        # so an inherited identity can be redirected to the other franchise
        # by an unrelated save (which is exactly how IE once ended up
        # searching OC's Trello workspace).
        prof = {"label": "Inland Empire"}
        for k in DEPT_IDENTITY_KEYS:
            if not _is_blank(base.get(k)):
                prof[k] = base[k]
        depts["IE"] = prof
        changed = True
    # Deliberately NOT seeding a second office. An install that is only
    # IE — or only OC, or only LA — was given two profiles and no way to
    # add a different one. Offices are added in Settings now.
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
