(() => {
  "use strict";
  const app = document.getElementById("connect4-replay");
  const bootstrap = document.getElementById("connect4-replay-bootstrap");
  if (!app || !bootstrap) return;
  const replay = JSON.parse(bootstrap.textContent);
  const frames = replay.frames;
  const board = document.getElementById("replay-board");
  const status = document.getElementById("replay-status");
  const position = document.getElementById("replay-position");
  const description = document.getElementById("replay-description");
  const previous = document.getElementById("replay-previous");
  const next = document.getElementById("replay-next");
  const step = document.getElementById("replay-step");
  let index = 0;

  function render() {
    const frame = frames[index];
    if (!frame || !Array.isArray(frame.state?.board)) return;
    board.replaceChildren();
    frame.state.board.forEach((row, rowIndex) => {
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
    position.textContent = `Move ${index} of ${frames.length - 1}`;
    step.value = String(index);
    previous.disabled = index === 0;
    next.disabled = index === frames.length - 1;
    if (index === 0) {
      status.textContent = "Start of match";
      description.textContent = "The board is empty.";
    } else {
      const move = frame.move;
      const marker = `${move.marker[0].toUpperCase()}${move.marker.slice(1)}`;
      description.textContent = `${marker} dropped in column ${move.column + 1}.`;
      if (frame.state.result?.outcome === "draw") status.textContent = "Draw game";
      else if (frame.state.result?.outcome === "win") status.textContent = `${marker} wins`;
      else status.textContent = `Move ${index}`;
    }
  }
  previous.addEventListener("click", () => { if (index > 0) { index -= 1; render(); } });
  next.addEventListener("click", () => {
    if (index < frames.length - 1) { index += 1; render(); }
  });
  step.addEventListener("input", () => {
    const selected = Number(step.value);
    if (Number.isInteger(selected) && selected >= 0 && selected < frames.length) {
      index = selected;
      render();
    }
  });
  render();
})();
