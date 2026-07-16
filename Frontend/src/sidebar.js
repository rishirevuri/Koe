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
    report: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3h7l5 5v13H7z"></path><path d="M14 3v6h5"></path><path d="M9 14h6M9 17h4"></path></svg>`,
    account: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3.5"></circle><path d="M5 20c1.4-3.4 3.7-5 7-5s5.6 1.6 7 5"></path></svg>`,
    logout: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 12H4"></path><path d="M8 8l-4 4 4 4"></path><path d="M13 4h6v16h-6"></path></svg>`,
    collapse: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 6l-6 6 6 6"></path></svg>`,
  };
  return icons[name] || "";
}

/**
 * @param {{ restaurantName: string, active: "dashboard" | "count", mobileActive?: "dashboard" | "count" | "reports" | "account" }} options
 */
export function renderSidebar({ restaurantName, active, mobileActive = active }) {
  return `
    <button class="sidebar-toggle" id="sidebar-toggle" type="button" aria-label="Toggle navigation">
      <span></span><span></span><span></span>
    </button>
    <div class="sidebar-scrim" id="sidebar-scrim" aria-hidden="true"></div>
    <aside class="sidebar" aria-label="Primary navigation">
      <div class="sidebar-head">
        <a class="sidebar-logo" href="./dashboard.html">Koe</a>
        <a class="sidebar-restaurant" href="./dashboard.html" title="${escapeHtml(restaurantName)}">${escapeHtml(restaurantName || "Your Restaurant")}</a>
        <button class="sidebar-collapse" id="sidebar-collapse" type="button" aria-label="Collapse navigation" title="Collapse navigation">
          ${icon("collapse")}
        </button>
      </div>
      <nav class="sidebar-nav">
        <a class="sidebar-link ${active === "dashboard" ? "is-active" : ""}" href="./dashboard.html" title="Dashboard" ${active === "dashboard" ? 'aria-current="page"' : ""}>
          ${icon("grid")}<span>Dashboard</span>
        </a>
        <a class="sidebar-link ${active === "count" ? "is-active" : ""}" href="./product.html" title="Count" ${active === "count" ? 'aria-current="page"' : ""}>
          ${icon("mic")}<span>Count</span>
        </a>
      </nav>
      <button class="sidebar-logout" id="sidebar-logout" type="button" title="Exit">
        ${icon("logout")}<span>Exit</span>
      </button>
    </aside>
    <nav class="mobile-bottom-nav" aria-label="Mobile navigation">
      <a class="mobile-bottom-link ${mobileActive === "dashboard" ? "is-active" : ""}" href="./dashboard.html" ${mobileActive === "dashboard" ? 'aria-current="page"' : ""}>
        ${icon("grid")}<span>Dashboard</span>
      </a>
      <a class="mobile-bottom-link ${mobileActive === "count" ? "is-active" : ""}" href="./product.html#count" ${mobileActive === "count" ? 'aria-current="page"' : ""}>
        ${icon("mic")}<span>Count</span>
      </a>
      <a class="mobile-bottom-link ${mobileActive === "reports" ? "is-active" : ""}" href="./dashboard.html#past-counts" ${mobileActive === "reports" ? 'aria-current="page"' : ""}>
        ${icon("report")}<span>Reports</span>
      </a>
      <a class="mobile-bottom-link ${mobileActive === "account" ? "is-active" : ""}" href="./product.html#account" ${mobileActive === "account" ? 'aria-current="page"' : ""}>
        ${icon("account")}<span>Account</span>
      </a>
    </nav>
  `;
}

/**
 * Wire up sidebar interactions. Call after each render that includes the sidebar.
 * @param {{ onLogout: () => void }} handlers
 */
export function bindSidebar({ onLogout }) {
  const shell = document.querySelector(".app-shell");
  const collapseButton = document.querySelector("#sidebar-collapse");
  const close = () => shell?.classList.remove("sidebar-open");
  const setCollapsed = (collapsed) => {
    shell?.classList.toggle("sidebar-collapsed", collapsed);
    collapseButton?.setAttribute("aria-label", collapsed ? "Expand navigation" : "Collapse navigation");
    collapseButton?.setAttribute("title", collapsed ? "Expand navigation" : "Collapse navigation");
    window.localStorage.setItem("koe:sidebarCollapsed", collapsed ? "1" : "0");
  };

  setCollapsed(window.localStorage.getItem("koe:sidebarCollapsed") === "1");

  document.querySelector("#sidebar-toggle")?.addEventListener("click", () => {
    shell?.classList.toggle("sidebar-open");
  });
  collapseButton?.addEventListener("click", () => {
    setCollapsed(!shell?.classList.contains("sidebar-collapsed"));
  });
  document.querySelector("#sidebar-scrim")?.addEventListener("click", close);
  document.querySelectorAll(".sidebar-link").forEach((link) => link.addEventListener("click", close));
  document.querySelector("#sidebar-logout")?.addEventListener("click", () => {
    close();
    onLogout?.();
  });
}
