"""ResponsiveSnap tests — confirm that the movable widget actually
moves between its narrow-mode and inline-mode parents and that callers
can't accidentally hit the Tk "can't pack into a sibling" trap.

The shared session-scoped tk_root fixture comes from conftest.py.
"""
import pytest


def _make_layout(parent, movable_parent="root"):
    """Build a primary row + narrow row + movable inner, then return
    handles for the test to drive ResponsiveSnap. movable_parent="root"
    parents the movable to `parent` (correct); "narrow" parents to
    narrow_row (the buggy pattern that was hiding the audit checkboxes).
    """
    import tkinter as tk
    top   = tk.Frame(parent, width=400, height=30, bg="#EEE")
    top.pack(fill="x")
    nrow  = tk.Frame(parent, width=400, height=30, bg="#FFF")
    nrow.pack(fill="x")
    mp    = parent if movable_parent == "root" else nrow
    inner = tk.Frame(mp, width=200, height=20, bg="#DEF")
    inner.pack(in_=nrow, side="left", anchor="w")
    tk.Label(inner, text="movable contents").pack()
    return top, nrow, inner


def test_snap_moves_widget_between_parents(tk_root):
    from tool_panel import ResponsiveSnap
    holder = __import__("tkinter").Frame(tk_root)
    holder.pack(fill="both", expand=True)
    top, nrow, inner = _make_layout(holder, movable_parent="root")
    snap = ResponsiveSnap(holder,
                           inline_parent=top,
                           narrow_parent=nrow,
                           movable=inner,
                           narrow_after=top,
                           padding=10)
    try:
        # Force apply with a wide width — should move inner under top.
        holder.update_idletasks()
        # winfo_width may report 1 before mapping; bypass apply and call
        # the inline branch by setting state and calling directly.
        snap.apply()
        # Snap the layout to "wide" by faking the threshold check
        # via direct branch invocation. We test both transitions.
        # Wide → inline
        # Force inline by setting width manually in a stable way:
        # call apply with monkey-patched winfo_width.
        import types
        holder.winfo_width = lambda: 9999  # type: ignore
        snap._inline = False
        snap.apply()
        assert snap._inline is True
        assert inner.winfo_manager() == "pack"
        # In inline mode, inner should be drawn inside top.
        # The pack info shows the in_ widget; on Tk this surfaces via
        # 'in' key in pack_info().
        info = inner.pack_info()
        assert info.get("in") in (str(top), top)

        # Narrow → switch back
        holder.winfo_width = lambda: 50  # type: ignore
        snap.apply()
        assert snap._inline is False
        info = inner.pack_info()
        assert info.get("in") in (str(nrow), nrow)
    finally:
        holder.destroy()


def test_buggy_pattern_raises_or_hides(tk_root):
    """Sanity — packing a widget into a sibling of its parent fails on Tk.
    This guards against a future refactor that "simplifies" call sites
    by re-parenting the movable to narrow_parent.
    """
    import tkinter as tk
    holder = tk.Frame(tk_root)
    holder.pack(fill="both", expand=True)
    try:
        top, nrow, inner = _make_layout(holder, movable_parent="narrow")
        # Try the cross-sibling pack that ResponsiveSnap would attempt
        inner.pack_forget()
        with pytest.raises(tk.TclError):
            inner.pack(in_=top, side="right")
    finally:
        holder.destroy()
