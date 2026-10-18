(() => {
  "use strict";
  const app = document.getElementById("connect4-viewer");
  const bootstrap = document.getElementById("connect4-viewer-bootstrap");
  if (!app || !bootstrap) return;
  const initial = JSON.parse(bootstrap.textContent);
  const board = document.getElementById("connect4-board");
  const status = document.getElementById("connect4-status");
  const connection = document.getElementById("connect4-connection");
  const count = document.getElementById("connect4-move-count");
  const message = document.getElementById("connect4-message");
  const resultLink = document.getElementById("connect4-result-link");
  let state = initial.state;
  let version = initial.state_version;
  let connected = false;
  let stopped = false;
  let retryDelay = 500;

  function valid(candidate) {
    return candidate && Array.isArray(candidate.board) && candidate.board.length === 6 &&
      candidate.board.every((row) => Array.isArray(row) && row.length === 7);
  }
  function render() {
    if (!valid(state)) {
      message.textContent = "The match state could not be displayed.";
      return;
    }
    board.replaceChildren();
    state.board.forEach((row, rowIndex) => {
      const tr = document.createElement("tr");
      row.forEach((cell, columnIndex) => {
        const marker = cell === "red" || cell === "yellow" ? cell : "empty";
        const td = document.createElement("td");
        td.className = `connect4-cell connect4-cell-${marker}`;
        td.setAttribute("aria-label", `Row ${rowIndex + 1}, column ${columnIndex + 1}: ${marker}`);
        const disc = document.createElement("span");
        disc.className = "connect4-disc";
        disc.setAttribute("aria-hidden", "true");
        disc.textContent = marker === "empty" ? "" : marker[0].toUpperCase();
        td.appendChild(disc);
        tr.appendChild(td);
      });
      board.appendChild(tr);
    });
    count.textContent = String(state.move_count);
    if (resultLink) resultLink.hidden = state.status !== "completed";
    const result = state.result;
    if (result?.outcome === "draw") status.textContent = "Draw game.";
    else if (result?.outcome === "win") {
      const winner = state.players.find((player) => player.actor_id === result.winner_actor_id);
      status.textContent = winner ? `${winner.marker[0].toUpperCase()}${winner.marker.slice(1)} wins!` : "Game complete.";
    } else {
      const player = state.players.find((entry) => entry.actor_id === state.turn_actor_id);
      status.textContent = player ? `${player.marker[0].toUpperCase()}${player.marker.slice(1)} to move.` : "Match in progress.";
    }
    connection.textContent = connected ? "Live" : "Reconnecting…";
    connection.classList.toggle("is-online", connected);
  }
  function apply(payload) {
    if (!payload || !valid(payload.state) || !Number.isInteger(payload.state_version) ||
        payload.state_version < version) return;
    version = payload.state_version;
    state = payload.state;
    message.textContent = "";
    render();
  }
  function connect() {
    if (stopped) return;
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${window.location.host}${app.dataset.wsPath}`);
    socket.addEventListener("message", (event) => {
      let data;
      try { data = JSON.parse(event.data); } catch { return; }
      if (data.session_uuid !== initial.session_uuid) return;
      if (data.type === "GAME_SNAPSHOT") {
        connected = true;
        retryDelay = 500;
        apply(data.payload);
      } else if (data.type === "GAME_STATE") apply(data.payload);
      else if (data.type === "ERROR") message.textContent = data.payload?.message || "Live update failed.";
    });
    socket.addEventListener("close", (event) => {
      connected = false;
      render();
      if (event.code === 4403) { stopped = true; message.textContent = "This overlay link is unavailable."; return; }
      window.setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 2, 10000);
    });
  }
  render();
  connect();
})();
