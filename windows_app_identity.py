"""Shared taskbar/toast identity; repair only our dedicated Start-menu shortcut."""
import subprocess
import sys
from pathlib import Path


def app_id(channel):
    if channel not in ('Main', 'Trial', 'Dev'):
        raise ValueError('Unknown app channel')
    return f'Servpro.LinguarHub.{channel}.2026.2'


def register_notifications(channel):
    import pythoncom
    import winreg
    from win32com.shell import shell, shellcon
    from win32com.propsys import propsys, pscon
    import paths

    identity = app_id(channel)
    name = 'OneLoss' + (f' — {channel.upper()}' if channel != 'Main' else '')
    root = Path(__file__).resolve().parent
    target = sys.executable
    arguments = ''
    if not getattr(sys, 'frozen', False):
        arguments = subprocess.list2cmdline([str(root / 'tools' / 'launch_notification_shell.py'), channel])
    pythoncom.CoInitialize()
    try:
        programs = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_PROGRAMS, None, 0))
        shortcut = programs / f'OneLoss {channel}.lnk'
        link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None,
                                         pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
        link.SetPath(target)
        link.SetArguments(arguments)
        link.SetWorkingDirectory(str(root))
        link.SetDescription(name)
        link.SetIconLocation(paths.resource('linguar_hub.ico'), 0)
        properties = link.QueryInterface(propsys.IID_IPropertyStore)
        properties.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(identity))
        properties.Commit()
        link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(shortcut), 1)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                             'Software\\Classes\\AppUserModelId\\' + identity) as key:
            winreg.SetValueEx(key, 'DisplayName', 0, winreg.REG_SZ, name)
            winreg.SetValueEx(key, 'IconUri', 0, winreg.REG_SZ, paths.resource('linguar_hub.ico'))
    finally:
        pythoncom.CoUninitialize()
    return identity
