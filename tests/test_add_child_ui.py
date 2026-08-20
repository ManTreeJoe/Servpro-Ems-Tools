"""The Add Claim/Unit dialog — adopt-first, and honest about partials.

The dialog exists so the office ADOPTS the folder/card/project that
already exist instead of making a second one. Work starts in Trello here,
so a provision-everything flow would create a duplicate card at the front
door — the identity problem this whole effort has been unwinding.
"""
import io
import os

import pytest

import audit_web
import snapshot_web

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def js():
    return io.open(os.path.join(ROOT, "web_shared", "audit_detail.js"),
                   encoding="utf-8").read()


def test_the_button_exists(js):
    assert 'data-action="add-child"' in js
    assert "openAddChildModal" in js


def test_it_previews_before_it_writes(js):
    """plan_child is read-only; showing what exists is the entire point."""
    body = js[js.index("async function openAddChildModal"):]
    body = body[:body.index("\n  // ")]
    assert "plan_child" in body
    assert "add_child" in body
    assert body.index("plan_child") < body.index("add_child")


def test_the_preview_is_debounced(js):
    """It hits Trello. Firing per keystroke would spend the rate limit on
    a half-typed unit number."""
    body = js[js.index("async function openAddChildModal"):]
    body = body[:body.index("\n  // ")]
    assert "setTimeout" in body and "clearTimeout" in body


def test_an_existing_child_is_called_out(js):
    """Adding one that exists is an UPDATE. Silently creating a second
    row is how a client ends up with two of the same unit."""
    body = js[js.index("async function openAddChildModal"):]
    body = body[:body.index("\n  // ")]
    assert "existing_child" in body


def test_every_step_is_reported(js):
    """A folder that succeeded while CompanyCam failed must say so —
    reporting success because something worked is the half-provisioned
    lie."""
    body = js[js.index("async function openAddChildModal"):]
    body = body[:body.index("\n  // ")]
    assert "res.steps" in body or "steps" in body
    assert "s.ok" in body


def test_a_project_is_only_created_when_ticked(js):
    """Never create a CompanyCam project behind the user's back."""
    body = js[js.index("async function openAddChildModal"):]
    body = body[:body.index("\n  // ")]
    assert "ac-mkproj" in body


def test_the_row_refreshes_after_a_success(js):
    """The detail pane reads children from the row, so without this the
    new child is invisible until a manual refresh — the same writeback
    trap as the re-audit sites."""
    body = js[js.index("async function openAddChildModal"):]
    body = body[:body.index("\n  // ")]
    assert "reauditAndRerender" in body


# ── the API both panels need ───────────────────────────────────────────

@pytest.mark.parametrize("method", ["plan_child", "add_child"])
def test_both_panels_expose_it(method):
    """Snapshot renders the same shared card, so every call that card
    makes has to exist there too."""
    assert hasattr(audit_web.Api, method)
    assert hasattr(snapshot_web.Api, method)


def test_plan_child_writes_nothing():
    import inspect
    src = inspect.getsource(audit_web.Api.plan_child)
    assert "apply_child" not in src
    assert "cp.plan_child" in src


def test_add_child_reaudits_the_parent():
    import inspect
    src = inspect.getsource(audit_web.Api.add_child)
    assert "reaudit_one" in src
