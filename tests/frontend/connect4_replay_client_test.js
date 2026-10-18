// Dependency-free replay controls and board rendering check.
const assert = require("node:assert/strict");
const vm = require("node:vm");
const source = globalThis.CONNECT4_REPLAY_SOURCE || require("node:fs").readFileSync(
  require("node:path").resolve(__dirname, "../../play/static/play/connect4_replay.js"),
  "utf8"
);

class Element {
  constructor() {
    this.children = [];
    this.listeners = {};
    this.textContent = "";
    this.value = "";
    this.disabled = false;
  }
  appendChild(child) { this.children.push(child); }
  replaceChildren() { this.children = []; }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  click() { this.listeners.click(); }
  input() { this.listeners.input(); }
}

const initial = Array.from({length: 6}, () => Array(7).fill(null));
const afterFirst = structuredClone(initial);
afterFirst[5][3] = "red";
const final = structuredClone(afterFirst);
final[5][4] = "yellow";
const frames = [
  {state_version: 1, state: {board: initial}, move: null},
  {state_version: 2, state: {board: afterFirst},
   move: {number: 1, column: 3, row: 5, marker: "red"}},
  {state_version: 3, state: {board: final, result: {outcome: "win"}},
   move: {number: 2, column: 4, row: 5, marker: "yellow"}},
];
const elements = Object.fromEntries([
  "connect4-replay", "connect4-replay-bootstrap", "replay-board",
  "replay-status", "replay-position", "replay-description",
  "replay-previous", "replay-next", "replay-step",
].map((id) => [id, new Element()]));
elements["connect4-replay-bootstrap"].textContent = JSON.stringify({frames});
const document = {
  getElementById: (id) => elements[id],
  createElement: () => new Element(),
};
vm.runInNewContext(source, {document, console});

const board = elements["replay-board"];
const previous = elements["replay-previous"];
const next = elements["replay-next"];
const step = elements["replay-step"];
assert.equal(previous.disabled, true);
assert.equal(board.children[5].children[3].children[0].textContent, "");
next.click();
assert.equal(board.children[5].children[3].children[0].textContent, "R");
assert.equal(elements["replay-position"].textContent, "Move 1 of 2");
assert.equal(previous.disabled, false);
previous.click();
assert.equal(board.children[5].children[3].children[0].textContent, "");
step.value = "2";
step.input();
assert.equal(board.children[5].children[4].children[0].textContent, "Y");
assert.equal(elements["replay-status"].textContent, "Yellow wins");
assert.equal(next.disabled, true);
console.log("Connect4 replay client behavior passed");
