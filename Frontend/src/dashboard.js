import {
  createRestaurant,
  deleteCountSession,
  downloadCsv,
  getAuthMe,
  getCountSessions,
  getDashboardSummary,
  getReport,
  getRestaurants,
  getSelectedRestaurantId,
  setSelectedRestaurantId,
} from "./api.js";
import { isSupabaseConfigured, supabase } from "./supabaseClient.js";
import { bindSidebar, renderSidebar } from "./sidebar.js";

const app = document.querySelector("#dashboard-app");
const authHandoffKey = "koe:authHandoff";
const authRedirectKey = "koe:authRedirecting";
const googleDashboardRedirectKey = "koe:googleDashboardRedirect";
const REVIEW_STATUSES = new Set(["Needs Review", "Missing Unit", "Possible Duplicate"]);
const CATEGORY_COLORS = {
  Produce: "#9fbf9f",
  "Dairy & Eggs": "#f0d980",
  Proteins: "#b98272",
  Bakery: "#d4a66a",
  "Sauces & Condiments": "#c97f5f",
  "Oils & Liquids": "#7da4b8",
  Beverages: "#8aa0c4",
  "Dry Goods": "#c79a4b",
  Frozen: "#a8d1df",
  Supplies: "#a9ada8",
  Uncategorized: "#d8d6cf",
};
const CATEGORY_FALLBACK_COLORS = ["#9fbf9f", "#f0d980", "#b98272", "#d4a66a", "#c97f5f", "#7da4b8", "#8aa0c4", "#c79a4b", "#a8d1df", "#a9ada8"];
const CATEGORY_ORDER = ["Produce", "Dairy & Eggs", "Proteins", "Bakery", "Sauces & Condiments", "Oils & Liquids", "Beverages", "Frozen", "Supplies", "Dry Goods", "Uncategorized"];

const state = {
  restaurantName: "Your Restaurant",
  phase: "loading", // loading | ready | error | select-restaurant
  error: "",
  data: null,
  activeTab: getDashboardTabFromHash(),
  restaurants: [],
  userEmail: "",
  countSessions: [],
  countsLoading: false,
  countsError: "",
  selectedCountId: null,
  selectedReport: null,
  reportLoading: false,
  reportError: "",
  expandedCountYearKey: "",
  expandedCountMonthKey: "",
  deleteTargetCountId: null,
  deleteLoading: false,
  deleteError: "",
  latestReport: null,
  latestReportLoading: false,
  latestReportError: "",
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

function formatCountMonthLong(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, {
    month: "long",
    year: "numeric",
  }).format(date);
}

function formatCountMonthName(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, {
    month: "long",
  }).format(date);
}

function formatCountYear(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, {
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

function getRestaurantNameFromSession(session) {
  const metadata = session?.user?.user_metadata || {};
  return String(metadata.restaurant_name || metadata.restaurantName || metadata.organization || "").trim();
}

function isAuthCallbackUrl() {
  const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const searchParams = new URLSearchParams(window.location.search);
  return Boolean(
    hashParams.get("access_token") ||
      hashParams.get("refresh_token") ||
      hashParams.get("type") ||
      searchParams.get("code"),
  );
}

function consumeGoogleDashboardRedirect() {
  try {
    const shouldRedirect = window.sessionStorage.getItem(googleDashboardRedirectKey) === "1";
    window.sessionStorage.removeItem(googleDashboardRedirectKey);
    return shouldRedirect;
  } catch {
    return false;
  }
}

function debugAuthFlow(message, details = {}) {
  if (!import.meta.env.DEV) return;
  console.log(`[koe-auth] ${message}`, details);
}

function consumeDashboardAuthRedirect() {
  try {
    const wasRedirecting = window.sessionStorage.getItem(authRedirectKey) === "1";
    window.sessionStorage.removeItem(authRedirectKey);
    return wasRedirecting;
  } catch {
    return false;
  }
}

function waitForAuthSession(timeoutMs = 1250) {
  return new Promise((resolve) => {
    let settled = false;
    let timer = null;
    let subscription = null;
    const finish = (session) => {
      if (settled) return;
      settled = true;
      if (timer) window.clearTimeout(timer);
      subscription?.unsubscribe?.();
      resolve(session || null);
    };
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      if (session) finish(session);
    });
    subscription = data?.subscription || null;
    timer = window.setTimeout(() => finish(null), timeoutMs);
  });
}

async function getSessionWithRestore() {
  let { data } = await supabase.auth.getSession();
  debugAuthFlow("dashboard getSession result", { hasSession: Boolean(data.session), phase: "initial" });
  if (data.session) return data.session;

  const authCode = new URLSearchParams(window.location.search).get("code");
  if (authCode) {
    const { data: exchanged, error } = await supabase.auth.exchangeCodeForSession(authCode);
    debugAuthFlow("dashboard code exchange result", { hasSession: Boolean(exchanged?.session), hasError: Boolean(error) });
    if (exchanged?.session) return exchanged.session;
  }

  const waitedSession = await waitForAuthSession();
  debugAuthFlow("dashboard getSession result", { hasSession: Boolean(waitedSession), phase: "after_grace" });
  if (waitedSession) return waitedSession;

  ({ data } = await supabase.auth.getSession());
  debugAuthFlow("dashboard getSession result", { hasSession: Boolean(data.session), phase: "post_grace_check" });
  if (data.session) return data.session;

  let handoff = null;
  try {
    handoff = JSON.parse(window.sessionStorage.getItem(authHandoffKey) || "null");
    window.sessionStorage.removeItem(authHandoffKey);
  } catch {
    handoff = null;
  }
  if (!handoff?.access_token || !handoff?.refresh_token) return null;

  const { data: restored, error } = await supabase.auth.setSession({
    access_token: handoff.access_token,
    refresh_token: handoff.refresh_token,
  });
  if (error) return null;
  debugAuthFlow("dashboard getSession result", { hasSession: Boolean(restored.session), phase: "handoff_fallback" });
  return restored.session || null;
}

async function returnToLogin() {
  try {
    await supabase.auth.signOut();
  } catch {
    // Ignore and still navigate to the login screen.
  }
  setSelectedRestaurantId("");
  window.location.assign("/product.html");
}

function getCountTimestamp(count) {
  return count?.completed_at || count?.started_at || null;
}

function sortCountSessions(sessions) {
  return [...(sessions || [])].sort((a, b) => {
    const bTime = new Date(getCountTimestamp(b) || 0).getTime();
    const aTime = new Date(getCountTimestamp(a) || 0).getTime();
    return bTime - aTime || Number(b.id || 0) - Number(a.id || 0);
  });
}

