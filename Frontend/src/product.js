import {
  checkBackendHealth,
  createRestaurant,
  createCountSession,
  downloadCsv,
  getAuthMe,
  getCountSessions,
  getDashboardSummary,
  getReport,
  linkTesterRestaurant,
  parseVoiceCount,
  setSelectedRestaurantId,
} from "./api.js";
import { isSupabaseConfigured, supabase, supabaseConfigError } from "./supabaseClient.js";
import { bindSidebar, renderSidebar } from "./sidebar.js";

const AREA_OPTIONS = ["Dry Storage", "Walk-in", "Freezer", "Bar", "Wine Storage", "Prep Station"];
const MOBILE_AREA_OPTIONS = ["Walk-in", "Dry Storage", "Bar", "Kitchen", "Other"];
const dashboardRedirectUrl = `${window.location.origin}/dashboard.html`;
const authHandoffKey = "koe:authHandoff";
const authRedirectKey = "koe:authRedirecting";
const googleDashboardRedirectKey = "koe:googleDashboardRedirect";
const REVIEW_STATUSES = new Set(["Needs Review", "Missing Unit", "Possible Duplicate"]);
const VALID_STATUSES = new Set(["Clean", "Partial Quantity", "Missing Unit", "Needs Review", "Possible Duplicate", "Converted Unit"]);
const CATEGORY_ORDER = ["Produce", "Dairy & Eggs", "Proteins", "Bakery", "Sauces & Condiments", "Oils & Liquids", "Beverages", "Frozen", "Supplies", "Dry Goods", "Uncategorized"];
const INVALID_FALLBACK_ITEM_NAMES = new Set([
  "of",
  "and",
  "then",
  "packs of",
  "cases of",
  "bunches wait no scratch that",
  "is half empty",
  "more on the bottom shelf",
]);

const state = {
  backendConnected: false,
  backendChecked: false,
  backendMessage: "Checking backend...",
  authReady: false,
  authMode: "login",
  authFirstName: "",
  authLastName: "",
  authRestaurantName: "",
  authEmail: "",
  authPassword: "",
  authConfirmPassword: "",
  authLoading: false,
  authRedirectPending: false,
  session: null,
  userEmail: "",
  workspaceMissing: false,
  workspaceCreateAttempted: false,
  workspace: null,
  selectedRestaurantId: null,
  selectedRestaurantName: "",
  selectedRestaurantLocation: "",
  selectedArea: "",
  status: "Ready",
  activeCountId: null,
  activeCountCompleted: false,
  countStartedAt: null,
  transcript: "",
  parsedEntries: [],
  parserDebug: null,
  report: null,
  dataHealthItems: [],
  isCreatingCount: false,
  isProcessing: false,
  isGeneratingReport: false,
  isRecording: false,
  recordingMode: "idle",
  recordingSeconds: 0,
  voiceLevel: 0,
  speechRecognition: null,
  recognitionBaseTranscript: "",
  recognitionFinalTranscript: "",
  recordingTimer: null,
  audioContext: null,
  audioAnalyser: null,
  audioStream: null,
  audioMonitorFrame: null,
  shouldRestartRecognition: false,
  notice: "",
  error: "",
  authStatus: "Checking session...",
  view: "checking",
  lastScrolledHash: "",
  mobileAreaOtherActive: false,
  mobileActiveTab: getMobileTabFromHash(),
  dashboardData: null,
  dashboardError: "",
  dashboardLoading: false,
  mobileCountSessions: [],
  mobileCountsLoading: false,
  mobileCountsError: "",
  mobileSelectedCountId: null,
  mobileSelectedReport: null,
  mobileReportLoading: false,
  mobileReportError: "",
  mobileExportLoading: false,
};

