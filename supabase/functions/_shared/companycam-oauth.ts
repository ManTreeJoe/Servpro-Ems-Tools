export const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, "Content-Type": "application/json" },
  });
}

export function publishableKey(): string {
  const legacy = Deno.env.get("SUPABASE_ANON_KEY") || "";
  if (legacy) return legacy;
  try {
    const keys = JSON.parse(Deno.env.get("SUPABASE_PUBLISHABLE_KEYS") || "{}");
    return String(keys.default || Object.values(keys)[0] || "");
  } catch {
    return "";
  }
}

export function callbackUrl(): string {
  return `${Deno.env.get("SUPABASE_URL") || ""}/functions/v1/companycam-oauth-callback`;
}

export function companyCamApp(department: string): { clientId: string; clientSecret: string } {
  const dept = department.trim().toUpperCase();
  return {
    clientId: Deno.env.get(`COMPANYCAM_${dept}_CLIENT_ID`) || "",
    clientSecret: Deno.env.get(`COMPANYCAM_${dept}_CLIENT_SECRET`) || "",
  };
}

export async function signedInUser(auth: string, apiKey: string) {
  const response = await fetch(`${Deno.env.get("SUPABASE_URL")}/auth/v1/user`, {
    headers: { Authorization: auth, apikey: apiKey },
  });
  if (!response.ok) throw new Error("Sign in to Linguar Hub first.");
  return await response.json();
}

export async function appAccess(auth: string, apiKey: string) {
  const response = await fetch(`${Deno.env.get("SUPABASE_URL")}/rest/v1/rpc/my_app_access`, {
    method: "POST",
    headers: { Authorization: auth, apikey: apiKey, "Content-Type": "application/json" },
    body: "{}",
  });
  if (!response.ok) throw new Error("Franchise access could not be verified.");
  return await response.json();
}

function base64Url(bytes: Uint8Array): string {
  let binary = "";
  bytes.forEach((value) => binary += String.fromCharCode(value));
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function fromBase64Url(value: string): Uint8Array {
  const padded = value.replaceAll("-", "+").replaceAll("_", "/") + "===".slice((value.length + 3) % 4);
  return Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
}

async function hmacKey(): Promise<CryptoKey> {
  const secret = Deno.env.get("OAUTH_STATE_SECRET") || "";
  if (secret.length < 32) throw new Error("OAuth state signing is not configured.");
  return await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"],
  );
}

export async function createState(userId: string, department: string): Promise<string> {
  const payload = base64Url(new TextEncoder().encode(JSON.stringify({
    user_id: userId,
    department,
    expires_at: Date.now() + 10 * 60 * 1000,
    nonce: crypto.randomUUID(),
  })));
  const signature = new Uint8Array(await crypto.subtle.sign(
    "HMAC", await hmacKey(), new TextEncoder().encode(payload),
  ));
  return `${payload}.${base64Url(signature)}`;
}

export async function verifyState(state: string): Promise<{ user_id: string; department: string }> {
  const [payload, signature, ...extra] = String(state || "").split(".");
  if (!payload || !signature || extra.length) throw new Error("Invalid connection state.");
  const valid = await crypto.subtle.verify(
    "HMAC", await hmacKey(), fromBase64Url(signature), new TextEncoder().encode(payload),
  );
  if (!valid) throw new Error("Invalid connection state.");
  const decoded = JSON.parse(new TextDecoder().decode(fromBase64Url(payload)));
  if (!decoded.user_id || !/^[A-Z0-9_-]{1,20}$/.test(decoded.department || "")) {
    throw new Error("Invalid connection state.");
  }
  if (Number(decoded.expires_at || 0) < Date.now()) throw new Error("Connection request expired. Start again in Linguar Hub.");
  return { user_id: String(decoded.user_id), department: String(decoded.department) };
}

async function encryptionKey(): Promise<CryptoKey> {
  const encoded = Deno.env.get("OAUTH_TOKEN_ENCRYPTION_KEY") || "";
  const raw = fromBase64Url(encoded);
  if (raw.byteLength !== 32) throw new Error("OAuth token encryption is not configured.");
  return await crypto.subtle.importKey("raw", raw, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]);
}

export async function encryptSecret(value: string): Promise<{ cipher: string; iv: string }> {
  if (!value) return { cipher: "", iv: "" };
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const encrypted = new Uint8Array(await crypto.subtle.encrypt(
    { name: "AES-GCM", iv }, await encryptionKey(), new TextEncoder().encode(value),
  ));
  return { cipher: base64Url(encrypted), iv: base64Url(iv) };
}

export async function decryptSecret(cipher: string, iv: string): Promise<string> {
  if (!cipher) return "";
  const decrypted = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: fromBase64Url(iv) }, await encryptionKey(), fromBase64Url(cipher),
  );
  return new TextDecoder().decode(decrypted);
}

export function serviceHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!serviceKey) throw new Error("Server credential unavailable.");
  return { Authorization: `Bearer ${serviceKey}`, apikey: serviceKey, "Content-Type": "application/json", ...extra };
}
