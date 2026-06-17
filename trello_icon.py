"""Shared Trello-logo icon for Tk buttons across the suite.

Tk's `PhotoImage` lifetime is tied to its master root — you can't share
one instance across Toplevels, and you can't let it get garbage-
collected or the button paints blank. This module caches one
`PhotoImage` per Tk root so any number of "open in Trello" buttons can
hold a reference without each one re-loading the PNG from disk.

Usage:
    from trello_icon import trello_icon
    btn = tk.Button(parent, image=trello_icon(parent), ...)

The icon file `trello.png` ships next to this module (18×18, the source
512px logo resampled with LANCZOS so the brand mark is crisp at button
sizes). Falls back to `None` on any load failure — callers should
provide a `text="T"` fallback in their button so a missing-icon
deployment still gets a clickable, recognizable button.
"""
from __future__ import annotations

import os
import tkinter as tk
from typing import Optional

import paths


# Route through paths.resource() so the icon resolves correctly in both
# dev mode (next to this file) AND in PyInstaller-frozen builds (where
# bundled data files live under sys._MEIPASS, not the source tree).
_ICON_PATH = paths.resource("trello.png")

# Keyed by id(root) so each Tk root keeps its own image; PhotoImage
# can't be shared across roots and a hard reference here also prevents
# the GC from collecting it while buttons still need it.
_CACHE: dict[int, tk.PhotoImage] = {}


def trello_icon(widget: tk.Misc) -> Optional[tk.PhotoImage]:
    """Return the 18×18 Trello-logo PhotoImage for `widget`'s root.
    Cached after first load; subsequent calls in the same Tk root are
    O(1). Returns None if the PNG can't be loaded — callers should
    have a text fallback so the button still renders something."""
    try:
        root = widget.winfo_toplevel()
    except Exception:
        root = None
    if root is None:
        try:
            root = widget._root()  # type: ignore[attr-defined]
        except Exception:
            return None
    key = id(root)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    if not os.path.isfile(_ICON_PATH):
        return None
    try:
        img = tk.PhotoImage(master=root, file=_ICON_PATH)
    except tk.TclError:
        return None
    _CACHE[key] = img
    return img