function getCountMonthKey(session) {
  const value = getCountTimestamp(session);
  if (!value) return "unscheduled";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unscheduled";
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function getCountMonthLabel(session) {
  const value = getCountTimestamp(session);
  return formatCountMonthName(value) || "Unscheduled";
}

function getCountYearKey(session) {
  const value = getCountTimestamp(session);
  if (!value) return "unscheduled";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unscheduled";
  return String(date.getFullYear());
}

function getCountYearLabel(session) {
  const value = getCountTimestamp(session);
  return formatCountYear(value) || "Unscheduled";
}

function groupCountSessionsByYear(sessions) {
  const yearGroups = [];
  const byYearKey = new Map();
  sortCountSessions(sessions).forEach((session) => {
    const yearKey = getCountYearKey(session);
    const monthKey = getCountMonthKey(session);
    if (!byYearKey.has(yearKey)) {
      const yearGroup = { key: yearKey, label: getCountYearLabel(session), months: [], monthMap: new Map() };
      byYearKey.set(yearKey, yearGroup);
      yearGroups.push(yearGroup);
    }
    const yearGroup = byYearKey.get(yearKey);
    if (!yearGroup.monthMap.has(monthKey)) {
      const monthGroup = { key: monthKey, label: getCountMonthLabel(session), sessions: [] };
      yearGroup.monthMap.set(monthKey, monthGroup);
      yearGroup.months.push(monthGroup);
    }
    yearGroup.monthMap.get(monthKey).sessions.push(session);
  });
  return yearGroups.map((group) => {
    const { monthMap, ...publicGroup } = group;
    return publicGroup;
  });
}

function applyCountSessions(sessions, selectCountId = null) {
  state.countSessions = sortCountSessions(sessions);
  const preferredId = selectCountId || state.selectedCountId || state.countSessions[0]?.id || null;
  const selectedExists = state.countSessions.some((session) => Number(session.id) === Number(preferredId));
  state.selectedCountId = selectedExists && preferredId ? Number(preferredId) : state.countSessions[0]?.id ? Number(state.countSessions[0].id) : null;
  if (!state.selectedCountId) {
    state.selectedReport = null;
  }
  if (state.expandedCountMonthKey && !state.countSessions.some((session) => getCountMonthKey(session) === state.expandedCountMonthKey)) {
    state.expandedCountMonthKey = "";
  }
  if (state.expandedCountYearKey && !state.countSessions.some((session) => getCountYearKey(session) === state.expandedCountYearKey)) {
    state.expandedCountYearKey = "";
  }
}

function renderTrashIcon() {
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M9 4h6"></path>
      <path d="M4 7h16"></path>
      <path d="M10 11v6"></path>
      <path d="M14 11v6"></path>
      <path d="M6 7l1 14h10l1-14"></path>
    </svg>
  `;
}

function renderChevronIcon() {
  return `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6 9l6 6 6-6"></path>
    </svg>
  `;
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
  if (value === null || value === undefined || value === "") return "—";
  return Number.isInteger(value) ? String(value) : String(value);
}

function formatNeededQuantity(value) {
  const neededQuantity = String(value ?? "").trim();
  return !neededQuantity || neededQuantity.toLowerCase() === "tbd" ? "—" : neededQuantity;
}

function getLatestCount(data = state.data) {
  return data?.last_count_summary || null;
}

function getLatestCountId(data = state.data) {
  return data?.last_count_summary?.count_id || data?.export_status?.count_id || null;
}

function getRowsForCount(countId = getLatestCountId()) {
  if (!countId || Number(state.latestReport?.count_id) !== Number(countId)) return [];
  return state.latestReport?.entries || [];
}

function isReviewStatus(status) {
  return REVIEW_STATUSES.has(status);
}

function isPartialRow(row) {
  return row?.status === "Partial Quantity" || (typeof row?.quantity === "number" && !Number.isInteger(row.quantity));
}

function normalizeCategoryLabel(value) {
  const raw = String(value || "").trim();
  if (!raw) return "Uncategorized";
  const normalized = raw.toLowerCase().replaceAll("&", "and").replaceAll("_", " ").replace(/\s+/g, " ").trim();
  const categoryMap = {
    produce: "Produce",
    "dairy eggs": "Dairy & Eggs",
    "dairy and eggs": "Dairy & Eggs",
    dairy: "Dairy & Eggs",
    eggs: "Dairy & Eggs",
    bakery: "Bakery",
    bread: "Bakery",
    meat: "Proteins",
    meats: "Proteins",
    protein: "Proteins",
    proteins: "Proteins",
    "dry goods": "Dry Goods",
    dry: "Dry Goods",
    liquid: "Oils & Liquids",
    liquids: "Oils & Liquids",
    oil: "Oils & Liquids",
    oils: "Oils & Liquids",
    "oils liquids": "Oils & Liquids",
    "oils and liquids": "Oils & Liquids",
    beverage: "Beverages",
    beverages: "Beverages",
    bar: "Beverages",
    condiment: "Sauces & Condiments",
    condiments: "Sauces & Condiments",
    sauce: "Sauces & Condiments",
    sauces: "Sauces & Condiments",
    "sauces condiments": "Sauces & Condiments",
    "sauces and condiments": "Sauces & Condiments",
    frozen: "Frozen",
    supplies: "Supplies",
    supply: "Supplies",
    other: "Uncategorized",
    uncategorized: "Uncategorized",
  };
  return categoryMap[normalized] || raw.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function firstPresentValue(...values) {
  return values.find((value) => String(value ?? "").trim());
}

function inferCategoryFromRow(row) {
  const name = String(row?.item_name_clean || row?.item_name_raw || row?.item_name || "").toLowerCase();
  const unit = String(row?.unit || "").toLowerCase();
  if (/\b(tomato|tomatoes|lettuce|cucumber|cucumbers|cilantro|onion|onions|pepper|peppers|potato|potatoes|lime|limes|lemon|lemons|fruit|herb|herbs|greens|produce)\b/.test(name)) {
    return "Produce";
  }
  if (/\b(milk|cream|egg|eggs|cheese|butter|yogurt|dairy)\b/.test(name)) {
    return "Dairy & Eggs";
  }
  if (/\b(chicken|beef|pork|bacon|steak|fish|salmon|tuna|shrimp|turkey|wing|wings|breast|breasts|patty|patties|meat)\b/.test(name)) {
    return "Proteins";
  }
  if (/\b(burger buns?|hamburger buns?|sourdough|bread)\b/.test(name)) {
    return "Bakery";
  }
  if (/\b(marinara sauce|tomato sauce|pesto|ranch dressing|caesar dressing|pickles?)\b/.test(name)) {
    return "Sauces & Condiments";
  }
  if (/\b(olive oil|canola oil|oil|vinegar)\b/.test(name)) {
    return "Oils & Liquids";
  }
  if (/\b(water bottles?|sparkling water|tonic waters?|ginger beers?|coke|cola|juice|wine|beer|liquor)\b/.test(name)) {
    return "Beverages";
  }
  if (/\b(frozen fries|frozen berries|ice cream|gelato|mozzarella sticks)\b/.test(name)) {
    return "Frozen";
  }
  if (/\b(napkins?|straws?|receipt paper|paper cups?|takeout containers?|supply|supplies)\b/.test(name)) {
    return "Supplies";
  }
  if (/\b(flour|rice|sugar|dough|pasta|bread|bun|buns|napkin|napkins|dry)\b/.test(name)) {
    return name.includes("napkin") ? "Supplies" : "Dry Goods";
  }
  return "Uncategorized";
}

function getRowCategory(row) {
  const directCategory = firstPresentValue(
    row?.category,
    row?.parsed_category,
    row?.item_category,
    row?.category_name,
    row?.itemCategory,
    row?.clean_category,
    row?.normalized_category,
    row?.metadata?.category,
    row?.entry?.category,
    row?.inventory_item?.category,
    row?.inventoryItem?.category,
    row?.item?.category,
  );
  return normalizeCategoryLabel(directCategory || inferCategoryFromRow(row));
}

function getCategory(row) {
  return getRowCategory(row);
}

function getStatusCounts(rows) {
  return rows.reduce(
    (counts, row) => {
      counts.total += 1;
      if (row.status === "Clean") counts.clean += 1;
      if (isReviewStatus(row.status)) counts.review += 1;
      if (isPartialRow(row)) counts.partial += 1;
      if (row.status === "Converted Unit") counts.converted += 1;
      if (!row.area) counts.missingArea += 1;
      if (getCategory(row) === "Uncategorized") counts.uncategorized += 1;
      return counts;
    },
    {
      total: 0,
      clean: 0,
      review: 0,
      partial: 0,
      converted: 0,
      missingArea: 0,
      uncategorized: 0,
    },
  );
}

function getCategoryCounts(rows) {
  const counts = new Map();
  rows.forEach((row) => {
    const category = getCategory(row);
    counts.set(category, (counts.get(category) || 0) + 1);
  });
  return [...counts.entries()]
    .map(([category, count]) => ({ category, count }))
    .sort((a, b) => {
      const aIndex = CATEGORY_ORDER.indexOf(a.category);
      const bIndex = CATEGORY_ORDER.indexOf(b.category);
      return (aIndex === -1 ? 99 : aIndex) - (bIndex === -1 ? 99 : bIndex) || a.category.localeCompare(b.category);
    });
}

function getCategoryColor(category, index = 0) {
  return CATEGORY_COLORS[category] || CATEGORY_FALLBACK_COLORS[index % CATEGORY_FALLBACK_COLORS.length] || CATEGORY_COLORS.Uncategorized;
}

function getCategoryStatusBreakdown(rows) {
  const groups = new Map();
  rows.forEach((row) => {
    const category = getCategory(row);
    if (!groups.has(category)) {
      groups.set(category, { category, total: 0, clean: 0, partial: 0, review: 0, converted: 0 });
    }
    const group = groups.get(category);
    group.total += 1;
    if (isReviewStatus(row.status)) {
      group.review += 1;
    } else if (isPartialRow(row)) {
      group.partial += 1;
    } else if (row.status === "Converted Unit") {
      group.converted += 1;
    } else {
      group.clean += 1;
    }
  });
  return [...groups.values()].sort((a, b) => b.total - a.total || a.category.localeCompare(b.category));
}

function getDataQualityScore(rows) {
  const counts = getStatusCounts(rows);
  if (!counts.total) return { value: null, label: "No data" };
  const value = Math.round(((counts.total - counts.review) / counts.total) * 100);
  return {
    value,
    label: value >= 90 ? "Great" : value >= 75 ? "Good" : "Needs cleanup",
  };
}

function getParCounts(rows, data = state.data || {}) {
  if (!rows.length) {
    const summary = data.estimated_par_summary || {};
    return {
      critical: Number(summary.critical_items || 0),
      low: Number(summary.low_items || 0),
      unknown: Number(summary.unknown_items || 0),
      watchlist: Number(summary.watchlist_items || 0),
    };
  }
  return rows.reduce(
    (counts, row) => {
      if (row.par_status === "critical") counts.critical += 1;
      if (row.par_status === "low") counts.low += 1;
      if (row.par_status === "unknown") counts.unknown += 1;
      counts.watchlist = counts.critical + counts.low;
      return counts;
    },
    { critical: 0, low: 0, unknown: 0, watchlist: 0 },
  );
}

function getEstimatedWatchlist(rows, data = state.data || {}) {
  const source = rows.length ? rows : data.estimated_reorder_watchlist || [];
  const rank = { critical: 0, low: 1 };
  return source
    .filter((row) => row.par_status === "critical" || row.par_status === "low")
    .map((row) => ({
      item_name: row.item_name || row.item_name_clean || row.item_name_raw || "Unnamed item",
      quantity: row.quantity,
      unit: row.unit || "",
      estimated_par_quantity: row.estimated_par_quantity ?? null,
      par_unit: row.par_unit || "",
      par_status: row.par_status,
      par_reason: row.par_reason || "Demo estimate based on common restaurant usage patterns.",
      par_confidence: row.par_confidence || "low",
    }))
    .sort((a, b) => (rank[a.par_status] ?? 9) - (rank[b.par_status] ?? 9) || String(a.item_name).localeCompare(String(b.item_name)));
}

function getPrioritySnapshotRows(rows) {
  const priority = {
    "Needs Review": 0,
    "Missing Unit": 0,
    "Possible Duplicate": 0,
    "Partial Quantity": 1,
    "Converted Unit": 2,
    Clean: 3,
  };
  return [...rows]
    .sort((a, b) => (priority[a.status] ?? 4) - (priority[b.status] ?? 4))
    .slice(0, 8);
}

function summarizeExamples(rows, predicate) {
  const names = rows.filter(predicate).map((row) => row.item_name_clean || row.item_name_raw || "Unnamed item");
  const uniqueNames = [...new Set(names)];
  if (!uniqueNames.length) return "None";
  const shown = uniqueNames.slice(0, 3).join(", ");
  const remaining = uniqueNames.length - 3;
  return remaining > 0 ? `${shown} +${remaining} more` : shown;
}

async function logout() {
  try {
    await supabase.auth.signOut();
  } catch {
    // ignore; navigate to the auth page regardless
  }
  setSelectedRestaurantId("");
  window.location.assign("/product.html");
}

function goToLogin() {
  debugAuthFlow("dashboard route decision", { route: "login" });
  window.location.assign("/product.html");
}

async function initialize() {
  const arrivedFromLogin = consumeDashboardAuthRedirect() || isAuthCallbackUrl();
  debugAuthFlow("dashboard boot start", { arrivedFromLogin });
  state.phase = "loading";
  renderShell();

  if (!isSupabaseConfigured) {
    goToLogin();
    return;
  }

  let session = null;
  try {
    session = await getSessionWithRestore();
  } catch (error) {
    debugAuthFlow("dashboard session restore failed", { error: error?.name || "Error" });
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
    if (error.status === 401 || error.status === 403) {
      try {
        await supabase.auth.signOut();
      } catch {
        // Ignore and continue to login.
      }
      goToLogin();
      return;
    }
    state.phase = "error";
    state.error = error.message || "Could not load your restaurants.";
    renderShell();
    return;
  }
  debugAuthFlow("dashboard restaurant fetch result", { count: state.restaurants.length });

  if (!state.restaurants.length) {
    const restaurantName = getRestaurantNameFromSession(session);
    if (restaurantName) {
      try {
        const restaurant = await createRestaurant(restaurantName, session);
        state.restaurants = [restaurant];
        debugAuthFlow("dashboard created signup restaurant", { restaurantId: restaurant.id });
      } catch (error) {
        state.phase = "error";
        state.error = error.message || "Could not register your restaurant workspace.";
        renderShell();
        return;
      }
    }
  }

  consumeGoogleDashboardRedirect();

  if (!state.restaurants.length) {
    setSelectedRestaurantId("");
    state.phase = "select-restaurant";
    debugAuthFlow("dashboard route decision", { route: "chooser", restaurantCount: 0 });
    renderRestaurantChooser();
    return;
  }

  if (arrivedFromLogin && state.restaurants.length > 1) {
    setSelectedRestaurantId("");
    state.phase = "select-restaurant";
    debugAuthFlow("dashboard route decision", { route: "chooser", restaurantCount: state.restaurants.length, reason: "fresh_login" });
    renderRestaurantChooser();
    return;
  }

  if (state.restaurants.length > 1) {
    const savedRestaurantId = getSelectedRestaurantId();
    const savedRestaurant = state.restaurants.find((restaurant) => String(restaurant.id) === String(savedRestaurantId));
    if (!arrivedFromLogin && savedRestaurant) {
      state.restaurantName = savedRestaurant.name || state.restaurantName;
      setSelectedRestaurantId(savedRestaurant.id);
    } else {
      setSelectedRestaurantId("");
      state.phase = "select-restaurant";
      debugAuthFlow("dashboard route decision", { route: "chooser", restaurantCount: state.restaurants.length });
      renderRestaurantChooser();
      return;
    }
  } else {
    setSelectedRestaurantId(state.restaurants[0].id);
  }

  // Confirm the selected workspace before loading protected dashboard data.
  try {
    const me = await getAuthMe();
    state.restaurantName = me?.restaurant?.name || state.restaurantName;
  } catch (error) {
    if (error.status === 401) {
      goToLogin();
      return;
    }
    if (error.status === 404) {
      setSelectedRestaurantId("");
      state.phase = "select-restaurant";
      debugAuthFlow("dashboard route decision", { route: "chooser", reason: "selected_restaurant_missing" });
      renderRestaurantChooser();
      return;
    }
    // Backend reachable problem but still signed in: show the shell with an error.
    state.restaurantName = state.restaurantName;
  }

  debugAuthFlow("dashboard route decision", {
    route: "dashboard",
    restaurantCount: state.restaurants.length,
  });
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
  } else if (!state.data && state.phase !== "loading") {
    loadSummary();
  }
});

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
    applyCountSessions(sessions, selectCountId);
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

function getDeleteTargetSession() {
  return state.countSessions.find((session) => Number(session.id) === Number(state.deleteTargetCountId)) || null;
}

function openDeleteCountDialog(countId) {
  state.deleteTargetCountId = Number(countId);
  state.deleteError = "";
  renderShell();
}

function closeDeleteCountDialog() {
  if (state.deleteLoading) return;
  state.deleteTargetCountId = null;
  state.deleteError = "";
  renderShell();
}

function toggleCountMonth(monthKey) {
  state.expandedCountMonthKey = state.expandedCountMonthKey === monthKey ? "" : monthKey;
  renderShell();
}

function toggleCountYear(yearKey) {
  state.expandedCountYearKey = state.expandedCountYearKey === yearKey ? "" : yearKey;
  renderShell();
}

async function confirmDeleteCount() {
  const targetId = state.deleteTargetCountId;
  if (!targetId || state.deleteLoading) return;
  state.deleteLoading = true;
  state.deleteError = "";
  renderShell();
  try {
    await deleteCountSession(targetId);
    const remaining = state.countSessions.filter((session) => Number(session.id) !== Number(targetId));
    const nextSelectedId = Number(state.selectedCountId) === Number(targetId) ? remaining[0]?.id || null : state.selectedCountId;
    state.deleteTargetCountId = null;
    state.deleteLoading = false;
    const [summary, sessions] = await Promise.all([getDashboardSummary(), getCountSessions()]);
    state.data = summary;
    state.latestReport = null;
    state.latestReportError = "";
    const latestCountId = getLatestCountId(summary);
    if (latestCountId) {
      try {
        state.latestReport = await getReport(latestCountId);
      } catch (reportError) {
        state.latestReportError = reportError.message || "Could not load latest count rows.";
      }
    }
    applyCountSessions(sessions, nextSelectedId);
    if (state.selectedCountId) {
      await loadSelectedReport(state.selectedCountId, { renderBefore: false });
    } else {
      state.selectedReport = null;
      state.reportError = "";
      renderShell();
    }
  } catch (error) {
    state.deleteLoading = false;
    state.deleteError = error.message || "Could not delete this count.";
    renderShell();
  }
}

async function exportLatestCount() {
  const countId = getLatestCountId();
  if (!countId || state.exportLoading) return;
  state.exportLoading = true;
  renderShell();
  try {
    await downloadCsv(countId);
    await loadSummary();
  } catch (error) {
    state.latestReportError = error.message || "CSV export failed.";
    renderShell();
  } finally {
    state.exportLoading = false;
    renderShell();
  }
}

function renderRestaurantChooser() {
  const hasRestaurants = state.restaurants.length > 0;
  app.innerHTML = `
    <main class="restaurant-select-shell">
      <section class="restaurant-select-panel">
        <a href="./index.html" class="product-logo">Koe</a>
        <div class="restaurant-select-copy">
          <h1>${hasRestaurants ? "Choose a restaurant" : "No registered restaurants"}</h1>
          <p>${
            hasRestaurants
              ? "Select the workspace you want to open."
              : "This login is not connected to a restaurant workspace yet. Use a different login or ask the account owner to add this account."
          }</p>
        </div>
        ${
          hasRestaurants
            ? `<div class="restaurant-choice-list">
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
              </div>`
            : `<div class="dashboard-calm">No restaurant workspaces are registered under ${escapeHtml(state.userEmail || "this account")}.</div>`
        }
        <button class="ghost-button dashboard-logout-button" id="restaurant-chooser-logout" type="button">Use a different login</button>
      </section>
    </main>
  `;
  document.querySelectorAll(".restaurant-choice-button").forEach((button) => {
    button.addEventListener("click", () => selectRestaurant(button.dataset.restaurantId));
  });
  document.querySelector("#restaurant-chooser-logout")?.addEventListener("click", logout);
}

async function loadSummary() {
  state.phase = "loading";
  state.error = "";
  renderShell();
  try {
    state.data = await getDashboardSummary();
    const latestCountId = getLatestCountId(state.data);
    state.selectedCountId = state.selectedCountId || latestCountId || null;
    state.countsError = "";
    state.latestReport = null;
    state.latestReportError = "";
    if (latestCountId) {
      state.latestReportLoading = true;
      try {
        state.latestReport = await getReport(latestCountId);
      } catch (reportError) {
        state.latestReportError = reportError.message || "Could not load latest count rows.";
      } finally {
        state.latestReportLoading = false;
      }
    }
    state.countsLoading = true;
    try {
      const sessions = await getCountSessions();
      applyCountSessions(sessions, state.selectedCountId || latestCountId);
    } catch (countsError) {
      state.countsError = countsError.message || "Could not load past counts.";
    } finally {
      state.countsLoading = false;
    }
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
      ${renderSidebar({
        restaurantName: state.restaurantName,
        active: "dashboard",
        mobileActive: state.activeTab === "past-counts" ? "reports" : "dashboard",
      })}
      <main class="app-main dashboard-main">
        ${renderContent()}
      </main>
      ${renderDeleteCountDialog()}
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
  document.querySelector("#dashboard-export-latest")?.addEventListener("click", exportLatestCount);
  document.querySelectorAll("[data-dashboard-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset.dashboardAction;
      if (action === "report") setDashboardTab("past-counts", getLatestCountId());
      if (action === "export") exportLatestCount();
      if (action === "reorder") {
        document.querySelector("#estimated-reorder-watchlist")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      if (action === "review") {
        document.querySelector("#dashboard-quality")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  });
  document.querySelector("[data-dashboard-mobile-action='past-counts']")?.addEventListener("click", () => {
    setDashboardTab("past-counts", state.selectedCountId);
  });
  document.querySelectorAll("[data-dashboard-mobile-count-id]").forEach((button) => {
    button.addEventListener("click", () => setDashboardTab("past-counts", button.dataset.dashboardMobileCountId));
  });
  document.querySelector("#mobile-dashboard-counts-refresh")?.addEventListener("click", () => loadPastCounts({ selectCountId: state.selectedCountId }));
  document.querySelector("#past-count-export")?.addEventListener("click", exportSelectedCount);
  document.querySelector("#past-count-refresh")?.addEventListener("click", () => loadPastCounts({ selectCountId: state.selectedCountId }));
  document.querySelectorAll("[data-count-month-key]").forEach((button) => {
    button.addEventListener("click", () => toggleCountMonth(button.dataset.countMonthKey));
  });
  document.querySelectorAll("[data-count-year-key]").forEach((button) => {
    button.addEventListener("click", () => toggleCountYear(button.dataset.countYearKey));
  });
  document.querySelectorAll("[data-delete-count-id]").forEach((button) => {
    button.addEventListener("click", () => openDeleteCountDialog(button.dataset.deleteCountId));
  });
  document.querySelector("#delete-count-cancel")?.addEventListener("click", closeDeleteCountDialog);
  document.querySelector("#delete-count-confirm")?.addEventListener("click", confirmDeleteCount);
}

function renderDeleteCountDialog() {
  const session = getDeleteTargetSession();
  if (!session) return "";
  return `
    <div class="delete-count-backdrop" role="presentation">
      <section class="delete-count-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-count-title">
        <div class="delete-count-icon" aria-hidden="true">${renderTrashIcon()}</div>
        <div>
          <span>Delete Past Count</span>
          <h2 id="delete-count-title">Are you sure you want to delete this?</h2>
          <p>
            Count #${escapeHtml(session.id)} from ${escapeHtml(formatDateTime(getCountTimestamp(session)))} will be removed from Past Counts.
            This cannot be undone.
          </p>
          ${state.deleteError ? `<p class="delete-count-error">${escapeHtml(state.deleteError)}</p>` : ""}
        </div>
        <div class="delete-count-actions">
          <button class="dashboard-secondary-button" id="delete-count-cancel" type="button" ${state.deleteLoading ? "disabled" : ""}>Cancel</button>
          <button class="delete-count-confirm-button" id="delete-count-confirm" type="button" ${state.deleteLoading ? "disabled" : ""}>
            ${state.deleteLoading ? "Deleting..." : "Confirm"}
          </button>
        </div>
      </section>
    </div>
  `;
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
    ${renderPostCountHeader(data)}
    ${renderDashboardTabs()}
    ${state.activeTab === "past-counts" ? renderPastCounts() : renderOverviewContent(data)}
  `;
}

function renderPostCountHeader(data) {
  const latestCountId = getLatestCountId(data);
  return `
    <header class="dashboard-header dashboard-header--post-count">
      <div>
        <span>${escapeHtml(state.restaurantName)}</span>
        <h1>Dashboard</h1>
        <p>Insights and data quality from your latest inventory count.</p>
      </div>
      <div class="dashboard-header-actions">
        <a class="new-count-button" href="./product.html#count">New count</a>
        <button class="dashboard-secondary-button" id="dashboard-export-latest" type="button" ${!latestCountId || state.exportLoading ? "disabled" : ""}>
          ${state.exportLoading ? "Exporting..." : "Export CSV"}
        </button>
        <button class="dashboard-more-button" type="button" aria-label="More dashboard actions">•••</button>
      </div>
    </header>
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

  const latestCount = getLatestCount(data);
  const rows = getRowsForCount(latestCount?.count_id);
  if (state.latestReportLoading) {
    return `
      <div class="dashboard-status post-count-loading">
        <div class="dashboard-spinner" aria-hidden="true"></div>
        <p>Loading count insights...</p>
      </div>
    `;
  }
  if (state.latestReportError) {
    return `
      <section class="post-count-empty-state">
        <h2>Dashboard summary loaded</h2>
        <p>${escapeHtml(state.latestReportError)}</p>
        <button class="new-count-button" id="dashboard-open-latest" data-count-id="${escapeHtml(latestCount?.count_id || "")}" type="button">Open latest count</button>
      </section>
    `;
  }
  return renderPostCountOverview(data, latestCount, rows);
}

function renderPostCountOverview(data, latestCount, rows) {
  return `
    <section class="dashboard-priority-grid" aria-label="Top inventory overview">
      ${renderInventoryBreakdown(rows)}
      ${renderReorderPriorityCard(data, rows)}
    </section>
    ${renderKpiCards(rows, data)}
    ${renderMobilePastCountsPreview()}
    ${renderMainSummaryGrid(data, latestCount, rows)}
    ${renderEstimatedReorderWatchlist(data, rows)}
    <section class="dashboard-lower-grid">
      ${renderLatestSnapshot(rows)}
      ${renderDataQualitySummary(rows)}
    </section>
    ${renderBottomActionStrip(rows)}
  `;
}

function renderMobilePastCountsPreview() {
  if (state.countsLoading && !state.countSessions.length) {
    return `
      <section class="mobile-dashboard-past-counts">
        <div class="mobile-dashboard-section-heading">
          <h2>Past Counts</h2>
        </div>
        <div class="dashboard-calm">Loading saved counts...</div>
      </section>
    `;
  }

  if (state.countsError && !state.countSessions.length) {
    return `
      <section class="mobile-dashboard-past-counts">
        <div class="mobile-dashboard-section-heading">
          <h2>Past Counts</h2>
          <button id="mobile-dashboard-counts-refresh" type="button">Retry</button>
        </div>
        <div class="dashboard-calm">${escapeHtml(state.countsError)}</div>
      </section>
    `;
  }

  if (!state.countSessions.length) {
    return `
      <section class="mobile-dashboard-past-counts">
        <div class="mobile-dashboard-section-heading">
          <h2>Past Counts</h2>
        </div>
        <div class="dashboard-calm">No saved counts yet. Start a count to see dashboard insights.</div>
      </section>
    `;
  }

  return `
    <section class="mobile-dashboard-past-counts" aria-label="Recent saved counts">
      <div class="mobile-dashboard-section-heading">
        <h2>Past Counts</h2>
        <button data-dashboard-mobile-action="past-counts" type="button">View all</button>
      </div>
      <div class="mobile-dashboard-count-list">
        ${state.countSessions
          .slice(0, 4)
          .map(
            (session) => `
              <button class="mobile-dashboard-count-row" data-dashboard-mobile-count-id="${escapeHtml(session.id)}" type="button">
                <span>
                  <strong>${escapeHtml(session.area || "Not set")}</strong>
                  <small>${escapeHtml(formatDateTime(getCountTimestamp(session)))}</small>
                </span>
                <em>${escapeHtml(session.summary?.total_entries ?? 0)} rows</em>
              </button>
            `,
          )
          .join("")}
      </div>
    </section>
  `;
}

function renderKpiCards(rows, data = state.data || {}) {
  const counts = getStatusCounts(rows);
  const quality = getDataQualityScore(rows);
  const parCounts = getParCounts(rows, data);
  const cards = [
    { icon: "R", label: "Reorder watchlist", value: parCounts.watchlist, text: "Low + critical demo par" },
    { icon: "!", label: "Critical items", value: parCounts.critical, text: "Review before ordering" },
    { icon: "!", label: "Needs review", value: counts.review, text: "Review before export" },
    { icon: "Σ", label: "Total items counted", value: counts.total, text: "Rows saved from latest count" },
    { icon: "✓", label: "Clean items", value: counts.clean, text: "No cleanup flags" },
    { icon: "½", label: "Partial quantities", value: counts.partial, text: "Fractions or partial containers" },
    { icon: "↔", label: "Converted units", value: counts.converted, text: "Package conversions handled" },
    { icon: "%", label: "Data quality score", value: quality.value === null ? "—" : `${quality.value}%`, text: quality.label },
  ];
  return `
    <section class="post-count-kpis" aria-label="Latest count KPIs">
      ${cards
        .map(
          (card) => `
            <article class="post-count-kpi">
              <span class="kpi-icon">${escapeHtml(card.icon)}</span>
              <div>
                <p>${escapeHtml(card.label)}</p>
                <strong>${escapeHtml(card.value)}</strong>
                <small>${escapeHtml(card.text)}</small>
              </div>
            </article>
          `,
        )
        .join("")}
    </section>
  `;
}

function renderMainSummaryGrid(data, latestCount, rows) {
  return `
    <section class="dashboard-summary-grid">
      ${renderCountSummaryCard(data, latestCount, rows)}
      ${renderInsightsCard(data, rows)}
      ${renderManagerActionsCard(rows)}
    </section>
  `;
}

function renderCountSummaryCard(data, latestCount, rows) {
  const counts = getStatusCounts(rows);
  const exported = Boolean(data.export_status?.exported);
  const reviewText = counts.review > 0 ? "Review recommended before export" : "Ready to export";
  return `
    <article class="post-count-card count-summary-card">
      <div class="post-count-card-heading">
        <span>Count Summary</span>
        <h2>${escapeHtml(latestCount?.area || "Latest count")}</h2>
      </div>
      <div class="count-summary-lines">
        <div><span>Completed</span><strong>${escapeHtml(formatDateTime(getCountTimestamp(latestCount)))}</strong></div>
        <div><span>Area covered</span><strong>${escapeHtml(latestCount?.area || "Not set")}</strong></div>
        <div><span>Total items</span><strong>${counts.total}</strong></div>
        <div><span>Review status</span><strong>${escapeHtml(reviewText)}</strong></div>
        <div><span>Export status</span><strong>${exported ? "Exported" : "Not exported"}</strong></div>
      </div>
      <div class="count-summary-strip ${counts.review ? "is-review" : "is-clean"}">${escapeHtml(reviewText)}</div>
    </article>
  `;
}

function renderInsightsCard(data, rows) {
  const counts = getStatusCounts(rows);
  const parCounts = getParCounts(rows, data);
  const insights = [
    {
      tone: "review",
      icon: "!",
      title: "Items needing review",
      text: counts.review ? "Manager attention required before export." : "No review blockers found.",
      value: counts.review,
    },
    {
      tone: "partial",
      icon: "½",
      title: "Partial quantities detected",
      text: counts.partial ? "Partial containers were normalized." : "No partial quantity rows.",
      value: counts.partial,
    },
    {
      tone: "converted",
      icon: "↔",
      title: "Unit conversions detected",
      text: counts.converted ? "Package counts were converted." : "No converted unit rows.",
      value: counts.converted,
    },
    {
      tone: parCounts.watchlist ? "review" : "neutral",
      icon: "R",
      title: "Estimated low stock",
      text: parCounts.watchlist ? "Below demo estimated par. Review before ordering." : "No low or critical demo par rows.",
      value: parCounts.watchlist || "—",
    },
    {
      tone: parCounts.critical ? "review" : "neutral",
      icon: "!",
      title: "Critical reorder candidates",
      text: parCounts.critical ? "Below 50% of demo estimated par." : "No critical demo par candidates.",
      value: parCounts.critical || "—",
    },
    {
      tone: "neutral",
      icon: "D",
      title: "Demo par estimates enabled",
      text: "Based on common restaurant usage patterns, not exact demand.",
      value: "On",
    },
  ];
  return `
    <article class="post-count-card insights-card">
      <div class="post-count-card-heading">
        <span>Insights</span>
        <h2>Recommendations</h2>
      </div>
      <div class="insight-action-list">
        ${insights
          .map(
            (insight) => `
              <div class="insight-action-row">
                <i class="insight-dot insight-dot--${escapeHtml(insight.tone)}">${escapeHtml(insight.icon)}</i>
                <span>
                  <strong>${escapeHtml(insight.title)}</strong>
                  <small>${escapeHtml(insight.text)}</small>
                </span>
                <b>${escapeHtml(insight.value)}</b>
              </div>
            `,
          )
          .join("")}
      </div>
    </article>
  `;
}

function renderEstimatedReorderWatchlist(data, rows) {
  const parCounts = getParCounts(rows, data);
  const watchlist = getEstimatedWatchlist(rows, data);
  return `
    <section class="estimated-reorder-section" id="estimated-reorder-watchlist" aria-label="Estimated reorder watchlist">
      <article class="post-count-card estimated-reorder-card">
        <div class="estimated-reorder-header">
          <div class="post-count-card-heading">
            <span>Demo Estimate</span>
            <h2>Estimated Reorder Watchlist</h2>
            <p>Estimated par based on common restaurant usage patterns. Review before ordering.</p>
          </div>
          <div class="estimated-par-counts" aria-label="Estimated par status counts">
            <span class="par-count par-count--critical"><strong>${parCounts.critical}</strong><small>Critical</small></span>
            <span class="par-count par-count--low"><strong>${parCounts.low}</strong><small>Low</small></span>
            <span class="par-count par-count--unknown"><strong>${parCounts.unknown}</strong><small>Unknown</small></span>
          </div>
        </div>
        ${
          watchlist.length
            ? `<div class="estimated-reorder-list">
                ${watchlist.map((row) => renderEstimatedReorderRow(row)).join("")}
              </div>`
            : `<div class="dashboard-calm estimated-reorder-empty">
                No low or critical demo par estimates were found for matched rows. This is not exact demand forecasting; review unknown items and manager context before ordering.
              </div>`
        }
      </article>
    </section>
  `;
}

function renderEstimatedReorderRow(row) {
  const statusLabel = row.par_status === "critical" ? "Critical" : "Low";
  return `
    <div class="estimated-reorder-row estimated-reorder-row--${escapeHtml(row.par_status)}">
      <div>
        <strong>${escapeHtml(row.item_name)}</strong>
        <small>${escapeHtml(row.par_reason)}</small>
      </div>
      <span>${escapeHtml(formatQty(row.quantity))} ${escapeHtml(row.unit || "counted")}</span>
      <span>Estimated par ${escapeHtml(formatQty(row.estimated_par_quantity))} ${escapeHtml(row.par_unit)}</span>
      <i>${escapeHtml(statusLabel)}</i>
    </div>
  `;
}

function renderManagerActionsCard(rows) {
  const counts = getStatusCounts(rows);
  const parCounts = getParCounts(rows);
  const ready = counts.review === 0;
  const actions = [
    { action: "reorder", label: "Review estimated par", detail: `${parCounts.watchlist} demo reorder candidates`, highlighted: parCounts.watchlist > 0 },
    { action: "review", label: "Review flagged items", detail: `${counts.review} items need attention`, highlighted: counts.review > 0 },
    { action: "report", label: "Open full report", detail: "View the saved spreadsheet" },
    { action: "export", label: "Export CSV", detail: "Download manager-ready rows" },
  ];
  return `
    <article class="post-count-card manager-actions-card">
      <div class="post-count-card-heading">
        <span>Manager Actions</span>
        <h2>Next steps</h2>
      </div>
      <div class="manager-action-list">
        ${actions
          .map(
            (item) => `
              <button class="manager-action ${item.highlighted ? "is-highlighted" : ""}" data-dashboard-action="${escapeHtml(item.action)}" type="button">
                <span>
                  <strong>${escapeHtml(item.label)}</strong>
                  <small>${escapeHtml(item.detail)}</small>
                </span>
                <i>›</i>
              </button>
            `,
          )
          .join("")}
        <a class="manager-action" href="./product.html#count">
          <span><strong>Start new count</strong><small>Begin another area count</small></span>
          <i>›</i>
        </a>
      </div>
      ${ready ? `<div class="ready-strip">Ready to export</div>` : ""}
    </article>
  `;
}

function renderReorderPriorityCard(data, rows) {
  const parCounts = getParCounts(rows, data);
  const calculatedWatchlist = parCounts.critical + parCounts.low;
  const watchlistCount = calculatedWatchlist || parCounts.watchlist;
  const criticalPercent = calculatedWatchlist ? Math.round((parCounts.critical / calculatedWatchlist) * 100) : 0;
  const lowPercent = calculatedWatchlist ? Math.max(0, 100 - criticalPercent) : 0;
  const statusCopy = watchlistCount
    ? `${watchlistCount} item${watchlistCount === 1 ? "" : "s"} need reorder review`
    : "No low or critical demo par rows";
  return `
    <article class="post-count-card reorder-priority-card">
      <div class="post-count-card-heading">
        <span>Demo Estimate</span>
        <h2>Low and critical items</h2>
        <p>Estimated par based on common restaurant usage patterns. Review before ordering.</p>
      </div>
      <div class="reorder-priority-display ${watchlistCount ? "has-watchlist" : "is-clear"}">
        <div class="reorder-priority-total">
          <span>Reorder watchlist</span>
          <strong>${escapeHtml(watchlistCount)}</strong>
          <small>${escapeHtml(statusCopy)}</small>
        </div>
        <div class="reorder-priority-stat reorder-priority-stat--critical">
          <span>Critical</span>
          <strong>${escapeHtml(parCounts.critical)}</strong>
          <small>Below 50% estimated par</small>
        </div>
        <div class="reorder-priority-stat reorder-priority-stat--low">
          <span>Low</span>
          <strong>${escapeHtml(parCounts.low)}</strong>
          <small>Below estimated par</small>
        </div>
      </div>
      <div class="reorder-priority-bar" aria-hidden="true">
        <i class="reorder-priority-bar-critical" style="width: ${escapeHtml(criticalPercent)}%"></i>
        <i class="reorder-priority-bar-low" style="width: ${escapeHtml(lowPercent)}%"></i>
      </div>
    </article>
  `;
}

function renderInventoryBreakdown(rows) {
  const categories = getCategoryCounts(rows);
  const total = rows.length;
  return `
    <article class="post-count-card inventory-breakdown-card">
      <div class="post-count-card-heading">
        <span>Inventory Breakdown</span>
        <h2>Category mix</h2>
      </div>
      ${renderDonutChart(categories, total)}
    </article>
  `;
}

function renderDonutChart(categories, total) {
  const gradient = total
    ? `conic-gradient(${categories
        .reduce(
          (segments, item, index) => {
            const start = segments.cursor;
            const end = start + (item.count / total) * 100;
            segments.parts.push(`${getCategoryColor(item.category, index)} ${start.toFixed(2)}% ${end.toFixed(2)}%`);
            segments.cursor = end;
            return segments;
          },
          { cursor: 0, parts: [] },
        )
        .parts.join(", ")})`
    : `conic-gradient(${CATEGORY_COLORS.Uncategorized} 0 100%)`;
  return `
    <div class="donut-layout">
      <div class="donut-chart" style="--donut-gradient: ${escapeHtml(gradient)}">
        <div><strong>${total || "—"}</strong><span>Total items</span></div>
      </div>
      <div class="donut-legend">
        ${
          total
            ? categories
                .map((item, index) => {
                  const percent = Math.round((item.count / total) * 100);
                  return `
                    <div class="donut-legend-row">
                      <i style="background: ${escapeHtml(getCategoryColor(item.category, index))}"></i>
                      <span>${escapeHtml(item.category)}</span>
                      <b>${item.count}</b>
                      <small>${percent}%</small>
                    </div>
                  `;
                })
                .join("")
            : `<p>No category data yet.</p>`
        }
      </div>
    </div>
  `;
}

function renderCategoryStatusCard(rows) {
  const breakdown = getCategoryStatusBreakdown(rows);
  return `
    <article class="post-count-card category-status-card">
      <div class="post-count-card-heading">
        <span>Category Status</span>
        <h2>Quality by group</h2>
      </div>
      <div class="category-status-list">
        ${
          breakdown.length
            ? breakdown.map((group) => renderCategoryStatusRow(group)).join("")
            : `<div class="dashboard-calm">No category rows available yet.</div>`
        }
      </div>
    </article>
  `;
}

function renderCategoryStatusRow(group) {
  const segments = [
    ["clean", group.clean],
    ["partial", group.partial],
    ["review", group.review],
    ["converted", group.converted],
  ];
  return `
    <div class="category-status-row">
      <div class="category-status-top">
        <strong>${escapeHtml(group.category)}</strong>
        <span>${group.total} items</span>
      </div>
      <div class="category-status-bar">
        ${segments
          .filter(([, value]) => value > 0)
          .map(([name, value]) => `<i class="status-segment status-segment--${name}" style="width: ${(value / group.total) * 100}%"></i>`)
          .join("")}
      </div>
      <div class="category-status-chips">
        ${group.review ? `<span class="review-chip">${group.review} review</span>` : ""}
        ${group.partial ? `<span class="partial-chip">${group.partial} partial</span>` : ""}
        ${group.converted ? `<span class="converted-chip">${group.converted} converted</span>` : ""}
      </div>
    </div>
  `;
}

function renderLatestSnapshot(rows) {
  const snapshot = getPrioritySnapshotRows(rows);
  return `
    <article class="post-count-card latest-snapshot-card">
      <div class="post-count-card-heading">
        <span>Latest Count Snapshot</span>
        <h2>Rows to scan</h2>
      </div>
      ${
        snapshot.length
          ? `<div class="snapshot-table">
              <div class="snapshot-row snapshot-row--head"><span>Item</span><span>Category</span><span>Qty</span><span>Unit</span><span>Status</span></div>
              ${snapshot
                .map(
                  (row) => `
                    <div class="snapshot-row">
                      <span>${escapeHtml(row.item_name_clean || row.item_name_raw || "Unnamed item")}</span>
                      <span>${escapeHtml(getCategory(row))}</span>
                      <span>${escapeHtml(formatQty(row.quantity))}</span>
                      <span>${escapeHtml(row.unit || "—")}</span>
                      <span><i class="status-pill ${statusClass(row.status)}">${escapeHtml(row.status || "Clean")}</i></span>
                    </div>
                  `,
                )
                .join("")}
            </div>`
          : `<div class="dashboard-calm">No saved rows found for the latest count.</div>`
      }
    </article>
  `;
}

function renderDataQualitySummary(rows) {
  const counts = getStatusCounts(rows);
  const groups = [
    {
      label: "Review required",
      count: counts.review,
      examples: summarizeExamples(rows, (row) => isReviewStatus(row.status)),
      tone: "review",
    },
    {
      label: "Partial quantities",
      count: counts.partial,
      examples: summarizeExamples(rows, (row) => isPartialRow(row)),
      tone: "partial",
    },
    {
      label: "Unit conversions",
      count: counts.converted,
      examples: summarizeExamples(rows, (row) => row.status === "Converted Unit"),
      tone: "converted",
    },
    {
      label: "Missing areas",
      count: counts.missingArea,
      examples: summarizeExamples(rows, (row) => !row.area),
      tone: "review",
    },
    {
      label: "Uncategorized items",
      count: counts.uncategorized,
      examples: summarizeExamples(rows, (row) => getCategory(row) === "Uncategorized"),
      tone: "neutral",
    },
  ].filter((group) => group.count > 0 || ["Review required", "Partial quantities", "Unit conversions"].includes(group.label));
  return `
    <article class="post-count-card data-quality-card" id="dashboard-quality">
      <div class="post-count-card-heading">
        <span>Data Quality</span>
        <h2>Cleanup summary</h2>
      </div>
      <div class="quality-group-list">
        ${groups
          .map(
            (group) => `
              <div class="quality-group quality-group--${escapeHtml(group.tone)}">
                <div><strong>${escapeHtml(group.label)} — ${group.count} items</strong><small>${escapeHtml(group.examples)}</small></div>
              </div>
            `,
          )
          .join("")}
      </div>
    </article>
  `;
}

function renderBottomActionStrip(rows) {
  const counts = getStatusCounts(rows);
  const message =
    counts.review === 0
      ? "Data quality looks clean; review estimated par before ordering."
      : "Almost done; review flagged items and estimated par before export.";
  return `
    <section class="dashboard-action-strip">
      <p>${escapeHtml(message)}</p>
      <div>
        <button class="dashboard-secondary-button" data-dashboard-action="report" type="button">Open Full Report</button>
        <button class="dashboard-secondary-button" data-dashboard-action="review" type="button">Review Flagged Items</button>
        <button class="new-count-button" data-dashboard-action="export" type="button" ${state.exportLoading ? "disabled" : ""}>
          ${state.exportLoading ? "Exporting..." : "Export CSV"}
        </button>
      </div>
    </section>
  `;
}

function renderPastCounts() {
  const sessions = state.countSessions;
  const selectedSession = sessions.find((session) => Number(session.id) === Number(state.selectedCountId)) || sessions[0] || null;
  const yearGroups = groupCountSessionsByYear(sessions);

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
        ${yearGroups.map((group) => renderPastCountYearGroup(group)).join("")}
      </aside>
      <section class="past-counts-detail">
        ${renderSelectedCountDetail(selectedSession)}
      </section>
    </section>
  `;
}

function renderPastCountYearGroup(group) {
  const isExpanded = state.expandedCountYearKey === group.key;
  return `
    <section class="past-count-year-group">
      <div class="past-counts-calendar-header">
        <button class="past-count-year-button ${isExpanded ? "is-expanded" : ""}" data-count-year-key="${escapeHtml(group.key)}" type="button" aria-expanded="${isExpanded}">
          <span>Count History</span>
          <strong>${escapeHtml(group.label || "Recent")}</strong>
          <i aria-hidden="true">${renderChevronIcon()}</i>
        </button>
      </div>
      <div class="past-count-year-panel ${isExpanded ? "is-expanded" : ""}">
        <div class="past-count-list past-count-month-list">
          ${group.months.map((monthGroup, index) => renderPastCountMonthGroup(monthGroup, index)).join("")}
        </div>
      </div>
    </section>
  `;
}

function renderPastCountMonthGroup(group, index = 0) {
  const isExpanded = state.expandedCountMonthKey === group.key;
  const countLabel = `${group.sessions.length} count${group.sessions.length === 1 ? "" : "s"}`;
  return `
    <section class="past-count-month-group" style="--month-index: ${index}">
      <button class="past-count-month-button ${isExpanded ? "is-expanded" : ""}" data-count-month-key="${escapeHtml(group.key)}" type="button" aria-expanded="${isExpanded}">
        <span>
          <strong>${escapeHtml(group.label)}</strong>
          <small>${escapeHtml(countLabel)} • most recent first</small>
        </span>
        <i aria-hidden="true">${renderChevronIcon()}</i>
      </button>
      <div class="past-count-month-panel ${isExpanded ? "is-expanded" : ""}">
        <div class="past-count-month-stack">
          ${group.sessions.map((session) => renderPastCountListItem(session)).join("")}
        </div>
      </div>
    </section>
  `;
}

function renderPastCountListItem(session) {
  const isActive = Number(session.id) === Number(state.selectedCountId);
  const entryCount = session.summary?.total_entries ?? null;
  const reviewCount = session.summary?.entries_needing_review ?? null;
  return `
    <div class="past-count-item-row ${isActive ? "is-active" : ""}">
      <button class="past-count-item ${isActive ? "is-active" : ""}" data-count-id="${session.id}" type="button">
        <span class="past-count-date">
          <strong>${escapeHtml(formatCountDay(getCountTimestamp(session)))}</strong>
          <small>${escapeHtml(formatCountTime(getCountTimestamp(session)))}</small>
        </span>
        <span class="past-count-meta">
          <b>${escapeHtml(session.area || "Not set")}</b>
          <small>${entryCount === null ? "Open spreadsheet" : `${entryCount} rows${reviewCount ? ` • ${reviewCount} review` : ""}`}</small>
        </span>
      </button>
      <button class="past-count-delete-button" data-delete-count-id="${escapeHtml(session.id)}" type="button" aria-label="Delete count ${escapeHtml(session.id)}" title="Delete count">
        ${renderTrashIcon()}
      </button>
    </div>
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
        <span>${escapeHtml(formatDateTime(getCountTimestamp(session)))}</span>
        <h2>${escapeHtml(session.area || "Inventory Count")}</h2>
        <p>Saved count #${escapeHtml(session.id)}${session.status ? ` • ${escapeHtml(session.status)}` : ""}</p>
      </div>
      <div class="past-count-detail-actions">
        <button class="past-count-delete-button past-count-delete-button--detail" data-delete-count-id="${escapeHtml(session.id)}" type="button" aria-label="Delete count ${escapeHtml(session.id)}" title="Delete count">
          ${renderTrashIcon()}
        </button>
        <button class="report-button report-button--primary" id="past-count-export" type="button" ${state.exportLoading || !entries.length ? "disabled" : ""}>
          ${state.exportLoading ? "Exporting..." : "Export CSV"}
        </button>
      </div>
    </div>
    <dl class="past-count-summary">
      <div><dt>Rows</dt><dd>${summary.total_items ?? entries.length}</dd></div>
      <div><dt>Needs review</dt><dd>${summary.items_needing_review ?? 0}</dd></div>
      <div><dt>Area</dt><dd>${escapeHtml(session.area || "Not set")}</dd></div>
      <div><dt>Completed</dt><dd>${escapeHtml(formatCountTime(getCountTimestamp(session)))}</dd></div>
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
            <th>Category</th>
            <th>Qty</th>
            <th>Unit</th>
            <th>Quantity to Purchase</th>
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
                  <td>${escapeHtml(getCategory(entry))}</td>
                  <td>${escapeHtml(formatQty(entry.quantity ?? ""))}</td>
                  <td>${escapeHtml(entry.unit || "")}</td>
                  <td>${escapeHtml(formatNeededQuantity(entry.needed_quantity))}</td>
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

function renderLowStock(items) {
  if (!items.length) {
    return `
      <section class="dashboard-section">
        <h2>Low Stock Items</h2>
        <div class="dashboard-calm">No configured low-stock items found. Review estimated par and manager context before ordering.</div>
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