const app = document.querySelector("#product-app");

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatTimer(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60)
    .toString()
    .padStart(2, "0");
  const seconds = (totalSeconds % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function formatDateTime(date) {
  if (!date) return "—";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function getMobileTabFromHash() {
  const tab = window.location.hash.replace("#", "").toLowerCase();
  return ["dashboard", "count", "reports", "account"].includes(tab) ? tab : "count";
}

function requestGoogleDashboardRedirect() {
  try {
    window.sessionStorage.setItem(googleDashboardRedirectKey, "1");
  } catch {
    // OAuth still uses dashboardRedirectUrl if session storage is unavailable.
  }
}

function debugAuthFlow(message, details = {}) {
  if (!import.meta.env.DEV) return;
  console.log(`[koe-auth] ${message}`, details);
}

function markDashboardAuthRedirect() {
  try {
    window.sessionStorage.setItem(authRedirectKey, "1");
  } catch {
    // The redirect still works if session storage is unavailable.
  }
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

function hasGoogleDashboardRedirect() {
  try {
    return window.sessionStorage.getItem(googleDashboardRedirectKey) === "1";
  } catch {
    return false;
  }
}

function storeAuthHandoff(session) {
  if (!session?.access_token || !session?.refresh_token) return;
  try {
    window.sessionStorage.setItem(
      authHandoffKey,
      JSON.stringify({
        access_token: session.access_token,
        refresh_token: session.refresh_token,
      }),
    );
  } catch {
    // Supabase local persistence usually handles this; the handoff only covers redirect timing.
  }
}

function setMobileTab(tab) {
  if (redirectProductDashboardTabIfNeeded(tab)) return;
  state.mobileActiveTab = tab;
  if (window.location.hash !== `#${tab}`) {
    window.location.hash = tab;
    return;
  }
  render();
  handleMobileTabActivation(tab);
}

function getProductDashboardRedirect(tab = state.mobileActiveTab) {
  if (tab === "dashboard") return "/dashboard.html";
  if (tab === "reports") return "/dashboard.html#past-counts";
  return "";
}

function redirectProductDashboardTabIfNeeded(tab = state.mobileActiveTab) {
  const target = getProductDashboardRedirect(tab);
  if (!target) return false;
  state.navigatingAway = true;
  window.location.assign(target);
  return true;
}

function formatReportDate(value) {
  if (!value) return "Not saved yet";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Not saved yet";
  const today = new Date();
  const isToday = date.toDateString() === today.toDateString();
  const day = isToday
    ? "Today"
    : new Intl.DateTimeFormat(undefined, { weekday: "short" }).format(date);
  const time = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(date);
  return `${day} ${time}`;
}

function getSpeechRecognitionConstructor() {
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function syncTranscriptInputs(value = state.transcript) {
  document.querySelectorAll("#transcript-input, #mobile-transcript-input").forEach((input) => {
    if (input.value === value) return;
    const wasNearBottom = input.scrollTop + input.clientHeight >= input.scrollHeight - 12;
    input.value = value;
    if (wasNearBottom) {
      input.scrollTop = input.scrollHeight;
    }
  });
}

function setTranscriptText(value, options = {}) {
  const { renderView = false } = options;
  state.transcript = value;
  syncTranscriptInputs(value);
  if (renderView) render();
}

function appendTranscriptText(previous, next) {
  return joinTranscriptParts(previous, next);
}

function vibrateRecordingFeedback() {
  if (!navigator.vibrate) return;
  try {
    navigator.vibrate([18, 28, 22]);
  } catch {
    // Haptic feedback is optional and may be blocked by the browser/device.
  }
}

function setVoiceLevel(level) {
  const clamped = Math.max(0, Math.min(1, Number(level) || 0));
  const voiceVars = {
    "--voice-level": clamped.toFixed(3),
    "--voice-opacity": (0.16 + clamped * 0.5).toFixed(3),
    "--voice-wave-scale": (0.35 + clamped * 1.6).toFixed(3),
    "--voice-spread": `${6 + clamped * 8}px`,
    "--voice-shadow-alpha": (0.06 + clamped * 0.1).toFixed(3),
    "--voice-ring-opacity": (clamped * 0.58).toFixed(3),
    "--voice-ring-scale": (0.82 + clamped * 0.2).toFixed(3),
  };
  state.voiceLevel = clamped;
  document.querySelectorAll(".mic-button").forEach((ring) => {
    Object.entries(voiceVars).forEach(([name, value]) => ring.style.setProperty(name, value));
  });
  document.querySelectorAll(".voice-capture--interactive, .mobile-recorder-card").forEach((capture) => {
    Object.entries(voiceVars).forEach(([name, value]) => capture.style.setProperty(name, value));
  });
}

async function startVoiceMeter() {
  if (!navigator.mediaDevices?.getUserMedia) return;

  stopVoiceMeter();

  const AudioContext = window.AudioContext || window.webkitAudioContext;
  if (!AudioContext) return;

  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const context = new AudioContext();
  const source = context.createMediaStreamSource(stream);
  const analyser = context.createAnalyser();
  const samples = new Uint8Array(analyser.fftSize);

  analyser.fftSize = 1024;
  analyser.smoothingTimeConstant = 0.72;
  source.connect(analyser);

  state.audioContext = context;
  state.audioAnalyser = analyser;
  state.audioStream = stream;

  const measure = () => {
    if (!state.audioAnalyser) return;
    state.audioAnalyser.getByteTimeDomainData(samples);
    let total = 0;
    for (const sample of samples) {
      const centered = (sample - 128) / 128;
      total += centered * centered;
    }
    const rms = Math.sqrt(total / samples.length);
    setVoiceLevel(Math.min(1, rms * 7.5));
    state.audioMonitorFrame = window.requestAnimationFrame(measure);
  };

  measure();
}

function stopVoiceMeter() {
  if (state.audioMonitorFrame) {
    window.cancelAnimationFrame(state.audioMonitorFrame);
    state.audioMonitorFrame = null;
  }
  if (state.audioStream) {
    state.audioStream.getTracks().forEach((track) => track.stop());
    state.audioStream = null;
  }
  if (state.audioContext) {
    state.audioContext.close().catch(() => {});
    state.audioContext = null;
  }
  state.audioAnalyser = null;
  setVoiceLevel(0);
}

function joinTranscriptParts(...parts) {
  return parts
    .map((part) => part.trim())
    .filter(Boolean)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
}

function ProductIcon(name) {
  const icons = {
    plus: `<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"></path></svg>`,
    pin: `<svg viewBox="0 0 24 24"><path d="M12 21s7-6.1 7-12a7 7 0 0 0-14 0c0 5.9 7 12 7 12z"></path><circle cx="12" cy="9" r="2.2"></circle></svg>`,
    edit: `<svg viewBox="0 0 24 24"><path d="M4 20h4l11-11-4-4L4 16v4z"></path><path d="M13.5 6.5l4 4"></path></svg>`,
    file: `<svg viewBox="0 0 24 24"><path d="M7 3h7l5 5v13H7z"></path><path d="M14 3v6h5"></path><path d="M9 14h6M9 17h6"></path></svg>`,
    export: `<svg viewBox="0 0 24 24"><path d="M12 3v12"></path><path d="M7 10l5 5 5-5"></path><path d="M5 21h14"></path></svg>`,
    sheet: `<svg viewBox="0 0 24 24"><path d="M7 3h10v18H7z"></path><path d="M7 8h10M7 13h10M12 8v13"></path></svg>`,
    shield: `<svg viewBox="0 0 24 24"><path d="M12 3l8 3v6c0 5-3.4 8.2-8 9-4.6-.8-8-4-8-9V6z"></path><path d="M8.5 12l2.2 2.2 4.8-5"></path></svg>`,
    heart: `<svg viewBox="0 0 24 24"><path d="M20.5 8.5c0 5-8.5 10.5-8.5 10.5S3.5 13.5 3.5 8.5A4.5 4.5 0 0 1 12 6a4.5 4.5 0 0 1 8.5 2.5z"></path><path d="M7 12h3l1.4-3 2.2 6 1.4-3h2"></path></svg>`,
    mic: `<svg viewBox="0 0 24 24"><path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z"></path><path d="M5 11a7 7 0 0 0 14 0"></path><path d="M12 18v3"></path></svg>`,
    store: `<svg viewBox="0 0 24 24"><path d="M4 10h16l-1.3-5.5H5.3z"></path><path d="M5 10v10h14V10"></path><path d="M9 20v-6h6v6"></path></svg>`,
    sparkle: `<svg viewBox="0 0 24 24"><path d="M12 3l2.2 6.8L21 12l-6.8 2.2L12 21l-2.2-6.8L3 12l6.8-2.2z"></path></svg>`,
    chart: `<svg viewBox="0 0 24 24"><path d="M5 19V9"></path><path d="M12 19V5"></path><path d="M19 19v-7"></path></svg>`,
    flag: `<svg viewBox="0 0 24 24"><path d="M6 21V4"></path><path d="M6 5h11l-2 4 2 4H6"></path></svg>`,
    check: `<svg viewBox="0 0 24 24"><path d="M5 12l4 4 10-10"></path></svg>`,
    chevron: `<svg viewBox="0 0 24 24"><path d="M9 5l6 7-6 7"></path></svg>`,
    plusCircle: `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"></circle><path d="M12 8v8M8 12h8"></path></svg>`,
    calendar: `<svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="15" rx="2"></rect><path d="M8 3v4M16 3v4M4 10h16"></path></svg>`,
    user: `<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="3.5"></circle><path d="M5 20c1.4-3.4 3.7-5 7-5s5.6 1.6 7 5"></path></svg>`,
    lock: `<svg viewBox="0 0 24 24"><rect x="5" y="10" width="14" height="10" rx="2"></rect><path d="M8 10V7a4 4 0 0 1 8 0v3"></path></svg>`,
    help: `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"></circle><path d="M9.8 9a2.4 2.4 0 0 1 4.5 1.2c0 1.8-2.3 2-2.3 3.8"></path><path d="M12 17h.01"></path></svg>`,
  };
  return icons[name] || "";
}

function setNotice(message) {
  state.notice = message;
  state.error = "";
}

function setError(message) {
  state.error = message;
  state.notice = "";
}

function clearMessages() {
  state.error = "";
  state.notice = "";
}

function resetWorkspaceState() {
  stopRecording();
  state.workspace = null;
  state.workspaceMissing = false;
  state.workspaceCreateAttempted = false;
  state.selectedRestaurantId = null;
  state.selectedRestaurantName = "";
  state.selectedRestaurantLocation = "";
  state.activeCountId = null;
  state.activeCountCompleted = false;
  state.countStartedAt = null;
  state.parsedEntries = [];
  state.parserDebug = null;
  state.report = null;
  state.dataHealthItems = [];
  state.status = "Ready";
  state.dashboardData = null;
  state.dashboardError = "";
  state.dashboardLoading = false;
  state.mobileCountSessions = [];
  state.mobileCountsLoading = false;
  state.mobileCountsError = "";
  state.mobileSelectedCountId = null;
  state.mobileSelectedReport = null;
  state.mobileReportLoading = false;
  state.mobileReportError = "";
  state.mobileExportLoading = false;
}

function renderVoiceMeter() {
  const level = state.isRecording ? state.voiceLevel : state.recordingMode === "paused" ? 0.18 : 0.08;
  return `
    <div class="mic-meter" aria-hidden="true">
      ${Array.from({ length: 9 })
        .map((_, index) => {
          const offset = Math.abs(index - 4);
          const height = 6 + Math.max(0, level * 34 - offset * 4);
          return `<span style="height: ${height.toFixed(1)}px"></span>`;
        })
        .join("")}
    </div>
  `;
}

function normalizeItemName(value) {
  return String(value || "").trim().replace(/\s+/g, " ");
}

function normalizeItemNameKey(value) {
  return normalizeItemName(value).toLowerCase().replace(/[.,]+$/g, "");
}

function normalizeStatus(entry) {
  const status = String(entry.status || "").trim();
  if (VALID_STATUSES.has(status)) return status;
  if (entry.quantity === null || entry.quantity === undefined || entry.quantity === "") return "Needs Review";
  if (!entry.unit) return "Missing Unit";
  return "Clean";
}

function getEntryArea(entry) {
  return normalizeItemName(entry.area || state.selectedArea || "");
}

function getCurrentSelectedArea() {
  const customInput = document.querySelector("#mobile-area-custom") || document.querySelector("#desktop-area-custom");
  const customArea = normalizeItemName(customInput?.value || "");
  if (customArea) return customArea;

  const activeAreaButton = document.querySelector(".mobile-area-option.is-active, .desktop-area-option.is-active");
  const activeArea = normalizeItemName(activeAreaButton?.dataset?.area || "");
  if (activeArea && activeArea !== "Other") return activeArea;

  return normalizeItemName(state.selectedArea);
}

function isInvalidFallbackEntry(entry) {
  if (state.parserDebug?.parser_source !== "deterministic_fallback") return false;
  const cleanName = normalizeItemNameKey(entry.item_name_clean || entry.item_name || entry.name);
  const rawName = normalizeItemNameKey(entry.item_name_raw || entry.raw_phrase || entry.original_phrase);
  return INVALID_FALLBACK_ITEM_NAMES.has(cleanName) || INVALID_FALLBACK_ITEM_NAMES.has(rawName);
}

function normalizeParsedEntry(entry, fallbackArea = "") {
  const itemNameClean = normalizeItemName(entry.item_name_clean || entry.item_name || entry.name);
  const itemNameRaw = normalizeItemName(entry.item_name_raw || entry.raw_phrase || itemNameClean);
  return {
    ...entry,
    count_id: entry.count_id ?? state.activeCountId ?? null,
    restaurant_id: entry.restaurant_id ?? state.selectedRestaurantId ?? null,
    area: normalizeItemName(entry.area || fallbackArea || state.selectedArea || ""),
    item_name_raw: itemNameRaw,
    item_name_clean: itemNameClean,
    category: entry.category || "",
    quantity: entry.quantity,
    unit: entry.unit || "",
    status: normalizeStatus(entry),
    original_phrase: entry.original_phrase || entry.raw_phrase || itemNameRaw,
    created_at: entry.created_at || null,
    counted_by: entry.counted_by || null,
  };
}

function normalizeParsedEntries(entries, fallbackArea = "") {
  return (entries || [])
    .map((entry) => normalizeParsedEntry(entry, fallbackArea))
    .filter((entry) => normalizeItemName(entry.item_name_clean))
    .filter((entry) => !isInvalidFallbackEntry(entry));
}

function getEntryCleanName(entry) {
  return entry.item_name_clean || "";
}

function getEntryRawName(entry) {
  return entry.item_name_raw || getEntryCleanName(entry);
}

function getEntryOriginalPhrase(entry) {
  return entry.original_phrase || getEntryRawName(entry);
}

function entryNeedsReview(entry) {
  const status = getEntryStatus(entry).label;
  return REVIEW_STATUSES.has(status);
}

function formatParserSource() {
  const source = state.parserDebug?.parser_source;
  if (source === "claude") return "Claude";
  if (source === "deterministic_fallback") return "Deterministic fallback";
  return "";
}

function renderParserDebugLine() {
  const parser = formatParserSource();
  if (!parser) return "";
  if (state.parserDebug?.parser_source === "deterministic_fallback") {
    const reason = state.parserDebug?.fallback_reason ? ` Reason: ${state.parserDebug.fallback_reason}` : "";
    return `
      <div class="parser-debug-line parser-debug-line--warning">
        Parser: <strong>${escapeHtml(parser)}</strong>
        <span>Fallback parser used - Claude unavailable. Review rows carefully.${escapeHtml(reason)}</span>
      </div>
    `;
  }
  return `<div class="parser-debug-line">Parser: <strong>${escapeHtml(parser)}</strong></div>`;
}

function buildDataHealth(entries) {
  if (!entries.length) return [];

  const items = [];
  const normalizedCount = entries.filter((entry) => getEntryCleanName(entry)).length;
  const partialCount = entries.filter((entry) => getEntryStatus(entry).label === "Partial Quantity").length;
  const reviewCount = entries.filter(entryNeedsReview).length;

  if (normalizedCount) items.push("Inventory names normalized");
  if (partialCount) items.push("Partial quantities resolved");
  items.push(reviewCount ? `${reviewCount} review flag${reviewCount === 1 ? "" : "s"} found` : "Review flags checked");

  return items;
}

function normalizeDisplayCategory(category) {
  const raw = String(category || "").trim();
  if (CATEGORY_ORDER.includes(raw)) return raw;
  const value = raw.toLowerCase();
  if (["oils", "oil", "liquid", "liquids", "oils & liquids", "oils and liquids"].includes(value)) return "Oils & Liquids";
  if (["beverage", "beverages", "bar", "wine"].includes(value)) return "Beverages";
  if (["sauce", "sauces", "condiment", "condiments", "sauces & condiments", "sauces and condiments"].includes(value)) return "Sauces & Condiments";
  if (value === "bakery") return "Bakery";
  if (value === "produce") return "Produce";
  if (["meat", "meats", "protein", "proteins", "seafood"].includes(value)) return "Proteins";
  if (["dairy", "eggs", "dairy & eggs"].includes(value)) return "Dairy & Eggs";
  if (["dry goods", "dry"].includes(value)) return "Dry Goods";
  if (value === "frozen") return "Frozen";
  if (value === "supplies") return "Supplies";
  if (value === "other" || value === "uncategorized") return "Uncategorized";
  return "";
}

function inferCategory(entry) {
  const category = normalizeDisplayCategory(entry.category);
  if (category) return category;

  const name = String(getEntryCleanName(entry)).toLowerCase();
  const unit = String(entry.unit || "").toLowerCase();
  if (/\b(marinara sauce|tomato sauce|pesto|ranch dressing|caesar dressing|pickles?)\b/.test(name)) {
    return "Sauces & Condiments";
  }
  if (/\b(olive oil|canola oil|oil|vinegar)\b/.test(name)) {
    return "Oils & Liquids";
  }
  if (/\b(water bottles?|sparkling water|tonic waters?|ginger beers?|coke|cola|wine|beer|juice)\b/.test(name)) {
    return "Beverages";
  }
  if (/\b(tomato|tomatoes|lettuce|cucumber|cucumbers|onion|onions|pepper|peppers|carrot|carrots|potato|potatoes|fruit|herb|herbs|greens)\b/.test(name)) {
    return "Produce";
  }
  if (/\b(chicken|beef|pork|bacon|steak|fish|salmon|tuna|shrimp|turkey|patty|patties|meat)\b/.test(name)) {
    return "Proteins";
  }
  if (/\b(egg|eggs|cheese|cream|butter|yogurt)\b/.test(name)) {
    return "Dairy & Eggs";
  }
  if (/\b(burger buns?|hamburger buns?|sourdough|bread)\b/.test(name)) {
    return "Bakery";
  }
  if (/\b(napkins?|straws?|receipt paper|paper cups?|takeout containers?)\b/.test(name)) {
    return "Supplies";
  }
  if (/\b(frozen fries|frozen berries|ice cream|gelato|mozzarella sticks)\b/.test(name)) {
    return "Frozen";
  }
  if (["bottles", "gallons", "ounces"].includes(unit)) {
    return "Oils & Liquids";
  }
  return "Uncategorized";
}

function groupEntriesByCategory(entries) {
  return CATEGORY_ORDER
    .map((category) => ({
      category,
      entries: entries.filter((entry) => inferCategory(entry) === category),
    }))
    .filter((group) => group.entries.length);
}

function getCountTimestamp(count) {
  return count?.completed_at || count?.started_at || count?.created_at || null;
}

function sortCountSessions(sessions) {
  return [...(sessions || [])].sort((a, b) => {
    const bTime = new Date(getCountTimestamp(b) || 0).getTime();
    const aTime = new Date(getCountTimestamp(a) || 0).getTime();
    return bTime - aTime || Number(b.id || 0) - Number(a.id || 0);
  });
}

function applyMobileCountSessions(sessions) {
  state.mobileCountSessions = sortCountSessions(sessions);
  const selectedExists = state.mobileCountSessions.some((session) => Number(session.id) === Number(state.mobileSelectedCountId));
  if (!selectedExists) {
    state.mobileSelectedCountId = state.mobileCountSessions[0]?.id ? Number(state.mobileCountSessions[0].id) : null;
    state.mobileSelectedReport = null;
  }
}

function getCountSummaryValue(session, key, fallback = 0) {
  const value = session?.summary?.[key];
  return Number.isFinite(Number(value)) ? Number(value) : fallback;
}

function getCountItemCount(session) {
  return getCountSummaryValue(session, "total_entries", 0);
}

function getCountReviewCount(session) {
  return getCountSummaryValue(session, "entries_needing_review", 0);
}

function getRecentCountCount(sessions) {
  const weekAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
  return sessions.filter((session) => {
    const time = new Date(getCountTimestamp(session) || 0).getTime();
    return Number.isFinite(time) && time >= weekAgo;
  }).length;
}

function getCountArea(session) {
  return normalizeItemName(session?.area || "Not set");
}

function getCountStatusLabel(session) {
  const status = normalizeItemName(session?.status || "");
  if (status) return status;
  return session?.completed_at ? "Completed" : "In Progress";
}

function handleMobileTabActivation(tab = state.mobileActiveTab) {
  if (state.view !== "ready" || !state.session) return;
  if (tab === "dashboard") {
    loadMobileDashboardSummary();
  } else if (tab === "reports") {
    loadMobileCountSessions({ loadReport: true });
  }
}

async function initializeAuthFlow() {
  state.view = "checking";
  state.authReady = false;
  state.authStatus = "Checking session...";
  render();

  try {
    await checkBackendHealth();
    state.backendConnected = true;
    state.backendMessage = "Backend connected";
  } catch {
    state.backendConnected = false;
    state.backendMessage = "Backend offline";
    setError("Backend not connected. Start FastAPI on port 8000.");
  } finally {
    state.backendChecked = true;
  }

  if (!isSupabaseConfigured) {
    console.log("No Supabase session found; rendering auth screen");
    resetWorkspaceState();
    state.session = null;
    state.userEmail = "";
    state.view = "unauthenticated";
    state.authReady = true;
    state.authStatus = "Sign in to account";
    setError(supabaseConfigError);
    render();
    return;
  }

  try {
    const { data } = await supabase.auth.getSession();
    state.session = data.session;
    state.userEmail = data.session?.user?.email || "";
  } catch (error) {
    setError(error.message || "Could not check Supabase session.");
  } finally {
  }

  if (!state.session) {
    console.log("No Supabase session found; rendering auth screen");
    resetWorkspaceState();
    state.view = "unauthenticated";
    state.authReady = true;
    state.authStatus = "Sign in to account";
    render();
    return;
  }

  console.log("Supabase session found; loading workspace");
  state.view = "loading-workspace";
  state.authReady = true;
  state.authStatus = "Setting up workspace...";
  await loadCurrentWorkspace();
}

function initialize() {
  initializeAuthFlow();

  window.addEventListener("hashchange", () => {
    state.mobileActiveTab = getMobileTabFromHash();
    state.lastScrolledHash = "";
    if (redirectProductDashboardTabIfNeeded(state.mobileActiveTab)) return;
    render();
    handleMobileTabActivation(state.mobileActiveTab);
  });

  supabase.auth.onAuthStateChange((_event, session) => {
    if (state.authRedirectPending || state.navigatingAway) {
      return;
    }
    if (session) {
      initializeAuthFlow();
      return;
    }

    console.log("No Supabase session found; rendering auth screen");
    resetWorkspaceState();
    state.session = null;
    state.userEmail = "";
    state.view = "unauthenticated";
    state.authReady = true;
    state.authStatus = "Sign in to account";
    render();
  });
}

async function handleInvalidSession() {
  await supabase.auth.signOut();
  setSelectedRestaurantId("");
  resetWorkspaceState();
  state.session = null;
  state.userEmail = "";
  state.view = "unauthenticated";
  state.authReady = true;
  state.authStatus = "Sign in to account";
  render();
}

function isMissingWorkspaceError(error) {
  return error.status === 404 && error.message === "No restaurant workspace found for this user.";
}

function isUnauthorizedError(error) {
  return error.status === 401;
}

async function loadCurrentWorkspace() {
  if (!state.session) {
    console.log("No Supabase session found; rendering auth screen");
    state.view = "unauthenticated";
    state.authStatus = "Sign in to account";
    render();
    return;
  }

  console.log("Supabase session found; loading workspace");
  state.view = "loading-workspace";
  state.authStatus = "Setting up workspace...";
  const shouldRedirectToDashboard = hasGoogleDashboardRedirect();
  try {
    const me = await getAuthMe();
    if (!state.session) return;
    state.workspace = me.restaurant;
    state.workspaceMissing = false;
    state.view = "ready";
    state.selectedRestaurantId = me.restaurant.id;
    setSelectedRestaurantId(me.restaurant.id);
    state.selectedRestaurantName = me.restaurant.name;
    state.selectedRestaurantLocation = "Restaurant workspace";
    state.userEmail = me.email || state.userEmail;
    state.authStatus = "Ready";
    clearMessages();
    if (redirectProductDashboardTabIfNeeded()) return;
    loadMobileDashboardSummary();
    console.log("Workspace loaded");
    if (state.pendingDashboardRedirect || shouldRedirectToDashboard) {
      if (shouldRedirectToDashboard) consumeGoogleDashboardRedirect();
      state.navigatingAway = true;
      window.location.assign("/dashboard.html");
      return;
    }
  } catch (error) {
    state.workspace = null;
    if (isUnauthorizedError(error)) {
      await handleInvalidSession();
      return;
    }
    if (isMissingWorkspaceError(error)) {
      if (shouldRedirectToDashboard) {
        state.navigatingAway = true;
        window.location.assign("/dashboard.html");
        return;
      }
      const pendingRestaurantName =
        state.authRestaurantName.trim() || state.session?.user?.user_metadata?.restaurant_name?.trim() || "";
      if (pendingRestaurantName && !state.workspaceCreateAttempted) {
        state.workspaceCreateAttempted = true;
        try {
          await createRestaurant(pendingRestaurantName, state.session);
          await loadCurrentWorkspace();
          return;
        } catch (createError) {
          console.error("Restaurant workspace creation failed:", createError.message);
          setError(createError.message || "Restaurant workspace setup failed.");
        }
      }
      if (!pendingRestaurantName) {
        await handleInvalidSession();
        return;
      }
      console.log("Workspace missing; rendering setup");
      state.workspaceMissing = true;
      state.view = "setup";
      state.authStatus = "Setting up workspace...";
      clearMessages();
    } else {
      setError(error.message);
    }
  } finally {
    if (!state.navigatingAway) render();
  }
}

async function loadMobileDashboardSummary() {
  if (state.dashboardLoading) return;
  state.dashboardLoading = true;
  state.mobileCountsLoading = true;
  state.dashboardError = "";
  state.mobileCountsError = "";
  try {
    const [summary, sessions] = await Promise.all([getDashboardSummary(), getCountSessions()]);
    state.dashboardData = summary;
    applyMobileCountSessions(sessions);
    if (state.mobileActiveTab === "reports" && state.mobileSelectedCountId) {
      await loadMobileSelectedReport(state.mobileSelectedCountId, { renderBefore: false });
    }
  } catch (error) {
    state.dashboardError = error.message || "Dashboard summary unavailable.";
    state.mobileCountsError = error.message || "Could not load saved counts.";
  } finally {
    state.dashboardLoading = false;
    state.mobileCountsLoading = false;
    if (state.view === "ready") render();
  }
}

async function loadMobileCountSessions(options = {}) {
  const { selectCountId = null, loadReport = false } = options;
  if (state.mobileCountsLoading) return;
  state.mobileCountsLoading = true;
  state.mobileCountsError = "";
  if (selectCountId) {
    state.mobileSelectedCountId = Number(selectCountId);
  }
  if (state.view === "ready") render();
  try {
    const sessions = await getCountSessions();
    applyMobileCountSessions(sessions);
    if (selectCountId) {
      state.mobileSelectedCountId = Number(selectCountId);
    }
    if (loadReport && state.mobileSelectedCountId) {
      await loadMobileSelectedReport(state.mobileSelectedCountId, { renderBefore: false });
    } else if (!state.mobileSelectedCountId) {
      state.mobileSelectedReport = null;
    }
  } catch (error) {
    state.mobileCountsError = error.message || "Could not load past counts.";
  } finally {
    state.mobileCountsLoading = false;
    if (state.view === "ready") render();
  }
}

async function loadMobileSelectedReport(countId, options = {}) {
  const { renderBefore = true } = options;
  if (!countId) return;
  state.mobileSelectedCountId = Number(countId);
  state.mobileReportLoading = true;
  state.mobileReportError = "";
  if (renderBefore && state.view === "ready") render();
  try {
    state.mobileSelectedReport = await getReport(countId);
  } catch (error) {
    state.mobileSelectedReport = null;
    state.mobileReportError = error.message || "Could not load this count.";
  } finally {
    state.mobileReportLoading = false;
    if (renderBefore && state.view === "ready") render();
  }
}

function openMobilePastCount(countId) {
  if (!countId) return;
  state.mobileSelectedCountId = Number(countId);
  if (state.mobileActiveTab !== "reports") {
    setMobileTab("reports");
  } else {
    render();
  }
  loadMobileSelectedReport(countId);
}

async function exportMobileSelectedCount() {
  clearMessages();
  if (!state.mobileSelectedCountId || state.mobileExportLoading) {
    setError("CSV export failed. Missing count id.");
    render();
    return;
  }
  state.mobileExportLoading = true;
  render();
  try {
    if (!state.session || state.view !== "ready") throw new Error("Sign in before exporting CSV.");
    await downloadCsv(state.mobileSelectedCountId);
    setNotice("CSV export started.");
  } catch (error) {
    state.mobileReportError = error.message || "CSV export failed.";
    setError(`CSV export failed. ${error.message}`);
  } finally {
    state.mobileExportLoading = false;
    render();
  }
}

async function handleAuthSubmit(mode) {
  clearMessages();
  if (!isSupabaseConfigured) {
    setError(supabaseConfigError);
    render();
    return;
  }

  const email = document.querySelector("#auth-email")?.value.trim() || state.authEmail.trim();
  const password = document.querySelector("#auth-password")?.value || state.authPassword;
  const confirmPassword = document.querySelector("#auth-confirm-password")?.value || state.authConfirmPassword;
  const firstName = document.querySelector("#auth-first-name")?.value.trim() || state.authFirstName.trim();
  const lastName = document.querySelector("#auth-last-name")?.value.trim() || state.authLastName.trim();
  const restaurantName = document.querySelector("#auth-restaurant-name")?.value.trim() || state.authRestaurantName.trim();
  if (!email || !password) {
    setError("Enter an email and password.");
    render();
    return;
  }
  if (mode === "signup" && !firstName) {
    setError("Enter your first name.");
    render();
    return;
  }
  if (mode === "signup" && !restaurantName) {
    setError("Enter the name of your restaurant.");
    render();
    return;
  }
  if (mode === "signup" && password !== confirmPassword) {
    setError("Passwords do not match.");
    render();
    return;
  }

  state.authLoading = true;
  state.authRedirectPending = true;
  render();
  const result =
    mode === "signup"
      ? await supabase.auth.signUp({
          email,
          password,
          options: {
            emailRedirectTo: dashboardRedirectUrl,
            data: {
              first_name: firstName,
              last_name: lastName,
              restaurant_name: restaurantName,
            },
          },
        })
      : await supabase.auth.signInWithPassword({ email, password });
  state.authLoading = false;

  if (result.error) {
    state.authRedirectPending = false;
    debugAuthFlow("product login failed", { mode, error: result.error.message });
    setError(result.error.message);
    render();
    return;
  }

  debugAuthFlow("product login success", {
    mode,
    hasSession: Boolean(result.data?.session),
    hasUser: Boolean(result.data?.user),
  });
  state.authFirstName = firstName;
  state.authLastName = lastName;
  state.authRestaurantName = restaurantName;
  state.authEmail = email;
  state.authPassword = "";
  state.authConfirmPassword = "";
  setSelectedRestaurantId("");
  if (mode === "signup" && restaurantName && result.data?.session) {
    try {
      await createRestaurant(restaurantName, result.data.session);
    } catch (error) {
      state.authRedirectPending = false;
      console.error("Restaurant workspace creation failed:", error.message);
      setError(error.message || "Account created, but restaurant workspace setup failed.");
      render();
      return;
    }
  }
  if (!result.data?.session) {
    state.authRedirectPending = false;
    setNotice(mode === "signup" ? "Account created. Check your email if confirmation is enabled." : "Check your email to finish signing in.");
    render();
    return;
  }

  markDashboardAuthRedirect();
  storeAuthHandoff(result.data.session);
  state.navigatingAway = true;
  debugAuthFlow("product redirecting to dashboard", { target: "/dashboard.html" });
  window.location.assign("/dashboard.html");
}

async function handleResetPassword() {
  clearMessages();
  if (!isSupabaseConfigured) {
    setError(supabaseConfigError);
    render();
    return;
  }

  const email = document.querySelector("#auth-email")?.value.trim() || state.authEmail.trim();
  if (!email) {
    setError("Enter your email first, then click Reset password.");
    render();
    return;
  }

  state.authLoading = true;
  setSelectedRestaurantId("");
  render();
  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: dashboardRedirectUrl,
  });
  state.authLoading = false;

  if (error) {
    setError(error.message);
  } else {
    setNotice("Password reset email sent.");
  }
  render();
}

async function handleGoogleSignIn() {
  clearMessages();
  if (!isSupabaseConfigured) {
    setError(supabaseConfigError);
    render();
    return;
  }

  state.authLoading = true;
  setSelectedRestaurantId("");
  markDashboardAuthRedirect();
  requestGoogleDashboardRedirect();
  debugAuthFlow("product redirecting to Google OAuth", { target: dashboardRedirectUrl });
  render();
  const { error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: {
      redirectTo: dashboardRedirectUrl,
    },
  });

  if (error) {
    console.error("Google sign-in failed:", error.message);
    consumeGoogleDashboardRedirect();
    state.authLoading = false;
    setError(error.message);
    render();
  }
}

async function logout() {
  clearMessages();
  stopRecording();
  await supabase.auth.signOut();
  setSelectedRestaurantId("");
  resetWorkspaceState();
  state.session = null;
  state.userEmail = "";
  state.view = "unauthenticated";
  state.authReady = true;
  state.authStatus = "Sign in to account";
  render();
}

async function linkWorkspace(restaurantName) {
  clearMessages();
  state.authLoading = true;
  render();
  try {
    await linkTesterRestaurant(restaurantName);
    state.authLoading = false;
    state.workspaceCreateAttempted = false;
    setSelectedRestaurantId("");
    await loadCurrentWorkspace();
  } catch (error) {
    setError(error.message);
    render();
  } finally {
    state.authLoading = false;
  }
}

async function ensureCountSession() {
  if (state.activeCountId && !state.activeCountCompleted) return state.activeCountId;
  if (!state.session || state.view !== "ready") throw new Error("Sign in before starting a count.");
  if (!state.backendConnected) throw new Error("Backend not connected. Start FastAPI on port 8000.");

  state.selectedArea = getCurrentSelectedArea();
  state.isCreatingCount = true;
  render();
  try {
    const count = await createCountSession({
      area: state.selectedArea || null,
      notes: "Frontend local demo count",
    });
    state.activeCountId = count.id;
    state.activeCountCompleted = false;
    state.countStartedAt = new Date(count.started_at || Date.now());
    state.status = "In Progress";
    state.parsedEntries = [];
    state.parserDebug = null;
    state.report = null;
    state.dataHealthItems = [];
    setNotice(`Count #${count.id} started.`);
    return count.id;
  } finally {
    state.isCreatingCount = false;
  }
}

async function startNewCount() {
  clearMessages();
  state.activeCountId = null;
  state.activeCountCompleted = false;
  state.countStartedAt = null;
  state.status = "Ready";
  setTranscriptText("");
  state.parsedEntries = [];
  state.parserDebug = null;
  state.report = null;
  state.dataHealthItems = [];
  try {
    await ensureCountSession();
  } catch (error) {
    setError(error.message);
  }
  render();
}

async function processCount() {
  clearMessages();
  const transcriptInput = document.querySelector("#mobile-transcript-input") || document.querySelector("#transcript-input");
  const transcript = (transcriptInput?.value || state.transcript).trim();
  setTranscriptText(transcript);
  state.selectedArea = getCurrentSelectedArea();
  if (!transcript) {
    setError("Add a transcript before processing the count.");
    render();
    return;
  }

  state.isProcessing = true;
  state.status = state.activeCountId && !state.activeCountCompleted ? "In Progress" : "Ready";
  render();

  try {
    const countId = await ensureCountSession();
    const result = await parseVoiceCount({
      count_session_id: countId,
      text: transcript,
      area: state.selectedArea,
      save: true,
    });
    const savedCountId = result.count_session_id ?? result.entries?.[0]?.count_id ?? countId;
    state.activeCountId = savedCountId;
    state.activeCountCompleted = true;
    state.parserDebug = {
      parser_source: result.parser_source || "deterministic_fallback",
      fallback_reason: result.fallback_reason || "",
      external_ai_enabled: Boolean(result.external_ai_enabled),
      text_ai_provider: result.text_ai_provider || "",
      anthropic_model: result.anthropic_model || "",
      anthropic_key_present: Boolean(result.anthropic_key_present),
    };
    state.parsedEntries = normalizeParsedEntries(result.entries || [], state.selectedArea);
    const firstArea = state.parsedEntries.find((entry) => entry.area)?.area;
    if (!state.selectedArea && firstArea) {
      state.selectedArea = firstArea;
    }
    console.log({
      parser_source: state.parserDebug.parser_source,
      item_count: state.parsedEntries.length,
      first_item: state.parsedEntries[0] || null,
      first_2_table_rows: state.parsedEntries.slice(0, 2),
      count_id: savedCountId,
      area: state.selectedArea || firstArea || "",
    });
    state.dataHealthItems = buildDataHealth(state.parsedEntries);
    state.report = null;
    state.status = "Completed";
    if (state.parsedEntries.length) {
      setNotice(`Processed ${state.parsedEntries.length} inventory item${state.parsedEntries.length === 1 ? "" : "s"}.`);
      loadMobileDashboardSummary();
    } else {
      setError("No inventory items were parsed. Include quantities and units, for example: three bottles of olive oil, two boxes of cheese.");
    }
  } catch (error) {
    setError(error.message);
  } finally {
    state.isProcessing = false;
    render();
  }
}

async function generateReport() {
  clearMessages();
  if (!state.activeCountId) {
    setError("Start and process a count first.");
    render();
    return;
  }

  state.isGeneratingReport = true;
  render();
  try {
    if (!state.session || state.view !== "ready") throw new Error("Sign in before generating a report.");
    state.report = await getReport(state.activeCountId);
    state.mobileSelectedCountId = Number(state.activeCountId);
    state.mobileSelectedReport = state.report;
    loadMobileCountSessions({ selectCountId: state.activeCountId });
    setNotice("Report preview generated.");
  } catch (error) {
    setError(error.message);
  } finally {
    state.isGeneratingReport = false;
    render();
  }
}

async function exportCsv() {
  clearMessages();
  if (!state.activeCountId) {
    setError("CSV export failed. Missing count id.");
    render();
    return;
  }
  try {
    if (!state.session || state.view !== "ready") throw new Error("Sign in before exporting CSV.");
    await downloadCsv(state.activeCountId);
  } catch (error) {
    console.error("CSV export failed", {
      message: error.message,
      status: error.status,
      count_id: state.activeCountId,
      area: state.selectedArea || state.parsedEntries[0]?.area || "",
    });
    setError(error.status === 404 ? "CSV export failed. Please generate a report first." : `CSV export failed. ${error.message}`);
    render();
  }
}

function handleClearParsedInventory() {
  const hadRows = state.parsedEntries.length > 0;
  clearMessages();
  state.parsedEntries = [];
  state.parserDebug = null;
  state.dataHealthItems = [];
  state.report = null;
  state.activeCountId = null;
  state.activeCountCompleted = false;
  state.countStartedAt = null;
  state.isGeneratingReport = false;
  state.status = "Ready";
  setNotice(hadRows ? "Parsed inventory cleared. Transcript and area were kept." : "Parsed inventory is already clear.");
  render();
}

function handleClearTranscript() {
  clearMessages();
  setTranscriptText("");
  state.recognitionBaseTranscript = "";
  state.recognitionFinalTranscript = "";
  setNotice("Transcript cleared.");
  render();
}

async function startRecording() {
  clearMessages();

  const SpeechRecognition = getSpeechRecognitionConstructor();
  if (!SpeechRecognition) {
    setError("Live speech recognition is not supported in this browser. Paste or type the count, or use desktop.");
    render();
    return;
  }

  try {
    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    state.speechRecognition = recognition;
    state.recognitionBaseTranscript = state.transcript.trim();
    state.recognitionFinalTranscript = "";
    state.shouldRestartRecognition = true;
    state.isRecording = true;
    state.recordingMode = "recording";
    state.status = "Recording";
    setVoiceLevel(0);

    recognition.onresult = (event) => {
      let interimText = "";

      for (let index = event.resultIndex || 0; index < event.results.length; index += 1) {
        const result = event.results[index];
        const transcript = result[0]?.transcript || "";
        if (result.isFinal) {
          state.recognitionFinalTranscript = appendTranscriptText(state.recognitionFinalTranscript, transcript);
        } else {
          interimText = joinTranscriptParts(interimText, transcript);
        }
      }

      const nextTranscript = appendTranscriptText(
        state.recognitionBaseTranscript,
        joinTranscriptParts(state.recognitionFinalTranscript, interimText),
      );
      setTranscriptText(nextTranscript);
    };

    recognition.onerror = (event) => {
      state.shouldRestartRecognition = false;
      stopRecording();
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        setError("Microphone permission was denied. Allow microphone access or type the transcript manually.");
      } else if (event.error === "no-speech") {
        setError("No speech was detected. Try recording again or type the transcript manually.");
      } else if (event.error === "audio-capture") {
        setError("No microphone was found. Check your microphone access, or paste/type the count.");
      } else if (event.error === "network") {
        setError("Speech recognition could not reach the browser speech service. Paste/type the count or try again.");
      } else {
        setError(`Speech recognition stopped: ${event.error || "unknown error"}. You can type the transcript manually.`);
      }
      render();
    };

    recognition.onend = () => {
      if (state.isRecording && state.shouldRestartRecognition) {
        try {
          recognition.start();
        } catch {
          state.shouldRestartRecognition = false;
        }
      }
    };

    try {
      await startVoiceMeter();
    } catch {
      stopVoiceMeter();
    }
    recognition.start();
    state.recordingTimer = window.setInterval(() => {
      state.recordingSeconds += 1;
      render();
    }, 1000);
    setNotice("Listening now. Speak your inventory count and it will appear in the transcript.");
  } catch {
    stopVoiceMeter();
    state.isRecording = false;
    state.shouldRestartRecognition = false;
    setError("Could not start speech recognition. Check microphone permission, then try again.");
  }
  render();
}

