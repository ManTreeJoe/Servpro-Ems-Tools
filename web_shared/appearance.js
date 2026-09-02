(function () {
  "use strict";

  const KEY = "linguar.appearance";
  const VALID = new Set(["system", "light", "dark"]);
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  let selected = "system";
  let systemMode = media.matches ? "dark" : "light";
  let effective = systemMode;

  try {
    const saved = localStorage.getItem(KEY);
    if (VALID.has(saved)) selected = saved;
  } catch (_) { /* localStorage can be unavailable in hardened WebViews */ }

  function normalize(value) {
    value = String(value || "system").toLowerCase();
    return VALID.has(value) ? value : "system";
  }

  function detectedSystemMode() {
    return media.matches ? "dark" : "light";
  }

  function apply(nextSelected, details) {
    selected = normalize(nextSelected);
    systemMode = normalize(details && details.system) === "system"
      ? detectedSystemMode()
      : normalize(details && details.system);
    if (systemMode === "system") systemMode = detectedSystemMode();
    effective = selected === "system" ? systemMode : selected;
    const root = document.documentElement;
    root.dataset.appearance = selected;
    root.dataset.theme = effective;
    root.style.colorScheme = effective;
    root.classList.toggle("density-compact", details && details.density === "compact");
    root.classList.toggle("reduce-motion", Boolean(details && details.reduce_motion));
    const color = effective === "light" ? "#F1F3ED" : "#0E1112";
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", color);
    try { localStorage.setItem(KEY, selected); } catch (_) {}
    window.dispatchEvent(new CustomEvent("linguar:appearance", { detail: current() }));
    return current();
  }

  function current() {
    return { selected, system: systemMode, effective };
  }

  function setPreference(value, details) {
    const result = apply(value, details || { system: detectedSystemMode() });
    if (window.parent && window.parent !== window) {
      try { window.parent.postMessage({ type: "linguar-appearance", ...result }, "*"); } catch (_) {}
    } else {
      document.querySelectorAll("iframe").forEach((frame) => {
        try { frame.contentWindow.postMessage({ type: "linguar-appearance", ...result }, "*"); } catch (_) {}
      });
    }
    return result;
  }

  window.LinguarAppearance = { apply, current, setPreference, detectedSystemMode };
  apply(selected, { system: detectedSystemMode() });

  function useParentTheme() {
    if (!window.parent || window.parent === window || !window.parent.LinguarAppearance) return false;
    const parentTheme = window.parent.LinguarAppearance.current();
    apply(parentTheme.selected, parentTheme);
    return true;
  }

  async function loadSavedPreference() {
    if (useParentTheme()) return;
    try {
      const api = window.pywebview && window.pywebview.api;
      if (api && api.appearance_preferences) {
        const result = await api.appearance_preferences();
        if (result) apply(result.selected, result);
      }
    } catch (_) { /* system/local fallback already applied */ }
  }

  window.addEventListener("pywebviewready", loadSavedPreference, { once: true });
  window.addEventListener("message", (event) => {
    if (event.data && event.data.type === "linguar-appearance") {
      apply(event.data.selected, event.data);
    }
  });
  media.addEventListener?.("change", () => {
    if (selected === "system") setPreference("system", { system: detectedSystemMode() });
  });
  window.addEventListener("storage", (event) => {
    if (event.key === KEY && VALID.has(event.newValue)) apply(event.newValue, { system: detectedSystemMode() });
  });
})();
