"""Preview the saved office document without rebuilding its legacy layout."""
from pathlib import Path


def preview_document(path):
    source = Path(path or '')
    if not source.is_file():
        return {'ok': False, 'error': 'No saved document was found for this day.'}
    if source.suffix.lower() != '.docx':
        return {'ok': False, 'error': 'Print preview requires a Word Run document. Open this file in its original application to print it.'}
    word = document = None
    initialized = False
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        initialized = True
        # Separate instance: never change or close another document the user edits.
        word = win32com.client.DispatchEx('Word.Application')
        word.AutomationSecurity = 3  # Do not execute document macros.
        document = word.Documents.Open(str(source.resolve()), ReadOnly=True,
                                       AddToRecentFiles=False)
        word.Visible = True
        document.Activate()
        document.PrintPreview()
        return {'ok': True}
    except Exception:
        if document is not None:
            try:
                document.Close(SaveChanges=0)
            except Exception:
                pass
        if word is not None:
            try:
                word.Quit(SaveChanges=0)
            except Exception:
                pass
        return {'ok': False, 'error': 'Word print preview could not open. Check that Microsoft Word is installed, or use Open in Word and choose File → Print.'}
    finally:
        if initialized:
            pythoncom.CoUninitialize()
