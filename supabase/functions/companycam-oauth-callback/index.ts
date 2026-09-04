import {
  callbackUrl, companyCamApp, encryptSecret, serviceHeaders, verifyState,
} from "../_shared/companycam-oauth.ts";

function page(title: string, detail: string, ok: boolean, status = 200): Response {
  const xml = (value: string) => value.replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&apos;");
  const words = detail.trim().split(/\s+/);
  const lines: string[] = [];
  for (const word of words) {
    const last = lines.length - 1;
    if (last >= 0 && `${lines[last]} ${word}`.length <= 64) lines[last] += ` ${word}`;
    else lines.push(word);
  }
  const detailLines = lines.slice(0, 3).map((line, index) =>
    `<text x="480" y="${338 + index * 28}" class="detail">${xml(line)}</text>`
  ).join("");
  const mark = ok
    ? '<path d="M430 232l30 30 68-76" class="mark"/>'
    : '<path d="M445 195l70 70m0-70l-70 70" class="mark"/>';
  return new Response(`<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 540" role="img" aria-labelledby="title detail" preserveAspectRatio="xMidYMid slice">
  <title id="title">${xml(title)}</title>
  <desc id="detail">${xml(detail)}</desc>
  <style>
    .heading{fill:#eef4ef;font:700 30px system-ui,-apple-system,"Segoe UI",sans-serif;text-anchor:middle}
    .detail{fill:#abb9af;font:20px system-ui,-apple-system,"Segoe UI",sans-serif;text-anchor:middle}
    .mark{fill:none;stroke:${ok ? "#50bf7c" : "#ee7a68"};stroke-width:15;stroke-linecap:round;stroke-linejoin:round}
  </style>
  <rect width="960" height="540" fill="#101410"/>
  <rect x="120" y="105" width="720" height="330" rx="24" fill="#182019" stroke="#34433a" stroke-width="2"/>
  <circle cx="480" cy="225" r="66" fill="#101410" stroke="${ok ? "#50bf7c" : "#ee7a68"}" stroke-width="3"/>
  ${mark}
  <text x="480" y="310" class="heading">${xml(title)}</text>
  ${detailLines}
</svg>`, {
    status,
    headers: {
      "Content-Type": "image/svg+xml; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
      "Cache-Control": "no-store",
    },
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
