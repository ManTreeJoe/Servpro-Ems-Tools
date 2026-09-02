/* Browser adapter for the pywebview interface used by Linguar Hub tools.
 *
 * The Home shell and every tool iframe continue calling
 * `window.pywebview.api.<method>()`.  In a normal browser this proxy sends the
 * same call to the local Operations portal.  The tool code therefore has one
 * interface and two adapters: native pywebview and browser HTTP.
 */
(function () {
  "use strict";
  if (window.pywebview && window.pywebview.api) return;

  let accessKey = new URLSearchParams(location.search).get("key")
    || sessionStorage.getItem("operations-key") || "";

  async function parseResponse(response) {
    const contentType = String(response.headers.get("content-type") || "").toLowerCase();
    const text = await response.text();
    if (!contentType.includes("application/json")) {
      throw new Error("The browser tool connection returned a page instead of data.");
    }
    let result = {};
    try { result = text ? JSON.parse(text) : {}; }
    catch (_) { throw new Error("The browser tool connection returned invalid data."); }
    if (!response.ok && !result.error) result.error = `Browser tool request failed (${response.status}).`;
    return result;
  }

  async function call(method, args, retried) {
    const headers = { "Content-Type": "application/json" };
    if (accessKey) headers["X-Operations-Key"] = accessKey;
    const response = await fetch("/api/tool-call", {
      method: "POST",
      headers,
      cache: "no-store",
      body: JSON.stringify({ method, args }),
    });
    if (response.status === 401 && !retried) {
      const entered = window.prompt("Enter the Operations Hub access key");
      if (entered) {
        accessKey = entered.trim();
        sessionStorage.setItem("operations-key", accessKey);
        return call(method, args, true);
      }
    }
    return parseResponse(response);
  }

  const api = new Proxy({}, {
    get(_target, method) {
      // Avoid making the Proxy look like a Promise to await/Promise.resolve.
      if (method === "then" || typeof method !== "string") return undefined;
      return (...args) => call(method, args, false);
    },
  });
  window.pywebview = { api };
  window.__LINGUAR_BROWSER_TOOLS__ = true;
  window.__linguarBrowserCall = (method, args) => call(method, args, false);

  // app.js registers its listener immediately after this injected script.
  setTimeout(() => window.dispatchEvent(new Event("pywebviewready")), 0);
})();