function pauseRecording() {
  if (state.recordingMode === "paused") {
    resetRecording();
    return;
  }
  if (!state.isRecording) return;
  stopRecording({ preserveMode: true });
  state.recordingMode = "paused";
  state.status = state.activeCountId && !state.activeCountCompleted ? "In Progress" : "Ready";
  setNotice("Recording paused. Resume when you are ready, or reset the capture.");
  render();
}

function resetRecording() {
  stopRecording();
  state.recordingMode = "idle";
  state.recordingSeconds = 0;
  setTranscriptText("");
  state.recognitionBaseTranscript = "";
  state.recognitionFinalTranscript = "";
  setNotice("Recording reset.");
  render();
}

function handlePrimaryRecordingAction() {
  if (state.isRecording) return;
  vibrateRecordingFeedback();
  startRecording();
}

function handleMicButtonClick() {
  vibrateRecordingFeedback();
  if (state.isRecording) {
    pauseRecording();
    return;
  }
  startRecording();
}

function stopRecording(options = {}) {
  state.shouldRestartRecognition = false;
  if (state.recordingTimer) {
    window.clearInterval(state.recordingTimer);
    state.recordingTimer = null;
  }
  if (state.speechRecognition) {
    state.speechRecognition.onresult = null;
    state.speechRecognition.onerror = null;
    state.speechRecognition.onend = null;
    try {
      state.speechRecognition.stop();
    } catch {
      // Recognition may already be stopped by the browser.
    }
    state.speechRecognition = null;
  }
  stopVoiceMeter();
  state.isRecording = false;
  if (!options.preserveMode) {
    state.recordingMode = "idle";
  }
  state.status = state.activeCountId && !state.activeCountCompleted ? "In Progress" : "Ready";
}

