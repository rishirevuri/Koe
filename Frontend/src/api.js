import { supabase } from "./supabaseClient.js";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "https://koe-backend-pfz2.onrender.com";

export function getAuthHeader(session) {
  const token = session?.access_token;
  if (!token) {
    throw new Error("No Supabase session found. Sign in before using Koe.");
  }
  return { Authorization: `Bearer ${token}` };
}

async function getAuthHeaders(session = null) {
  if (session) return getAuthHeader(session);
  const { data } = await supabase.auth.getSession();
  return getAuthHeader(data.session);
}

async function request(path, options = {}) {
  const { auth = true, headers = {}, session = null, ...fetchOptions } = options;
  const authHeaders = auth ? await getAuthHeaders(session) : {};
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...authHeaders,
      ...headers,
    },
    ...fetchOptions,
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

  return response.json();
}

export async function checkBackendHealth() {
  return request("/health", { auth: false });
}

export async function getAuthMe() {
  return request("/auth/me");
}

export async function linkTesterRestaurant(restaurantName) {
  return request("/auth/dev-link-restaurant", {
    method: "POST",
    body: JSON.stringify({ restaurant_name: restaurantName }),
  });
}

export async function getRestaurants() {
  return request("/restaurants");
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
