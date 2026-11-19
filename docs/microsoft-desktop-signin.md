# Microsoft sign-in in the Windows app

The Settings sign-in dialog offers Microsoft first, then email/password and the existing emailed-code option. Microsoft opens the system browser and does not require either local input field. No Microsoft client secret is shipped in the app.

## Server prerequisites

Enable the Azure provider on the intended Supabase Auth service, restricted to the organization's Microsoft tenant. Configure the optional `email` and `xms_edov` token claims for verified email identity. Keep the existing email/password provider available.

Microsoft's registered **Web** callback remains the public Supabase callback, currently `https://api.oneloss.work/auth/v1/callback` for production Main.

Separately, append this **exact** address to that Auth service's `GOTRUE_URI_ALLOW_LIST`, preserving every existing entry:

```text
http://127.0.0.1:43821/auth/microsoft/callback
```

This address returns the browser to the desktop app after the public Auth service has handled Microsoft authentication. It is not a replacement for Microsoft's registered HTTPS callback. Back up the correct Compose configuration and recreate only its Auth service; do not target a demo or legacy stack by hostname assumption.

These prerequisites were applied and verified on production Main during setup on 2026-11-19. Demo was not modified. This PR does not contain credentials or automatically apply server configuration.

## Desktop behavior

- Uses a fresh PKCE verifier/challenge for each attempt. The verifier stays in memory; the callback contains an authorization code rather than session tokens.
- Binds only `127.0.0.1`, on the fixed port above; validates the callback path and Host header. An occupied port fails with a retry message. The listener closes on completion, cancellation or timeout.
- Suppresses callback request logging and sends a no-store response. Callback authorization codes and returned tokens are not returned through the UI bridge.
- Reads `/auth/v1/user` using the new token and requires a confirmed email and Azure identity before storing the normal OneLoss session. An optional explicit expected email is supported by the Python helper; the UI leaves account selection to Microsoft.
- Preserves the prior local session on a failed/cancelled attempt and revokes only a rejected newly obtained session. Closing the dialog cancels the pending attempt. Concurrent Microsoft attempts are rejected.
- Uses the existing shared-backend selection, cache invalidation and session refresh/storage flow. It does not create or assign job permissions, franchise memberships or administrator roles.
- Provider registration and existing-account linking follow Supabase Auth's configured policies. The desktop helper does not itself prohibit a new tenant user from being created; database access still requires the normal server permissions.

## Validation

```text
python -m pytest tests/test_microsoft_auth.py tests/test_supabase_password_login.py -q
node tests/microsoft_signin.cjs
```

Tests cover PKCE, verified identity storage, optional email, mismatched-account rejection, cancellation/retry, timeout, browser failure, backend changes, concealed transport errors, loopback Host/path/code validation, the settings bridge and password fallback. Browser tests cover clicking Microsoft with both fields empty, busy controls, cancellation, retry and successful UI refresh.

An isolated Windows source candidate based on release 1.8.48 was tested against production on 2026-11-19. Microsoft returned the same existing Nathan account ID; the server's `my_app_access` response confirmed administrator access; authenticated job reads returned 2,353 jobs, and clients/links requests succeeded. Normal profile configuration/session file fingerprints remained unchanged. The no-email account-picker flow was also tested by the user. These checks establish identity, server-admin status and readable jobs, not every administrator mutation or every job action.

The subsequent dialog layout uses provider-first examples from [Coda](https://mobbin.com/screens/7dcf63ee-7054-4e54-bf22-b7da802e6d01) and [SavvyCal](https://mobbin.com/screens/ee7e9235-02ba-42b9-9e28-4b7893cb357f), with OneLoss theme tokens and existing login methods retained. Layout was checked at normal and narrow window sizes. No installer/update feed has been published for this feature; packaging must include `microsoft_auth.py` and the updated Settings assets, followed by a packaged-app sign-in check before rollout.