function renderMessages() {
  const offlineInstructions = !state.backendConnected && state.backendChecked
    ? `<pre class="connection-help">cd /Users/ramarevuri/Documents/Koe/Backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000</pre>`
    : "";

  return `
    <div class="message-stack">
      ${state.error ? `<div class="app-banner app-banner--error">${escapeHtml(state.error)}${offlineInstructions}</div>` : ""}
      ${state.notice ? `<div class="app-banner app-banner--success">${escapeHtml(state.notice)}</div>` : ""}
    </div>
  `;
}

function renderInventoryTable() {
  if (!state.parsedEntries.length) {
    return `
      <div class="empty-state">
        <strong>No items parsed yet.</strong>
        <span>Start a count or paste a transcript to begin.</span>
      </div>
    `;
  }

  const rows = groupEntriesByCategory(state.parsedEntries)
    .map((group) => {
      const itemRows = group.entries
        .map((entry) => {
          const status = getEntryStatus(entry);
          const detail = getEntryOriginalPhrase(entry);
          const cleanName = getEntryCleanName(entry);
          const area = getEntryArea(entry) || "Not set";
          return `
        <tr>
          <td class="drag-cell">⋮</td>
          <td>${escapeHtml(cleanName)}</td>
          <td>${escapeHtml(entry.quantity)}</td>
          <td>${escapeHtml(entry.unit)}</td>
          <td>${escapeHtml(area)}</td>
          <td><span class="status-pill ${status.className}">${escapeHtml(status.label)}</span></td>
        </tr>
        ${
          detail
            ? `<tr class="detail-row"><td></td><td colspan="5">${escapeHtml(detail)}</td></tr>`
            : ""
        }
      `;
        })
        .join("");

      return `
        <tr class="category-row"><td colspan="6">${escapeHtml(group.category)}</td></tr>
        ${itemRows}
      `;
    })
    .join("");

  return `
    <table class="product-table">
      <thead>
        <tr>
          <th></th>
          <th>Name</th>
          <th>Quantity</th>
          <th>Unit</th>
          <th>Area</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
    ${renderMobileInventoryCards()}
  `;
}

