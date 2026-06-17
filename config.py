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


# Module-level cache so each panel init doesn't re-read config.json off the
# share. Invalidates on file mtime change so an external edit (settings
# dialog → save) is picked up next call without a process restart. Each
# load() returned a fresh dict before, so callers that mutated the result
# would silently corrupt the cache — return a deep copy to preserve that
# contract. Saves ~50-200ms per panel construction (×11 embedded panels =
# 0.5-2s of startup time).
_CACHE = None
_CACHE_MTIME = None


def load():
    """Return the parsed config dict. Cached by file mtime."""
    global _CACHE, _CACHE_MTIME
    _ensure_user_config()
    path = _USER_CFG if _os.path.isfile(_USER_CFG) else _DEFAULT_CFG
    try:
        mtime = _os.path.getmtime(path)
    except OSError:
        mtime = None
    if _CACHE is not None and mtime is not None and mtime == _CACHE_MTIME:
        # Deep-copy via json round-trip — cheap and protects callers that
        # mutate the returned dict (e.g., overlay defaults before reading).
        return _json.loads(_json.dumps(_CACHE))
    with open(path, encoding="utf-8") as f:
        cfg = _json.load(f)
    _CACHE = cfg
    _CACHE_MTIME = mtime
    return _json.loads(_json.dumps(cfg))


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
