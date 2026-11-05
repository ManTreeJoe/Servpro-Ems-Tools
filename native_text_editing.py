"""Enable native editing/spelling menus without enabling developer tools."""
import logging
import json

SAVED_REPLIES = (
    ('CIF and CER sent', 'CIF and CER sent to the customer.'),
    ('Waiting on adjuster', 'Waiting on a response from the adjuster.'),
    ('Documents requested', 'Requested the outstanding documents from the customer.'),
    ('Follow-up needed', 'Follow-up needed: '),
)


def editing_script(command, text=''):
    if command not in ('undo', 'redo', 'insertText', 'cut', 'copy', 'selectAll'):
        raise ValueError('Unsupported editing command')
    # The shell embeds tools in same-origin frames. Operate only on the
    # currently focused editable field; never search for another text box.
    return """(() => {
      let d = document, e = d.activeElement;
      while (e && (e.tagName === 'IFRAME' || e.tagName === 'FRAME')) {
        try { d = e.contentDocument; e = d.activeElement; } catch (_) { return false; }
      }
      if (!e || e.disabled || e.readOnly || e.type === 'password') return false;
      if (!(e.isContentEditable || e.tagName === 'TEXTAREA' ||
            (e.tagName === 'INPUT' && ['text','search','email','url','tel'].includes(e.type)))) return false;
      return d.execCommand(%s, false, %s);
    })()""" % (json.dumps(command), json.dumps(text))


def populate_menu(core, args, kinds):
    items = args.MenuItems
    # Remove empty submenus recursively, but preserve spelling suggestions.
    def prune(collection):
        for index in range(collection.Count - 1, -1, -1):
            item = collection[index]
            if item.Kind == kinds.Submenu:
                prune(item.Children)
                if item.Children.Count == 0:
                    collection.RemoveAt(index)
    prune(items)
    if not args.ContextMenuTarget.IsEditable:
        return

    def command(label, action, text=''):
        item = core.Environment.CreateContextMenuItem(label, None, kinds.Command)
        def selected(sender, event):
            if action == 'paste':
                # Native menu callbacks run on the UI thread. Reading here
                # preserves clipboard support without browser paste privileges.
                from System.Windows.Forms import Clipboard
                if Clipboard.ContainsText():
                    core.ExecuteScriptAsync(editing_script('insertText', str(Clipboard.GetText())))
            else:
                core.ExecuteScriptAsync(editing_script(action, text))
        item.CustomItemSelected += selected
        return item

    names = {str(items[i].Name).lower() for i in range(items.Count)}
    for name, label in (('cut', 'Cut'), ('copy', 'Copy'), ('paste', 'Paste'),
                        ('selectAll', 'Select all')):
        if name.lower() not in names:
            items.Add(command(label, name))
    for name, label in (('undo', 'Undo'), ('redo', 'Redo')):
        if name not in names:
            items.Add(command(label, name))
    replies = core.Environment.CreateContextMenuItem('Saved replies', None, kinds.Submenu)
    for label, text in SAVED_REPLIES:
        replies.Children.Add(command(label, 'insertText', text))
    items.Add(replies)


def enable(window):
    try:
        from System import Action
        native = window.native

        def configure():
            try:
                core = native.webview.CoreWebView2
                core.Settings.AreDefaultContextMenusEnabled = True
                # A navigation clears window globals. Seed every future document
                # before page scripts can replace the native spelling menu.
                if not getattr(window, '_editing_marker_installed', False):
                    core.AddScriptToExecuteOnDocumentCreatedAsync("window.__oneLossNativeEditingMenu = true;")
                    window._editing_marker_installed = True
                core.ExecuteScriptAsync("window.__oneLossNativeEditingMenu = true;")
                if getattr(window, '_editing_menu_installed', False):
                    return
                from Microsoft.Web.WebView2.Core import CoreWebView2ContextMenuItemKind
                def requested(sender, args):
                    try:
                        populate_menu(core, args, CoreWebView2ContextMenuItemKind)
                    except Exception:
                        logging.getLogger(__name__).exception('Editing menu customization unavailable')
                core.ContextMenuRequested += requested
                window._editing_menu_handler = requested
                window._editing_menu_installed = True
            except Exception:
                logging.getLogger(__name__).exception('Native editing menus unavailable')

        native.Invoke(Action(configure))
    except Exception:
        logging.getLogger(__name__).exception('Could not enable native editing menus')
