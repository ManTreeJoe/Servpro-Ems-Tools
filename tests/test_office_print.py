from types import SimpleNamespace
from unittest.mock import Mock
import sys

import office_print


def install_word(monkeypatch, fail=False):
    doc = Mock()
    if fail:
        doc.PrintPreview.side_effect = RuntimeError('Word unavailable')
    word = Mock()
    word.Documents.Open.return_value = doc
    com = Mock()
    client = SimpleNamespace(DispatchEx=Mock(return_value=word))
    monkeypatch.setitem(sys.modules, 'pythoncom', com)
    monkeypatch.setitem(sys.modules, 'win32com', SimpleNamespace(client=client))
    monkeypatch.setitem(sys.modules, 'win32com.client', client)
    return word, doc, com


def test_preview_retains_saved_file_and_does_not_print(monkeypatch, tmp_path):
    source = tmp_path / 'Daily Run.docx'
    source.write_bytes(b'existing document layout')
    word, doc, com = install_word(monkeypatch)
    assert office_print.preview_document(str(source)) == {'ok': True}
    word.Documents.Open.assert_called_once_with(str(source.resolve()), ReadOnly=True, AddToRecentFiles=False)
    assert word.AutomationSecurity == 3
    doc.PrintPreview.assert_called_once()
    doc.PrintOut.assert_not_called()
    doc.Save.assert_not_called()
    word.Quit.assert_not_called()
    com.CoUninitialize.assert_called_once()
    assert source.read_bytes() == b'existing document layout'


def test_preview_failure_closes_only_its_instance(monkeypatch, tmp_path):
    source = tmp_path / 'APA.docx'
    source.touch()
    word, doc, com = install_word(monkeypatch, fail=True)
    assert not office_print.preview_document(str(source))['ok']
    doc.Close.assert_called_once_with(SaveChanges=0)
    word.Quit.assert_called_once_with(SaveChanges=0)
    com.CoUninitialize.assert_called_once()


def test_missing_and_outlook_sources_do_not_launch_word(monkeypatch, tmp_path):
    word, doc, com = install_word(monkeypatch)
    assert not office_print.preview_document(None)['ok']
    source = tmp_path / 'Run.msg'
    source.touch()
    assert not office_print.preview_document(str(source))['ok']
    word.Documents.Open.assert_not_called()
    com.CoInitialize.assert_not_called()


def test_schedule_prints_selected_day(monkeypatch):
    import run_doc_editor_web as run
    finder = Mock(return_value='selected.docx')
    preview = Mock(return_value={'ok': True})
    monkeypatch.setattr(run.run_doc, '_find_run_doc_for_date', finder)
    monkeypatch.setattr(office_print, 'preview_document', preview)
    api = run.Api()
    assert api.print_preview(-7)['ok']
    finder.assert_called_once_with(api._day(-7))
    preview.assert_called_once_with('selected.docx')
