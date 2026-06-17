"""ScrollableFrame smoke tests — ensure the helper builds and that each
instance gets its own bindtag (so wheel events don't leak across panels).

The shared session-scoped tk_root fixture comes from conftest.py.
"""
import pytest


def test_scrollable_frame_builds(tk_root):
    from tool_panel import ScrollableFrame
    wrap = ScrollableFrame(tk_root, bg="#FFFFFF")
    try:
        assert wrap.canvas is not None
        assert wrap.inner is not None
        # Inner must be parented to the canvas (so create_window works).
        assert wrap.inner.master is wrap.canvas
    finally:
        wrap.destroy()


def test_scrollable_frame_unique_bindtags(tk_root):
    """Each instance gets a unique bindtag so wheel events scoped to one
    panel don't fire handlers on another panel that happens to be hidden."""
    from tool_panel import ScrollableFrame
    a = ScrollableFrame(tk_root, bg="#FFFFFF")
    b = ScrollableFrame(tk_root, bg="#FFFFFF")
    try:
        assert a._scroll_tag != b._scroll_tag
        assert a._scroll_tag in a.canvas.bindtags()
        assert b._scroll_tag in b.canvas.bindtags()
        # Cross-contamination guard
        assert a._scroll_tag not in b.canvas.bindtags()
    finally:
        a.destroy()
        b.destroy()


def test_attach_wheel_walks_descendants(tk_root):
    import tkinter as tk
    from tool_panel import ScrollableFrame
    wrap = ScrollableFrame(tk_root, bg="#FFFFFF")
    try:
        outer = tk.Frame(wrap.inner)
        outer.pack()
        leaf = tk.Label(outer, text="leaf")
        leaf.pack()
        wrap.attach_wheel(outer)
        assert wrap._scroll_tag in leaf.bindtags()
    finally:
        wrap.destroy()


def test_descendants_added_after_construction_get_wheel_tag(tk_root):
    """Regression — once content was rendered into .inner from a render
    pass (the common case for every audit-style tool), wheel scrolling
    only worked while hovering the bare canvas/inner frame. The Configure-
    driven auto-walk should rescue that without callers having to call
    attach_wheel themselves.
    """
    import tkinter as tk
    from tool_panel import ScrollableFrame
    wrap = ScrollableFrame(tk_root, bg="#FFFFFF")
    wrap.pack()
    try:
        # Simulate an audit row being added after construction.
        row = tk.Frame(wrap.inner)
        row.pack(fill="x")
        leaf = tk.Label(row, text="job line")
        leaf.pack()
        # Force the deferred walk to execute (bypasses the 60ms debounce).
        wrap.update_idletasks()
        wrap._walk_attach_descendants()
        assert wrap._scroll_tag in row.bindtags()
        assert wrap._scroll_tag in leaf.bindtags()
    finally:
        wrap.destroy()
