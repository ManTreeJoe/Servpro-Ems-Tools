const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, "Content-Type": "application/json" },
  });
}

function publishableKey(): string {
  const legacy = Deno.env.get("SUPABASE_ANON_KEY") || "";
  if (legacy) return legacy;
  try {
    const keys = JSON.parse(Deno.env.get("SUPABASE_PUBLISHABLE_KEYS") || "{}");
    return String(keys.default || Object.values(keys)[0] || "");
  } catch {
    return "";
  }
}

async function signedInUser(auth: string, apiKey: string) {
  const base = Deno.env.get("SUPABASE_URL") || "";
  const response = await fetch(`${base}/auth/v1/user`, {
    headers: { Authorization: auth, apikey: apiKey },
  });
  if (!response.ok) throw new Error("invalid Linguar Hub session");
  return await response.json();
}

async function appAccess(auth: string, apiKey: string) {
  const base = Deno.env.get("SUPABASE_URL") || "";
  const response = await fetch(`${base}/rest/v1/rpc/my_app_access`, {
    method: "POST",
    headers: {
      Authorization: auth,
      apikey: apiKey,
      "Content-Type": "application/json",
    },
    body: "{}",
  });
  if (!response.ok) throw new Error("franchise access could not be verified");
  return await response.json();
}

function allowedPath(path: string): boolean {
  return /^\/projects(?:\/[A-Za-z0-9_-]+(?:\/photos)?)?$/.test(path) ||
    /^\/photos\/[A-Za-z0-9_-]+\/tags$/.test(path);
}

Deno.serve(async (request: Request) => {
  if (request.method === "OPTIONS") return new Response(null, { headers: CORS });
  if (request.method !== "POST") return json({ error: "method not allowed" }, 405);

  try {
    const auth = request.headers.get("Authorization") || "";
    const apiKey = publishableKey();
    if (!auth.startsWith("Bearer ") || !apiKey) {
      return json({ error: "sign in to Linguar Hub" }, 401);
    }

    const [user, access] = await Promise.all([
      signedInUser(auth, apiKey),
      appAccess(auth, apiKey),
    ]);
    const input = await request.json();
    const department = String(input.department || "").trim().toUpperCase();
    if (!/^[A-Z0-9_-]{1,20}$/.test(department)) {
      return json({ error: "invalid franchise" }, 400);
    }
    const memberships = Array.isArray(access?.departments)
      ? access.departments.map((value: unknown) => String(value).toUpperCase())
      : [];
    if (!access?.is_admin && !memberships.includes(department)) {
      return json({ error: `no access to ${department}` }, 403);
    }

    const path = String(input.path || "");
    const method = String(input.method || "GET").toUpperCase();
    if (!allowedPath(path) || !["GET", "POST", "PUT", "PATCH"].includes(method)) {
      return json({ error: "CompanyCam operation is not allowed" }, 400);
    }
    const credential = Deno.env.get(`COMPANYCAM_${department}_KEY`) || "";
    if (!credential) {
      return json({ error: `CompanyCam is not configured for ${department}` }, 503);
    }

    const url = new URL(`https://api.companycam.com/v2${path}`);
    const params = input.params && typeof input.params === "object" ? input.params : {};
    for (const [key, raw] of Object.entries(params)) {
      const values = Array.isArray(raw) ? raw : [raw];
      for (const value of values) {
        if (value !== null && value !== undefined) url.searchParams.append(key, String(value));
      }
    }
    const headers: Record<string, string> = {
      Authorization: `Bearer ${credential}`,
      Accept: "application/json",
      "User-Agent": "Linguar-Hub/1.0",
    };
    if (!["GET", "HEAD"].includes(method)) {
      headers["Content-Type"] = "application/json";
      if (user?.email) headers["X_COMPANYCAM_USER"] = String(user.email).toLowerCase();
    }
    const upstream = await fetch(url, {
      method,
      headers,
      body: input.data == null || method === "GET" ? undefined : JSON.stringify(input.data),
    });
    const raw = await upstream.text();
    return new Response(raw || "null", {
      status: upstream.status,
      headers: {
        ...CORS,
        "Content-Type": upstream.headers.get("Content-Type") || "application/json",
      },
    });
  } catch (error) {
    return json({ error: error instanceof Error ? error.message : "CompanyCam gateway failed" }, 500);
  }
});
