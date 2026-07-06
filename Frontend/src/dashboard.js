import { getAuthMe, getDashboardSummary } from "./api.js";
import { isSupabaseConfigured, supabase } from "./supabaseClient.js";
import { bindSidebar, renderSidebar } from "./sidebar.js";

const app = document.querySelector("#dashboard-app");

const state = {
  restaurantName: "Your Restaurant",
  phase: "loading", // loading | ready | error
  error: "",
  data: null,
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
  window.location.assign("./product.html");
}

function goToLogin() {
  window.location.assign("./product.html");
}

async function initialize() {
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

async function loadSummary() {
  state.phase = "loading";
  state.error = "";
  renderShell();
  try {
    state.data = await getDashboardSummary();
    state.phase = "ready";
  } catch (error) {
    state.phase = "error";
    state.error = error.message || "Could not load the dashboard.";
  }
  renderShell();
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
        <button class="new-count-button" id="dashboard-retry" type="button">Retry</button>
      </div>
    `;
  }

  const data = state.data || {};
  const hasEverCounted = Boolean(data.last_count_summary);

  if (!hasEverCounted) {
    return `
      <header class="dashboard-header">
        <h1>Welcome to Koe</h1>
        <p>Your manager dashboard will fill in once you run your first inventory count.</p>
      </header>
      <div class="dashboard-empty">
        <p>No counts yet. Start your first count and Koe will surface low-stock items, changes over time, and data-quality checks here.</p>
        <a class="new-count-button" href="./product.html">Start New Count</a>
      </div>
    `;
  }

  return `
    <header class="dashboard-header">
      <h1>Dashboard</h1>
      <p>${escapeHtml(state.restaurantName)}</p>
    </header>
    ${renderLowStock(data.low_stock_items || [])}
    ${renderLastCount(data.last_count_summary)}
    ${renderChanges(data.count_over_count_changes || [])}
    ${renderDataQuality(data.data_quality_insights || [])}
    ${renderExportStatus(data.export_status || {})}
    <div class="dashboard-cta">
      <a class="new-count-button" href="./product.html">Start New Count</a>
    </div>
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
      ? ` <a class="dashboard-inline-link" href="./product.html">Open count to export</a>`
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
