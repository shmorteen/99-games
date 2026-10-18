(() => {
  "use strict";
  const app = document.getElementById("hangman-app");
  const bootstrap = document.getElementById("hangman-bootstrap");
  if (!app || !bootstrap) return;
  const initial = JSON.parse(bootstrap.textContent);
  const player = app.dataset.player === "true";
  const buttons = [...app.querySelectorAll("[data-letter]")];
  const mask = document.getElementById("hangman-mask");
  const status = document.getElementById("hangman-status");
  const connection = document.getElementById("hangman-connection");
  const message = document.getElementById("hangman-message");
  const wrong = document.getElementById("hangman-wrong");
  const guessed = document.getElementById("hangman-guessed");
  const answer = document.getElementById("hangman-answer");
  let state = initial.state;
  let version = initial.state_version;
  let actor = initial.actor_id;
  let socket = null;
  let connected = false;
  let pending = null;
  let stopped = false;
  let delay = 500;

  const valid = (value) => value && value.game === "hangman" &&
    typeof value.mask === "string" && Array.isArray(value.guessed_letters) &&
    Number.isInteger(value.wrong_guesses) && Number.isInteger(value.max_wrong_guesses);
  const requestId = () => window.crypto.randomUUID();
  function render() {
    if (!valid(state)) {
      message.textContent = "The match state could not be displayed.";
      buttons.forEach((button) => { button.disabled = true; });
      return;
    }
    mask.textContent = state.mask;
    mask.setAttribute("aria-label", `Word pattern: ${state.mask.split("").join(" ")}`);
    wrong.textContent = String(state.wrong_guesses);
    guessed.textContent = state.guessed_letters.join(" ") || "None yet";
    const complete = state.status === "completed";
    answer.hidden = !complete;
    answer.replaceChildren();
    if (complete && typeof state.answer === "string") {
      answer.append("Answer: ");
      const strong = document.createElement("strong");
      strong.textContent = state.answer;
      answer.append(strong);
    }
    if (complete) status.textContent = state.result?.outcome === "win" ? "Word solved!" : "No attempts left.";
    else if (!connected) status.textContent = "Reconnecting to the match…";
    else if (!player) status.textContent = "Players are guessing.";
    else if (pending) status.textContent = "Guess sent. Waiting for the server…";
    else status.textContent = state.turn_actor_id === actor ? "Your turn. Choose a letter." : "Waiting for another player.";
    connection.textContent = connected ? "Live" : "Connecting…";
    buttons.forEach((button) => {
      button.disabled = !connected || Boolean(pending) || complete ||
        state.turn_actor_id !== actor || state.guessed_letters.includes(button.dataset.letter);
    });
  }
  function send(type, id, payload) {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({type, request_id: id, payload}));
  }
  function sendPending() {
    if (pending) send("GAME_ACTION", pending.id, {action: pending.action, state_version: pending.version});
  }
  function apply(payload) {
    if (!payload || !valid(payload.state) || !Number.isInteger(payload.state_version) || payload.state_version < version) return;
    state = payload.state;
    version = payload.state_version;
    if (pending && version > pending.version) pending = null;
    message.textContent = "";
    render();
  }
  function handle(event) {
    let item;
    try { item = JSON.parse(event.data); } catch { message.textContent = "An unreadable update was received."; return; }
    if (item.session_uuid !== initial.session_uuid) return;
    if (item.type === "GAME_SNAPSHOT") {
      connected = true; delay = 500;
      if (item.payload?.actor_id) actor = item.payload.actor_id;
      apply(item.payload);
      if (pending && version === pending.version) sendPending();
    } else if (item.type === "GAME_STATE" || item.type === "GAME_ACTION_ACK") {
      if (pending && item.request_id === pending.id) pending = null;
      apply(item.payload);
    } else if (item.type === "ERROR") {
      if (pending && item.request_id === pending.id) pending = null;
      message.textContent = item.payload?.message || "The guess was rejected.";
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
      if (!stopped) { window.setTimeout(connect, delay); delay = Math.min(delay * 2, 8000); }
    });
  }
  buttons.forEach((button) => button.addEventListener("click", () => {
    if (button.disabled) return;
    pending = {id: requestId(), version, action: {type: "guess_letter", letter: button.dataset.letter}};
    render(); sendPending();
  }));
  window.addEventListener("beforeunload", () => { stopped = true; if (socket) socket.close(); });
  render(); connect();
})();
