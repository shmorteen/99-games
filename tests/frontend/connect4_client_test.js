// Dependency-free browser-behavior check.
const assert = require("node:assert/strict");
const vm = require("node:vm");
const source = globalThis.CONNECT4_SOURCE || require("node:fs").readFileSync(
  require("node:path").resolve(__dirname, "../../play/static/play/connect4.js"),
  "utf8"
);

class Element {
  constructor() {
    this.children = [];
    this.listeners = {};
    this.dataset = {};
    this.disabled = false;
    this.textContent = "";
    this.classList = {toggle() {}};
  }
  appendChild(child) { this.children.push(child); }
  replaceChildren() { this.children = []; }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  click() { this.listeners.click(); }
}

const sessionId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const firstId = "11111111-1111-4111-8111-111111111111";
const secondId = "22222222-2222-4222-8222-222222222222";
const state = {
  status: "in_progress", board: Array.from({length: 6}, () => Array(7).fill(null)),
  turn_actor_id: firstId, move_count: 0,
};
const app = new Element();
app.dataset.wsPath = `/ws/games/${sessionId}/`;
const buttons = Array.from({length: 7}, (_, column) => {
  const button = new Element();
  button.dataset.column = String(column);
  return button;
});
app.querySelectorAll = () => buttons;
const bootstrap = new Element();
bootstrap.textContent = JSON.stringify({
  session_uuid: sessionId, state_version: 1, actor_id: firstId, state,
});
const elements = {
  "connect4-app": app,
  "connect4-bootstrap": bootstrap,
  "connect4-board": new Element(),
  "connect4-status": new Element(),
  "connect4-connection": new Element(),
  "connect4-message": new Element(),
  "connect4-move-count": new Element(),
};
const document = {
  getElementById: (id) => elements[id],
  createElement: () => new Element(),
};
const timers = [];
let requestNumber = 0;
const window = {
  crypto: {randomUUID: () => `aaaaaaaa-aaaa-4aaa-8aaa-${String(++requestNumber).padStart(12, "0")}`},
  location: {protocol: "http:", host: "localhost:8000"},
  addEventListener() {},
  setTimeout: (callback) => { timers.push(callback); return timers.length; },
  clearTimeout() {},
};
const sockets = [];
class FakeSocket {
  static OPEN = 1;
  constructor(url) {
    this.url = url;
    this.readyState = 1;
    this.listeners = {};
    this.sent = [];
    sockets.push(this);
  }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  send(value) { this.sent.push(JSON.parse(value)); }
  emit(type, value) { this.listeners[type](value); }
  close() {
    this.readyState = 3;
    this.emit("close", {});
  }
}

vm.runInNewContext(source, {window, document, WebSocket: FakeSocket});
assert.equal(sockets.length, 1);
assert.equal(buttons[3].disabled, true, "controls wait for a server snapshot");
sockets[0].emit("message", {data: JSON.stringify({
  type: "GAME_SNAPSHOT", session_uuid: sessionId,
  payload: {state_version: 1, actor_id: firstId, state},
})});
assert.equal(buttons[3].disabled, false);
buttons[3].click();
assert.equal(sockets[0].sent.length, 1);
assert.deepEqual(sockets[0].sent[0].payload, {
  action: {type: "drop_disc", column: 3}, state_version: 1,
});
assert.equal(buttons[3].disabled, true, "a pending move blocks repeat clicks");

const afterFirst = structuredClone(state);
afterFirst.board[5][3] = "red";
afterFirst.move_count = 1;
afterFirst.turn_actor_id = secondId;
sockets[0].emit("message", {data: JSON.stringify({
  type: "GAME_STATE", session_uuid: sessionId,
  request_id: sockets[0].sent[0].request_id,
  payload: {state_version: 2, state: afterFirst},
})});
assert.equal(elements["connect4-move-count"].textContent, "1");
assert.equal(buttons[3].disabled, true, "opponent's turn disables controls");
assert.equal(elements["connect4-board"].children[5].children[3].children[0].textContent, "R");

const afterSecond = structuredClone(afterFirst);
afterSecond.board[5][4] = "yellow";
afterSecond.move_count = 2;
afterSecond.turn_actor_id = firstId;
sockets[0].emit("message", {data: JSON.stringify({
  type: "GAME_STATE", session_uuid: sessionId,
  payload: {state_version: 3, state: afterSecond},
})});
assert.equal(buttons[1].disabled, false);
buttons[1].click();
const pendingRequest = sockets[0].sent[1].request_id;
sockets[0].close();
assert.equal(buttons[1].disabled, true, "disconnect disables controls");
timers.shift()();
assert.equal(sockets.length, 2);
sockets[1].emit("message", {data: JSON.stringify({
  type: "GAME_SNAPSHOT", session_uuid: sessionId,
  payload: {state_version: 3, actor_id: firstId, state: afterSecond},
})});
assert.equal(sockets[1].sent[0].request_id, pendingRequest, "reconnect retries the same ID");
assert.equal(sockets[1].sent[0].payload.state_version, 3);

const afterThird = structuredClone(afterSecond);
afterThird.board[5][1] = "red";
afterThird.move_count = 3;
afterThird.turn_actor_id = secondId;
sockets[1].emit("message", {data: JSON.stringify({
  type: "GAME_ACTION_ACK", session_uuid: sessionId, request_id: pendingRequest,
  payload: {state_version: 4, state: afterThird},
})});
assert.equal(elements["connect4-move-count"].textContent, "3");
assert.equal(buttons[1].disabled, true);
console.log("Connect4 client behavior passed");
