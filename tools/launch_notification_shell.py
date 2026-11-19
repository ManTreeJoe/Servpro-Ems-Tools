"""Explicit source launcher modes; configure before importing application state.

Dev and IsolatedDev both use the prepared isolated profile. There is no implicit
live Dev mode. Main is an explicit opt-in; installed Trial keeps its own launcher.
"""
import os
import sys
from pathlib import Path


def configure_channel(mode):
    if mode not in {"Main", "Dev", "IsolatedDev"}:
        raise SystemExit("Choose Main, Dev or IsolatedDev explicitly.")
    if getattr(sys, "frozen", False):
        raise SystemExit("Use the installed application's own launcher.")
    # These modules snapshot the channel at import time. Never retarget them in place.
    if any(name in sys.modules for name in ("paths", "config", "home_web")):
        raise RuntimeError("Channel selection must precede application imports.")
    os.environ.pop("ONELOSS_DEV_LIVE", None)
    os.environ["LINGUAR_CHANNEL"] = "main" if mode == "Main" else "dev"
    if mode == "Main":
        os.environ.pop("LINGUAR_DEV_MODE", None)
    else:
        os.environ["LINGUAR_DEV_MODE"] = "1"


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        raise SystemExit("Choose Main, Dev or IsolatedDev explicitly.")
    configure_channel(args[0])
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    if args[0] != "Main":
        import dev_runtime
        dev_runtime.install()  # Failure stops launch; never retry against Main.
    import home_web
    home_web.main()


if __name__ == "__main__":
    main()
