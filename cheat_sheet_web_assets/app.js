"use strict";
const state = { sections: [], active: 0, search: "" };
const $ = (s) => document.querySelector(s);

window.addEventListener("pywebviewready", async () => {
  state.sections = await pywebview.api.sections() || [];
  render();
  $("#search-box").addEventListener("input", (e) => { state.search = e.target.value; render(); });
  document.getElementById("export-pdf-btn")?.addEventListener("click", async () => {
    const btn = document.getElementById("export-pdf-btn");
    btn.disabled = true; const orig = btn.textContent;
    btn.textContent = "Generating…";
    const r = await pywebview.api.export_pdf();
    btn.disabled = false; btn.textContent = orig;
    if (!r?.ok) alert(`Export failed: ${r?.error || "?"}`);
  });
  // One delegated handler covers every copy affordance — the per-snippet
  // 📋 Copy buttons AND every inline click-to-copy <code> span. Keeps us
  // off inline onclick (cleaner + no CSP friction in WebView2).
  $("#content").addEventListener("click", onCopyClick);
});

// ── Copy interactions ──────────────────────────────────────────────
async function onCopyClick(e) {
  const el = e.target.closest("[data-copy]");
  if (!el) return;
  const text = decodeURIComponent(el.getAttribute("data-copy") || "");
  if (!text) return;
  const ok = await window.copyText(text);
  flashCopied(el, ok);
}

function flashCopied(el, ok) {
  if (el.classList.contains("copy-btn")) {
    if (!el.dataset.label) el.dataset.label = el.textContent;
    el.textContent = ok ? "✓ Copied" : "✕ Failed";
    el.classList.add("copied");
    setTimeout(() => {
      el.textContent = el.dataset.label;
      el.classList.remove("copied");
    }, 1200);
  } else {
    // Inline code span — flash + a little floating "Copied!" hint.
    el.classList.add("copied");
    setTimeout(() => el.classList.remove("copied"), 900);
    floatHint(el, ok ? "Copied!" : "Copy failed");
  }
}

function floatHint(anchor, msg) {
  const tip = document.createElement("span");
  tip.className = "copy-float";
  tip.textContent = msg;
  document.body.appendChild(tip);
  const r = anchor.getBoundingClientRect();
  tip.style.left = (r.left + r.width / 2) + "px";
  tip.style.top = (r.top - 4) + "px";
  requestAnimationFrame(() => tip.classList.add("show"));
  setTimeout(() => tip.remove(), 850);
}

// ── Render ─────────────────────────────────────────────────────────
function render() {
  $("#toc").innerHTML = state.sections.map((s, i) =>
    `<a class="${i === state.active ? "active" : ""}" data-i="${i}">${esc(s.title)}</a>`
  ).join("");
  document.querySelectorAll("#toc a").forEach((a) => a.addEventListener("click", () => {
    state.active = +a.dataset.i;
    render();
    $("#content").scrollTop = 0;
  }));
  const cur = state.sections[state.active];
  if (!cur) { $("#content").innerHTML = ""; return; }
  let html = `<h2>${esc(cur.title)}</h2>` + cur.subsections.map(renderSub).join("");
  const q = state.search.trim();
  if (q) html = highlight(html, q);
  $("#content").innerHTML = html;
}

function renderSub(sub) {
  const head = sub.title ? `<h3>${esc(sub.title)}</h3>` : "";
  return head + renderBlocks(sub.lines || []);
}

