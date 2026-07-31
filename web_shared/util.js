/* Linguar Hub — shared frontend utilities.
 *
 * One canonical home for the helpers every panel duplicates:
 *
 *   esc(s)          HTML-escape (for innerHTML)
 *   escapeAttr(s)   same — kept as a separate name for readability
 *                   when interpolating into an attribute
 *   escapeHtml(s)   alias of esc(); keeps older panel call sites
 *                   that imported under this name working unchanged
 *
 *   fmtDate(iso)    Render any date-ish string as MM-DD-YYYY.
 *                   Handles ISO ("2026-05-27"), slash ("5/27/26"
 *                   or "05/27/2026"), and already-MM-DD-YYYY input.
 *                   Returns "" for empty; "—" hint for falsy.
 *
 *   fmtAge(min)     Human-readable age: "12m", "3h 20m", "2d 4h".
 *
 *   fmtBytes(n)     "421 B" / "3.4 KB" / "12 MB". 1024 base.
 *
 *   pad2(n)         "01" / "02" / … (zero-padded 2 digits).
 *
 *   copyText(s)     Async — async navigator.clipboard.writeText
 *                   with try/catch + fallback to a textarea trick.
 *                   Returns true/false.
 *
 * Every panel's index.html loads this BEFORE its own app.js so
 * the helpers are global at app.js parse time. Panels are free to
 * still define their own local versions — `var foo = ...` shadows
 * the global; `function foo` collides at parse time and is the
 * source of the rare "Identifier 'esc' has already been declared"
 * console errors we used to see.
 *
 * Removal plan for legacy duplicates: leave them in place for now
 * (they keep working — JS just uses the most-local definition).
 * Future cleanup passes can delete them panel-by-panel once we're
 * sure nothing depends on a panel-local variant.
 */
(function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }
  const escapeAttr = esc;
  const escapeHtml = esc;

  function pad2(n) { return String(n).padStart(2, "0"); }

  function fmtDate(v) {
    const s = String(v == null ? "" : v).trim();
    if (!s) return "";
    // ISO `2026-05-27T...`
    let m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
    if (m) return `${pad2(m[2])}-${pad2(m[3])}-${m[1]}`;
    // Slash `5/27/26` or `05/27/2026`
    m = s.match(/^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})/);
    if (m) {
      const yy = m[3].length === 2 ? "20" + m[3] : m[3];
      return `${pad2(m[1])}-${pad2(m[2])}-${yy}`;
    }
    // Anything else (free-form text) — pass through unchanged so
    // junk cells don't render as "NaN-NaN-NaN".
    return s;
  }

  function fmtAge(minutes) {
    const m = parseInt(minutes, 10);
    if (!Number.isFinite(m) || m < 0) return "?";
    if (m < 60) return `${m}m`;
    const h = Math.floor(m / 60);
    if (h < 24) {
      const rem = m % 60;
      return rem ? `${h}h ${rem}m` : `${h}h`;
    }
    const d = Math.floor(h / 24);
    const rh = h % 24;
    return rh ? `${d}d ${rh}h` : `${d}d`;
  }

  function fmtBytes(n) {
    const b = Number(n || 0);
    if (!b) return "—";
    if (b < 1024) return `${b} B`;
    if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
    return `${(b / 1024 / 1024).toFixed(1)} MB`;
  }

  async function copyText(s) {
    const str = String(s == null ? "" : s);
    if (!str) return false;
    try {
      await navigator.clipboard.writeText(str);
      return true;
    } catch (_) {
      // Fallback for older WebView2 builds that block clipboard.write
      try {
        const ta = document.createElement("textarea");
        ta.value = str;
        ta.style.cssText = "position:fixed;left:-9999px;top:-9999px;";
        document.body.appendChild(ta);
        ta.select();
        const ok = document.execCommand("copy");
        ta.remove();
        return !!ok;
      } catch (_) {
        return false;
      }
    }
  }

  // Expose globally — panels just reference these without imports.
  window.esc          = esc;
  window.escapeAttr   = escapeAttr;
  window.escapeHtml   = escapeHtml;
  window.pad2         = pad2;
  window.fmtDate      = fmtDate;
  window.fmtAge       = fmtAge;
  window.fmtBytes     = fmtBytes;
  window.emsCopyText  = copyText;  // namespaced — `copyText` is taken in audit
})();
