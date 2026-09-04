import {
  CORS, appAccess, callbackUrl, companyCamApp, createState, json,
  publishableKey, signedInUser,
} from "../_shared/companycam-oauth.ts";

Deno.serve(async (request: Request) => {
  if (request.method === "OPTIONS") return new Response(null, { headers: CORS });
  if (request.method !== "POST") return json({ error: "method not allowed" }, 405);
  try {
    const auth = request.headers.get("Authorization") || "";
    const apiKey = publishableKey();
    if (!auth.startsWith("Bearer ") || !apiKey) return json({ error: "Sign in to Linguar Hub first." }, 401);
    const [user, access, input] = await Promise.all([
      signedInUser(auth, apiKey), appAccess(auth, apiKey), request.json(),
    ]);
    const department = String(input.department || "").trim().toUpperCase();
    if (!/^[A-Z0-9_-]{1,20}$/.test(department)) return json({ error: "Choose a valid franchise." }, 400);
    const memberships = Array.isArray(access?.departments)
      ? access.departments.map((value: unknown) => String(value).toUpperCase()) : [];
    if (!access?.is_admin && !memberships.includes(department)) {
      return json({ error: `You do not have access to ${department}.` }, 403);
    }
    const app = companyCamApp(department);
    if (!app.clientId || !app.clientSecret) return json({ error: `CompanyCam sign-in is not configured for ${department}.` }, 503);
    const params = new URLSearchParams({
      client_id: app.clientId,
      redirect_uri: callbackUrl(),
      response_type: "code",
      scope: "read write",
      state: await createState(String(user.id), department),
    });
    return json({ ok: true, url: `https://app.companycam.com/oauth/authorize?${params}` });
  } catch (error) {
    return json({ error: error instanceof Error ? error.message : "CompanyCam sign-in could not start." }, 500);
  }
});
