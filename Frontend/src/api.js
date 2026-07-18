import { supabase } from "./supabaseClient.js";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "https://koe-backend-pfz2.onrender.com";
const SELECTED_RESTAURANT_KEY = "koe:selectedRestaurantId";
const DEFAULT_REQUEST_TIMEOUT_MS = 45000;

export function getSelectedRestaurantId() {
  return window.localStorage.getItem(SELECTED_RESTAURANT_KEY) || "";
}

export function setSelectedRestaurantId(restaurantId) {
  if (restaurantId) {
    window.localStorage.setItem(SELECTED_RESTAURANT_KEY, String(restaurantId));
    return;
  }
  window.localStorage.removeItem(SELECTED_RESTAURANT_KEY);
}

export function getAuthHeader(session) {
  const token = session?.access_token;
  if (!token) {
    throw new Error("No Supabase session found. Sign in before using Koe.");
  }
  return { Authorization: `Bearer ${token}` };
}

async function getAuthHeaders(session = null) {
  const authHeader = session ? getAuthHeader(session) : getAuthHeader((await supabase.auth.getSession()).data.session);
  const selectedRestaurantId = getSelectedRestaurantId();
  return selectedRestaurantId
    ? { ...authHeader, "X-Restaurant-Id": selectedRestaurantId }
    : authHeader;
}

async function request(path, options = {}) {
  const { auth = true, headers = {}, session = null, timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS, ...fetchOptions } = options;
  const authHeaders = auth ? await getAuthHeaders(session) : {};
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...authHeaders,
        ...headers,
      },
      signal: controller.signal,
      ...fetchOptions,
    });
  } catch (error) {
    if (error.name === "AbortError") {
      const timeoutError = new Error(`Request timed out while contacting the backend at ${API_BASE_URL}. Try again after the backend is awake.`);
      timeoutError.status = 0;
      throw timeoutError;
    }
    const networkError = new Error(
      `Backend unreachable at ${API_BASE_URL}. Check that the API is running, awake, and allowed by CORS. Browser error: ${error.message}`,
    );
    networkError.status = 0;
    throw networkError;
  } finally {
    window.clearTimeout(timeout);
  }

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const errorBody = await response.json();
      detail = errorBody.detail || detail;
    } catch {
      detail = response.statusText || detail;
    }
    if (response.status === 401) {
      detail = `Auth expired or invalid. Sign in again. (${detail})`;
    } else if (response.status >= 500) {
      detail = `Backend server error. ${detail}`;
    }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }

  try {
    return await response.json();
  } catch (error) {
    const invalidResponseError = new Error(`Backend returned an invalid JSON response from ${path}.`);
    invalidResponseError.status = response.status;
    throw invalidResponseError;
  }
}

export async function checkBackendHealth() {
  return request("/health", { auth: false });
}

export async function getAuthMe() {
  return request("/auth/me");
}

export async function getDashboardSummary() {
  return request("/dashboard/summary");
}

export async function linkTesterRestaurant(restaurantName) {
  return request("/auth/dev-link-restaurant", {
    method: "POST",
    body: JSON.stringify({ restaurant_name: restaurantName }),
  });
}

export async function createRestaurant(name, session = null) {
  return request("/restaurants", {
    method: "POST",
    session,
    body: JSON.stringify({ name }),
  });
}

export async function getRestaurants() {
  return request("/restaurants");
}

export async function getCountSessions() {
  return request("/counts");
}

export async function deleteCountSession(countId) {
  return request(`/counts/${encodeURIComponent(countId)}`, {
    method: "DELETE",
  });
}

export async function getInventoryItems(restaurantId = null) {
  const suffix = restaurantId ? `?restaurant_id=${encodeURIComponent(restaurantId)}` : "";
  return request(`/inventory/items${suffix}`);
}

export async function createCountSession({ area, notes, restaurant_id = null }) {
  return request("/counts", {
    method: "POST",
    body: JSON.stringify({ restaurant_id, area, notes }),
  });
}

export async function parseVoiceCount({ count_session_id, text, area, save, restaurant_id = null }) {
  return request("/ai/parse-voice", {
    method: "POST",
    timeoutMs: 90000,
    body: JSON.stringify({ restaurant_id, count_session_id, text, area, save }),
  });
}

export async function getReport(countId) {
  return request(`/reports/${encodeURIComponent(countId)}`);
}

export async function downloadCsv(countId) {
  const authHeaders = await getAuthHeaders();
  const response = await fetch(`${API_BASE_URL}/reports/${encodeURIComponent(countId)}/csv`, {
    headers: authHeaders,
  });

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const errorBody = await response.json();
      detail = errorBody.detail || detail;
    } catch {
      detail = response.statusText || detail;
    }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `koe-count-${countId}.csv`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
