/* EMS Tools — skeleton helper. Returns HTML for N placeholder rows. */
(function () {
  "use strict";
  function mkSkeletonRows(n) {
    n = Math.max(1, Math.min(20, parseInt(n || 6, 10)));
    let out = "";
    for (let i = 0; i < n; i++) {
      out += `<div class="ems-skel-row ems-skel"></div>`;
    }
    return out;
  }
  function mkSkeletonCard() {
    return `<div style="padding:10px 14px;background:var(--surface,#1A1A1A);
                       border:1px solid var(--border,#2A2A2A);border-radius:6px;
                       margin-bottom:8px;">
      <div class="ems-skel ems-skel-title"></div>
      <div class="ems-skel ems-skel-sub"></div>
      <div style="margin-top:8px;">
        <span class="ems-skel ems-skel-chip"></span>
        <span class="ems-skel ems-skel-chip"></span>
      </div>
    </div>`;
  }
  window.mkSkeletonRows = mkSkeletonRows;
  window.mkSkeletonCard = mkSkeletonCard;
})();
