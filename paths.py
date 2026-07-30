"""
Path resolution for the EMS Automation suite.

Two roots:
  RESOURCE_DIR — read-only bundled assets (icon, cheat-sheet, default config).
                 In dev mode this is the scripts folder; in a PyInstaller
                 build it's sys._MEIPASS (onefile) or the exe folder (onedir).

  DATA_DIR    — writable user state (%APPDATA%\\EMS Automation).
                 state.json, audit_backlog.json, EMS_Audit_Log.md,
                 EMS_Audit_Backlog.md, ems.log, user config.json all live here.

Importing this module guarantees DATA_DIR exists and runs a one-time
migration of any files left behind in the legacy scripts folder.
"""
import os
import sys
import glob
import shutil

VERSION = "1.1.3"


def _detect_channel():
    """'trial' or 'main'. The Trial app is a separate build that installs to
    an "EMS Tools Trial" folder / exe, so a frozen build detects its channel
    from its own path. In dev (running from source) honor the EMS_CHANNEL env
    var so the trial code path can be exercised without a build. Data + config
    are SHARED between channels — only name / install dir / update channel
    differ."""
    try:
        if getattr(sys, "frozen", False):
            exe = sys.executable or ""
            probe = (os.path.basename(exe) + " "
                     + os.path.basename(os.path.dirname(exe))).lower()
            if "trial" in probe:
                return "trial"
            return "main"
    except Exception:
        pass
    return "trial" if os.environ.get("EMS_CHANNEL", "").lower() == "trial" else "main"


CHANNEL = _detect_channel()
IS_TRIAL = CHANNEL == "trial"


# ── Stdout/stderr encoding ─────────────────────────────────────────────────
# Windowed PyInstaller builds get cp1252 (or None) for stdout/stderr by
# default. Any traceback or print containing a non-ASCII character (emoji
# in toast text, accented client names returned by Trello, etc.) crashes
# with `UnicodeEncodeError: 'charmap' codec can't encode character`. The
# user hit this trying to autofill a Trello card from APA Monitor — the
# search worked, but the exception path emitted to stderr blew up. Force
# UTF-8 + replace-on-error on every entry point by running this at module
# import time. paths.py is imported by every tool, so this fires whether
# the process started via launcher.exe, run_standalone, or `--tool` dispatch.
def _force_utf8_stdio():
    for stream_name in ("stdout", "stderr"):
        s = getattr(sys, stream_name, None)
        if s is None:
            continue
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # Older Python or non-text stream — fall back to wrapping.
            try:
                import io
                buf = getattr(s, "buffer", None)
                if buf is not None:
                    setattr(sys, stream_name,
                            io.TextIOWrapper(buf, encoding="utf-8",
                                              errors="replace",
                                              line_buffering=True))
            except Exception:
                pass


_force_utf8_stdio()

FROZEN = getattr(sys, "frozen", False)

# ── Resource dir (read-only) ────────────────────────────────────────────────
if FROZEN:
    # PyInstaller --onefile extracts to a temp dir at sys._MEIPASS.
    # --onedir uses the exe's folder. _MEIPASS is set in both cases.
    RESOURCE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    RESOURCE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Writable data dir ───────────────────────────────────────────────────────
APPDATA  = os.environ.get("APPDATA") or os.path.expanduser(r"~\AppData\Roaming")
DATA_DIR = os.path.join(APPDATA, "EMS Automation")
os.makedirs(DATA_DIR, exist_ok=True)


def resource(name):
    """Path to a bundled read-only file."""
    return os.path.join(RESOURCE_DIR, name)


def data(name):
    """Path to a user-writable file under %APPDATA%\\EMS Automation."""
    return os.path.join(DATA_DIR, name)


# ── One-time migration from legacy scripts folder ───────────────────────────
_MIGRATABLE = (
    "state.json",
    "audit_backlog.json",
    "EMS_Audit_Log.md",
    "EMS_Audit_Backlog.md",
    "ems.log",
    "ems.log.bak",
    "config.json",
)


def _legacy_dir_candidates():
    """Locations to look for an existing scripts folder when migrating data."""
    cands = []
    # In dev mode, this *is* the scripts folder itself
    if not FROZEN:
        cands.append(os.path.dirname(os.path.abspath(__file__)))
    # OneDrive-synced Documents (any "OneDrive*" parent folder)
    home = os.path.expanduser("~")
    cands.extend(glob.glob(os.path.join(
        home, "OneDrive*", "Documents", "EMS Automation", "scripts")))
    # Plain Documents fallback
    cands.append(os.path.join(home, "Documents", "EMS Automation", "scripts"))
    seen = set()
    out = []
    for c in cands:
        c = os.path.abspath(c)
        if c not in seen and os.path.isdir(c):
            seen.add(c)
            out.append(c)
    return out


def _migrate_once():
    """Copy any legacy files into DATA_DIR if DATA_DIR doesn't have them yet."""
    for legacy in _legacy_dir_candidates():
        for name in _MIGRATABLE:
            src = os.path.join(legacy, name)
            dst = os.path.join(DATA_DIR, name)
            if os.path.isfile(src) and not os.path.exists(dst):
                try:
                    shutil.copy2(src, dst)
                except OSError as ex:
                    # Migration is best-effort, but losing state silently is
                    # worse than a noisy log line — record what didn't move.
                    try:
                        import ems_log
                        ems_log.warn(
                            "paths", f"migrate {name!r} from {legacy!r}: {ex}")
                    except Exception:
                        pass

