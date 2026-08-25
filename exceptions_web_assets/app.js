(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  let categories = [], selected = "", offset = 0, loading = false;
  const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const setStatus = text => { $("status").textContent = text; };

  function ageText(minutes) {
    if (minutes == null) return "No exception scan has run yet. Open Hygiene and run a scan.";
    if (minutes < 60) return `Exception scan updated ${minutes} minute${minutes === 1 ? "" : "s"} ago.`;
    const hours = Math.floor(minutes / 60);
    return `Exception scan updated ${hours} hour${hours === 1 ? "" : "s"} ago.`;
  }

  function renderCategories() {
    const needle = $("filter").value.trim().toLowerCase();
    const shown = categories.filter(c => !needle || c.label.toLowerCase().includes(needle));
    $("categories").innerHTML = shown.map(c => `<button class="category tier-${c.tier}${c.key === selected ? " active" : ""}" data-key="${escapeHtml(c.key)}" data-count="${c.count}" data-track="exceptions_category"><span class="rail"></span><span class="category-icon" aria-hidden="true">${escapeHtml(c.icon)}</span><span class="category-label">${escapeHtml(c.label)}</span><span class="category-count">${c.count}</span></button>`).join("") || '<div class="empty">No categories match.</div>';
    document.querySelectorAll(".category").forEach(el => el.addEventListener("click", () => selectCategory(el.dataset.key)));
  }

  async function loadSummary(force = false) {
    loading = true; setStatus("Refreshing checks…");
    try {
      const result = await window.pywebview.api.summary(force);
      categories = result.categories || [];
      $("total").textContent = result.total ?? 0;
      $("freshness").textContent = ageText(result.age_minutes) + (result.stale ? " Results may have changed; run Hygiene when you need a fresh Trello scan." : "");
      $("freshness").classList.toggle("warn", !!result.stale || !result.scanned);
      renderCategories();
      const next = categories.find(c => c.count > 0)?.key || categories[0]?.key;
      if (next) await selectCategory(categories.some(c => c.key === selected) ? selected : next);
      else $("items").innerHTML = '<div class="empty">No exceptions are available.</div>';
      setStatus("Checks refreshed");
    } catch (err) { setStatus(`Could not load exceptions: ${err}`); }
    finally { loading = false; }
  }

  async function selectCategory(key) {
    if (!key || loading) return;
    selected = key; offset = 0; renderCategories();
    const category = categories.find(c => c.key === key);
    $("detail-title").textContent = category?.label || "Exceptions";
    $("detail-priority").textContent = category?.tier === 0 ? "Act first" : category?.tier === 1 ? "Review next" : "Routine follow-up";
    $("detail-count").textContent = category?.count ?? 0;
    $("items").innerHTML = '<div class="empty">Loading…</div>';
    await loadItems(false);
  }

  async function loadItems(append) {
    loading = true;
    try {
      const result = await window.pywebview.api.items(selected, append ? offset : 0, 50);
      const html = (result.items || []).map(item => `<article class="item"><span class="item-signal"></span><div class="item-copy"><div class="item-title">${escapeHtml(item.client || "Unnamed item")}</div><div class="item-detail">${escapeHtml(item.subtitle || "Review this item in its original tool.")}</div>${item.action ? `<div class="item-action">Next: ${escapeHtml(item.action)}</div>` : ""}</div>${item.card_url ? `<a href="${escapeHtml(item.card_url)}" target="_blank" rel="noopener">Open Trello</a>` : ""}</article>`).join("");
      if (append) $("items").insertAdjacentHTML("beforeend", html);
      else $("items").innerHTML = html || '<div class="empty">Nothing needs attention in this category.</div>';
      offset = result.next_offset || 0;
      $("more").classList.toggle("hidden", !result.has_more);
      setStatus(`${result.total || 0} item${result.total === 1 ? "" : "s"}`);
    } catch (err) { $("items").innerHTML = `<div class="empty">Could not load this category: ${escapeHtml(err)}</div>`; setStatus("Category unavailable"); }
    finally { loading = false; }
  }

  $("refresh").addEventListener("click", () => loadSummary(true));
  $("filter").addEventListener("input", renderCategories);
  $("more").addEventListener("click", () => loadItems(true));
  window.addEventListener("pywebviewready", () => loadSummary(false));
})();
