import {
  createRestaurant,
  downloadCsv,
  getAuthMe,
  getCountSessions,
  getDashboardSummary,
  getReport,
  getRestaurants,
  setSelectedRestaurantId,
} from "./api.js";
import { isSupabaseConfigured, supabase } from "./supabaseClient.js";
import { bindSidebar, renderSidebar } from "./sidebar.js";

const app = document.querySelector("#dashboard-app");

const state = {
  restaurantName: "Your Restaurant",
  phase: "loading", // loading | ready | error
  error: "",
  data: null,
  activeTab: getDashboardTabFromHash(),
  restaurants: [],
  setupRestaurantName: "",
  setupLoading: false,
  userEmail: "",
  countSessions: [],
  countsLoading: false,
  countsError: "",
  selectedCountId: null,
  selectedReport: null,
  reportLoading: false,
  reportError: "",
  exportLoading: false,
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function formatCountDay(value) {
  if (!value) return "Unscheduled";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unscheduled";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(date);
}

function formatCountMonth(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    year: "numeric",
  }).format(date);
}

function formatCountTime(value) {
  if (!value) return "No time";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "No time";
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function getDashboardTabFromHash() {
  return window.location.hash.replace("#", "").trim().toLowerCase() === "past-counts" ? "past-counts" : "overview";
}

function setDashboardTab(tab, countId = null) {
  state.activeTab = tab;
  if (countId) {
    state.selectedCountId = Number(countId);
  }
  if (tab === "past-counts") {
    if (window.location.hash !== "#past-counts") {
      window.location.hash = "past-counts";
    } else {
      renderShell();
    }
    if (!state.countSessions.length && !state.countsLoading) {
      loadPastCounts({ selectCountId: countId || state.selectedCountId });
    } else if (state.selectedCountId) {
      loadSelectedReport(state.selectedCountId);
    }
    return;
  }
  if (window.location.hash) {
    window.location.hash = "";
  } else {
    renderShell();
  }
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
}

function formatQty(value) {
  return Number.isInteger(value) ? String(value) : String(value);
}

async function logout() {
  try {
    await supabase.auth.signOut();
  } catch {
    // ignore; navigate to the auth page regardless
  }
  setSelectedRestaurantId("");
  window.location.assign("./product.html");
}

function goToLogin() {
  window.location.assign("./product.html");
}

async function initialize() {
  state.phase = "loading";
  renderShell();

  if (!isSupabaseConfigured) {
    goToLogin();
    return;
  }

  let session = null;
  try {
    const { data } = await supabase.auth.getSession();
    session = data.session;
  } catch {
    goToLogin();
    return;
  }
  if (!session) {
    goToLogin();
    return;
  }
  state.userEmail = session.user?.email || "";

  try {
    state.restaurants = await getRestaurants();
  } catch (error) {
    if (error.status === 401) {
      goToLogin();
      return;
    }
    state.phase = "error";
    state.error = error.message || "Could not load your restaurants.";
    renderShell();
    return;
  }

  if (!state.restaurants.length) {
    setSelectedRestaurantId("");
    state.phase = "setup-restaurant";
    renderRestaurantSetup();
    return;
  }

  if (state.restaurants.length > 1) {
    setSelectedRestaurantId("");
    state.phase = "select-restaurant";
    renderRestaurantChooser();
    return;
  }

  setSelectedRestaurantId(state.restaurants[0].id);

  // Confirm the workspace. Workspace provisioning/setup lives on product.html,
  // so send the user there if they are not yet linked.
  try {
    const me = await getAuthMe();
    state.restaurantName = me?.restaurant?.name || state.restaurantName;
  } catch (error) {
    if (error.status === 401 || error.status === 404) {
      goToLogin();
      return;
    }
    // Backend reachable problem but still signed in: show the shell with an error.
    state.restaurantName = state.restaurantName;
  }

  renderShell();
  loadSummary();
}

window.addEventListener("hashchange", () => {
  state.activeTab = getDashboardTabFromHash();
  renderShell();
  if (state.activeTab === "past-counts") {
    if (!state.countSessions.length && !state.countsLoading) {
      loadPastCounts({ selectCountId: state.selectedCountId });
    } else if (state.selectedCountId) {
      loadSelectedReport(state.selectedCountId);
    }
  }
});

async function submitRestaurantSetup(event) {
  event.preventDefault();
  const name = document.querySelector("#dashboard-restaurant-name")?.value.trim() || state.setupRestaurantName.trim();
  if (!name) {
    state.phase = "setup-restaurant";
    state.error = "Enter your restaurant name.";
    renderRestaurantSetup();
    return;
  }

  state.setupRestaurantName = name;
  state.setupLoading = true;
  state.error = "";
  renderRestaurantSetup();

  try {
    const restaurant = await createRestaurant(name);
    setSelectedRestaurantId(restaurant.id);
    state.restaurants = [restaurant];
    state.restaurantName = restaurant.name || state.restaurantName;
    state.phase = "loading";
    renderShell();
    await loadSummary();
  } catch (error) {
    state.phase = "setup-restaurant";
    state.error = error.message || "Could not create your restaurant workspace.";
  } finally {
    state.setupLoading = false;
    if (state.phase === "setup-restaurant") {
      renderRestaurantSetup();
    }
  }
}

async function selectRestaurant(restaurantId) {
  const restaurant = state.restaurants.find((item) => String(item.id) === String(restaurantId));
  if (!restaurant) return;
  setSelectedRestaurantId(restaurant.id);
  state.restaurantName = restaurant.name || state.restaurantName;
  state.countSessions = [];
  state.selectedCountId = null;
  state.selectedReport = null;
  state.phase = "loading";
  renderShell();
  loadSummary();
}

async function loadPastCounts({ selectCountId = null } = {}) {
  state.countsLoading = true;
  state.countsError = "";
  renderShell();
  try {
    const sessions = await getCountSessions();
    state.countSessions = [...sessions].sort((a, b) => {
      const bTime = new Date(b.started_at || 0).getTime();
      const aTime = new Date(a.started_at || 0).getTime();
      return bTime - aTime || Number(b.id) - Number(a.id);
    });
    const preferredId = selectCountId || state.selectedCountId || state.countSessions[0]?.id || null;
    state.selectedCountId = preferredId ? Number(preferredId) : null;
    if (state.selectedCountId) {
      await loadSelectedReport(state.selectedCountId, { renderBefore: false });
    } else {
      state.selectedReport = null;
    }
  } catch (error) {
    state.countsError = error.message || "Could not load past counts.";
  } finally {
    state.countsLoading = false;
    renderShell();
  }
}

async function loadSelectedReport(countId, { renderBefore = true } = {}) {
  if (!countId) return;
  state.selectedCountId = Number(countId);
  state.reportLoading = true;
  state.reportError = "";
  if (renderBefore) renderShell();
  try {
    state.selectedReport = await getReport(countId);
  } catch (error) {
    state.selectedReport = null;
    state.reportError = error.message || "Could not load this count.";
  } finally {
    state.reportLoading = false;
    renderShell();
  }
}

async function exportSelectedCount() {
  if (!state.selectedCountId || state.exportLoading) return;
  state.exportLoading = true;
  renderShell();
  try {
    await downloadCsv(state.selectedCountId);
    await loadSummary();
  } catch (error) {
    state.reportError = error.message || "CSV export failed.";
    renderShell();
  } finally {
    state.exportLoading = false;
    renderShell();
  }
}

function renderRestaurantChooser() {
  app.innerHTML = `
    <main class="restaurant-select-shell">
      <section class="restaurant-select-panel">
        <a href="./index.html" class="product-logo">Koe</a>
        <div class="restaurant-select-copy">
          <h1>Choose a restaurant</h1>
          <p>Select the workspace you want to open.</p>
        </div>
        <div class="restaurant-choice-list">
          ${state.restaurants
            .map(
              (restaurant) => `
                <button class="restaurant-choice-button" data-restaurant-id="${restaurant.id}" type="button">
                  <span>
                    <strong>${escapeHtml(restaurant.name)}</strong>
                    <small>${escapeHtml(restaurant.location || "Restaurant workspace")}</small>
                  </span>
                  <i aria-hidden="true">→</i>
                </button>
              `,
            )
            .join("")}
        </div>
      </section>
    </main>
  `;
  document.querySelectorAll(".restaurant-choice-button").forEach((button) => {
    button.addEventListener("click", () => selectRestaurant(button.dataset.restaurantId));
  });
}

function renderRestaurantSetup() {
  app.innerHTML = `
    <main class="restaurant-select-shell">
      <section class="restaurant-select-panel">
        <a href="./index.html" class="product-logo">Koe</a>
        <div class="restaurant-select-copy">
          <h1>Set up your restaurant</h1>
          <p>${escapeHtml(state.userEmail || "This Google account")} is signed in. Add your restaurant workspace to open the dashboard.</p>
        </div>
        <form class="dashboard-setup-form" id="dashboard-setup-form">
          <label for="dashboard-restaurant-name">
            <span>Name of Restaurant</span>
            <input id="dashboard-restaurant-name" type="text" autocomplete="organization" placeholder="Restaurant name" value="${escapeHtml(state.setupRestaurantName)}" ${state.setupLoading ? "disabled" : ""} required />
          </label>
          ${state.error ? `<p class="message message--error">${escapeHtml(state.error)}</p>` : ""}
          <button class="new-count-button" type="submit" ${state.setupLoading ? "disabled" : ""}>
            ${state.setupLoading ? "Creating workspace..." : "Continue to Dashboard"}
          </button>
        </form>
        <button class="ghost-button dashboard-logout-button" id="dashboard-setup-logout" type="button">Use a different login</button>
      </section>
    </main>
  `;
  document.querySelector("#dashboard-setup-form")?.addEventListener("submit", submitRestaurantSetup);
  document.querySelector("#dashboard-setup-logout")?.addEventListener("click", logout);
}

async function loadSummary() {
  state.phase = "loading";
  state.error = "";
  renderShell();
  try {
    state.data = await getDashboardSummary();
    state.selectedCountId =
      state.selectedCountId || state.data?.export_status?.count_id || state.data?.last_count_summary?.count_id || null;
    state.phase = "ready";
  } catch (error) {
    state.phase = "error";
    state.error = error.message || "Could not load the dashboard.";
  }
  renderShell();
  if (state.phase === "ready" && state.activeTab === "past-counts") {
    loadPastCounts({ selectCountId: state.selectedCountId });
  }
}

function renderShell() {
  app.innerHTML = `
    <div class="app-shell">
      ${renderSidebar({ restaurantName: state.restaurantName, active: "dashboard" })}
      <main class="app-main dashboard-main">
        ${renderContent()}
      </main>
    </div>
  `;
  bindSidebar({ onLogout: logout });
  document.querySelector("#dashboard-retry")?.addEventListener("click", loadSummary);
  document.querySelectorAll(".dashboard-tab").forEach((button) => {
    button.addEventListener("click", () => setDashboardTab(button.dataset.tab));
  });
  document.querySelectorAll(".past-count-item").forEach((button) => {
    button.addEventListener("click", () => loadSelectedReport(button.dataset.countId));
  });
  document.querySelector("#dashboard-open-latest")?.addEventListener("click", () => {
    const countId = document.querySelector("#dashboard-open-latest")?.dataset.countId || state.selectedCountId;
    setDashboardTab("past-counts", countId);
  });
  document.querySelector("#past-count-export")?.addEventListener("click", exportSelectedCount);
  document.querySelector("#past-count-refresh")?.addEventListener("click", () => loadPastCounts({ selectCountId: state.selectedCountId }));
}

function renderContent() {
  if (state.phase === "loading") {
    return `
      <div class="dashboard-status">
        <div class="dashboard-spinner" aria-hidden="true"></div>
        <p>Loading your dashboard…</p>
      </div>
    `;
  }

  if (state.phase === "error") {
    return `
      <div class="dashboard-status">
        <h1>We couldn't load your dashboard</h1>
        <p class="dashboard-status-detail">${escapeHtml(state.error)}</p>
        <button class="new-count-button" id="dashboard-retry" type="button">Try again</button>
      </div>
    `;
  }

  const data = state.data || {};
  return `
    <header class="dashboard-header">
      <h1>Dashboard</h1>
      <p>${escapeHtml(state.restaurantName)}</p>
    </header>
    ${renderDashboardTabs()}
    ${state.activeTab === "past-counts" ? renderPastCounts() : renderOverviewContent(data)}
  `;
}

function renderDashboardTabs() {
  return `
    <nav class="dashboard-tabs" aria-label="Dashboard sections">
      <button class="dashboard-tab ${state.activeTab === "overview" ? "is-active" : ""}" data-tab="overview" type="button">
        Overview
      </button>
      <button class="dashboard-tab ${state.activeTab === "past-counts" ? "is-active" : ""}" data-tab="past-counts" type="button">
        Past Counts
      </button>
    </nav>
  `;
}

function renderOverviewContent(data) {
  const hasEverCounted = Boolean(data.last_count_summary);

  if (!hasEverCounted) {
    return `
      <div class="dashboard-empty">
        <h2>Welcome to Koe</h2>
        <p>Start your first inventory count</p>
        <a class="new-count-button" href="./product.html">Start Count</a>
      </div>
    `;
  }

  return `
    ${renderMobileDashboardPanel(data)}
    ${renderLowStock(data.low_stock_items || [])}
    ${renderLastCount(data.last_count_summary)}
    ${renderChanges(data.count_over_count_changes || [])}
    ${renderDataQuality(data.data_quality_insights || [])}
    ${renderExportStatus(data.export_status || {})}
    <div class="dashboard-cta">
      <a class="new-count-button" href="./product.html">New count</a>
    </div>
  `;
}

function renderPastCounts() {
  const sessions = state.countSessions;
  const selectedSession = sessions.find((session) => Number(session.id) === Number(state.selectedCountId)) || sessions[0] || null;
  const monthLabel = formatCountMonth(selectedSession?.started_at || sessions[0]?.started_at);

  if (state.countsLoading && !sessions.length) {
    return `
      <section class="past-counts-shell">
        <div class="dashboard-status past-counts-loading">
          <div class="dashboard-spinner" aria-hidden="true"></div>
          <p>Loading count history...</p>
        </div>
      </section>
    `;
  }

  if (state.countsError) {
    return `
      <section class="past-counts-shell">
        <div class="dashboard-status past-counts-loading">
          <h1>Count history is unavailable</h1>
          <p class="dashboard-status-detail">${escapeHtml(state.countsError)}</p>
          <button class="new-count-button" id="past-count-refresh" type="button">Try again</button>
        </div>
      </section>
    `;
  }

  if (!sessions.length) {
    return `
      <section class="past-counts-shell">
        <div class="past-count-empty">
          <span>Past Counts</span>
          <h2>No saved counts yet</h2>
          <p>Run a count from the Count workspace. Koe will save it here by date so managers can review the spreadsheet later.</p>
          <a class="new-count-button" href="./product.html">Start Count</a>
        </div>
      </section>
    `;
  }

  return `
    <section class="past-counts-shell">
      <aside class="past-counts-calendar" aria-label="Past count dates">
        <div class="past-counts-calendar-header">
          <span>Count History</span>
          <strong>${escapeHtml(monthLabel || "Recent")}</strong>
        </div>
        <div class="past-count-list">
          ${sessions.map((session) => renderPastCountListItem(session)).join("")}
        </div>
      </aside>
      <section class="past-counts-detail">
        ${renderSelectedCountDetail(selectedSession)}
      </section>
    </section>
  `;
}

function renderPastCountListItem(session) {
  const isActive = Number(session.id) === Number(state.selectedCountId);
  const entryCount = session.summary?.total_entries ?? null;
  const reviewCount = session.summary?.entries_needing_review ?? null;
  return `
    <button class="past-count-item ${isActive ? "is-active" : ""}" data-count-id="${session.id}" type="button">
      <span class="past-count-date">
        <strong>${escapeHtml(formatCountDay(session.started_at))}</strong>
        <small>${escapeHtml(formatCountTime(session.started_at))}</small>
      </span>
      <span class="past-count-meta">
        <b>${escapeHtml(session.area || "Not set")}</b>
        <small>${entryCount === null ? "Open spreadsheet" : `${entryCount} rows${reviewCount ? ` • ${reviewCount} review` : ""}`}</small>
      </span>
    </button>
  `;
}

function renderSelectedCountDetail(session) {
  if (!session) return "";
  const report = state.selectedReport;
  const entries = report?.entries || [];
  const summary = report?.summary || {};
  return `
    <div class="past-count-detail-header">
      <div>
        <span>${escapeHtml(formatDateTime(session.started_at))}</span>
        <h2>${escapeHtml(session.area || "Inventory Count")}</h2>
        <p>Saved count #${escapeHtml(session.id)}${session.status ? ` • ${escapeHtml(session.status)}` : ""}</p>
      </div>
      <button class="report-button report-button--primary" id="past-count-export" type="button" ${state.exportLoading || !entries.length ? "disabled" : ""}>
        ${state.exportLoading ? "Exporting..." : "Export CSV"}
      </button>
    </div>
    <dl class="past-count-summary">
      <div><dt>Rows</dt><dd>${summary.total_items ?? entries.length}</dd></div>
      <div><dt>Needs review</dt><dd>${summary.items_needing_review ?? 0}</dd></div>
      <div><dt>Area</dt><dd>${escapeHtml(session.area || "Not set")}</dd></div>
      <div><dt>Started</dt><dd>${escapeHtml(formatCountTime(session.started_at))}</dd></div>
    </dl>
    ${renderPastCountSpreadsheet(entries)}
  `;
}

function renderPastCountSpreadsheet(entries) {
  if (state.reportLoading) {
    return `
      <div class="past-count-spreadsheet past-count-spreadsheet--state">
        <div class="dashboard-spinner" aria-hidden="true"></div>
        <p>Opening spreadsheet...</p>
      </div>
    `;
  }

  if (state.reportError) {
    return `
      <div class="past-count-spreadsheet past-count-spreadsheet--state">
        <h3>Could not open this count</h3>
        <p>${escapeHtml(state.reportError)}</p>
      </div>
    `;
  }

  if (!entries.length) {
    return `
      <div class="past-count-spreadsheet past-count-spreadsheet--state">
        <h3>No rows saved for this count</h3>
        <p>Counts appear here after inventory rows have been processed and saved.</p>
      </div>
    `;
  }

  return `
    <div class="past-count-spreadsheet" role="region" aria-label="Selected count spreadsheet" tabindex="0">
      <table>
        <thead>
          <tr>
            <th>Item</th>
            <th>Qty</th>
            <th>Unit</th>
            <th>Status</th>
            <th>Original phrase</th>
            <th>Counted by</th>
          </tr>
        </thead>
        <tbody>
          ${entries
            .map(
              (entry) => `
                <tr>
                  <td>
                    <strong>${escapeHtml(entry.item_name_clean || "Unnamed item")}</strong>
                    <small>${escapeHtml(entry.item_name_raw || "")}</small>
                  </td>
                  <td>${escapeHtml(formatQty(entry.quantity ?? ""))}</td>
                  <td>${escapeHtml(entry.unit || "")}</td>
                  <td><span class="status-pill ${statusClass(entry.status)}">${escapeHtml(entry.status || "Clean")}</span></td>
                  <td>${escapeHtml(entry.original_phrase || "")}</td>
                  <td>${escapeHtml(entry.counted_by || "—")}</td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function statusClass(status) {
  const normalized = String(status || "Clean").toLowerCase();
  if (normalized.includes("review") || normalized.includes("missing") || normalized.includes("duplicate")) return "status-pill--review";
  if (normalized.includes("partial")) return "status-pill--partial";
  if (normalized.includes("converted")) return "status-pill--converted";
  return "status-pill--clean";
}

function renderMobileDashboardPanel(data) {
  const summary = data.last_count_summary || {};
  const insights = data.data_quality_insights || [];
  const partialCount = insights.filter((line) => /partial/i.test(String(line))).length;
  return `
    <section class="mobile-dashboard-panel" aria-label="Mobile count summary">
      <div class="mobile-dashboard-heading">
        <span>${escapeHtml(state.restaurantName)}</span>
        <h2>Last count</h2>
      </div>
      <dl>
        <div><dt>Items counted</dt><dd>${summary.total_items_counted ?? 0}</dd></div>
        <div><dt>Needs review</dt><dd>${summary.needs_review_count ?? 0}</dd></div>
        <div><dt>Partial quantities</dt><dd>${partialCount}</dd></div>
        <div><dt>Area</dt><dd>${escapeHtml(summary.area || "Not set")}</dd></div>
      </dl>
      <a class="new-count-button" href="./product.html">Start Count</a>
    </section>
  `;
}

function renderLowStock(items) {
  if (!items.length) {
    return `
      <section class="dashboard-section">
        <h2>Low Stock Items</h2>
        <div class="dashboard-calm">All items above par level. Nothing to reorder right now.</div>
      </section>
    `;
  }

  const cards = items
    .map((item) => {
      const critical = item.par_level > 0 && item.shortfall / item.par_level >= 0.5;
      return `
        <div class="low-stock-card ${critical ? "is-critical" : ""}">
          <strong>${escapeHtml(item.item_name)}</strong>
          <div class="low-stock-meta">
            <span>${formatQty(item.current_quantity)} ${escapeHtml(item.unit)} on hand</span>
            <span>par ${formatQty(item.par_level)}</span>
          </div>
          <div class="low-stock-shortfall">Short by ${formatQty(item.shortfall)} ${escapeHtml(item.unit)}</div>
        </div>
      `;
    })
    .join("");

  return `
    <section class="dashboard-section dashboard-section--primary">
      <h2>Low Stock Items</h2>
      <div class="low-stock-grid">${cards}</div>
    </section>
  `;
}

function renderLastCount(summary) {
  if (!summary) return "";
  return `
    <section class="dashboard-section">
      <h2>Last Count</h2>
      <div class="workspace-card dashboard-card">
        <dl class="dashboard-dl">
          <div><dt>Date</dt><dd>${formatDateTime(summary.started_at)}</dd></div>
          <div><dt>Area</dt><dd>${escapeHtml(summary.area || "—")}</dd></div>
          <div><dt>Duration</dt><dd>${formatDuration(summary.duration_seconds)}</dd></div>
          <div><dt>Items counted</dt><dd>${summary.total_items_counted}</dd></div>
          <div><dt>Needs review</dt><dd>${summary.needs_review_count}</dd></div>
        </dl>
      </div>
    </section>
  `;
}

function renderChanges(changes) {
  if (!changes.length) return "";
  const rows = changes
    .map((change) => {
      const direction = change.delta > 0 ? "up" : "down";
      const sign = change.delta > 0 ? "+" : "";
      return `
        <li class="change-row">
          <span class="change-name">${escapeHtml(change.item_name)}</span>
          <span class="change-detail">${formatQty(change.previous_quantity)} → ${formatQty(change.current_quantity)} ${escapeHtml(change.unit)}</span>
          <span class="change-delta change-delta--${direction}">${sign}${formatQty(change.delta)}</span>
        </li>
      `;
    })
    .join("");
  return `
    <section class="dashboard-section">
      <h2>Changes Since Last Count</h2>
      <ul class="change-list">${rows}</ul>
    </section>
  `;
}

function renderDataQuality(insights) {
  const body = insights.length
    ? `<ul class="insight-list">${insights.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}</ul>`
    : `<div class="dashboard-calm">No data quality issues detected.</div>`;
  return `
    <section class="dashboard-section">
      <h2>Data Quality</h2>
      ${body}
    </section>
  `;
}

function renderExportStatus(status) {
  const exported = Boolean(status.exported);
  const link =
    !exported && status.count_id
      ? ` <button class="dashboard-inline-link" id="dashboard-open-latest" data-count-id="${escapeHtml(status.count_id)}" type="button">Open count</button>`
      : "";
  return `
    <section class="dashboard-section">
      <h2>Export Status</h2>
      <div class="dashboard-card export-line ${exported ? "is-exported" : ""}">
        ${exported ? "Last count exported." : "Last count not yet exported."}${link}
      </div>
    </section>
  `;
}

initialize();
