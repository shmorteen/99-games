(() => {
  "use strict";
  const app = document.getElementById("werewolves-app");
  const bootstrap = document.getElementById("werewolves-bootstrap");
  if (!app || !bootstrap) return;
  const initial = JSON.parse(bootstrap.textContent);
  const isPlayer = app.dataset.player === "true";
  const controls = [...app.querySelectorAll("[data-target]")];
  const elements = {};
  for (const id of ["phase", "round", "connection", "status", "message", "votes", "duration", "elimination", "players", "role", "role-help", "own-vote"]) {
    elements[id] = document.getElementById(`werewolves-${id}`);
  }
  let state = initial.state;
  let privateState = isPlayer ? initial.private_state : null;
  let version = initial.state_version;
  let actorId = initial.actor_id;
  let socket = null;
  let connected = false;
  let pending = null;
  let stopped = false;
  let retryDelay = 500;

  function valid(candidate) {
    return candidate && candidate.game === "werewolves-vs-villagers" &&
      Array.isArray(candidate.players) && Number.isInteger(candidate.round_number) &&
      Number.isInteger(candidate.votes_cast);
  }
  function requestId() { return window.crypto.randomUUID(); }
  function seatFor(actor) { return state.players.find((person) => person.actor_id === actor)?.seat; }
  function renderPlayers() {
    elements.players.replaceChildren();
    state.players.forEach((person) => {
      const row = document.createElement("li");
      row.className = person.alive ? "" : "is-dead";
      const seat = document.createElement("span");
      seat.textContent = `Seat ${person.seat}${person.actor_id === actorId ? " · You" : ""}`;
      const condition = document.createElement("span");
      condition.textContent = `${person.alive ? "Alive" : "Eliminated"}${state.status === "completed" && person.role ? ` · ${person.role}` : ""}`;
      row.append(seat, condition);
      elements.players.appendChild(row);
    });
  }
  function render() {
    if (!valid(state)) {
      elements.message.textContent = "The game state could not be displayed.";
      controls.forEach((button) => { button.disabled = true; });
      return;
    }
    renderPlayers();
    const completed = state.status === "completed";
    elements.phase.textContent = completed ? "Completed" : state.phase === "night" ? "Night" : "Day";
    elements.round.textContent = `Round ${state.round_number}`;
    elements.votes.textContent = String(state.votes_cast);
    elements.duration.textContent = state.phase_seconds == null ? "—" : String(state.phase_seconds);
    elements.connection.textContent = connected ? "Live" : "Connecting…";
    const removedSeat = seatFor(state.last_eliminated_actor_id);
    elements.elimination.textContent = removedSeat ? `Seat ${removedSeat} was eliminated in the previous phase.` : "No elimination in the previous phase.";
    if (completed) elements.status.textContent = state.result?.winner === "draw" ? "Draw game." : `${state.result?.winner === "villagers" ? "Villagers" : "Werewolves"} win!`;
    else if (!connected) elements.status.textContent = "Reconnecting to the game…";
    else if (pending) elements.status.textContent = "Ballot sent. Waiting for the server…";
    else elements.status.textContent = `${state.phase === "night" ? "Night" : "Day"} vote in progress.`;
    if (isPlayer) {
      const role = privateState?.role;
      elements.role.textContent = role === "werewolf" ? "Werewolf" : role === "villager" ? "Villager" : "Role unavailable";
      elements["role-help"].textContent = role === "werewolf" ? "You vote at night and during the day." : "You vote during the day. Stay alive and find the wolves.";
      const votedSeat = seatFor(privateState?.vote_target_actor_id);
      elements["own-vote"].textContent = votedSeat ? `You voted for seat ${votedSeat} this phase.` : "Choose one living player when eligible.";
      const allowed = new Set((privateState?.legal_actions || []).map((action) => action.target_actor_id));
      controls.forEach((button) => {
        button.disabled = !connected || Boolean(pending) || completed || !allowed.has(button.dataset.target);
      });
    }
  }
  function send(type, id, payload) {
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({type, request_id: id, payload}));
  }
  function sendPending() {
    if (pending) send("GAME_ACTION", pending.id, {action: pending.action, state_version: pending.version});
  }
  function apply(payload) {
    if (!payload || !valid(payload.state) || !Number.isInteger(payload.state_version) || payload.state_version < version) return;
    version = payload.state_version;
    state = payload.state;
    if (isPlayer && payload.private_state) privateState = payload.private_state;
    if (pending && version > pending.version) pending = null;
    elements.message.textContent = "";
    render();
  }
  function handle(event) {
    let item;
    try { item = JSON.parse(event.data); } catch { elements.message.textContent = "An unreadable update was received."; return; }
    if (item.session_uuid !== initial.session_uuid) return;
    if (item.type === "GAME_SNAPSHOT") {
      connected = true; retryDelay = 500;
      if (isPlayer && item.payload?.actor_id) actorId = item.payload.actor_id;
      apply(item.payload);
      if (pending && version === pending.version) sendPending();
    } else if (item.type === "GAME_STATE" || item.type === "GAME_ACTION_ACK") {
      if (pending && item.request_id === pending.id) pending = null;
      apply(item.payload);
    } else if (item.type === "ERROR") {
      if (pending && item.request_id === pending.id) pending = null;
      elements.message.textContent = item.payload?.message || "The ballot was rejected.";
      if (item.payload?.code === "stale_game_state") send("GAME_RESYNC", requestId(), {});
      if (item.payload?.code === "permission_denied") stopped = true;
      render();
    }
  }
  function connect() {
    if (stopped) return;
    const scheme = location.protocol === "https:" ? "wss:" : "ws:";
    const current = new WebSocket(`${scheme}//${location.host}${app.dataset.wsPath}`);
    socket = current;
    current.addEventListener("message", handle);
    current.addEventListener("error", () => current.close());
    current.addEventListener("close", () => {
      if (socket !== current) return;
      connected = false; render();
      if (!stopped) { window.setTimeout(connect, retryDelay); retryDelay = Math.min(retryDelay * 2, 8000); }
    });
  }
  controls.forEach((button) => button.addEventListener("click", () => {
    if (button.disabled) return;
    pending = {id: requestId(), version, action: {type: "vote", target_actor_id: button.dataset.target}};
    render(); sendPending();
  }));
  window.addEventListener("beforeunload", () => { stopped = true; if (socket) socket.close(); });
  render(); connect();
})();
