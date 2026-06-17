"""Make the scripts/ folder importable from tests/."""
import os
import sys

import pytest

_SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


@pytest.fixture(scope="session")
def tk_root():
    """Single Tk root shared across the whole test session.

    Tk doesn't allow multiple roots in one process — module-scoped
    fixtures in different test files would conflict and the later module
    would skip. Hoisting to session scope lets every Tk-using test share
    one withdrawn root.
    """
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
    except Exception as ex:
        pytest.skip(f"Tk display not available: {ex}")
    yield r
    try:
        r.destroy()
    except Exception:
        pass
