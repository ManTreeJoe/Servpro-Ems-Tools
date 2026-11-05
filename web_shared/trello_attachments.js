/* Linguar Hub — shared 📎 Trello attachments modal.
 *
 * Lists every attachment on a Trello card with image thumbnails
 * (when available), bulk-select checkboxes, and a per-row 📥
 * Download button. The Download-all action copies the selected
 * attachments into the job's `<job>/EMS/PICS/Trello attachments/`
 * folder (creates if missing), then opens that folder in Explorer
 * so the user can see what landed.
 *
 * Each panel calls:
 *
 *   window.openTrelloAttachmentsModal({
 *     cardId:  "abc123",       // required
 *     client:  "Smith, John",  // resolves PICS target dir
 *     onAfter: () => {...},    // optional refresh hook
 *   });
 *
 * The Pywebview `pywebview.api.list_card_attachments` and
 * `pywebview.api.download_card_attachments` methods do the heavy
 * lifting — the modal is purely presentational.
 */
(function () {
  "use strict";

  // Shared in-app viewer: opening a photo never changes import selection.
  window.openImportImagePreview = async function ({title = 'Photo', source} = {}) {
    const origin = document.activeElement;
    const dialog = document.createElement('dialog');
    dialog.className = 'modal-scrim import-image-viewer';
    dialog.setAttribute('aria-label', title);
    dialog.style.cssText = 'position:fixed;display:block;animation:none;backdrop-filter:none;inset:0;margin:auto;width:min(1100px,94vw);height:90vh;max-width:94vw;max-height:90vh;padding:16px;box-sizing:border-box;background:var(--bg,#202428);color:var(--text,#eee);border:1px solid var(--border,#555);border-radius:10px;';
    const heading = document.createElement('header');
    heading.style.cssText = 'display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:12px;';
    const name = document.createElement('strong'); name.textContent = title;
    const close = document.createElement('button'); close.className = 'btn'; close.textContent = 'Close preview';
    const message = document.createElement('p'); message.textContent = 'Loading image…'; message.setAttribute('role','status');
    const img = document.createElement('img'); img.alt = title;
    img.style.cssText = 'display:none;width:100%;height:calc(100% - 60px);object-fit:contain;';
    heading.append(name, close); dialog.append(heading, message, img); document.body.append(dialog);
    const dismiss = () => { dialog.close(); };
    const key = event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); dismiss(); }
    };
    window.addEventListener('keydown', key, true);
    dialog.addEventListener('close', () => {
      window.removeEventListener('keydown', key, true); dialog.remove();
      if (origin?.isConnected) origin.focus();
    }, {once:true});
    close.onclick = dismiss;
    dialog.showModal(); close.focus();
    img.onload = () => { message.hidden = true; img.style.display = 'block'; };
    img.onerror = () => { img.style.display = 'none'; message.hidden = false; message.textContent = 'Image could not load. Close this preview and try again.'; };
    try {
      const url = typeof source === 'function' ? await source() : source;
      if (!dialog.isConnected) return;
      if (typeof url !== 'string' || !/^(https:\/\/|data:image\/(?:png|jpeg|jpg|gif|webp|bmp);base64,)/i.test(url))
        throw Error('Image preview unavailable.');
      img.src = url;
    } catch (_) { if (dialog.isConnected) message.textContent = 'Image preview unavailable. Your selection is unchanged.'; }
  };

  function esc(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  }
  function fmtBytes(b) {
    if (!b) return "—";
    if (b < 1024) return `${b} B`;
    if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
    return `${(b / 1024 / 1024).toFixed(1)} MB`;
  }
  function fmtDate(iso) {
    if (!iso) return "—";
    const m = String(iso).match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
    if (!m) return iso;
    return `${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}-${m[1]}`;
  }

  function status(msg, kind) {
    // Try common setStatus / toast helpers across panels
    try { if (typeof window.setStatus === "function") return window.setStatus(msg, kind || ""); } catch (_) {}
    try { if (typeof window.toast      === "function") return window.toast(msg, kind || ""); } catch (_) {}
    console.log("[trello_attachments]", kind || "", msg);
  }

  window.openTrelloAttachmentsModal = async function ({ cardId, client, division = 'EMS', onAfter } = {}) {
    if (window.TrelloAttachmentGallery)
      return window.TrelloAttachmentGallery.open({cardId, client, division, onAfter});
    if (!cardId) {
      status("No Trello card pinned — pin one first", "warn");
      return;
    }
    const w = document.createElement("div");
    w.id = "ta-modal";
    w.style.cssText = "position:fixed;inset:0;z-index:300;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;";
    w.innerHTML = `
      <div style="background:var(--bg);border:1px solid var(--border);border-radius:10px;width:min(720px,94vw);max-height:90vh;display:flex;flex-direction:column;overflow:hidden;">
        <header style="padding:14px 20px;background:var(--surface);border-bottom:1px solid var(--border);">
          <div style="font-size:15px;font-weight:600;">📎 Trello attachments — ${esc(client || cardId)}</div>
          <div style="font-size:11px;color:var(--text-muted);margin-top:2px;" id="ta-status">Loading attachments…</div>
        </header>
        <div style="padding:10px 20px;display:flex;gap:8px;align-items:center;background:var(--surface);border-bottom:1px solid var(--border);">
          <button class="btn" id="ta-sel-images">✓ Select all images</button>
          <button class="btn" id="ta-sel-all">✓ Select all</button>
          <button class="btn" id="ta-sel-none">✕ Clear selection</button>
          <span style="flex:1;"></span>
          <span class="muted" id="ta-sel-count" style="font-size:11px;">0 selected</span>
          <button class="btn btn-primary" id="ta-download" disabled>📥 Download selected</button>
        </div>
        <div id="ta-list" style="flex:1;overflow-y:auto;padding:12px 20px;display:flex;flex-direction:column;gap:6px;"></div>
        <footer style="padding:10px 20px;background:var(--surface);border-top:1px solid var(--border);display:flex;justify-content:flex-end;">
          <button class="btn" id="ta-close">Close</button>
        </footer>
      </div>`;
    document.body.appendChild(w);
    const close = () => w.remove();
    w.querySelector("#ta-close").addEventListener("click", close);

    const listEl = w.querySelector("#ta-list");
    const statusEl = w.querySelector("#ta-status");
    const countEl = w.querySelector("#ta-sel-count");
    const dlBtn = w.querySelector("#ta-download");

    let attachments = [];
    const selected = new Set();
    const thumbCache = new Map();  // att_id -> base64 data URI (authed fetch)
    const thumbTried = new Set();  // att_id we've already attempted, ok or not

    function refreshCount() {
      countEl.textContent = `${selected.size} selected`;
      dlBtn.disabled = selected.size === 0;
    }

    function render() {
      if (!attachments.length) {
        listEl.innerHTML = `<div class="muted" style="padding:30px;text-align:center;">No attachments on this card.</div>`;
        return;
      }
      listEl.innerHTML = attachments.map((a) => {
        const isSel = selected.has(a.id);
        // Trello preview URLs 401 without auth, so a raw <img src> stays
        // blank. We lazily fetch each thumbnail through the backend
        // (which adds the OAuth header) and cache the data URI; until it
        // arrives, show a placeholder tagged so loadThumbs() can swap it.
        const thumbBox = "width:64px;height:64px;object-fit:cover;border-radius:4px;border:1px solid var(--border);";
        let thumb;
        if (a.is_image && thumbCache.has(a.id)) {
          thumb = `<img src="${esc(thumbCache.get(a.id))}" alt="" style="${thumbBox}" />`;
        } else if (a.is_image) {
          thumb = `<div class="ta-thumb-ph" data-thumb="${esc(a.id)}" style="${thumbBox}display:flex;align-items:center;justify-content:center;background:var(--surface-2);font-size:28px;">🖼</div>`;
        } else {
          thumb = `<div style="${thumbBox}display:flex;align-items:center;justify-content:center;background:var(--surface-2);font-size:28px;">📄</div>`;
        }
        return `
          <div class="ta-row" data-id="${esc(a.id)}"
                 style="display:grid;grid-template-columns:auto auto 1fr auto auto;gap:12px;align-items:center;padding:8px 12px;background:${isSel ? "var(--green-soft)" : "var(--surface)"};border:1px solid ${isSel ? "var(--green)" : "var(--border)"};border-radius:6px;cursor:pointer;">
            <input type="checkbox" class="ta-cb" aria-label="Select ${esc(a.name)}" data-id="${esc(a.id)}" ${isSel ? "checked" : ""} />
            ${a.is_image ? `<button type="button" class="ta-preview" data-id="${esc(a.id)}" aria-label="Preview ${esc(a.name)}" style="padding:0;border:0;background:transparent;cursor:zoom-in;">${thumb}</button>` : thumb}
            <div style="min-width:0;">
              <div style="font-weight:600;font-size:13px;word-break:break-word;">${esc(a.name)}</div>
              <div class="muted" style="font-size:11px;">${a.is_image ? "🖼 image" : (a.mime || "file")} · ${fmtBytes(a.size)} · ${esc(fmtDate(a.date))}${a.is_upload ? "" : " · external link"}</div>
            </div>
            <button class="btn ta-open" data-url="${esc(a.url)}" style="font-size:10px;padding:3px 8px;" title="Open in browser">👁</button>
            <button class="btn ta-one" data-id="${esc(a.id)}" style="font-size:10px;padding:3px 8px;" title="Download this one">📥</button>
          </div>`;
      }).join("");
      // Wire row checkboxes
      listEl.querySelectorAll(".ta-cb").forEach((cb) =>
        cb.addEventListener("change", (e) => {
          e.stopPropagation();
          if (cb.checked) selected.add(cb.dataset.id);
          else selected.delete(cb.dataset.id);
          render();
        }));
      listEl.querySelectorAll(".ta-preview").forEach(b => b.addEventListener('click', () => {
        const attachment = attachments.find(a => a.id === b.dataset.id);
        window.openImportImagePreview({title:attachment.name, source:async () => {
          const result = await pywebview.api.fetch_trello_image(attachment.url);
          if (!result?.ok || !result.data_uri) throw Error('Preview failed');
          return result.data_uri;
        }});
      }));
      // Open URL button
      listEl.querySelectorAll(".ta-open").forEach((b) =>
        b.addEventListener("click", (e) => {
          e.stopPropagation();
          pywebview.api.open_url(b.dataset.url);
        }));
      // One-shot download per row
      listEl.querySelectorAll(".ta-one").forEach((b) =>
        b.addEventListener("click", async (e) => {
          e.stopPropagation();
          b.disabled = true; b.textContent = "…";
          const res = await pywebview.api.download_card_attachments(
            cardId, [b.dataset.id], client || "");
          b.disabled = false; b.textContent = "📥";
          if (!res?.ok) { status(`Download failed: ${res?.error || "?"}`, "error"); return; }
          status(`📥 Saved ${res.downloaded_count}/${ids(b.dataset.id, 1)} → ${res.target}`, "ok");
        }));
      refreshCount();
    }
    function ids(_a, _b) { return _b; }  // shim so the toast line above reads naturally

    // Lazily pull each image thumbnail through the backend (adds the
    // OAuth header Trello requires) and swap the placeholder for an
    // <img>. Cached so re-renders (selection changes) don't refetch.
    async function loadThumbs() {
      for (const a of attachments) {
        if (!a.is_image || !a.preview) continue;
        if (thumbCache.has(a.id) || thumbTried.has(a.id)) continue;
        thumbTried.add(a.id);
        let r;
        try { r = await pywebview.api.fetch_trello_image(a.preview); }
        catch (_) { r = null; }
        if (!r || !r.ok || !r.data_uri) continue;
        thumbCache.set(a.id, r.data_uri);
        const ph = listEl.querySelector(`.ta-thumb-ph[data-thumb="${a.id}"]`);
        if (ph) {
          ph.outerHTML = `<img src="${esc(r.data_uri)}" alt="" style="width:64px;height:64px;object-fit:cover;border-radius:4px;border:1px solid var(--border);" />`;
        }
      }
    }

    // Bulk select buttons
    w.querySelector("#ta-sel-images").addEventListener("click", () => {
      attachments.forEach((a) => { if (a.is_image) selected.add(a.id); });
      render();
    });
    w.querySelector("#ta-sel-all").addEventListener("click", () => {
      attachments.forEach((a) => selected.add(a.id));
      render();
    });
    w.querySelector("#ta-sel-none").addEventListener("click", () => {
      selected.clear();
      render();
    });
    dlBtn.addEventListener("click", async () => {
      if (!selected.size) return;
      dlBtn.disabled = true; dlBtn.textContent = "Downloading…";
      const res = await pywebview.api.download_card_attachments(
        cardId, [...selected], client || "");
      dlBtn.disabled = false; dlBtn.textContent = "📥 Download selected";
      if (!res?.ok) { status(`Download failed: ${res?.error || "?"}`, "error"); return; }
      const ok = res.downloaded_count || 0;
      const bad = res.failed_count || 0;
      status(`📥 ${ok} downloaded${bad ? ` · ${bad} failed` : ""} → ${res.target}`, ok ? "ok" : "warn");
      if (typeof onAfter === "function") { try { onAfter(); } catch (_) {} }
    });

    // Pull attachment list + render
    const res = await pywebview.api.list_card_attachments(cardId);
    if (!res?.ok) {
      statusEl.textContent = `Error: ${res?.error || "?"}`;
      statusEl.style.color = "var(--red)";
      return;
    }
    attachments = res.attachments || [];
    statusEl.textContent =
      `${res.total} attachment${res.total !== 1 ? "s" : ""} · ${res.image_count} image${res.image_count !== 1 ? "s" : ""}`;
    render();
    loadThumbs();  // fire-and-forget; fills thumbnails as they arrive
  };
})();
