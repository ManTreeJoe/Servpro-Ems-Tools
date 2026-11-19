"""Explicit --tool emergency_admin entry, separate from employee sign-in."""
from __future__ import annotations


def authenticate(email, password, client=None):
    if client is None:
        import supabase_client as client
    payload = client._raw('POST', '/auth/v1/token', params={'grant_type': 'password'},
                          body={'email': email.strip(), 'password': password}, _max_retries=0)
    token = payload.get('access_token')
    if not token:
        raise PermissionError('Recovery sign-in was not accepted.')
    try:
        access = client._raw('POST', '/rest/v1/rpc/my_app_access', body={}, token=token)
        if not (access.get('auth_mode') == 'emergency' and access.get('is_admin')
                and access.get('access_state') == 'approved'):
            raise PermissionError('This account is not the recovery administrator.')
        with client._LOCK, client._cross_process_session_lock():
            client._store_session(payload)
    except Exception:
        try:
            client._raw('POST', '/auth/v1/logout', params={'scope': 'local'}, token=token)
        except Exception:
            pass
        raise


def main(on_authenticated=None):
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.title('OneLoss — administrator recovery')
    frame = ttk.Frame(root, padding=28)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Administrator recovery', font=('Segoe UI', 17)).pack(anchor='w')
    ttk.Label(frame, text='Restricted to the existing recovery administrator.').pack(anchor='w', pady=12)
    ttk.Label(frame, text='Work email').pack(anchor='w')
    email = ttk.Entry(frame, width=45); email.pack(fill='x')
    ttk.Label(frame, text='Password').pack(anchor='w', pady=(12,0))
    password = ttk.Entry(frame, show='•'); password.pack(fill='x')
    message = tk.StringVar(); ttk.Label(frame, textvariable=message, wraplength=380).pack(pady=12)
    accepted = False
    def submit():
        nonlocal accepted
        try:
            authenticate(email.get(), password.get())
            accepted = True; root.destroy()
        except Exception:
            message.set('Recovery sign-in failed. Check the recovery account and server connection.')
            password.delete(0, 'end')
    ttk.Button(frame, text='Sign in to recovery', command=submit).pack(fill='x')
    root.mainloop()
    if accepted:
        import employee_access
        employee_access.enter_recovery()
        if on_authenticated is not None:
            on_authenticated()
        else:
            import home_web
            home_web.main(argv=[])


if __name__ == '__main__':
    main()
