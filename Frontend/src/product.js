import {
  checkBackendHealth,
  createCountSession,
  downloadCsv,
  getAuthMe,
  getReport,
  linkTesterRestaurant,
  parseVoiceCount,
} from "./api.js";
import { isSupabaseConfigured, supabase, supabaseConfigError } from "./supabaseClient.js";
import { bindSidebar, renderSidebar } from "./sidebar.js";

const DEMO_TRANSCRIPT =
  "We have 3 bottles of olive oil, one of which is half empty, 3 heads of lettuce, 5 boxes of tomatoes, and 2 boxes of cheese.";

const AREA_OPTIONS = ["Dry Storage", "Walk-in", "Freezer", "Bar", "Wine Storage", "Prep Station"];

const state = {
  backendConnected: false,
  backendChecked: false,
  backendMessage: "Checking backend...",
  authReady: false,
  authMode: "login",
  authEmail: "",
  authPassword: "",
  authLoading: false,
  session: null,
  userEmail: "",
  workspaceMissing: false,
  workspace: null,
  selectedRestaurantId: null,
  selectedRestaurantName: "",
  selectedRestaurantLocation: "",
  selectedArea: "",
  status: "Ready",
  activeCountId: null,
  countStartedAt: null,
  transcript: "",
  parsedEntries: [],
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

function getSpeechRecognitionConstructor() {
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function playRecordingChirp() {
  const AudioContext = window.AudioContext || window.webkitAudioContext;
  if (!AudioContext) return;

  try {
    const context = new AudioContext();
    const oscillator = context.createOscillator();
    const tremolo = context.createOscillator();
    const tremoloGain = context.createGain();
    const gain = context.createGain();
    const startedAt = context.currentTime;

    oscillator.type = "triangle";
    oscillator.frequency.setValueAtTime(118, startedAt);
    oscillator.frequency.linearRampToValueAtTime(132, startedAt + 0.18);
    oscillator.frequency.linearRampToValueAtTime(110, startedAt + 0.34);

    tremolo.type = "sine";
    tremolo.frequency.setValueAtTime(38, startedAt);
    tremoloGain.gain.setValueAtTime(0.045, startedAt);
    tremolo.connect(tremoloGain);
    tremoloGain.connect(gain.gain);

    gain.gain.setValueAtTime(0.0001, startedAt);
    gain.gain.exponentialRampToValueAtTime(0.1, startedAt + 0.035);
    gain.gain.exponentialRampToValueAtTime(0.0001, startedAt + 0.38);

    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start(startedAt);
    tremolo.start(startedAt);
    oscillator.stop(startedAt + 0.4);
    tremolo.stop(startedAt + 0.4);
    window.setTimeout(() => context.close(), 520);
  } catch {
    // Audio feedback is optional and can be blocked by browser policy.
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
  const ring = document.querySelector("#mic-button");
  const capture = document.querySelector(".voice-capture--interactive");
  if (ring) {
    Object.entries(voiceVars).forEach(([name, value]) => ring.style.setProperty(name, value));
  }
  if (capture) {
    Object.entries(voiceVars).forEach(([name, value]) => capture.style.setProperty(name, value));
  }
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
  state.selectedRestaurantId = null;
  state.selectedRestaurantName = "";
  state.selectedRestaurantLocation = "";
  state.activeCountId = null;
  state.countStartedAt = null;
  state.parsedEntries = [];
  state.report = null;
  state.dataHealthItems = [];
  state.status = "Ready";
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

function buildDataHealth(entries) {
  if (!entries.length) return [];

  const items = [];
  const normalizedCount = entries.filter((entry) => entry.normalized_item_name).length;
  const partialCount = entries.filter((entry) => entry.partial_detail).length;
  const reviewCount = entries.filter((entry) => entry.needs_review).length;

  if (normalizedCount) items.push("Inventory names normalized");
  if (partialCount) items.push("Partial quantities resolved");
  items.push(reviewCount ? `${reviewCount} review flag${reviewCount === 1 ? "" : "s"} found` : "Review flags checked");

  return items;
}

function normalizeDisplayCategory(category) {
  const value = String(category || "").toLowerCase();
  if (["oils", "beverages", "liquid", "liquids", "bar", "wine"].includes(value)) return "Liquids";
  if (value === "produce") return "Produce";
  if (["meat", "meats", "seafood"].includes(value)) return "Meats";
  if (["dairy", "eggs", "dairy & eggs"].includes(value)) return "Dairy & Eggs";
  return "";
}

function inferCategory(entry) {
  const category = normalizeDisplayCategory(entry.category);
  if (category) return category;

  const name = String(entry.item_name || entry.name || "").toLowerCase();
  const unit = String(entry.unit || "").toLowerCase();
  if (/\b(oil|vinegar|water|wine|beer|juice|syrup|sauce|stock|broth|milk)\b/.test(name) || ["bottles", "gallons", "ounces"].includes(unit)) {
    return "Liquids";
  }
  if (/\b(tomato|tomatoes|lettuce|cucumber|cucumbers|onion|onions|pepper|peppers|carrot|carrots|potato|potatoes|fruit|herb|herbs|greens)\b/.test(name)) {
    return "Produce";
  }
  if (/\b(chicken|beef|pork|steak|fish|salmon|tuna|shrimp|turkey|meat)\b/.test(name)) {
    return "Meats";
  }
  if (/\b(egg|eggs|cheese|cream|butter|yogurt)\b/.test(name)) {
    return "Dairy & Eggs";
  }
  return "Other";
}

function groupEntriesByCategory(entries) {
  const order = ["Liquids", "Produce", "Meats", "Dairy & Eggs", "Other"];
  return order
    .map((category) => ({
      category,
      entries: entries.filter((entry) => inferCategory(entry) === category),
    }))
    .filter((group) => group.entries.length);
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
    state.authStatus = "Sign in to use Koe";
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
    state.authStatus = "Sign in to use Koe";
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

  supabase.auth.onAuthStateChange((_event, session) => {
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
    state.authStatus = "Sign in to use Koe";
    render();
  });
}

async function handleInvalidSession() {
  await supabase.auth.signOut();
  resetWorkspaceState();
  state.session = null;
  state.userEmail = "";
  state.view = "unauthenticated";
  state.authReady = true;
  state.authStatus = "Sign in to use Koe";
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
    state.authStatus = "Sign in to use Koe";
    render();
    return;
  }

  console.log("Supabase session found; loading workspace");
  state.view = "loading-workspace";
  state.authStatus = "Setting up workspace...";
  try {
    const me = await getAuthMe();
    if (!state.session) return;
    state.workspace = me.restaurant;
    state.workspaceMissing = false;
    state.view = "ready";
    state.selectedRestaurantId = me.restaurant.id;
    state.selectedRestaurantName = me.restaurant.name;
    state.selectedRestaurantLocation = "Restaurant workspace";
    state.userEmail = me.email || state.userEmail;
    state.authStatus = "Ready";
    clearMessages();
    console.log("Workspace loaded");
    if (state.pendingDashboardRedirect) {
      state.navigatingAway = true;
      window.location.assign("./dashboard.html");
      return;
    }
  } catch (error) {
    state.workspace = null;
    if (isUnauthorizedError(error)) {
      await handleInvalidSession();
      return;
    }
    if (isMissingWorkspaceError(error)) {
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

async function handleAuthSubmit(mode) {
  clearMessages();
  if (!isSupabaseConfigured) {
    setError(supabaseConfigError);
    render();
    return;
  }

  const email = document.querySelector("#auth-email")?.value.trim() || state.authEmail.trim();
  const password = document.querySelector("#auth-password")?.value || state.authPassword;
  if (!email || !password) {
    setError("Enter an email and password.");
    render();
    return;
  }

  state.authLoading = true;
  render();
  const result =
    mode === "signup"
      ? await supabase.auth.signUp({ email, password })
      : await supabase.auth.signInWithPassword({ email, password });
  state.authLoading = false;

  if (result.error) {
    setError(result.error.message);
    render();
    return;
  }

  state.authEmail = email;
  state.authPassword = "";
  setNotice(mode === "signup" ? "Account created. Check your email if confirmation is enabled." : "Logged in.");
  // After a successful auth + confirmed workspace, land on the dashboard.
  state.pendingDashboardRedirect = true;
  await initializeAuthFlow();
}

async function logout() {
  clearMessages();
  stopRecording();
  await supabase.auth.signOut();
  resetWorkspaceState();
  state.session = null;
  state.userEmail = "";
  state.view = "unauthenticated";
  state.authReady = true;
  state.authStatus = "Sign in to use Koe";
  render();
}

async function linkWorkspace(restaurantName) {
  clearMessages();
  state.authLoading = true;
  render();
  try {
    await linkTesterRestaurant(restaurantName);
    state.authLoading = false;
    await loadCurrentWorkspace();
    setNotice(`${restaurantName} linked to this login.`);
    render();
  } catch (error) {
    setError(error.message);
    render();
  } finally {
    state.authLoading = false;
  }
}

async function ensureCountSession() {
  if (state.activeCountId) return state.activeCountId;
  if (!state.session || state.view !== "ready") throw new Error("Sign in before starting a count.");
  if (!state.backendConnected) throw new Error("Backend not connected. Start FastAPI on port 8000.");

  state.isCreatingCount = true;
  render();
  try {
    const count = await createCountSession({
      area: state.selectedArea || null,
      notes: "Frontend local demo count",
    });
    state.activeCountId = count.id;
    state.countStartedAt = new Date(count.started_at || Date.now());
    state.status = "In Progress";
    state.parsedEntries = [];
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
  state.countStartedAt = null;
  state.status = "Ready";
  state.parsedEntries = [];
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
  const transcriptInput = document.querySelector("#transcript-input");
  const transcript = (transcriptInput?.value || state.transcript).trim();
  state.transcript = transcript;
  if (!transcript) {
    setError("Add a transcript before processing the count.");
    render();
    return;
  }

  state.isProcessing = true;
  state.status = state.activeCountId ? "In Progress" : "Ready";
  render();

  try {
    const countId = await ensureCountSession();
    const result = await parseVoiceCount({
      count_session_id: countId,
      text: transcript,
      area: state.selectedArea,
      save: true,
    });
    state.parsedEntries = result.entries || [];
    state.dataHealthItems = buildDataHealth(state.parsedEntries);
    state.report = null;
    state.status = "In Progress";
    if (state.parsedEntries.length) {
      setNotice(`Processed ${state.parsedEntries.length} inventory item${state.parsedEntries.length === 1 ? "" : "s"}.`);
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
    setError("Start and process a count first.");
    render();
    return;
  }
  if (!state.selectedArea.trim()) {
    setError("Pick or type a kitchen area before exporting CSV.");
    render();
    return;
  }
  try {
    if (!state.session || state.view !== "ready") throw new Error("Sign in before exporting CSV.");
    await downloadCsv(state.activeCountId);
  } catch (error) {
    setError(error.message);
    render();
  }
}

async function startRecording() {
  clearMessages();

  const SpeechRecognition = getSpeechRecognitionConstructor();
  if (!SpeechRecognition) {
    setError("Live speech-to-text is not supported in this browser. Use Chrome or type the transcript manually.");
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
    state.shouldRestartRecognition = true;
    state.isRecording = true;
    state.recordingMode = "recording";
    state.status = "Recording";
    setVoiceLevel(0);

    recognition.onresult = (event) => {
      let finalText = "";
      let interimText = "";

      for (let index = 0; index < event.results.length; index += 1) {
        const result = event.results[index];
        const transcript = result[0]?.transcript || "";
        if (result.isFinal) {
          finalText = joinTranscriptParts(finalText, transcript);
        } else {
          interimText = joinTranscriptParts(interimText, transcript);
        }
      }

      state.transcript = joinTranscriptParts(state.recognitionBaseTranscript, finalText, interimText);
      render();
    };

    recognition.onerror = (event) => {
      state.shouldRestartRecognition = false;
      stopRecording();
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        setError("Microphone permission was denied. Allow microphone access or type the transcript manually.");
      } else if (event.error === "no-speech") {
        setError("No speech was detected. Try recording again or type the transcript manually.");
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

    playRecordingChirp();
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
  state.status = state.activeCountId ? "In Progress" : "Ready";
  setNotice("Recording paused. Resume when you are ready, or reset the capture.");
  render();
}

function resetRecording() {
  stopRecording();
  state.recordingMode = "idle";
  state.recordingSeconds = 0;
  state.transcript = "";
  state.recognitionBaseTranscript = "";
  setNotice("Recording reset.");
  render();
}

function handlePrimaryRecordingAction() {
  if (state.isRecording) return;
  startRecording();
}

function handleMicButtonClick() {
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
  state.status = state.activeCountId ? "In Progress" : "Ready";
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
          const statusClass = entry.needs_review ? "status-pill status-pill--review" : "status-pill";
          const statusText = entry.needs_review ? "Needs Review" : "Confirmed";
          const detail = entry.partial_detail || entry.review_reason || entry.raw_phrase || "";
          return `
        <tr>
          <td class="drag-cell">⋮</td>
          <td>${escapeHtml(entry.item_name)}</td>
          <td>${escapeHtml(entry.quantity)}</td>
          <td>${escapeHtml(entry.unit)}</td>
          <td>${escapeHtml(entry.source || "Voice")}</td>
          <td><span class="${statusClass}">${entry.needs_review ? "!" : "✓"} ${statusText}</span></td>
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
          <th>Source</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
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
                  <td>${escapeHtml(entry.name)}</td>
                  <td>${escapeHtml(entry.quantity)}</td>
                  <td>${escapeHtml(entry.unit)}</td>
                  <td>${escapeHtml(entry.area || "—")}</td>
                  <td>${escapeHtml(entry.review_status)}</td>
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </section>
  `;
}

function renderAuthPanel() {
  const isSignup = state.authMode === "signup";
  return `
    <main class="auth-shell">
      <section class="auth-panel">
        <a href="./index.html" class="product-logo">Koe</a>
        <div class="auth-copy">
          <span class="auth-status">${escapeHtml(state.authStatus || "Sign in to use Koe")}</span>
          <h1>${isSignup ? "Create Tester Login" : "Sign in to use Koe"}</h1>
          <p>Use the email and password for your restaurant tester account.</p>
        </div>
        ${renderMessages()}
        <form class="auth-form" id="auth-form">
          <label>
            <span>Email</span>
            <input id="auth-email" type="email" autocomplete="email" value="${escapeHtml(state.authEmail)}" required />
          </label>
          <label>
            <span>Password</span>
            <input id="auth-password" type="password" autocomplete="${isSignup ? "new-password" : "current-password"}" required />
          </label>
          <button class="new-count-button auth-submit-button" type="submit" ${state.authLoading || !state.backendConnected ? "disabled" : ""}>
            ${state.authLoading ? "Please wait..." : isSignup ? "Sign Up" : "Log In"}
          </button>
        </form>
        <button class="ghost-button auth-switch-button" id="auth-switch-button" type="button">
          ${isSignup ? "Use an existing login" : "Create a tester login"}
        </button>
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
          <button class="ghost-button" id="logout-button" type="button">Logout</button>
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
    state.authStatus = "Sign in to use Koe";
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
  const needsReview = state.parsedEntries.filter((entry) => entry.needs_review).length;
  const source = state.activeCountId ? "Voice Count" : "Not started";
  const started = state.countStartedAt ? formatDateTime(state.countStartedAt) : "—";
  const selectedArea = state.selectedArea.trim();
  const countId = state.activeCountId || "—";
  const recordingLabel = state.isRecording ? "Transcribing" : state.recordingMode === "paused" ? "Paused" : "Ready";
  const primaryRecordingLabel = state.recordingMode === "paused" ? "Resume" : "Start";
  const secondaryRecordingLabel = state.recordingMode === "paused" ? "Reset" : "Pause";
  app.innerHTML = `
    <div class="app-shell">
      ${renderSidebar({ restaurantName: state.selectedRestaurantName, active: "count" })}
      <main class="app-main product-shell">
      <header class="product-topbar">
        <a href="./index.html" class="product-logo">Koe</a>
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
        <button class="ghost-button logout-topbar-button" id="logout-button" type="button">Logout</button>
        <button class="new-count-button" id="start-count-button" type="button" ${state.isCreatingCount || !state.backendConnected ? "disabled" : ""}>
          ${ProductIcon("plus")} ${state.isCreatingCount ? "Starting..." : "Start New Count"}
        </button>
      </header>

      ${renderMessages()}

      <section class="product-grid" aria-label="Inventory count workspace">
        <div class="workspace-column">
          <section class="workspace-card voice-card">
            <div class="section-heading">
              <div>
                <span class="step-number">01</span>
                <h2>Count by Voice</h2>
                <p>Speak into your browser microphone and Koe will place the live transcript here. You can also paste or type manually.</p>
              </div>
              <div class="listening-pill ${state.isRecording ? "" : "listening-pill--idle"}"><span></span> ${recordingLabel} <i></i></div>
            </div>
            <div class="voice-capture voice-capture--interactive">
              <div class="mic-panel">
                <button class="mic-ring mic-button ${state.isRecording ? "mic-button--recording" : ""}" id="mic-button" type="button" aria-label="${state.isRecording ? "Pause recording" : state.recordingMode === "paused" ? "Resume recording" : "Start recording"}" style="--voice-level: ${state.voiceLevel.toFixed(3)}">
                  <div class="mic-core">${ProductIcon("mic")}</div>
                </button>
                <strong>${formatTimer(state.recordingSeconds)}</strong>
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
                  <button class="ghost-button" id="demo-transcript-button" type="button">Use Demo Transcript</button>
                  <button class="new-count-button process-button" id="process-count-button" type="button" ${state.isProcessing ? "disabled" : ""}>
                    ${state.isProcessing ? "Processing Count..." : "Process Count"}
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
              </div>
              <button class="ghost-button" id="edit-items-button" type="button">${ProductIcon("edit")} Edit Items</button>
            </div>
            ${renderInventoryTable()}
            <div class="table-footer">
              <button class="add-item-button" id="add-item-button" type="button">${ProductIcon("plus")} Add Item</button>
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
            <button class="ghost-button" id="review-items-button" type="button">Review All Items</button>
          </section>

          ${renderReportPreview()}
        </div>

        <aside class="insight-column" aria-label="Count tools">
          <section class="workspace-card summary-card">
            <h2>${ProductIcon("file")} Count Summary</h2>
            <div class="area-control">
              <label for="area-input">Kitchen area</label>
              <div class="area-input-shell">
                <input id="area-input" list="area-options" value="${escapeHtml(state.selectedArea)}" placeholder="Type or choose an area" />
                <span aria-hidden="true"></span>
              </div>
              <datalist id="area-options">
                ${AREA_OPTIONS.map((area) => `<option value="${escapeHtml(area)}"></option>`).join("")}
              </datalist>
            </div>
            <dl>
              <div><dt>Total Items</dt><dd>${totalItems}</dd></div>
              <div><dt>Needs Review</dt><dd>${needsReview}</dd></div>
              <div><dt>Source</dt><dd>${source}</dd></div>
              <div><dt>Area</dt><dd>${escapeHtml(selectedArea || "Not set")}</dd></div>
              <div><dt>Started</dt><dd>${started}</dd></div>
              <div><dt>Count ID</dt><dd>${escapeHtml(countId)}</dd></div>
            </dl>
          </section>

          <section class="workspace-card data-card">
            <h2>${ProductIcon("heart")} Data Health</h2>
            <p>We clean and normalize your data after backend parsing.</p>
            ${renderDataHealth()}
          </section>

          <div class="report-actions">
            <button class="report-button report-button--primary" id="generate-report-button" type="button" ${state.isGeneratingReport || !state.activeCountId ? "disabled" : ""}>
              ${ProductIcon("file")} ${state.isGeneratingReport ? "Generating..." : "Generate Report"} <span>→</span>
            </button>
            <button class="report-button" id="export-csv-button" type="button" ${!state.activeCountId ? "disabled" : ""}>${ProductIcon("export")} Export CSV</button>
            <button class="report-button report-button--disabled" id="send-sheets-button" type="button" disabled>${ProductIcon("sheet")} Send to Sheets — Coming Soon</button>
          </div>
        </aside>
      </section>
      </main>
    </div>
  `;

  bindEvents();
}

function bindAuthEvents() {
  document.querySelector("#auth-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    state.authEmail = document.querySelector("#auth-email")?.value || "";
    state.authPassword = document.querySelector("#auth-password")?.value || "";
    handleAuthSubmit(state.authMode);
  });
  document.querySelector("#auth-email")?.addEventListener("input", (event) => {
    state.authEmail = event.target.value;
  });
  document.querySelector("#auth-password")?.addEventListener("input", (event) => {
    state.authPassword = event.target.value;
  });
  document.querySelector("#auth-switch-button")?.addEventListener("click", () => {
    clearMessages();
    state.authMode = state.authMode === "login" ? "signup" : "login";
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
  document.querySelector("#logout-button")?.addEventListener("click", logout);
  document.querySelector("#start-count-button")?.addEventListener("click", startNewCount);
  document.querySelector("#process-count-button")?.addEventListener("click", processCount);
  document.querySelector("#demo-transcript-button")?.addEventListener("click", () => {
    state.transcript = DEMO_TRANSCRIPT;
    setNotice("Demo transcript added.");
    render();
  });
  document.querySelector("#mic-button")?.addEventListener("click", handleMicButtonClick);
  document.querySelector("#recording-start-action")?.addEventListener("click", handlePrimaryRecordingAction);
  document.querySelector("#recording-pause-action")?.addEventListener("click", pauseRecording);
  document.querySelector("#generate-report-button")?.addEventListener("click", generateReport);
  document.querySelector("#export-csv-button")?.addEventListener("click", exportCsv);
  document.querySelector("#send-sheets-button")?.addEventListener("click", () => {
    setNotice("Google Sheets export is not enabled yet. Use CSV export for now.");
    render();
  });
  document.querySelector("#edit-items-button")?.addEventListener("click", () => {
    setNotice("Manual row editing coming next.");
    render();
  });
  document.querySelector("#add-item-button")?.addEventListener("click", () => {
    setNotice("Manual item entry coming next.");
    render();
  });
  document.querySelector("#review-items-button")?.addEventListener("click", () => {
    setNotice("Detailed review workflow coming next.");
    render();
  });
  document.querySelector("#transcript-input")?.addEventListener("input", (event) => {
    state.transcript = event.target.value;
  });
  document.querySelector("#area-input")?.addEventListener("input", (event) => {
    state.selectedArea = event.target.value;
  });
}

window.addEventListener("beforeunload", stopRecording);
initialize();
