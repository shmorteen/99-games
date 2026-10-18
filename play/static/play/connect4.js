(() => {
  "use strict";

  const app = document.getElementById("connect4-app");
  const bootstrap = document.getElementById("connect4-bootstrap");
  if (!app || !bootstrap) return;

  const initial = JSON.parse(bootstrap.textContent);
  const boardBody = document.getElementById("connect4-board");
  const statusLabel = document.getElementById("connect4-status");
  const connectionLabel = document.getElementById("connect4-connection");
  const messageLabel = document.getElementById("connect4-message");
  const moveCountLabel = document.getElementById("connect4-move-count");
  const resultLink = document.getElementById("connect4-result-link");
  const buttons = [...app.querySelectorAll(".connect4-drop")];

  let state = initial.state;
  let version = initial.state_version;
  let actorId = initial.actor_id;
  let socket = null;
  let connected = false;
  let pending = null;
  let blocked = false;
  let stopped = false;
  let retryDelay = 500;
  let retryTimer = null;

  function requestId() {
    if (window.crypto.randomUUID) return window.crypto.randomUUID();
    return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (digit) =>
      (Number(digit) ^ (window.crypto.getRandomValues(new Uint8Array(1))[0] & 15)
        >> (Number(digit) / 4)).toString(16)
    );
  }

  function validState(candidate) {
    return candidate && Array.isArray(candidate.board) &&
      candidate.board.length === 6 &&
      candidate.board.every((row) => Array.isArray(row) && row.length === 7);
  }

  function statusText() {
    if (state.status === "completed") {
      if (state.result?.outcome === "draw") return "Draw game.";
      return state.result?.winner_actor_id === actorId ? "You won!" : "Opponent won.";
    }
    if (!connected) return "Reconnecting to the match…";
    if (pending) return "Move sent. Waiting for the server…";
    return state.turn_actor_id === actorId
      ? "Your turn — choose a column."
      : "Opponent's turn.";
  }

  function renderBoard() {
    boardBody.replaceChildren();
    state.board.forEach((row, rowIndex) => {
      const tr = document.createElement("tr");
      row.forEach((cell, columnIndex) => {
        const td = document.createElement("td");
        const marker = cell === "red" || cell === "yellow" ? cell : "empty";
        td.className = `connect4-cell connect4-cell-${marker}`;
        td.setAttribute(
          "aria-label",
          `Row ${rowIndex + 1}, column ${columnIndex + 1}: ${marker}`
        );
        const disc = document.createElement("span");
        disc.className = "connect4-disc";
        disc.setAttribute("aria-hidden", "true");
        disc.textContent = marker === "empty" ? "" : marker[0].toUpperCase();
        td.appendChild(disc);
        tr.appendChild(td);
      });
      boardBody.appendChild(tr);
    });
  }

  function render() {
    if (!validState(state)) {
      blocked = true;
      messageLabel.textContent = "The match state could not be displayed.";
      buttons.forEach((button) => { button.disabled = true; });
      return;
    }
    renderBoard();
    statusLabel.textContent = statusText();
    moveCountLabel.textContent = String(state.move_count);
    if (resultLink) resultLink.hidden = state.status !== "completed";
    connectionLabel.textContent = connected ? "Live" : "Connecting…";
    connectionLabel.classList.toggle("is-online", connected);
    buttons.forEach((button) => {
      const column = Number(button.dataset.column);
      button.disabled = blocked || !connected || Boolean(pending) ||
        state.status !== "in_progress" || state.turn_actor_id !== actorId ||
        state.board[0][column] !== null;
    });
  }

  function send(eventType, requestIdValue, payload) {
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify({type: eventType, request_id: requestIdValue, payload}));
    return true;
  }

  function sendPending() {
    if (!pending) return;
    send("GAME_ACTION", pending.requestId, {
      action: pending.action,
      state_version: pending.version,
    });
  }

  function applyState(payload) {
    if (!payload || !validState(payload.state) ||
        !Number.isInteger(payload.state_version)) return;
    if (payload.state_version < version) return;
    version = payload.state_version;
    state = payload.state;
    if (pending && version > pending.version) pending = null;
    messageLabel.textContent = "";
    render();
  }

  function handleMessage(raw) {
    let message;
    try {
      message = JSON.parse(raw.data);
    } catch {
      messageLabel.textContent = "An unreadable update was received.";
      return;
    }
    if (message.session_uuid !== initial.session_uuid) return;
    const payload = message.payload;
    if (message.type === "GAME_SNAPSHOT") {
      connected = true;
      retryDelay = 500;
      if (payload.actor_id) actorId = payload.actor_id;
      applyState(payload);
      if (pending && version === pending.version) sendPending();
    } else if (message.type === "GAME_STATE" || message.type === "GAME_ACTION_ACK") {
      if (pending && message.request_id === pending.requestId) pending = null;
      applyState(payload);
    } else if (message.type === "ERROR") {
      if (pending && message.request_id === pending.requestId) pending = null;
      messageLabel.textContent = payload?.message || "The move was rejected.";
      if (payload?.code === "stale_game_state") {
        send("GAME_RESYNC", requestId(), {});
      } else if (payload?.code === "permission_denied") {
        blocked = true;
        socket.close();
      }
      render();
    }
  }

  function connect() {
    if (stopped || blocked) return;
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    const connection = new WebSocket(
      `${scheme}//${window.location.host}${app.dataset.wsPath}`
    );
    socket = connection;
    connection.addEventListener("message", handleMessage);
    connection.addEventListener("error", () => connection.close());
    connection.addEventListener("close", () => {
      if (socket !== connection) return;
      connected = false;
      render();
      if (!stopped && !blocked) {
        retryTimer = window.setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 8000);
      }
    });
  }

  buttons.forEach((button) => button.addEventListener("click", () => {
    const column = Number(button.dataset.column);
    if (button.disabled || !Number.isInteger(column)) return;
    pending = {
      requestId: requestId(),
      version,
      action: {type: "drop_disc", column},
    };
    messageLabel.textContent = "";
    render();
    sendPending();
  }));

  window.addEventListener("beforeunload", () => {
    stopped = true;
    if (retryTimer !== null) window.clearTimeout(retryTimer);
    if (socket) socket.close();
  });
  render();
  connect();
})();
