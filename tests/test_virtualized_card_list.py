"""Smoke tests for VirtualizedCardList — covers register/derealize.

The full realize/derealize round-trip is hard to test deterministically
because Tk's geometry pass and after-callback timing varies on Windows;
the integration test that actually exercises that path is the audit
panel itself. These tests cover the contract surface that's stable in
a unit harness: registration tracks the card, the visibility tick
tears down children when the card is outside the viewport band, and
clear()/destroyed-frame paths don't crash.
"""
import tkinter as tk
import unittest

from tool_panel import ScrollableFrame, VirtualizedCardList


class VirtualizedCardListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.geometry("400x200+0+0")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except tk.TclError:
            pass

    def setUp(self):
        self.sf = ScrollableFrame(self.root)
        self.sf.pack(fill="both", expand=True)
        self.virt = VirtualizedCardList(self.sf, overscan_px=50)
        self.root.update_idletasks()
        self.root.update()

    def tearDown(self):
        try:
            self.sf.destroy()
        except tk.TclError:
            pass

    def _add_card(self, height_px=80):
        body = tk.Frame(self.sf.inner, bg="white", height=height_px)
        body.pack(fill="x", pady=2)

        build_count = [0]

        def _build(frame):
            build_count[0] += 1
            tk.Label(frame, text=f"build #{build_count[0]}",
                     bg="white").pack(fill="x")

        _build(body)
        self.virt.register(body, _build)
        return body, build_count

    def _flush(self):
        # Several update cycles for the after(60) tick + layout.
        for _ in range(8):
            self.root.update_idletasks()
            self.root.update()

    def test_register_marks_card_realized(self):
        body, _ = self._add_card()
        states = [c for c in self.virt.cards if c["frame"] is body]
        self.assertEqual(len(states), 1)
        self.assertTrue(states[0]["realized"])

    def test_card_outside_viewport_gets_derealized(self):
        cards = [self._add_card(height_px=80) for _ in range(20)]
        # Force the visibility check synchronously so we don't depend
        # on after-timer scheduling. Zero out the scroll-idle timestamp
        # too — when the suite runs with other Tk tests before this,
        # the cumulative canvas <Configure>/scroll events leave
        # _last_scroll_ts within the 150ms idle window, which would
        # make _update_visibility defer instead of executing.
        self.root.update_idletasks()
        self.root.update()
        self.virt._last_scroll_ts = 0.0
        self.virt._update_visibility()
        last_body, _ = cards[-1]
        last_state = next(c for c in self.virt.cards
                          if c["frame"] is last_body)
        self.assertFalse(last_state["realized"])
        self.assertEqual(len(last_body.winfo_children()), 0)
        self.assertGreater(last_state["cached_height"] or 0, 0)

    def test_clear_drops_registry(self):
        for _ in range(5):
            self._add_card()
        self.assertEqual(len(self.virt.cards), 5)
        self.virt.clear()
        self.assertEqual(len(self.virt.cards), 0)

    def test_destroyed_frame_is_skipped(self):
        body, _ = self._add_card()
        body.destroy()
        self.virt._update_visibility()  # must not raise


if __name__ == "__main__":
    unittest.main()
