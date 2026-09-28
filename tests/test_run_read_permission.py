from unittest.mock import patch
import pytest
import run_doc_editor as editor
from run_doc_editor_web import Api


def test_locked_document_preserves_permission_error():
    with patch('run_doc_editor.open_read', side_effect=PermissionError('locked')):
        with pytest.raises(PermissionError):
            editor.read_document('locked.docx')


def test_schedule_distinguishes_locked_from_missing(monkeypatch):
    import run_doc
    monkeypatch.setattr(run_doc, '_find_run_doc_for_date', lambda day: 'locked.docx')
    monkeypatch.setattr(editor, 'read_document', lambda path: (_ for _ in ()).throw(PermissionError('locked')))
    result = Api().load_day()
    assert result['ok'] is False
    assert result['exists'] is True
    assert result['locked'] is True
    assert 'Word' in result['error']