_migrate_once()


# ── Auto-detection of folder paths ──────────────────────────────────────────
def auto_detect():
    """
    Best-effort guess at the per-PC folder paths, by searching the file system.

    Returns a dict with whichever keys we found. Caller overlays these on
    top of the bundled defaults so unknown keys keep their default value.
    """
    home = os.path.expanduser("~")
    onedrive_roots = sorted(set(
        glob.glob(os.path.join(home, "OneDrive*"))
        + glob.glob(os.path.join(home, "OneDrive - *"))
    ))

    detected = {}

    # audit_base — typically a mapped X: drive at the SERVPRO franchise
    for cand in (r"X:\IE_Public", r"X:\IE Public", r"X:\\"):
        if os.path.isdir(cand):
            detected["audit_base"] = os.path.normpath(cand)
            break

    # runs_dir — OneDrive subfolder containing daily run .docx files
    runs_candidates = []
    for od in onedrive_roots:
        runs_candidates.extend(glob.glob(os.path.join(od, "*Run*")))
        runs_candidates.extend(glob.glob(os.path.join(od, "*Daily*")))
    # Prefer ones that actually contain .docx files
    for cand in runs_candidates:
        if os.path.isdir(cand) and glob.glob(os.path.join(cand, "*.docx")):
            detected["runs_dir"] = os.path.normpath(cand)
            break
    if "runs_dir" not in detected:
        for cand in runs_candidates:
            if os.path.isdir(cand):
                detected["runs_dir"] = os.path.normpath(cand)
                break

    # photos_root — OneDrive subfolder with "Photo" in the name
    for od in onedrive_roots:
        for cand in glob.glob(os.path.join(od, "*Photo*")):
            if os.path.isdir(cand):
                detected["photos_root"] = os.path.normpath(cand)
                break
        if "photos_root" in detected:
            break

    # snapshot_template — typically under <audit_base>\Front Operation\
    if "audit_base" in detected:
        for sub in ("Front Operation", "Front Office"):
            cand = os.path.join(
                detected["audit_base"], sub, "snapshot_handoff_fillable.pdf")
            if os.path.isfile(cand):
                detected["snapshot_template"] = os.path.normpath(cand)
                break

    # snapshot_output — Snapshots folder near the template, else Downloads
    if "audit_base" in detected:
        cand = os.path.join(detected["audit_base"], "Front Operation", "Snapshots")
        if os.path.isdir(cand):
            detected["snapshot_output"] = os.path.normpath(cand)
    if "snapshot_output" not in detected:
        downloads = os.path.join(home, "Downloads")
        if os.path.isdir(downloads):
            detected["snapshot_output"] = os.path.normpath(downloads)

    # apa_monitor_root — typically <audit_base>\APA Monitor
    if "audit_base" in detected:
        cand = os.path.join(detected["audit_base"], "APA Monitor")
        if os.path.isdir(cand):
            detected["apa_monitor_root"] = os.path.normpath(cand)

    return detected


# ── Configured location helpers ─────────────────────────────────────────────
# Thin wrappers around `config.load()` so panels don't each duplicate the
# `_CFG = config.load(); AUDIT_BASE = _CFG.get("audit_base", ...)` boilerplate.
# Lazy-import config inside the body — paths.py is imported by config.py, so
# a top-level `import config` would create a circular import.

def audit_base():
    """Configured audit_base (typically X:\\IE_Public)."""
    import config
    return config.load().get("audit_base", r"X:\IE_Public")


def runs_dir():
    """Configured run-doc directory (OneDrive subfolder of daily run .docx files)."""
    import config
    return config.load().get("runs_dir", "")


def photos_root():
    """Configured SharePoint photos root."""
    import config
    return config.load().get("photos_root", "")


# ── First-run marker ────────────────────────────────────────────────────────
_CONFIGURED_MARKER = os.path.join(DATA_DIR, ".configured")


def is_first_run():
    """True until the user has opened (and dismissed) the settings dialog at
    least once on this machine."""
    return not os.path.isfile(_CONFIGURED_MARKER)


def mark_configured():
    """Drop the marker so we don't auto-pop the wizard again."""
    try:
        with open(_CONFIGURED_MARKER, "w") as f:
            f.write("")
    except OSError:
        pass


# ── Sub-process launching helper ────────────────────────────────────────────
def launcher_command(tool, *args):
    """
    Build the argv for spawning a tool through the launcher dispatcher.

    Frozen:  [<this exe>, "--tool", tool, *args]
    Dev:     [sys.executable, <launcher.py>, "--tool", tool, *args]
    """
    if FROZEN:
        return [sys.executable, "--tool", tool, *args]
    launcher_py = os.path.join(RESOURCE_DIR, "launcher.py")
    return [sys.executable, launcher_py, "--tool", tool, *args]


def spawn_tool(tool, *args):
    """Launch a sibling tool in a new process via the launcher dispatcher."""
    import subprocess
    creationflags = 0
    if sys.platform == "win32":
        # DETACHED_PROCESS so closing the parent doesn't kill the child
        creationflags = 0x00000008
    subprocess.Popen(launcher_command(tool, *args), creationflags=creationflags)
