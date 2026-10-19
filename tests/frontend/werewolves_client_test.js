const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.resolve(__dirname, "../../play/static/play/werewolves.js"), "utf8");

class Element {
  constructor() { this.textContent = ""; this.dataset = {}; this.disabled = false; this.listeners = {}; this.children = []; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  replaceChildren() { this.children = []; }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.children.push(child); }
  click() { this.listeners.click(); }
}
const sessionId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const first = "11111111-1111-4111-8111-111111111111";
const second = "22222222-2222-4222-8222-222222222222";
const state = {game: "werewolves-vs-villagers", status: "in_progress", phase: "night", round_number: 1, phase_seconds: 120, votes_cast: 0, last_eliminated_actor_id: null, players: [{actor_id: first, seat: 1, alive: true}, {actor_id: second, seat: 2, alive: true}]};
const privateState = {actor_id: first, role: "werewolf", alive: true, vote_target_actor_id: null, legal_actions: [{type: "vote", target_actor_id: second}]};
const app = new Element();
app.dataset.wsPath = `/ws/games/${sessionId}/`;
app.dataset.player = "true";
const button = new Element();
button.dataset.target = second;
app.querySelectorAll = () => [button];
const bootstrap = new Element();
bootstrap.textContent = JSON.stringify({session_uuid: sessionId, state_version: 1, actor_id: first, state, private_state: privateState});
const elements = {"werewolves-app": app, "werewolves-bootstrap": bootstrap};
for (const name of ["phase", "round", "connection", "status", "message", "votes", "duration", "elimination", "players", "role", "role-help", "own-vote"]) elements[`werewolves-${name}`] = new Element();
const document = {getElementById: (id) => elements[id], createElement: () => new Element()};
const timers = [];
const window = {crypto: {randomUUID: () => "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}, setTimeout: (callback) => timers.push(callback), addEventListener() {}};
const sockets = [];
class Socket {
  static OPEN = 1;
  constructor() { this.readyState = 1; this.listeners = {}; this.sent = []; sockets.push(this); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  send(raw) { this.sent.push(JSON.parse(raw)); }
  emit(name, value) { this.listeners[name](value); }
  close() { this.readyState = 3; this.emit("close", {}); }
}
vm.runInNewContext(source, {window, document, WebSocket: Socket, location: {protocol: "http:", host: "localhost"}});
assert.equal(button.disabled, true, "controls wait for a server snapshot");
sockets[0].emit("message", {data: JSON.stringify({type: "GAME_SNAPSHOT", session_uuid: sessionId, payload: {state_version: 1, actor_id: first, state, private_state: privateState}})});
assert.equal(elements["werewolves-role"].textContent, "Werewolf");
assert.equal(button.disabled, false);
button.click();
assert.deepEqual(sockets[0].sent[0].payload, {action: {type: "vote", target_actor_id: second}, state_version: 1});
assert.equal(button.disabled, true, "a pending ballot blocks repeat clicks");
sockets[0].close();
timers.shift()();
sockets[1].emit("message", {data: JSON.stringify({type: "GAME_SNAPSHOT", session_uuid: sessionId, payload: {state_version: 1, actor_id: first, state, private_state: privateState}})});
assert.equal(sockets[1].sent[0].request_id, sockets[0].sent[0].request_id, "reconnect retries the same ballot ID");
const next = {...state, phase: "day", votes_cast: 0, last_eliminated_actor_id: second, players: [{actor_id: first, seat: 1, alive: true}, {actor_id: second, seat: 2, alive: false}]};
const nextPrivate = {...privateState, vote_target_actor_id: null, legal_actions: []};
sockets[1].emit("message", {data: JSON.stringify({type: "GAME_ACTION_ACK", session_uuid: sessionId, request_id: sockets[1].sent[0].request_id, payload: {state_version: 2, state: next, private_state: nextPrivate}})});
assert.equal(elements["werewolves-phase"].textContent, "Day");
assert.equal(button.disabled, true);
assert.equal(elements["werewolves-elimination"].textContent, "Seat 2 was eliminated in the previous phase.");
console.log("Werewolves client behavior passed");
