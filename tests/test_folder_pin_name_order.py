"""Folder-pin lookup must reconcile name ORDER, not just case/spacing.

Regression: Linda Valek (2026-06-12). The OD folder pin was stored under
"linda valek" / "valek, linda", but the IUQ card / OD folder name was
"Valek Linda" (Last First, no comma). `get_folder_path` only matched on
`_canon_pin_key`, which normalizes case/whitespace/" - Carrier" but NOT
order — so WC/SP import said "no OD folder" even though the OD opened fine
(open-OD has a row-path hint that import lacks). `_pin_lookup_keys` now
tries name-order variants so every call site that reads the pin agrees.
"""
import pytest

import persistence


@pytest.fixture(autouse=True)
def _isolate_persistence(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(persistence, "_STATE_PATH", str(state_path))
    monkeypatch.setattr(persistence, "_CACHE", None, raising=False)
    monkeypatch.setattr(persistence, "_CACHE_MTIME", None, raising=False)
    yield


PATH = r"X:\IE_Public\2026 Jobs\Valek Linda"


def test_pin_set_first_last_resolves_last_first_no_comma():
    # Pinned from a card title "Linda Valek"; looked up as the bare OD
    # folder name "Valek Linda" (the failing import case).
    persistence.set_folder_path("Linda Valek", PATH)
    assert persistence.get_folder_path("Valek Linda") == PATH
    assert persistence.get_folder_path("VALEK LINDA") == PATH


def test_pin_set_last_first_comma_resolves_first_last():
    persistence.set_folder_path("Valek, Linda", PATH)
    assert persistence.get_folder_path("Linda Valek") == PATH
    assert persistence.get_folder_path("Valek Linda") == PATH


def test_pin_set_no_comma_resolves_comma_form():
    persistence.set_folder_path("Valek Linda", PATH)
    assert persistence.get_folder_path("Valek, Linda") == PATH
    assert persistence.get_folder_path("Linda Valek") == PATH


def test_carrier_suffix_still_stripped_with_order_swap():
    persistence.set_folder_path("Linda Valek", PATH)
    assert persistence.get_folder_path("Valek Linda - State Farm") == PATH


def test_unknown_client_still_returns_none():
    persistence.set_folder_path("Linda Valek", PATH)
    assert persistence.get_folder_path("Somebody Else") is None


def test_three_token_name_not_falsely_reordered():
    # A 3-token no-comma name must NOT blindly reverse to a different
    # person; only the comma form drives the 2-part swap.
    persistence.set_folder_path("Mary Jane Smith", PATH)
    assert persistence.get_folder_path("Mary Jane Smith") == PATH
    # "Smith, Mary Jane" (comma form) should still find it.
    assert persistence.get_folder_path("Smith, Mary Jane") == PATH
    # An unrelated reorder should not.
    assert persistence.get_folder_path("Smith Jane Mary") is None
