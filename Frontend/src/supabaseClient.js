import { createClient } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

function hasUsableEnvValue(value) {
  const trimmed = String(value || "").trim();
  return Boolean(trimmed && trimmed !== "..." && !trimmed.startsWith("your_"));
}

export const isSupabaseConfigured = hasUsableEnvValue(supabaseUrl) && hasUsableEnvValue(supabaseAnonKey);
export const supabaseConfigError =
  "Supabase frontend environment variables are missing. Check Frontend/.env and restart npm run dev.";

export const supabase = createClient(
  supabaseUrl || "https://example.supabase.co",
  supabaseAnonKey || "anon-key-not-configured",
);
