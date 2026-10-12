def test_main_opens_approved_schedule_without_dev_flag(monkeypatch):
    import home_web
    monkeypatch.delenv('LINGUAR_DEV_MODE', raising=False)
    assert home_web._asset_folder_for('run_doc_editor') == '../run_doc_editor_web_assets/calendar_preview.html?live=1'
