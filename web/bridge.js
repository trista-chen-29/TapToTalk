"use strict";

// Category order is defined by CONTRACT.md. Phrase IDs and text come only
// from bridge state messages; the browser never chooses a menu transition.
const categories = [
  ["needs", "Needs"],
  ["pain_comfort", "Pain / comfort"],
  ["people", "People"],
  ["yes_no", "Yes / no"],
];
const status = document.getElementById("connection-status");
const message = document.getElementById("bridge-message");
const mode = document.getElementById("current-mode");
const categoryGrid = document.getElementById("category-grid");
const phraseGrid = document.getElementById("phrase-grid");
const phraseHeading = document.getElementById("phrase-heading");
const speakButton = document.getElementById("speak-button");
const sendStatus = document.getElementById("send-status");
let socket;
let connected = false;
let selectedPhrase = null;
let currentSnapshot = null;
let pendingSnapshot = null;

function updateSpeak() {
  speakButton.disabled = !connected || socket?.readyState !== WebSocket.OPEN ||
    !selectedPhrase || pendingSnapshot !== null;
  speakButton.textContent = pendingSnapshot === null ? "Speak" : "Sending…";
  speakButton.setAttribute("aria-busy", String(pendingSnapshot !== null));
  for (const item of phraseGrid.children) {
    item.children[0].disabled = !connected || pendingSnapshot !== null;
  }
}

function submitPhrase(phraseId) {
  if (!connected || socket.readyState !== WebSocket.OPEN || !selectedPhrase ||
      pendingSnapshot !== null) return;
  // Share the submission guard with direct phrase activation.
  pendingSnapshot = currentSnapshot;
  sendStatus.textContent = "Sending selection to bridge… Speech is not confirmed.";
  updateSpeak();
  try {
    socket.send(JSON.stringify({ type: "select", phrase_id: phraseId, source: "ui" }));
  } catch {
    pendingSnapshot = null;
    sendStatus.textContent = "Could not send selection. Check the connection and try again.";
    updateSpeak();
  }
}

speakButton.addEventListener("click", () => {
  if (selectedPhrase) submitPhrase(selectedPhrase.id);
});

function clearSelection() {
  selectedPhrase = null;
  currentSnapshot = null;
  for (const tile of categoryGrid.children) {
    tile.classList.remove("highlight");
    tile.removeAttribute("aria-current");
  }
  phraseGrid.replaceChildren();
  phraseHeading.textContent = "Phrases";
  updateSpeak();
}

for (const [id, label] of categories) {
  const tile = document.createElement("li");
  tile.className = "tile";
  tile.dataset.category = id;
  tile.textContent = label;
  // Decorative SVG only; category order, IDs and bridge selection stay unchanged.
  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  icon.setAttribute("viewBox", "0 0 32 32");
  icon.setAttribute("aria-hidden", "true");
  icon.setAttribute("focusable", "false");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#icon-${id}`);
  icon.append(use);
  tile.prepend(icon);
  categoryGrid.append(tile);
}

function renderState(state) {
  if (!state || state.type !== "state") return;
  const categoryIndex = categories.findIndex(([id]) => id === state.category);
  const phrases = state.phrases;
  const validPhrases = Array.isArray(phrases) && phrases.every((phrase) =>
    phrase && typeof phrase.id === "string" && phrase.id.length > 0 &&
    typeof phrase.text === "string" && phrase.text.trim().length > 0,
  );
  if (!["idle", "category", "phrase"].includes(state.mode) ||
      !Number.isInteger(state.highlight_index) || state.highlight_index < 0 ||
      !validPhrases || new Set(phrases.map((phrase) => phrase.id)).size !== phrases.length ||
      (state.mode === "category" && state.highlight_index >= categories.length) ||
      (state.mode === "phrase" && (
        state.highlight_index >= phrases.length ||
        (state.category != null && categoryIndex < 0)
      ))) {
    clearSelection();
    mode.textContent = "Mode: unavailable";
    message.textContent = "Could not read the bridge state. Waiting for an update.";
    return;
  }

  const snapshot = JSON.stringify([
    state.mode, state.category, state.highlight_index, phrases.map((phrase) => phrase.id),
  ]);
  if (pendingSnapshot !== null && snapshot !== pendingSnapshot) {
    pendingSnapshot = null;
    sendStatus.textContent = "Bridge state updated. Speech is not confirmed.";
  }
  clearSelection();
  currentSnapshot = snapshot;
  if (state.mode === "phrase") selectedPhrase = phrases[state.highlight_index];
  updateSpeak();
  mode.textContent = `Mode: ${state.mode}`;
  // Retain the Task 1 diagnostic so the connection smoke test stays useful.
  message.textContent = `Test message received: bridge state (${state.mode}).`;
  if (state.mode === "idle") return;

  if (state.mode === "category" || categoryIndex >= 0) {
    const selectedCategory = state.mode === "category"
      ? state.highlight_index : categoryIndex;
    const categoryTile = categoryGrid.children[selectedCategory];
    categoryTile.classList.add("highlight");
    categoryTile.setAttribute("aria-current", "true");
  }
  if (state.mode !== "phrase") return;

  phraseHeading.textContent = categoryIndex >= 0
    ? `${categories[categoryIndex][1]} phrases`
    : "Phrases";
  phrases.forEach((phrase, index) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tile phrase-button";
    button.dataset.phraseId = phrase.id;
    button.textContent = phrase.text;
    if (index === state.highlight_index) {
      button.classList.add("highlight");
      button.setAttribute("aria-current", "true");
    }
    button.addEventListener("click", () => {
      submitPhrase(phrase.id);
      // Wait for the bridge's next state. Focus is not selection highlighting.
    });
    item.append(button);
    phraseGrid.append(item);
  });
  updateSpeak();
}

function connect() {
  socket = new WebSocket(`ws://${window.location.host}/`);
  socket.addEventListener("open", () => {
    connected = true;
    clearSelection();
    updateSpeak();
    status.setAttribute("data-connection", "connected");
    status.textContent = "Connected to bridge";
    message.textContent = "Waiting for bridge state.";
  });
  socket.addEventListener("message", (event) => {
    try {
      renderState(JSON.parse(event.data));
    } catch {
      clearSelection();
      mode.textContent = "Mode: unavailable";
      message.textContent = "Could not read the bridge message.";
    }
  });
  socket.addEventListener("error", () => {
    connected = false;
    updateSpeak();
    status.setAttribute("data-connection", "disconnected");
    status.textContent = "Bridge connection unavailable";
  });
  socket.addEventListener("close", () => {
    connected = false;
    if (pendingSnapshot !== null) {
      sendStatus.textContent = "Connection lost. Selection outcome is unknown; nothing will be resent automatically.";
    }
    pendingSnapshot = null;
    clearSelection();
    mode.textContent = "Mode: unavailable";
    status.setAttribute("data-connection", "disconnected");
    status.textContent = "Bridge disconnected — reconnecting…";
    message.textContent = "Waiting for the bridge to reconnect.";
    window.setTimeout(connect, 2000);
  });
}

updateSpeak();
connect();
