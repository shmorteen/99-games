const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");
const source = fs.readFileSync(path.resolve(__dirname, "../../play/static/play/hangman.js"), "utf8");

class Element {
  constructor() { this.textContent = ""; this.dataset = {}; this.disabled = false; this.hidden = false; this.listeners = {}; this.children = []; }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  setAttribute() {}
  replaceChildren() { this.children = []; this.textContent = ""; }
  append(...items) { this.children.push(...items); }
  click() { this.listeners.click(); }
}

const id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const first = "11111111-1111-4111-8111-111111111111";
const second = "22222222-2222-4222-8222-222222222222";
const state = {game: "hangman", status: "in_progress", mask: "_____", guessed_letters: [], wrong_guesses: 0, max_wrong_guesses: 6, turn_actor_id: first};
const app = new Element();
app.dataset.wsPath = `/ws/games/${id}/`;
app.dataset.player = "true";
const buttons = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("").map((letter) => { const button = new Element(); button.dataset.letter = letter; return button; });
app.querySelectorAll = () => buttons;
const bootstrap = new Element();
bootstrap.textContent = JSON.stringify({session_uuid: id, state_version: 1, actor_id: first, state});
const elements = {"hangman-app": app, "hangman-bootstrap": bootstrap};
for (const name of ["mask", "status", "connection", "message", "wrong", "guessed", "answer"]) elements[`hangman-${name}`] = new Element();
const document = {getElementById: (key) => elements[key], createElement: () => new Element()};
const timers = [];
const window = {crypto: {randomUUID: () => "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}, setTimeout: (callback) => timers.push(callback), addEventListener() {}};
const sockets = [];
class Socket {
  static OPEN = 1;
  constructor() { this.readyState = 1; this.listeners = {}; this.sent = []; sockets.push(this); }
  addEventListener(type, callback) { this.listeners[type] = callback; }
  send(raw) { this.sent.push(JSON.parse(raw)); }
  emit(type, value) { this.listeners[type](value); }
  close() { this.readyState = 3; this.emit("close", {}); }
}
vm.runInNewContext(source, {window, document, WebSocket: Socket, location: {protocol: "http:", host: "localhost"}});
assert.equal(buttons[0].disabled, true);
sockets[0].emit("message", {data: JSON.stringify({type: "GAME_SNAPSHOT", session_uuid: id, payload: {state_version: 1, actor_id: first, state}})});
assert.equal(buttons[0].disabled, false);
buttons[0].click();
assert.deepEqual(sockets[0].sent[0].payload, {action: {type: "guess_letter", letter: "A"}, state_version: 1});
assert.equal(buttons[0].disabled, true);
sockets[0].close();
timers.shift()();
sockets[1].emit("message", {data: JSON.stringify({type: "GAME_SNAPSHOT", session_uuid: id, payload: {state_version: 1, actor_id: first, state}})});
assert.equal(sockets[1].sent[0].request_id, sockets[0].sent[0].request_id);
const next = {...state, turn_actor_id: second, guessed_letters: ["A"], wrong_guesses: 1};
sockets[1].emit("message", {data: JSON.stringify({type: "GAME_ACTION_ACK", session_uuid: id, request_id: sockets[1].sent[0].request_id, payload: {state_version: 2, state: next}})});
assert.equal(elements["hangman-wrong"].textContent, "1");
assert.equal(buttons[1].disabled, true);
console.log("Hangman client behavior passed");
