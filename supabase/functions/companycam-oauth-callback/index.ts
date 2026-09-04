import {
  callbackUrl, companyCamApp, encryptSecret, serviceHeaders, verifyState,
} from "../_shared/companycam-oauth.ts";

function page(title: string, detail: string, ok: boolean, status = 200): Response {
  const safeTitle = title.replaceAll("&", "&amp;").replaceAll("<", "&lt;");
  const safeDetail = detail.replaceAll("&", "&amp;").replaceAll("<", "&lt;");
  return new Response(`<!doctype html><meta charset="utf-8"><title>${safeTitle}</title>
  <style>body{margin:0;background:#101410;color:#eef4ef;font:15px/1.5 system-ui;display:grid;place-items:center;min-height:100vh}.card{width:min(420px,calc(100vw - 48px));padding:28px;border:1px solid #34433a;border-radius:12px;background:#182019;box-shadow:0 18px 50px #0007}.mark{font-size:32px;color:${ok ? "#50bf7c" : "#ee7a68"}}h1{font-size:20px;margin:8px 0}p{color:#abb9af;margin:0}</style>
  <main class="card"><div class="mark">${ok ? "✓" : "×"}</div><h1>${safeTitle}</h1><p>${safeDetail}</p></main>`, {
    status, headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}

Deno.serve(async (request: Request) => {
  if (request.method !== "GET") return page("Connection failed", "Use the Connect button in Linguar Hub.", false, 405);
  try {
    const url = new URL(request.url);
    if (url.searchParams.get("error")) return page("CompanyCam was not connected", "No changes were made. You can close this tab and try again.", false, 400);
    const code = url.searchParams.get("code") || "";
    const state = await verifyState(url.searchParams.get("state") || "");
    if (!code) return page("Connection failed", "CompanyCam did not return an authorization code.", false, 400);
    const app = companyCamApp(state.department);
    if (!app.clientId || !app.clientSecret) throw new Error(`CompanyCam is not configured for ${state.department}.`);
    const tokenResponse = await fetch("https://app.companycam.com/oauth/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
      body: new URLSearchParams({
        client_id: app.clientId, client_secret: app.clientSecret, code,
        grant_type: "authorization_code", redirect_uri: callbackUrl(),
      }),
    });
    const token = await tokenResponse.json();
    if (!tokenResponse.ok || !token?.access_token) throw new Error("CompanyCam did not accept the connection.");
    const access = await encryptSecret(String(token.access_token));
    const refresh = await encryptSecret(String(token.refresh_token || ""));
    const now = new Date();
    const expiresAt = token.expires_in
      ? new Date(now.getTime() + Number(token.expires_in) * 1000).toISOString() : null;
    const base = Deno.env.get("SUPABASE_URL") || "";
    const credentialResponse = await fetch(`${base}/rest/v1/external_oauth_credentials?on_conflict=user_id,provider,department`, {
      method: "POST",
      headers: serviceHeaders({ Prefer: "resolution=merge-duplicates" }),
      body: JSON.stringify({
        user_id: state.user_id, provider: "companycam", department: state.department,
        access_token_cipher: access.cipher, access_token_iv: access.iv,
        refresh_token_cipher: refresh.cipher, refresh_token_iv: refresh.iv,
        expires_at: expiresAt, scopes: ["read", "write"], updated_at: now.toISOString(),
      }),
    });
    if (!credentialResponse.ok) throw new Error("The secure connection could not be saved.");
    const statusResponse = await fetch(`${base}/rest/v1/external_connection_status?on_conflict=user_id,provider,department`, {
      method: "POST",
      headers: serviceHeaders({ Prefer: "resolution=merge-duplicates" }),
      body: JSON.stringify({
        user_id: state.user_id, provider: "companycam", department: state.department,
        status: "connected", scopes: ["read", "write"], connected_at: now.toISOString(),
        updated_at: now.toISOString(),
      }),
    });
    if (!statusResponse.ok) throw new Error("The connection status could not be saved.");
    return page("CompanyCam connected", `${state.department} is ready. Close this tab and return to Linguar Hub.`, true);
  } catch (error) {
    return page("Connection failed", error instanceof Error ? error.message : "Try again from Linguar Hub.", false, 400);
  }
});
