"use strict";

const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");
const MIN_BOX = 3; // px: accidental clicks below this size are discarded

const state = {
  classes: [],
  colors: [],
  images: [], // [{path, annotated}]
  index: -1,
  boxes: [], // pixel-space rects {class_id, x, y, w, h}
  selected: -1,
  currentClass: 0,
  img: null,
  imageW: 0,
  imageH: 0,
  dirty: false,
  drawing: null, // {x0, y0, x1, y1}
};

const el = (id) => document.getElementById(id);

function toast(message, kind) {
  const node = el("toast");
  node.textContent = message;
  node.className = kind;
  window.setTimeout(() => { node.className = "hidden"; }, 2200);
}

async function api(path, options) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

// ------------------------------------------------------------ boot
async function boot() {
  let config;
  try {
    config = await api("/api/config");
  } catch {
    toast("Cannot reach the annotation server", "err");
    return;
  }
  state.classes = config.classes;
  state.colors = config.colors;
  renderLegend();

  try {
    const data = await api("/api/images");
    state.images = data.images;
    updateProgress(data.stats);
    if (state.images.length === 0) {
      el("empty-msg").classList.remove("hidden");
      return;
    }
    el("empty-msg").classList.add("hidden");
    goto(0);
  } catch (err) {
    toast(err.message, "err");
  }
}

// ------------------------------------------------------------- legend
function renderLegend() {
  const list = el("legend");
  list.innerHTML = "";
  state.classes.forEach((name, id) => {
    const li = document.createElement("li");
    li.dataset.id = id;
    li.innerHTML = `<span class="swatch" style="background:${state.colors[id]};"></span>${name}` +
      `<span class="legend-key">${id}</span>`;
    li.addEventListener("click", () => onClassChoice(id));
    list.appendChild(li);
  });
  highlightLegend();
}

function highlightLegend() {
  document.querySelectorAll("#legend li").forEach((li) => {
    const id = Number(li.dataset.id);
    const isCurrent = id === state.currentClass && state.selected < 0;
    const isSelectedClass = state.selected >= 0 && state.boxes[state.selected] && state.boxes[state.selected].class_id === id;
    li.classList.toggle("current", isCurrent);
    li.classList.toggle("selected-box-class", isSelectedClass);
  });
}

function onClassChoice(id) {
  if (id < 0 || id >= state.classes.length) return;
  if (state.selected >= 0) {
    state.boxes[state.selected].class_id = id;
    state.dirty = true;
  } else {
    state.currentClass = id;
  }
  render();
  highlightLegend();
  el("box-count").textContent = `${state.boxes.length} boxes`;
}

// ----------------------------------------------------------- progress
function updateProgress(stats) {
  el("progress-text").textContent = `Annotated: ${stats.annotated} / ${stats.total} · Progress: ${stats.percent}%`;
  el("progress-bar").style.width = `${stats.percent}%`;
}

function recomputeProgress() {
  const annotated = state.images.filter((img) => img.annotated).length;
  const total = state.images.length;
  updateProgress({ annotated, total, percent: total ? Math.round((100 * annotated) / total) : 0 });
}

// ------------------------------------------------------------ image nav
function goto(index) {
  if (index < 0 || index >= state.images.length) return;
  state.index = index;
  state.boxes = [];
  state.selected = -1;
  state.dirty = false;
  state.drawing = null;
  const image = state.images[index];
  el("current-path").textContent = image.path;
  el("box-count").textContent = "0 boxes";
  loadImage(image.path);
}

function tryGoto(index) {
  if (state.dirty && !window.confirm("Unsaved box changes will be lost. Continue?")) return;
  goto(index);
}

function nextImage() { tryGoto(state.index + 1); }
function prevImage() { tryGoto(state.index - 1); }

async function loadImage(path) {
  const img = new Image();
  img.onload = async () => {
    state.img = img;
    state.imageW = img.naturalWidth;
    state.imageH = img.naturalHeight;
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    try {
      const data = await api(`/api/annotation?path=${encodeURIComponent(path)}`);
      state.boxes = data.boxes.map(denormalize);
      el("box-count").textContent = `${state.boxes.length} boxes`;
    } catch {
      state.boxes = [];
    }
    render();
  };
  img.onerror = () => toast(`Failed to load ${path}`, "err");
  img.src = `/api/image?path=${encodeURIComponent(path)}`;
}

function normalize(box) {
  return {
    class_id: box.class_id,
    cx: +(Math.min(Math.max((box.x + box.w / 2) / state.imageW, 0), 1)).toFixed(6),
    cy: +(Math.min(Math.max((box.y + box.h / 2) / state.imageH, 0), 1)).toFixed(6),
    w: +(Math.min(box.w / state.imageW, 1)).toFixed(6),
    h: +(Math.min(box.h / state.imageH, 1)).toFixed(6),
  };
}

function denormalize(box) {
  return {
    class_id: box.class_id,
    x: (box.cx - box.w / 2) * state.imageW,
    y: (box.cy - box.h / 2) * state.imageH,
    w: box.w * state.imageW,
    h: box.h * state.imageH,
  };
}

// -------------------------------------------------------------- drawing
function eventCoords(e) {
  const rect = canvas.getBoundingClientRect();
  const sx = state.imageW / rect.width;
  const sy = state.imageH / rect.height;
  return {
    x: Math.min(Math.max((e.clientX - rect.left) * sx, 0), state.imageW),
    y: Math.min(Math.max((e.clientY - rect.top) * sy, 0), state.imageH),
  };
}

