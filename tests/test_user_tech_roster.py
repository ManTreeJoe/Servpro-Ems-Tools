"""User-added tech roster — persistence + live regex rebuild.

Adding a tech via the UI must:
  1. Save to persistence so it survives restart
  2. Live-update audit_logic.TECH_PATTERN so every consumer (snapshot,
     run audit, job notes) recognizes the new name without restart

Pinning both halves here so future refactors of the regex builder don't
silently lose user names."""
import audit_logic
import persistence


def _matches(text):
    return [m.group(0) for m in audit_logic.TECH_PATTERN.finditer(text)]


def _isolate(monkeypatch):
    """Replace the persistence cache with a clean dict so this test
    can't see / write the user's real state.json."""
    monkeypatch.setattr(persistence, "_CACHE", {}, raising=False)
    monkeypatch.setattr(persistence, "_CACHE_MTIME", None, raising=False)
    # Stub the disk-write path too — _save would clobber the real file.
    monkeypatch.setattr(persistence, "_save",
                         lambda state: persistence.__dict__.update(
                             _CACHE=state, _CACHE_MTIME=None))
    monkeypatch.setattr(persistence, "_load",
                         lambda: persistence._CACHE)


def test_get_user_techs_default_shape(monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.setattr(persistence, "_CACHE", {}, raising=False)
    out = persistence.get_user_techs()
    assert out == {"names": [], "abbrev": {}}


def test_set_user_techs_round_trip(monkeypatch):
    _isolate(monkeypatch)
    persistence.set_user_techs(["Carlos", "Mark T"], {"CL": "Carlos"})
    out = persistence.get_user_techs()
    assert out["names"] == ["Carlos", "Mark T"]
    assert out["abbrev"] == {"CL": "Carlos"}


def test_set_user_techs_strips_blanks(monkeypatch):
    _isolate(monkeypatch)
    persistence.set_user_techs(["  Carlos  ", "", None],
                                {"  CL  ": "  Carlos  "})
    out = persistence.get_user_techs()
    assert out["names"] == ["Carlos"]
    assert out["abbrev"] == {"CL": "Carlos"}


def test_rebuild_tech_pattern_picks_up_user_added_name(monkeypatch):
    _isolate(monkeypatch)
    # Baseline: Carlos isn't in the hardcoded list.
    audit_logic.rebuild_tech_pattern()
    assert "Carlos" not in _matches("Demo - Carlos/Pablo")

    # Add Carlos via the UI flow.
    persistence.set_user_techs(["Carlos"], {})
    audit_logic.rebuild_tech_pattern()
    try:
        assert "Carlos" in _matches("Demo - Carlos/Pablo")
        # Hardcoded names still match — adding doesn't replace.
        assert "Pablo" in _matches("Demo - Carlos/Pablo")
    finally:
        # Reset so other tests aren't affected.
        persistence.set_user_techs([], {})
        audit_logic.rebuild_tech_pattern()


def test_rebuild_tech_pattern_handles_multi_token_name(monkeypatch):
    """User adds 'Mark T' — regex must match 'Mark T' AND 'Mark  T'
    (extra space between tokens) so dispatch typos still get caught."""
    _isolate(monkeypatch)
    persistence.set_user_techs(["Mark T"], {})
    audit_logic.rebuild_tech_pattern()
    try:
        assert "Mark T" in _matches("Demo - Mark T")
        # Tolerate double space — the builder uses \s* between tokens.
        assert _matches("Demo - Mark  T") != []
    finally:
        persistence.set_user_techs([], {})
        audit_logic.rebuild_tech_pattern()


def test_user_abbrev_merges_with_hardcoded(monkeypatch):
    _isolate(monkeypatch)
    persistence.set_user_techs(["Carlos"], {"CL": "Carlos"})
    audit_logic.rebuild_tech_pattern()
    try:
        # User abbrev present
        assert audit_logic.ABBREV.get("CL") == "Carlos"
        # Hardcoded abbrev preserved
        assert audit_logic.ABBREV.get("FB") == "Fernando"
    finally:
        persistence.set_user_techs([], {})
        audit_logic.rebuild_tech_pattern()


def test_persistence_failure_falls_back_to_hardcoded(monkeypatch):
    """If persistence raises (e.g. corrupt state.json), the regex must
    still build from the hardcoded list — the tools shouldn't crash on
    a bad config file."""
    def _explode():
        raise RuntimeError("simulated state.json corruption")
    monkeypatch.setattr(persistence, "get_user_techs", _explode)
    pat = audit_logic._build_tech_pattern()
    # Hardcoded names should still match.
    assert pat.search("Demo - Cesar/Nestor")
