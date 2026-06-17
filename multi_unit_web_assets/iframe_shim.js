/* EMS Tools — iframe shim (v2).
 *
 * Sets up `window.pywebview.api` inside each tool's iframe as a
 * Proxy that auto-prefixes method names with the tool's namespace
 * and forwards calls to the parent window's HomeApi.
 *
 * Timing matters: the tool's app.js listens for `pywebviewready`
 * via `window.addEventListener`. If the event fires before app.js
 * has run, the listener is never called and the tool appears stuck
 * loading. We guard against this by deferring the dispatch until
 * `document.readyState === "complete"` (all scripts loaded).
 */
(function () {
  if (window.parent === window) return;  // standalone — let pywebview do its thing
  const parentWin = window.parent;
  let alreadyFired = false;

  function fireReady() {
    if (alreadyFired) return;
    alreadyFired = true;
    // Microtask delay so the call stack settles + any synchronous
    // listener registration in app.js runs first.
    setTimeout(() => {
      window.dispatchEvent(new Event("pywebviewready"));
    }, 0);
  }

  function dispatchWhenReady() {
    if (document.readyState === "complete") {
      fireReady();
    } else {
      window.addEventListener("load", fireReady);
      // Also try DOMContentLoaded in case the load event is slow
      // due to images/iframes etc. — pywebviewready only needs the
      // DOM + scripts, not all subresources.
      window.addEventListener("DOMContentLoaded", () => {
        // Give scripts a beat to register listeners
        setTimeout(fireReady, 10);
      });
    }
  }

  function tryWire() {
    if (!parentWin.pywebview || !parentWin.pywebview.api) {
      setTimeout(tryWire, 30);
      return;
    }
    const parentApi = parentWin.pywebview.api;
    let ns = "";
    try {
      const parts = location.pathname.split(/[\/\\]/);
      const dir = parts[parts.length - 2] || "";
      ns = dir.replace(/_web_assets$/, "");
    } catch (_) { ns = ""; }
    const handler = {
      get(_target, prop) {
        if (typeof prop !== "string") return undefined;
        return function (...args) {
          const nsKey = ns + "_" + prop;
          if (typeof parentApi[nsKey] === "function") {
            return parentApi[nsKey](...args);
          }
          if (typeof parentApi[prop] === "function") {
            return parentApi[prop](...args);
          }
          console.warn("[shim] pywebview.api." + prop + " — neither "
            + nsKey + " nor " + prop + " on parent HomeApi");
          return Promise.resolve(null);
        };
      }
    };
    window.pywebview = { api: new Proxy({}, handler) };
    dispatchWhenReady();
  }
  tryWire();
})();