function hitTest(point) {
  for (let i = state.boxes.length - 1; i >= 0; i -= 1) {
    const b = state.boxes[i];
    if (point.x >= b.x && point.x <= b.x + b.w && point.y >= b.y && point.y <= b.y + b.h) return i;
  }
  return -1;
}

canvas.addEventListener("mousedown", (e) => {
  if (e.button !== 0 || !state.img) return;
  const point = eventCoords(e);
  const hit = hitTest(point);
  if (hit >= 0) {
    state.selected = hit;
    state.drawing = null;
    render();
    highlightLegend();
    return;
  }
  state.selected = -1;
  state.drawing = { x0: point.x, y0: point.y, x1: point.x, y1: point.y };
});

canvas.addEventListener("mousemove", (e) => {
  if (!state.drawing || !state.img) return;
  const point = eventCoords(e);
  state.drawing.x1 = point.x;
  state.drawing.y1 = point.y;
  render();
});

canvas.addEventListener("mouseup", () => {
  if (!state.drawing) return;
  const d = state.drawing;
  state.drawing = null;
  const x = Math.min(d.x0, d.x1);
  const y = Math.min(d.y0, d.y1);
  const w = Math.abs(d.x1 - d.x0);
  const h = Math.abs(d.y1 - d.y0);
  if (w < MIN_BOX || h < MIN_BOX) {
    render();
    return;
  }
  state.boxes.push({ class_id: state.currentClass, x, y, w, h });
  state.selected = state.boxes.length - 1;
  state.dirty = true;
  el("box-count").textContent = `${state.boxes.length} boxes`;
  render();
  highlightLegend();
});

// -------------------------------------------------------------- actions
async function save() {
  if (!state.img) return;
  try {
    const normalized = state.boxes.map(normalize);
    const result = await api("/api/annotation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: state.images[state.index].path, boxes: normalized }),
    });
    state.dirty = false;
    state.images[state.index].annotated = true;
    recomputeProgress();
    toast(`Saved ${result.saved} boxes`, "ok");
  } catch (err) {
    toast(`Save failed: ${err.message}`, "err");
  }
}

function deleteSelected() {
  if (state.selected < 0) return;
  state.boxes.splice(state.selected, 1);
  state.selected = -1;
  state.dirty = true;
  el("box-count").textContent = `${state.boxes.length} boxes`;
  render();
  highlightLegend();
}

function clearAll() {
  if (state.boxes.length === 0) return;
  if (!window.confirm("Clear all boxes on this image?")) return;
  state.boxes = [];
  state.selected = -1;
  state.dirty = true;
  el("box-count").textContent = "0 boxes";
  render();
  highlightLegend();
}

function quit() {
  window.close();
  toast("Close this browser tab to stop", "ok");
}

// --------------------------------------------------------------- render
function render() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (state.img) ctx.drawImage(state.img, 0, 0);
  state.boxes.forEach((b, i) => drawBox(b, i));
  if (state.drawing) {
    const d = state.drawing;
    const x = Math.min(d.x0, d.x1);
    const y = Math.min(d.y0, d.y1);
    ctx.save();
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = Math.max(2, state.imageW / 500);
    ctx.setLineDash([6, 4]);
    ctx.strokeRect(x, y, Math.abs(d.x1 - d.x0), Math.abs(d.y1 - d.y0));
    ctx.restore();
  }
}

function drawBox(b, index) {
  const color = state.colors[b.class_id % state.colors.length];
  const selected = index === state.selected;
  ctx.save();
  ctx.fillStyle = color;
  ctx.globalAlpha = 0.18;
  ctx.fillRect(b.x, b.y, b.w, b.h);
  ctx.globalAlpha = 1;
  ctx.strokeStyle = color;
  ctx.lineWidth = selected ? Math.max(4, state.imageW / 250) : Math.max(2, state.imageW / 500);
  ctx.strokeRect(b.x, b.y, b.w, b.h);
  ctx.fillStyle = color;
  ctx.font = `bold ${Math.max(14, state.imageW / 50)}px system-ui`;
  ctx.fillText(String(b.class_id), b.x + 4, b.y + ctx.lineWidth + 16);
  ctx.restore();
}

// ------------------------------------------------------------ shortcuts
document.addEventListener("keydown", (e) => {
  const key = e.key.toLowerCase();
  if (["n", "p", "s", "d", "c", "q", "arrowright", "arrowleft"].includes(key)) e.preventDefault();
  switch (key) {
    case "n":
    case "arrowright": nextImage(); break;
    case "p":
    case "arrowleft": prevImage(); break;
    case "s": save(); break;
    case "d": deleteSelected(); break;
    case "c": clearAll(); break;
    case "q": quit(); break;
    default:
      if (key >= "0" && key <= "9") {
        onClassChoice(Number(key));
      }
  }
});

el("btn-prev").addEventListener("click", prevImage);
el("btn-next").addEventListener("click", nextImage);
el("btn-save").addEventListener("click", save);
el("btn-delete").addEventListener("click", deleteSelected);
el("btn-clear").addEventListener("click", clearAll);
el("btn-quit").addEventListener("click", quit);

boot();