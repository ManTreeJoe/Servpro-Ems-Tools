(function () {
  "use strict";

  const KEY = "linguar.appearance";
  const VALID = new Set(["system", "light", "dark"]);
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  let selected = "system";
  let systemMode = media.matches ? "dark" : "light";
  let effective = systemMode;
  let revision = 0;
  let extras = {density:'comfortable', reduce_motion:false, sidebar_auto_collapse:false};

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
    for (const key of Object.keys(extras)) if (details && key in details) extras[key] = details[key];
    revision++;
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
    root.classList.toggle("density-compact", extras.density === "compact");
    root.classList.toggle("reduce-motion", Boolean(extras.reduce_motion));
    root.classList.toggle("sidebar-auto-collapse", Boolean(extras.sidebar_auto_collapse));
    const color = effective === "light" ? "#F1F3ED" : "#0E1112";
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", color);
    window.dispatchEvent(new CustomEvent("linguar:appearance", { detail: current() }));
    return current();
  }

  function current() {
    return { selected, system: systemMode, effective, ...extras };
  }

  function setPreference(value, details) {
    const result = apply(value, details || { system: detectedSystemMode() });
    try { localStorage.setItem(KEY, selected); } catch (_) {}
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

  function useParentTheme() {
    try {
      if (!window.parent || window.parent === window || !window.parent.LinguarAppearance) return false;
      const parentTheme = window.parent.LinguarAppearance.current();
      apply(parentTheme.selected, parentTheme);
      return true;
    } catch (_) { return false; }
  }

  // A tool's temporary startup fallback must never overwrite the shared choice.
  if (!useParentTheme()) apply(selected, { system: detectedSystemMode() });

  function broadcast() {
    document.querySelectorAll('iframe').forEach(frame => {
      try { frame.contentWindow.postMessage({type:'linguar-appearance', ...current()}, '*'); } catch (_) {}
    });
  }

  async function loadSavedPreference() {
    if (useParentTheme()) return;
    const started = revision;
    try {
      const api = window.pywebview && window.pywebview.api;
      if (api && api.appearance_preferences) {
        const result = await api.appearance_preferences();
        if (result && VALID.has(result.selected) && revision === started) {
          apply(result.selected, result);
          broadcast();
        }
      }
    } catch (_) { /* system/local fallback already applied */ }
  }

  window.addEventListener("pywebviewready", loadSavedPreference, { once: true });
  window.addEventListener("message", (event) => {
    const fromParent = window.parent !== window && event.source === window.parent;
    const fromChild = [...document.querySelectorAll('iframe')].some(frame => frame.contentWindow === event.source);
    if ((fromParent || fromChild) && event.data?.type === "linguar-appearance" && VALID.has(event.data.selected)) {
      apply(event.data.selected, event.data);
      broadcast();
    }
  });
  media.addEventListener?.("change", () => {
    if (selected === "system") { apply("system", { system: detectedSystemMode() }); broadcast(); }
  });
  window.addEventListener("storage", (event) => {
    if (event.key === KEY && VALID.has(event.newValue)) { apply(event.newValue, { system: detectedSystemMode() }); broadcast(); }
  });
})();