function getEntryStatus(entry) {
  const status = normalizeStatus(entry);
  if (status === "Needs Review" || status === "Missing Unit" || status === "Possible Duplicate") {
    return { label: status, className: "status-pill--review" };
  }
  if (status === "Partial Quantity") return { label: "Partial Quantity", className: "status-pill--partial" };
  if (status === "Converted Unit") return { label: "Converted Unit", className: "status-pill--partial" };
  if (!entry.unit) return { label: "Missing Unit", className: "status-pill--review" };
  return { label: "Clean", className: "" };
}

function renderMobileAreaSelector() {
  const showCustomArea =
    state.mobileAreaOtherActive || Boolean(state.selectedArea && !MOBILE_AREA_OPTIONS.includes(state.selectedArea));
  return `
    <section class="workspace-card mobile-area-card" aria-label="Area selector">
      <span>Area</span>
      <div class="mobile-area-options">
        ${MOBILE_AREA_OPTIONS.map((area) => {
          const active =
            area === "Other"
              ? showCustomArea
              : state.selectedArea === area;
          return `<button class="mobile-area-option ${active ? "is-active" : ""}" data-area="${escapeHtml(area)}" type="button">${escapeHtml(area)}</button>`;
        }).join("")}
      </div>
      ${
        showCustomArea
          ? `<input class="mobile-area-custom" id="mobile-area-custom" value="${escapeHtml(MOBILE_AREA_OPTIONS.includes(state.selectedArea) ? "" : state.selectedArea)}" placeholder="Type custom area" />`
          : ""
      }
    </section>
  `;
}

function renderMobileInventoryCards() {
  if (!state.parsedEntries.length) {
    return `
      <div class="mobile-inventory-list">
        <div class="mobile-empty-card">
          <strong>No items parsed yet</strong>
          <span>Record or type a count, then process it here.</span>
        </div>
      </div>
    `;
  }

  const mobileCards = state.parsedEntries
    .map((entry) => {
      const status = getEntryStatus(entry);
      const cleanName = getEntryCleanName(entry);
      const detail = getEntryOriginalPhrase(entry);
      return `
        <article class="mobile-inventory-card">
          <div>
            <h3>${escapeHtml(cleanName)}</h3>
            <p>${escapeHtml(entry.quantity)} ${escapeHtml(entry.unit || "unit")}</p>
          </div>
          <span class="status-pill ${status.className}">${escapeHtml(status.label)}</span>
          ${detail ? `<small>${escapeHtml(detail)}</small>` : ""}
          <button class="mobile-card-edit" type="button" aria-label="Edit ${escapeHtml(cleanName)}">Edit</button>
        </article>
      `;
    })
    .join("");

  return `<div class="mobile-inventory-list">${mobileCards}</div>`;
}

function renderDataHealth() {
  if (!state.dataHealthItems.length) {
    return `
      <div class="empty-state empty-state--compact">
        <strong>No parsed data yet.</strong>
        <span>Process a count to see normalization checks.</span>
      </div>
    `;
  }

  return `
    <div class="normalization-list normalization-list--simple">
      ${state.dataHealthItems.map((item) => `<div><span>${escapeHtml(item)}</span><i>✓</i></div>`).join("")}
    </div>
    <small>✓ Data checks completed from backend response</small>
  `;
}

