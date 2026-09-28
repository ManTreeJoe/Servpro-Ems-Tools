import initial_note_templates


def test_builtin_templates_keep_initial_note_usable_before_optional_schema(monkeypatch):
    import supabase_client

    def missing(*_args, **_kwargs):
        raise RuntimeError("PGRST205 job_note_templates missing from schema cache")

    monkeypatch.setattr(supabase_client, "rest", missing)
    rows = initial_note_templates.list_templates("IE", "EMS")

    assert [row["name"] for row in rows] == [
        "Initial inspection update",
        "Post-inspection customer / adjuster update",
    ]
    assert all("{date}" in row["body"] for row in rows)


def test_initial_note_ui_posts_db_first_and_keeps_legacy_copy_action():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] /
          "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")

    assert "async function openInitialNoteModal" in js
    assert "pywebview.api.initial_note_templates(division)" in js
    assert "pywebview.api.post_job_comment(client, cardId, text)" in js
    assert "saved in OneLoss first" in js
    assert "data-import-existing-initial-notes" in js
    assert "pywebview.api.import_initial_notes" in js


def test_job_log_accepts_a_named_custom_activity():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] /
          "pipeline_web_assets" / "app.js").read_text(encoding="utf-8")

    assert 'value="__custom__"' in js
    assert "data-log-custom-row" in js
    assert 'if (payload.work_type === "__custom__")' in js
