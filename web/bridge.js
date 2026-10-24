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
let socket;

function clearSelection() {
  for (const tile of categoryGrid.children) {
    tile.classList.remove("highlight");
    tile.removeAttribute("aria-current");
  }
  phraseGrid.replaceChildren();
  phraseHeading.textContent = "Phrases";
}

for (const [id, label] of categories) {
  const tile = document.createElement("li");
  tile.className = "tile";
  tile.dataset.category = id;
  tile.textContent = label;
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
      (state.mode === "phrase" && (categoryIndex < 0 ||
        state.highlight_index >= phrases.length))) {
    clearSelection();
    mode.textContent = "Mode: unavailable";
    message.textContent = "Could not read the bridge state. Waiting for an update.";
    return;
  }

  clearSelection();
  mode.textContent = `Mode: ${state.mode}`;
  // Retain the Task 1 diagnostic so the connection smoke test stays useful.
  message.textContent = `Test message received: bridge state (${state.mode}).`;
  if (state.mode === "idle") return;

  const selectedCategory = state.mode === "category"
    ? state.highlight_index : categoryIndex;
  const categoryTile = categoryGrid.children[selectedCategory];
  categoryTile.classList.add("highlight");
  categoryTile.setAttribute("aria-current", "true");
  if (state.mode !== "phrase") return;

  phraseHeading.textContent = `${categories[categoryIndex][1]} phrases`;
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
      if (socket.readyState !== WebSocket.OPEN) return;
      socket.send(JSON.stringify({ type: "select", phrase_id: phrase.id, source: "ui" }));
      // Wait for the bridge's next state. Focus is not selection highlighting.
    });
    item.append(button);
    phraseGrid.append(item);
  });
}

function connect() {
  socket = new WebSocket(`ws://${window.location.host}/`);
  socket.addEventListener("open", () => {
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
    status.textContent = "Bridge connection unavailable";
  });
  socket.addEventListener("close", () => {
    clearSelection();
    mode.textContent = "Mode: unavailable";
    status.textContent = "Bridge disconnected — reconnecting…";
    message.textContent = "Waiting for the bridge to reconnect.";
    window.setTimeout(connect, 2000);
  });
}

connect();