function renderReportPreview() {
  if (!state.report) return "";
  const entries = state.report.entries || [];
  return `
    <section class="workspace-card report-preview-card">
      <div class="section-heading section-heading--row">
        <div>
          <h2>Report Preview</h2>
          <p>Count #${escapeHtml(state.report.count_id)} • ${escapeHtml(state.report.status)}</p>
        </div>
        <div class="report-stats">
          <span>${state.report.summary?.total_items ?? entries.length} total</span>
          <span>${state.report.summary?.items_needing_review ?? 0} review</span>
        </div>
      </div>
      <table class="product-table report-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Quantity</th>
            <th>Unit</th>
            <th>Area</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          ${entries
            .map(
              (entry) => `
                <tr>
                  <td>${escapeHtml(getEntryCleanName(entry))}</td>
                  <td>${escapeHtml(entry.quantity)}</td>
                  <td>${escapeHtml(entry.unit)}</td>
                  <td>${escapeHtml(entry.area || "—")}</td>
                  <td>${escapeHtml(getEntryStatus(entry).label)}</td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </section>
  `;
}

function renderMobileAppShell(context) {
  const activeTab = state.mobileActiveTab;
  const screens = {
    dashboard: renderMobileDashboardScreen(context),
    count: renderMobileCountScreen(context),
    reports: renderMobileReportsScreen(context),
    account: renderMobileAccountScreen(),
  };
  return `
    <section class="mobile-app-shell" data-mobile-tab="${escapeHtml(activeTab)}">
      ${renderMobileTopBar()}
      ${screens[activeTab] || screens.count}
    </section>
  `;
}

function renderMobileTopBar() {
  const restaurantName = state.selectedRestaurantName || "Massimo's";
  return `
    <header class="mobile-app-bar">
      <a class="mobile-app-logo" href="./dashboard.html" aria-label="Koe dashboard">Koe</a>
      <div class="mobile-restaurant-name" aria-label="Current restaurant">${escapeHtml(restaurantName)}</div>
      <a class="mobile-avatar" href="#account" aria-label="Open account">
        <span>${escapeHtml((state.userEmail || "K").slice(0, 1).toUpperCase())}</span>
      </a>
    </header>
  `;
}

function renderMobilePageTitle(title, subtitle) {
  return `
    <div class="mobile-page-title">
      <div>
        <h1>${escapeHtml(title)}</h1>
        <p>${escapeHtml(subtitle)}</p>
      </div>
      <span class="mobile-sparkle" aria-hidden="true">${ProductIcon("sparkle")}</span>
    </div>
  `;
}

function renderMobileDashboardScreen({ totalItems, needsReview }) {
  const summary = state.dashboardData?.last_count_summary || {};
  const latestSession = state.mobileCountSessions[0] || null;
  const itemsCounted = summary.total_items_counted ?? getCountItemCount(latestSession) ?? totalItems;
  const flagged = summary.needs_review_count ?? getCountReviewCount(latestSession) ?? needsReview;
  const countsThisWeek = getRecentCountCount(state.mobileCountSessions);
  const qualityValue = state.dashboardLoading && !state.dashboardData ? "Loading" : itemsCounted ? (flagged ? "Review" : "Clean") : "No data";
  const qualityDetail = itemsCounted ? `${itemsCounted} latest item${itemsCounted === 1 ? "" : "s"}` : "Start a saved count";
  return `
    <main class="mobile-tab-panel mobile-dashboard-screen" id="dashboard">
      ${renderMobilePageTitle("Dashboard", "Today's inventory snapshot and recent activity.")}
      ${state.dashboardError ? `<div class="mobile-dashboard-status">${escapeHtml(state.dashboardError)}</div>` : ""}
      <section class="mobile-stats-grid" aria-label="Dashboard stats">
        ${renderMobileStatCard("chart", "Counts this week", String(countsThisWeek), countsThisWeek ? "saved in last 7 days" : "No saved counts", "green")}
        ${renderMobileStatCard("flag", "Items flagged", String(flagged || 0), latestSession ? "latest saved count" : "No saved count", "gold")}
        ${renderMobileStatCard("shield", "Data status", qualityValue, qualityDetail, flagged ? "gold" : "green", true)}
      </section>
      <section class="mobile-recent-card">
        <div class="mobile-card-heading">
          <h2>Past Counts</h2>
          <button type="button" data-mobile-tab-target="reports">View all</button>
        </div>
        ${renderMobilePastCountsPreview()}
      </section>
      <section class="mobile-quick-actions">
        <h2>Quick Actions</h2>
        <div>
          <button class="mobile-primary-action" type="button" data-mobile-tab-target="count">${ProductIcon("plusCircle")} Start Count <i>→</i></button>
          <button class="mobile-secondary-action" type="button" data-mobile-tab-target="reports">${ProductIcon("chart")} View Reports <i>→</i></button>
        </div>
      </section>
    </main>
  `;
}

function renderMobilePastCountsPreview() {
  if (state.mobileCountsLoading && !state.mobileCountSessions.length) {
    return `<div class="mobile-past-count-empty">Loading saved counts...</div>`;
  }
  if (state.mobileCountsError && !state.mobileCountSessions.length) {
    return `<div class="mobile-past-count-empty">${escapeHtml(state.mobileCountsError)}</div>`;
  }
  if (!state.mobileCountSessions.length) {
    return `<div class="mobile-past-count-empty">No saved counts yet. Start a count and it will stay here after refresh or login.</div>`;
  }
  return state.mobileCountSessions
    .slice(0, 5)
    .map((session) => renderMobilePastCountRow(session))
    .join("");
}

function renderMobilePastCountRow(session, options = {}) {
  const { compact = false } = options;
  const reviewCount = getCountReviewCount(session);
  const status = getCountStatusLabel(session);
  const isReview = reviewCount > 0 || /review/i.test(status);
  const itemCount = getCountItemCount(session);
  const active = Number(session.id) === Number(state.mobileSelectedCountId);
  return `
    <button class="mobile-recent-row mobile-past-count-row ${active ? "is-active" : ""}" type="button" data-mobile-count-id="${escapeHtml(session.id)}">
      <span class="mobile-row-icon">${ProductIcon(compact ? "file" : "store")}</span>
      <span>
        <strong>${escapeHtml(getCountArea(session))}</strong>
        <small>${escapeHtml(formatReportDate(getCountTimestamp(session)))}${compact ? "" : ` · ${itemCount} item${itemCount === 1 ? "" : "s"}`}</small>
      </span>
      <em class="${isReview ? "is-review" : ""}">${ProductIcon(isReview ? "calendar" : "check")} ${escapeHtml(status)}</em>
      <i aria-hidden="true">${ProductIcon("chevron")}</i>
    </button>
  `;
}

function renderMobileStatCard(iconName, label, value, detail, tone, isTextValue = false) {
  return `
    <article class="mobile-stat-card">
      <span class="mobile-stat-icon mobile-stat-icon--${tone}">${ProductIcon(iconName)}</span>
      <p>${escapeHtml(label)}</p>
      <strong class="${isTextValue ? "is-text-value" : ""}">${escapeHtml(value)}</strong>
      <small>${escapeHtml(detail)}</small>
    </article>
  `;
}

function renderMobileCountScreen({ totalItems, needsReview, primaryRecordingLabel, secondaryRecordingLabel }) {
  const restaurantName = state.selectedRestaurantName || "Restaurant workspace";
  const showActions = state.parsedEntries.length > 0 || state.report;
  return `
    <main class="mobile-tab-panel mobile-count-screen" id="count">
      <section class="mobile-count-card">
        ${renderMobilePageTitle("New Count", "Capture inventory quickly by voice.")}
        ${renderMessages()}
        ${renderMobileAreaSelector()}

        <section class="mobile-recorder-card">
          <strong>${formatTimer(state.recordingSeconds)}</strong>
          <p>${state.isRecording ? "Recording..." : state.recordingMode === "paused" ? "Paused" : "Ready to record"}</p>
          <button class="mobile-mic-button mic-button ${state.isRecording ? "mic-button--recording" : ""}" id="mobile-mic-button" type="button" aria-label="${state.isRecording ? "Pause recording" : state.recordingMode === "paused" ? "Resume recording" : "Start recording"}" style="--voice-level: ${state.voiceLevel.toFixed(3)}">
            <span>${ProductIcon("mic")}</span>
          </button>
          <div class="mobile-recording-controls" aria-label="Recording controls">
            <button class="recording-button recording-button--primary" id="mobile-recording-start-action" type="button" ${state.isRecording ? "disabled" : ""}>${primaryRecordingLabel === "Record" ? "Record" : primaryRecordingLabel}</button>
            <button class="recording-button recording-button--secondary" id="mobile-recording-pause-action" type="button" ${state.recordingMode === "idle" && !state.isRecording ? "disabled" : ""}>${secondaryRecordingLabel === "Clear" ? "Reset" : secondaryRecordingLabel}</button>
          </div>
        </section>

        <section class="mobile-transcript-card">
          <div>
            <label for="mobile-transcript-input">Transcript</label>
            <span aria-hidden="true">▥</span>
          </div>
          <textarea id="mobile-transcript-input" placeholder="Speak or type the count here...">${escapeHtml(state.transcript)}</textarea>
        </section>

        <div class="mobile-transcript-actions">
          <button class="mobile-process-button" id="mobile-process-count-button" type="button" ${state.isProcessing ? "disabled" : ""}>
            ${state.isProcessing ? "Processing" : "Process Count"} <i>→</i>
          </button>
          <button class="transcript-clear-button" id="mobile-clear-transcript-button" type="button">Clear</button>
        </div>
      </section>

      <section class="mobile-parsed-section">
        <div class="mobile-section-title">
          <h2>Parsed Items</h2>
          <span>${totalItems} total · ${needsReview} review</span>
        </div>
        ${renderParserDebugLine()}
        ${renderMobileInventoryCards()}
      </section>

      <div class="mobile-count-action-bar ${showActions ? "is-visible" : ""}" aria-label="Report actions">
        <button class="report-button report-button--primary" id="mobile-generate-report-button" type="button" ${state.isGeneratingReport || !state.activeCountId ? "disabled" : ""}>
          ${state.isGeneratingReport ? "Creating" : "Generate Report"}
        </button>
        <button class="report-button" id="mobile-export-action-button" type="button" ${!state.activeCountId ? "disabled" : ""}>Export CSV</button>
      </div>
    </main>
  `;
}

function getMobileReportEntries() {
  const entries = state.mobileSelectedReport?.entries || [];
  return entries.map((entry) => {
    const status = getEntryStatus(entry);
    return {
      name: getEntryCleanName(entry),
      quantity: `${entry.quantity ?? ""} ${entry.unit || ""}`.trim() || "Quantity not set",
      status: status.label === "Clean" ? "Confirmed" : status.label,
    };
  });
}

function renderMobileReportsScreen() {
  const sessions = state.mobileCountSessions;
  const selectedSession = sessions.find((session) => Number(session.id) === Number(state.mobileSelectedCountId)) || sessions[0] || null;
  const entries = getMobileReportEntries();
  const reportSummary = state.mobileSelectedReport?.summary || {};
  const total = reportSummary.total_items ?? getCountItemCount(selectedSession) ?? entries.length;
  const review = reportSummary.items_needing_review ?? getCountReviewCount(selectedSession) ?? entries.filter((entry) => entry.status !== "Confirmed").length;

  if (state.mobileCountsLoading && !sessions.length) {
    return `
      <main class="mobile-tab-panel mobile-reports-screen" id="reports">
        ${renderMobilePageTitle("Past Counts", "Saved count history for this restaurant.")}
        <section class="mobile-empty-report-card">
          <span>${ProductIcon("file")}</span>
          <h2>Loading saved counts...</h2>
        </section>
      </main>
    `;
  }

  if (state.mobileCountsError && !sessions.length) {
    return `
      <main class="mobile-tab-panel mobile-reports-screen" id="reports">
        ${renderMobilePageTitle("Past Counts", "Saved count history for this restaurant.")}
        <section class="mobile-empty-report-card">
          <span>${ProductIcon("file")}</span>
          <h2>Count history is unavailable.</h2>
          <p>${escapeHtml(state.mobileCountsError)}</p>
          <button class="mobile-primary-action" id="mobile-past-refresh-button" type="button">Try again <i>→</i></button>
        </section>
      </main>
    `;
  }

  if (!sessions.length) {
    return `
      <main class="mobile-tab-panel mobile-reports-screen" id="reports">
        ${renderMobilePageTitle("Past Counts", "Saved count history for this restaurant.")}
        ${renderMessages()}
        <section class="mobile-empty-report-card">
          <span>${ProductIcon("file")}</span>
          <h2>No saved counts yet.</h2>
          <p>Run a count from this restaurant and Koe will load it here after refresh or login.</p>
          <button class="mobile-primary-action" type="button" data-mobile-tab-target="count">Start Count <i>→</i></button>
        </section>
      </main>
    `;
  }

  return `
    <main class="mobile-tab-panel mobile-reports-screen" id="reports">
      ${renderMobilePageTitle("Past Counts", "Saved count history for this restaurant.")}
      ${renderMessages()}
      <section class="mobile-recent-card mobile-past-counts-list" aria-label="Saved counts">
        <div class="mobile-card-heading">
          <h2>Saved Counts</h2>
          <button id="mobile-past-refresh-button" type="button">Refresh</button>
        </div>
        ${sessions.map((session) => renderMobilePastCountRow(session, { compact: true })).join("")}
      </section>
      <section class="mobile-report-card">
        <div class="mobile-report-title-row">
          <span>${ProductIcon("file")}</span>
          <div>
            <h2>${escapeHtml(selectedSession ? `${getCountArea(selectedSession)} Count` : "Saved Count")}</h2>
            <p>${escapeHtml(formatReportDate(getCountTimestamp(selectedSession)))} <b>•</b> ${escapeHtml(getCountStatusLabel(selectedSession))}</p>
          </div>
        </div>
        <div class="mobile-report-summary-strip">
          <div><strong>${total}</strong><span>items counted</span></div>
          <div><strong>${review}</strong><span>needs review</span></div>
          <div><strong>${ProductIcon("check")}</strong><span>CSV ready</span></div>
        </div>
      </section>
      <section class="mobile-report-items" aria-label="Inventory report rows">
        ${
          state.mobileReportLoading
            ? `<div class="mobile-past-count-empty">Loading saved report...</div>`
            : state.mobileReportError
              ? `<div class="mobile-past-count-empty">${escapeHtml(state.mobileReportError)}</div>`
              : entries.length
                ? entries.map((entry) => renderMobileReportItem(entry)).join("")
                : `<div class="mobile-past-count-empty">Tap a saved count to load its report rows.</div>`
        }
      </section>
      <button class="mobile-process-button" id="mobile-past-export-button" type="button" ${!state.mobileSelectedCountId || state.mobileExportLoading ? "disabled" : ""}>
        ${ProductIcon("export")} ${state.mobileExportLoading ? "Exporting" : "Export CSV"}
      </button>
    </main>
  `;
}

function renderMobileReportItem(entry) {
  return `
    <article class="mobile-report-item">
      <span class="mobile-row-icon">${ProductIcon("store")}</span>
      <strong>${escapeHtml(entry.name)}</strong>
      <p>${escapeHtml(entry.quantity)}</p>
      <em>${ProductIcon("check")} ${escapeHtml(entry.status)}</em>
    </article>
  `;
}

function renderMobileAccountScreen() {
  return `
    <main class="mobile-tab-panel mobile-account-screen" id="account">
      ${renderMobilePageTitle("Account", "Workspace access and tester settings.")}
      <section class="mobile-profile-card">
        <span>${ProductIcon("user")}</span>
        <div>
          <h2>${escapeHtml(state.userEmail || "Koe tester")}</h2>
          <p>Tester</p>
        </div>
      </section>
      <section class="mobile-settings-card">
        <h2>Restaurant Workspace</h2>
        <div><span>${ProductIcon("store")}</span><strong>${escapeHtml(state.selectedRestaurantName || "Restaurant workspace")}</strong></div>
        <p>${escapeHtml(state.selectedRestaurantLocation || "Active restaurant workspace")}</p>
      </section>
      <section class="mobile-settings-card">
        <h2>Settings</h2>
        <button type="button">${ProductIcon("check")} Connected Google Sign-In ${ProductIcon("chevron")}</button>
        <button type="button">${ProductIcon("lock")} Privacy ${ProductIcon("chevron")}</button>
        <button type="button">${ProductIcon("help")} Help ${ProductIcon("chevron")}</button>
      </section>
      <button class="mobile-process-button" id="mobile-logout-button" type="button">Logout</button>
    </main>
  `;
}

function renderAuthPanel() {
  const isSignup = state.authMode === "signup";
  const title = isSignup ? "Create an account" : "Sign in to account";
  const subtitle = isSignup
    ? "Sign up with email or Google to get started."
    : "Use your email or Google to access your restaurant workspace.";
  const submitLabel = isSignup ? "Sign up" : "Sign in";
  const googleLabel = isSignup ? "Sign up with Google" : "Sign in with Google";
  return `
    <main class="auth-shell">
      <section class="auth-panel">
        <a href="./index.html" class="product-logo">Koe</a>
        <div class="auth-copy">
          <h1>${title}</h1>
          <p>${subtitle}</p>
        </div>
        ${renderMessages()}
        <form class="auth-form ${isSignup ? "auth-form--signup" : "auth-form--signin"}" id="auth-form">
          ${
            isSignup
              ? `<div class="auth-name-grid">
                  <label>
                    <span>First name</span>
                    <input id="auth-first-name" type="text" autocomplete="given-name" placeholder="Jane" value="${escapeHtml(state.authFirstName)}" required />
                  </label>
                  <label>
                    <span>Last name <em>(optional)</em></span>
                    <input id="auth-last-name" type="text" autocomplete="family-name" placeholder="Doe" value="${escapeHtml(state.authLastName)}" />
                  </label>
                </div>`
              : ""
          }
          ${
            isSignup
              ? `<label class="auth-restaurant-field">
                  <span>Name of Restaurant</span>
                  <input id="auth-restaurant-name" type="text" autocomplete="organization" placeholder="Restaurant name" value="${escapeHtml(state.authRestaurantName)}" required />
                </label>`
              : ""
          }
          <label class="auth-email-field">
            <span>Email</span>
            <input id="auth-email" type="email" autocomplete="email" placeholder="you@company.com" value="${escapeHtml(state.authEmail)}" required />
          </label>
          <label class="auth-password-field">
            <span>Password</span>
            <input id="auth-password" type="password" autocomplete="${isSignup ? "new-password" : "current-password"}" placeholder="${isSignup ? "Create a password" : ""}" required />
          </label>
          ${
            isSignup
              ? `<label class="auth-confirm-field">
                  <span>Confirm password</span>
                  <input id="auth-confirm-password" type="password" autocomplete="new-password" placeholder="Confirm your password" required />
                </label>`
              : ""
          }
          <button class="new-count-button auth-submit-button" type="submit" ${state.authLoading ? "disabled" : ""}>
            ${state.authLoading ? "Please wait..." : submitLabel}
          </button>
        </form>
        <div class="auth-divider"><span>Or</span></div>
        <button class="google-auth-button" id="google-auth-button" type="button" ${state.authLoading ? "disabled" : ""}>
          <span class="google-auth-mark" aria-hidden="true">G</span>
          <span>${googleLabel}</span>
        </button>
        <div class="auth-links">
          ${
            isSignup
              ? `<p>Already have an account? <button id="auth-switch-button" type="button">Sign in</button></p>`
              : `<p>Having trouble? <button id="reset-password-button" type="button">Reset password</button></p>
                 <p>Don't have an account? <button id="auth-switch-button" type="button">Sign up</button></p>`
          }
        </div>
      </section>
    </main>
  `;
}

function renderWorkspaceSetup() {
  return `
    <main class="auth-shell">
      <section class="auth-panel setup-panel">
        <div class="auth-panel-topline">
          <a href="./index.html" class="product-logo">Koe</a>
          <button class="ghost-button" id="logout-button" type="button">Exit</button>
        </div>
        <div class="auth-copy">
          <span class="auth-status">${escapeHtml(state.authStatus || "Setting up workspace...")}</span>
          <h1>Set up your restaurant workspace</h1>
          <p>${escapeHtml(state.userEmail || "This login")} is authenticated. Choose one tester workspace for local setup.</p>
        </div>
        ${renderMessages()}
        <div class="setup-actions">
          <button class="new-count-button tester-link-button" data-restaurant="Smoking Pig BBQ" type="button" ${state.authLoading ? "disabled" : ""}>Smoking Pig BBQ</button>
          <button class="new-count-button tester-link-button" data-restaurant="Massimo’s" type="button" ${state.authLoading ? "disabled" : ""}>Massimo’s</button>
        </div>
      </section>
    </main>
  `;
}

function renderDesktopAreaSelector() {
  const showCustomArea =
    state.mobileAreaOtherActive || Boolean(state.selectedArea && !MOBILE_AREA_OPTIONS.includes(state.selectedArea));
  return `
    <section class="workspace-card area-select-card" aria-label="Kitchen area">
      <span class="area-select-label">Kitchen area</span>
      <div class="desktop-area-options">
        ${MOBILE_AREA_OPTIONS.map((area) => {
          const active = area === "Other" ? showCustomArea : state.selectedArea === area;
          return `<button class="desktop-area-option ${active ? "is-active" : ""}" data-area="${escapeHtml(area)}" type="button">${escapeHtml(area)}</button>`;
        }).join("")}
      </div>
      ${
        showCustomArea
          ? `<input class="desktop-area-custom" id="desktop-area-custom" value="${escapeHtml(MOBILE_AREA_OPTIONS.includes(state.selectedArea) ? "" : state.selectedArea)}" placeholder="Type a custom area name" />`
          : ""
      }
    </section>
  `;
}

function renderDesktopSummaryPanel({ totalItems, needsReview, source, started, countId, selectedArea }) {
  const hasCount = Boolean(state.activeCountId);
  const hasData = totalItems > 0;

  const metaRows = [];
  if (selectedArea) metaRows.push(["Area", escapeHtml(selectedArea)]);
  if (hasCount) {
    metaRows.push(["Source", escapeHtml(source)]);
    if (state.countStartedAt) metaRows.push(["Started", escapeHtml(started)]);
    metaRows.push(["Count ID", escapeHtml(String(countId))]);
  }

  const summaryBody =
    hasCount || hasData
      ? `
        <div class="summary-stats">
          <div class="summary-stat">
            <strong>${totalItems}</strong>
            <span>Total items</span>
          </div>
          <div class="summary-stat ${needsReview ? "summary-stat--flag" : ""}">
            <strong>${needsReview}</strong>
            <span>Needs review</span>
          </div>
        </div>
        ${
          metaRows.length
            ? `<dl class="summary-meta">${metaRows
                .map(([label, value]) => `<div><dt>${label}</dt><dd>${value}</dd></div>`)
                .join("")}</dl>`
            : ""
        }
      `
      : `
        <div class="summary-empty">
          <strong>No count in progress</strong>
          <span>Start a count to see live totals and details here.</span>
        </div>
      `;

  return `
    <section class="workspace-card summary-panel">
      <div class="summary-section">
        <h2>${ProductIcon("file")} Count Summary</h2>
        ${summaryBody}
      </div>
      <div class="summary-section">
        <h3>${ProductIcon("heart")} Data Health</h3>
        ${renderDataHealth()}
      </div>
      <div class="summary-section summary-section--actions">
        <button class="report-button report-button--primary" id="generate-report-button" type="button" ${state.isGeneratingReport || !state.activeCountId || !totalItems ? "disabled" : ""}>
          ${ProductIcon("file")} ${state.isGeneratingReport ? "Creating" : "Report"} <span>→</span>
        </button>
        <button class="report-button" id="export-csv-button" type="button" ${!state.activeCountId || !totalItems ? "disabled" : ""}>${ProductIcon("export")} Export</button>
        <button class="report-button report-button--disabled" id="send-sheets-button" type="button" disabled>${ProductIcon("sheet")} Sheets</button>
      </div>
    </section>
  `;
}

function render() {
  if (!state.authReady) {
    app.innerHTML = `
      <main class="auth-shell">
        <section class="auth-panel">
          <a href="./index.html" class="product-logo">Koe</a>
          <div class="auth-copy">
            <h1>Loading</h1>
            <p>Checking session...</p>
          </div>
        </section>
      </main>
    `;
    return;
  }

  if (!isSupabaseConfigured) {
    state.authStatus = "Sign in to account";
    setError(supabaseConfigError);
    app.innerHTML = renderAuthPanel();
    bindAuthEvents();
    return;
  }

  if (!state.session) {
    app.innerHTML = renderAuthPanel();
    bindAuthEvents();
    return;
  }

  if (state.view === "setup" || state.workspaceMissing || !state.workspace) {
    app.innerHTML = renderWorkspaceSetup();
    bindAuthEvents();
    return;
  }

  if (state.view !== "ready") {
    app.innerHTML = `
      <main class="auth-shell">
        <section class="auth-panel">
          <a href="./index.html" class="product-logo">Koe</a>
          <div class="auth-copy">
            <h1>Loading</h1>
            <p>Setting up workspace...</p>
          </div>
        </section>
      </main>
    `;
    return;
  }

  const totalItems = state.parsedEntries.length;
  const needsReview = state.parsedEntries.filter(entryNeedsReview).length;
  const source = state.activeCountId ? "Voice Count" : "Not started";
  const started = state.countStartedAt ? formatDateTime(state.countStartedAt) : "—";
  const selectedArea = state.selectedArea.trim();
  const countId = state.activeCountId || "—";
  const primaryRecordingLabel = state.recordingMode === "paused" ? "Resume" : "Record";
  const secondaryRecordingLabel = state.recordingMode === "paused" ? "Clear" : "Pause";
  const mobileContext = { totalItems, needsReview, primaryRecordingLabel, secondaryRecordingLabel };
  app.innerHTML = `
    <div class="app-shell">
      ${renderSidebar({ restaurantName: state.selectedRestaurantName, active: "count", mobileActive: state.mobileActiveTab })}
      <main class="app-main product-shell">
      <div class="desktop-count-workspace">
        <header class="product-topbar">
          <div class="product-title-block">
            <h1>Inventory Count Workspace</h1>
          </div>
          <div class="account-panel">
            <span>${ProductIcon("pin")}</span>
            <div>
              <strong>${escapeHtml(state.userEmail || "Logged in")}</strong>
              <small>${escapeHtml(state.selectedRestaurantName)}</small>
            </div>
          </div>
          <button class="ghost-button logout-topbar-button" id="logout-button" type="button">Exit</button>
          <button class="new-count-button" id="start-count-button" type="button" ${state.isCreatingCount || !state.backendConnected ? "disabled" : ""}>
            ${ProductIcon("plus")} ${state.isCreatingCount ? "Starting" : "New count"}
          </button>
        </header>

        ${renderMessages()}

        <section class="product-grid" aria-label="Inventory count workspace">
          <div class="workspace-column">
            ${renderDesktopAreaSelector()}

            <section class="workspace-card voice-card">
              <div class="section-heading">
                <div>
                  <span class="step-number">01</span>
                  <h2>Count by Voice</h2>
                  <p>Speak into your browser microphone and Koe will place the live transcript here. You can also paste or type manually.</p>
                </div>
              </div>
              <div class="voice-capture voice-capture--interactive">
                <div class="mic-panel">
                  <button class="mic-ring mic-button ${state.isRecording ? "mic-button--recording" : ""}" id="mic-button" type="button" aria-label="${state.isRecording ? "Pause recording" : state.recordingMode === "paused" ? "Resume recording" : "Start recording"}" style="--voice-level: ${state.voiceLevel.toFixed(3)}">
                    <div class="mic-core">${ProductIcon("mic")}</div>
                  </button>
                  <strong>${formatTimer(state.recordingSeconds)}</strong>
                  <p class="mic-status">${state.isRecording ? "Recording…" : state.recordingMode === "paused" ? "Paused" : "Ready to record"}</p>
                  ${renderVoiceMeter()}
                  <div class="recording-controls" aria-label="Recording controls">
                    <button class="recording-button recording-button--primary" id="recording-start-action" type="button" ${state.isRecording ? "disabled" : ""}>${primaryRecordingLabel}</button>
                    <button class="recording-button recording-button--secondary" id="recording-pause-action" type="button" ${state.recordingMode === "idle" && !state.isRecording ? "disabled" : ""}>${secondaryRecordingLabel}</button>
                  </div>
                </div>
                <div class="transcript-panel transcript-panel--editor">
                  <label for="transcript-input">Transcript</label>
                  <textarea id="transcript-input" placeholder="Paste or type what your staff counted...">${escapeHtml(state.transcript)}</textarea>
                  <div class="transcript-actions">
                    <button class="transcript-clear-button" id="clear-transcript-button" type="button">Clear</button>
                    <button class="new-count-button process-button" id="process-count-button" type="button" ${state.isProcessing ? "disabled" : ""}>
                      ${state.isProcessing ? "Processing" : "Process"}
                    </button>
                  </div>
                </div>
              </div>
            </section>

            <section class="workspace-card parsed-card">
              <div class="section-heading section-heading--row">
                <div>
                  <span class="step-number">02</span>
                  <h2>Parsed Inventory</h2>
                  <p>Koe turns your transcript into structured, clean data from the local backend.</p>
                  ${renderParserDebugLine()}
                </div>
                <div class="parsed-header-actions">
                  <button class="ghost-button" id="edit-items-button" type="button">${ProductIcon("edit")} Edit</button>
                  <button class="clear-parsed-button" id="clear-parsed-button" type="button">Clear</button>
                </div>
              </div>
              ${renderInventoryTable()}
              <div class="table-footer">
                <button class="add-item-button" id="add-item-button" type="button">${ProductIcon("plus")} Add</button>
                <span>${totalItems} item${totalItems === 1 ? "" : "s"} total</span>
              </div>
            </section>

            <section class="workspace-card review-card">
              <div class="review-icon">${ProductIcon("shield")}</div>
              <div>
                <h2>Review Issues</h2>
                <p>${needsReview ? `${needsReview} item${needsReview === 1 ? "" : "s"} need review.` : "No critical issues found yet."}</p>
                <small>${totalItems ? "Review flags come directly from the backend parse response." : "Process a count to check for review issues."}</small>
              </div>
              <button class="ghost-button" id="review-items-button" type="button">Review</button>
            </section>

            ${renderReportPreview()}
          </div>

          <aside class="insight-column" aria-label="Count summary">
            ${renderDesktopSummaryPanel({ totalItems, needsReview, source, started, countId, selectedArea })}
          </aside>
        </section>
      </div>
      ${renderMobileAppShell(mobileContext)}
      </main>
    </div>
  `;

  bindEvents();
  scrollHashTargetIntoView();
}

function scrollHashTargetIntoView() {
  const hash = window.location.hash;
  if (!hash || state.lastScrolledHash === hash) return;
  const target = document.querySelector(hash);
  if (!target) return;
  state.lastScrolledHash = hash;
  window.requestAnimationFrame(() => {
    target.scrollIntoView({ block: "start" });
  });
}

function bindAuthEvents() {
  document.querySelector("#auth-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    state.authFirstName = document.querySelector("#auth-first-name")?.value || "";
    state.authLastName = document.querySelector("#auth-last-name")?.value || "";
    state.authRestaurantName = document.querySelector("#auth-restaurant-name")?.value || "";
    state.authEmail = document.querySelector("#auth-email")?.value || "";
    state.authPassword = document.querySelector("#auth-password")?.value || "";
    handleAuthSubmit(state.authMode);
  });
  document.querySelector("#auth-first-name")?.addEventListener("input", (event) => {
    state.authFirstName = event.target.value;
  });
  document.querySelector("#auth-last-name")?.addEventListener("input", (event) => {
    state.authLastName = event.target.value;
  });
  document.querySelector("#auth-restaurant-name")?.addEventListener("input", (event) => {
    state.authRestaurantName = event.target.value;
  });
  document.querySelector("#auth-email")?.addEventListener("input", (event) => {
    state.authEmail = event.target.value;
  });
  document.querySelector("#auth-password")?.addEventListener("input", (event) => {
    state.authPassword = event.target.value;
  });
  document.querySelector("#auth-confirm-password")?.addEventListener("input", (event) => {
    state.authConfirmPassword = event.target.value;
  });
  document.querySelector("#google-auth-button")?.addEventListener("click", handleGoogleSignIn);
  document.querySelector("#reset-password-button")?.addEventListener("click", handleResetPassword);
  document.querySelector("#auth-switch-button")?.addEventListener("click", () => {
    clearMessages();
    state.authMode = state.authMode === "login" ? "signup" : "login";
    state.authFirstName = "";
    state.authLastName = "";
    state.authRestaurantName = "";
    state.authPassword = "";
    state.authConfirmPassword = "";
    render();
  });
  document.querySelectorAll(".tester-link-button").forEach((button) => {
    button.addEventListener("click", () => {
      linkWorkspace(button.dataset.restaurant);
    });
  });
  document.querySelector("#logout-button")?.addEventListener("click", logout);
}

function bindEvents() {
  bindSidebar({ onLogout: logout });
  document.querySelectorAll("[data-mobile-tab-target]").forEach((button) => {
    button.addEventListener("click", () => setMobileTab(button.dataset.mobileTabTarget || "count"));
  });
  document.querySelector("#logout-button")?.addEventListener("click", logout);
  document.querySelector("#start-count-button")?.addEventListener("click", startNewCount);
  document.querySelector("#mobile-start-count-button")?.addEventListener("click", startNewCount);
  document.querySelector("#process-count-button")?.addEventListener("click", processCount);
  document.querySelector("#mobile-process-count-button")?.addEventListener("click", processCount);
  document.querySelector("#clear-transcript-button")?.addEventListener("click", handleClearTranscript);
  document.querySelector("#mobile-clear-transcript-button")?.addEventListener("click", handleClearTranscript);
  document.querySelector("#mic-button")?.addEventListener("click", handleMicButtonClick);
  document.querySelector("#mobile-mic-button")?.addEventListener("click", handleMicButtonClick);
  document.querySelector("#recording-start-action")?.addEventListener("click", handlePrimaryRecordingAction);
  document.querySelector("#mobile-recording-start-action")?.addEventListener("click", handlePrimaryRecordingAction);
  document.querySelector("#recording-pause-action")?.addEventListener("click", pauseRecording);
  document.querySelector("#mobile-recording-pause-action")?.addEventListener("click", pauseRecording);
  document.querySelector("#generate-report-button")?.addEventListener("click", generateReport);
  document.querySelector("#mobile-generate-report-button")?.addEventListener("click", generateReport);
  document.querySelector("#export-csv-button")?.addEventListener("click", exportCsv);
  document.querySelector("#mobile-export-csv-button")?.addEventListener("click", exportCsv);
  document.querySelector("#mobile-export-action-button")?.addEventListener("click", exportCsv);
  document.querySelector("#mobile-past-export-button")?.addEventListener("click", exportMobileSelectedCount);
  document.querySelector("#mobile-past-refresh-button")?.addEventListener("click", () => loadMobileCountSessions({ loadReport: true }));
  document.querySelectorAll("[data-mobile-count-id]").forEach((button) => {
    button.addEventListener("click", () => openMobilePastCount(button.dataset.mobileCountId));
  });
  document.querySelector("#mobile-logout-button")?.addEventListener("click", logout);
  document.querySelector("#send-sheets-button")?.addEventListener("click", () => {
    setNotice("Google Sheets export is not enabled yet. Use CSV export for now.");
    render();
  });
  document.querySelector("#edit-items-button")?.addEventListener("click", () => {
    setNotice("Manual row editing coming next.");
    render();
  });
  document.querySelector("#clear-parsed-button")?.addEventListener("click", handleClearParsedInventory);
  document.querySelector("#add-item-button")?.addEventListener("click", () => {
    setNotice("Manual item entry coming next.");
    render();
  });
  document.querySelector("#review-items-button")?.addEventListener("click", () => {
    setNotice("Detailed review workflow coming next.");
    render();
  });
  document.querySelectorAll("#transcript-input, #mobile-transcript-input").forEach((input) => {
    input.addEventListener("input", (event) => {
      setTranscriptText(event.target.value);
      event.target.scrollTop = event.target.scrollHeight;
    });
  });
  document.querySelectorAll(".desktop-area-option").forEach((button) => {
    button.addEventListener("click", () => {
      const area = button.dataset.area || "";
      state.mobileAreaOtherActive = area === "Other";
      state.selectedArea = area === "Other" ? "" : area;
      render();
      if (area === "Other") {
        document.querySelector("#desktop-area-custom")?.focus();
      }
    });
  });
  document.querySelector("#desktop-area-custom")?.addEventListener("input", (event) => {
    state.selectedArea = event.target.value;
    state.mobileAreaOtherActive = true;
  });
  document.querySelectorAll(".mobile-area-option").forEach((button) => {
    button.addEventListener("click", () => {
      const area = button.dataset.area || "";
      state.mobileAreaOtherActive = area === "Other";
      state.selectedArea = area === "Other" ? "" : area;
      render();
      if (area === "Other") {
        document.querySelector("#mobile-area-custom")?.focus();
      }
    });
  });
  document.querySelector("#mobile-area-custom")?.addEventListener("input", (event) => {
    state.selectedArea = event.target.value;
    state.mobileAreaOtherActive = true;
  });
}

window.addEventListener("beforeunload", stopRecording);
initialize();
