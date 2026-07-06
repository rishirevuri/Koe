// Shared left sidebar used on all authenticated pages (dashboard + count).
// Rendered as a string so it drops into each page's existing render() flow.

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function icon(name) {
  const icons = {
    grid: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1.5"></rect><rect x="14" y="3" width="7" height="7" rx="1.5"></rect><rect x="3" y="14" width="7" height="7" rx="1.5"></rect><rect x="14" y="14" width="7" height="7" rx="1.5"></rect></svg>`,
    mic: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z"></path><path d="M5 11a7 7 0 0 0 14 0"></path><path d="M12 18v3"></path></svg>`,
    logout: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 12H4"></path><path d="M8 8l-4 4 4 4"></path><path d="M13 4h6v16h-6"></path></svg>`,
  };
  return icons[name] || "";
}

/**
 * @param {{ restaurantName: string, active: "dashboard" | "count" }} options
 */
export function renderSidebar({ restaurantName, active }) {
  return `
    <button class="sidebar-toggle" id="sidebar-toggle" type="button" aria-label="Toggle navigation">
      <span></span><span></span><span></span>
    </button>
    <div class="sidebar-scrim" id="sidebar-scrim" aria-hidden="true"></div>
    <aside class="sidebar" aria-label="Primary navigation">
      <div class="sidebar-head">
        <a class="sidebar-logo" href="./dashboard.html">Koe</a>
        <a class="sidebar-restaurant" href="./dashboard.html" title="${escapeHtml(restaurantName)}">${escapeHtml(restaurantName || "Your Restaurant")}</a>
      </div>
      <nav class="sidebar-nav">
        <a class="sidebar-link ${active === "dashboard" ? "is-active" : ""}" href="./dashboard.html" ${active === "dashboard" ? 'aria-current="page"' : ""}>
          ${icon("grid")}<span>Dashboard</span>
        </a>
        <a class="sidebar-link ${active === "count" ? "is-active" : ""}" href="./product.html" ${active === "count" ? 'aria-current="page"' : ""}>
          ${icon("mic")}<span>Initiate Count</span>
        </a>
      </nav>
      <button class="sidebar-logout" id="sidebar-logout" type="button">
        ${icon("logout")}<span>Log Out</span>
      </button>
    </aside>
  `;
}

/**
 * Wire up sidebar interactions. Call after each render that includes the sidebar.
 * @param {{ onLogout: () => void }} handlers
 */
export function bindSidebar({ onLogout }) {
  const shell = document.querySelector(".app-shell");
  const close = () => shell?.classList.remove("sidebar-open");

  document.querySelector("#sidebar-toggle")?.addEventListener("click", () => {
    shell?.classList.toggle("sidebar-open");
  });
  document.querySelector("#sidebar-scrim")?.addEventListener("click", close);
  document.querySelectorAll(".sidebar-link").forEach((link) => link.addEventListener("click", close));
  document.querySelector("#sidebar-logout")?.addEventListener("click", () => {
    close();
    onLogout?.();
  });
}