// Block-aware renderer: walks the lines and groups multi-line constructs
// (fenced code, blockquotes, tables, lists) so each becomes a real block
// with the right interactive affordance instead of a stream of <p>s.
function renderBlocks(lines) {
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const raw = lines[i];
    const t = raw.trim();

    // Fenced code block ``` … ``` → copyable <pre> snippet.
    if (t.startsWith("```")) {
      const buf = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) { buf.push(lines[i]); i++; }
      i++; // skip closing fence
      out.push(snippet("code", buf.join("\n")));
      continue;
    }

    // Blockquote (one or more > lines) → copyable message card. These are
    // the canonical templates (DocuSign message, apology note, adjuster
    // walk-through) — the whole point of the copy button.
    if (t.startsWith(">")) {
      const buf = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) {
        buf.push(lines[i].trim().replace(/^>\s?/, ""));
        i++;
      }
      out.push(snippet("quote", buf.join("\n")));
      continue;
    }

    // Markdown table (consecutive | … | lines).
    if (t.startsWith("|") && t.endsWith("|")) {
      const buf = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) { buf.push(lines[i].trim()); i++; }
      out.push(renderTable(buf));
      continue;
    }

    // Unordered list / checklist (consecutive - lines).
    if (t.startsWith("- ")) {
      const items = [];
      while (i < lines.length && lines[i].trim().startsWith("- ")) {
        items.push(listItem(lines[i].trim().slice(2)));
        i++;
      }
      out.push(`<ul>${items.join("")}</ul>`);
      continue;
    }

    // Ordered list (consecutive N. lines).
    if (/^\d+\.\s/.test(t)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s/.test(lines[i].trim())) {
        items.push(`<li>${formatInline(lines[i].trim().replace(/^\d+\.\s/, ""))}</li>`);
        i++;
      }
      out.push(`<ol>${items.join("")}</ol>`);
      continue;
    }

    if (!t) { i++; continue; }           // blank line
    out.push(`<p>${formatInline(t)}</p>`); // paragraph
    i++;
  }
  return out.join("\n");
}

// A copyable card: a header bar with a 📋 Copy button + the rendered body.
// kind="code" keeps text verbatim (folder trees); kind="quote" copies the
// plain-text message (markdown bold/italic stripped) so it pastes clean
// into Teams / email.
function snippet(kind, raw) {
  const payload = kind === "code" ? raw : plain(raw);
  const enc = encodeURIComponent(payload);
  const body = kind === "code"
    ? `<pre class="snip-pre">${esc(raw)}</pre>`
    : `<blockquote class="snip-quote">${raw.split("\n").map(formatInline).join("<br/>")}</blockquote>`;
  const tag = kind === "code" ? "📄 snippet" : "💬 message";
  return `<div class="snippet snippet-${kind}">
    <div class="snippet-bar">
      <span class="snippet-tag">${tag}</span>
      <button type="button" class="copy-btn" data-copy="${enc}">📋 Copy</button>
    </div>${body}</div>`;
}

function renderTable(rows) {
  const cells = (r) => r.replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
  // Drop the |---|---| separator row(s).
  const real = rows.filter((r) => !/^\|[\s:|-]+\|$/.test(r));
  if (!real.length) return "";
  const header = cells(real[0]);
  const thead = `<thead><tr>${header.map((h) => `<th>${formatInline(h)}</th>`).join("")}</tr></thead>`;
  const tbody = `<tbody>${real.slice(1).map((r) => {
    const c = cells(r);
    return `<tr>${c.map((x) => `<td>${formatInline(x)}</td>`).join("")}</tr>`;
  }).join("")}</tbody>`;
  return `<div class="table-wrap"><table class="cheat-table">${thead}${tbody}</table></div>`;
}

function listItem(s) {
  let cls = "", prefix = "";
  const m = s.match(/^\[([ xX])\]\s+(.*)$/);
  if (m) {
    const checked = m[1].toLowerCase() === "x";
    prefix = `<span class="chk">${checked ? "☑" : "☐"}</span> `;
    cls = checked ? "chk-item done" : "chk-item todo";
    s = m[2];
  }
  return `<li class="${cls}">${prefix}${formatInline(s)}</li>`;
}

// Inline markdown. Every `code` span becomes click-to-copy — that's how the
// short canonical values + the contents Trello comments get a copy button
// without cluttering each line with a separate button.
function formatInline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, (_m, c) =>
      `<code class="copyable" data-copy="${encodeURIComponent(decodeEnt(c))}" title="Click to copy">${c}</code>`)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
}

// Strip markdown emphasis/backticks for clipboard payloads (placeholders
// like <CITYOFPROPERTY> are preserved intentionally).
function plain(s) {
  return String(s)
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1");
}

function highlight(html, q) {
  if (!q) return html;
  const re = new RegExp("(" + q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig");
  // Only touch visible text (between > and <) so search never corrupts a
  // tag or a data-copy attribute value.
  return html.replace(/>([^<]+)</g, (_m, text) =>
    ">" + text.replace(re, "<mark>$1</mark>") + "<");
}

function decodeEnt(s) {
  return String(s)
    .replaceAll("&amp;", "&").replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">").replaceAll("&quot;", '"');
}

function esc(s) {
  return String(s ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}
