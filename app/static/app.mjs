// Oh-Brother's editor page. Plain JavaScript modules, no build step.
// The server renders every preview and print. This file is the page: it edits
// the layout (all geometry in mm), draws selection and guides over the
// preview, and handles undo, data, templates and printing. The logic that
// needs no page is in the modules beside it, with tests in tests/editor/.

import * as elementOps from "./elements.mjs";
import * as fieldOps from "./fields.mjs";
import { fkey, lowerKeys } from "./fields.mjs";
import * as geo from "./geometry.mjs";
import { History } from "./history.mjs";
import { IMAGE_MAX, sidesToTry, sizeAt } from "./images.mjs";
import * as job from "./job.mjs";
import { CATS, PRESETS, checkEls, imageOf, newElement, roundAll } from "./layouts.mjs";
import { fmt, fmt2, fromUnit, imperial, nudgeStep, r2, setUnits, tapeName, toUnit, units } from "./units.mjs";

const $ = (s) => document.querySelector(s);
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null) el.append(k);
  return el;
};

const api = async (path, opts = {}) => {
  const r = await fetch(path, {
    headers: opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {},
    ...opts,
    body: opts.body && !(opts.body instanceof FormData) ? JSON.stringify(opts.body) : opts.body,
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(j.error || `${r.status} ${r.statusText}`), { status: r.status });
  return j;
};

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const S = {
  meta: null,
  layout: { tape: "62red", length_mm: 30, orientation: "portrait", elements: [] },
  sel: -1,             // element in the properties panel (-1 = none, or several)
  pick: new Set(),      // selected element indexes
  editing: -1,          // element whose text field has focus
  alignTo: "selection", // several selected: align to "selection" or "label"
  fixed: {},            // field key (lowercase) -> fixed text
  data: null,           // loaded data file: {headers, rows}
  mapping: {},          // field key (lowercase) -> column name ("" = fixed text)
  picked: new Set(),    // data rows ticked for printing
  cur: 0,               // data row shown in the preview
  placeholders: [],     // the layout's field names, from the last preview
  blank: new Map(),     // element index -> "empty"|"invalid": codes, images and text the last preview left blank
  glyph: null,          // the last image chosen, for quick layouts with an empty image slot
  scale: 1,             // screen px per dot
};

const STORE = "oh-brother:v1";
const save = () => { clearTimeout(saveTimer); try { localStorage.setItem(STORE, JSON.stringify({ layout: S.layout, fixed: S.fixed })); } catch {} };
// Coalesce saves to this browser's storage: dragging changes the layout every frame
let saveTimer = 0;
const saveSoon = () => { clearTimeout(saveTimer); saveTimer = setTimeout(save, 400); };
addEventListener("pagehide", save);
const restore = () => {
  try {
    const j = JSON.parse(localStorage.getItem(STORE) || "null");
    const layout = elementOps.tidyLayout(j?.layout, S.meta.limits.length_mm);
    if (layout) { S.layout = layout; S.fixed = lowerKeys(j.fixed); return true; }
  } catch {}
  return false;
};

// ---------------------------------------------------------------------------
// Undo history: snapshots of the layout and fixed values. Every edit calls
// schedule(), which takes a snapshot once edits pause; drags and discrete
// actions take one straight away. Typing inside a field keeps the browser's
// own undo for that field.
// ---------------------------------------------------------------------------

const hist = new History(100);
let histTimer = 0, dragging = false;
const snapshot = () => JSON.stringify({ layout: S.layout, fixed: S.fixed });

function checkpoint() {
  clearTimeout(histTimer);
  if (hist.record(snapshot())) drawUndo();
}
const checkpointSoon = () => { clearTimeout(histTimer); if (!dragging) histTimer = setTimeout(checkpoint, 500); };

function stepHistory(d) {
  checkpoint();   // keep any edit not yet recorded
  const to = hist.step(d);
  if (to === null) return;
  const j = JSON.parse(to);
  S.layout = j.layout; S.fixed = j.fixed;
  const n = S.layout.elements.length;
  S.pick = new Set([...S.pick].filter((i) => i < n));
  S.sel = S.pick.size === 1 ? [...S.pick][0] : -1;
  drawAll(); schedule();
  drawUndo();
}
const undo = () => stepHistory(-1), redo = () => stepHistory(1);

function drawUndo() {
  $("#undoBtn").disabled = !hist.canUndo;
  $("#redoBtn").disabled = !hist.canRedo;
}
$("#undoBtn").addEventListener("click", undo);
$("#redoBtn").addEventListener("click", redo);

// Ctrl+Z undo; Ctrl+Shift+Z and Ctrl+Y redo (Cmd on macOS)
document.addEventListener("keydown", (ev) => {
  if (!(ev.ctrlKey || ev.metaKey) || ev.altKey) return;
  const k = ev.key.toLowerCase();
  if (ev.target.matches("input, textarea, select") || $("#settings").open) {
    // The field's own undo runs next; record any pending typing first so the
    // app's history keeps it as a step of its own
    if (k === "z" || k === "y") checkpoint();
    return;
  }
  if (k === "z") { ev.shiftKey ? redo() : undo(); ev.preventDefault(); }
  else if (k === "y") { redo(); ev.preventDefault(); }
});

const tape = () => S.meta.tapes.find((t) => t.id === S.layout.tape) || S.meta.tapes[0];
const dpmm = () => S.meta.dpmm;

// The printable canvas and the cut label around it, in mm (geometry.mjs)
const canvasMM = () => geo.canvasMM(tape(), S.layout, dpmm());
const paperMM = () => geo.paperMM(tape(), S.layout, dpmm());

// Display units (units.mjs). Each browser remembers its choice; mm by default.
const UNITS = "oh-brother:units";
try { if (localStorage.getItem(UNITS) === "in") setUnits("in"); } catch {}

// ---------------------------------------------------------------------------
// Quick-layout thumbnails. The layouts themselves are in layouts.mjs.
// ---------------------------------------------------------------------------

// Thumbnail: the preset as built for the current label (W x H mm), with text
// drawn as bars. Strokes and bar heights scale with the label.
function presetThumb(p, W, H) {
  const k = Math.max(W, H) / 60, kb = Math.min(W, H) / 30;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  const add = (tag, a) => { const n = document.createElementNS(svg.namespaceURI, tag); for (const k in a) n.setAttribute(k, a[k]); svg.append(n); };
  add("rect", { x: 0, y: 0, width: W, height: H, fill: "#fff", stroke: "#d6d3ce", "stroke-width": 0.6 * k, rx: k });
  for (const e of p.make(W, H)) {
    const col = e.color === "red" ? "#d42b20" : "#2a2a2a";
    if (e.type === "text") {
      if (e.invert) add("rect", { x: e.x, y: e.y, width: e.w, height: e.h, fill: col });
      const lines = Math.max(1, (e.text.match(/\n/g) || []).length + 1);
      const lh = Math.min(e.h / lines * 0.55, (e.bold ? 6 : 4) * kb);
      for (let i = 0; i < lines; i++) {
        const bw = e.w * (i % 2 ? 0.6 : 0.8);
        const bx = e.align === "center" ? e.x + (e.w - bw) / 2 : e.x + Math.min(1, e.w * 0.05);
        const by = e.valign === "top" ? e.y + Math.min(1, e.h * 0.05) + i * lh * 1.6 : e.y + (e.h - lines * lh * 1.6) / 2 + i * lh * 1.6 + lh * 0.3;
        add("rect", { x: bx, y: by, width: bw, height: lh, fill: e.invert ? "#fff" : col, rx: 0.5 * kb });
      }
    } else if (e.type === "qr") {
      add("rect", { x: e.x, y: e.y, width: e.w, height: e.h, fill: "none", stroke: col, "stroke-width": e.w * 0.1 });
      add("rect", { x: e.x + e.w * 0.3, y: e.y + e.h * 0.3, width: e.w * 0.4, height: e.h * 0.4, fill: col });
    } else if (e.type === "rect" && e.fill === false) {
      add("rect", { x: e.x, y: e.y, width: e.w, height: e.h, fill: "none", stroke: col, "stroke-width": 0.6 * k });
    } else if (e.type === "rect") {
      add("rect", { x: e.x, y: e.y, width: Math.max(e.w, 0.4 * k), height: Math.max(e.h, 0.4 * k), fill: col });
    } else if (e.type === "barcode") {
      for (let i = 0; i < 18; i++) add("rect", { x: e.x + (e.w / 18) * i, y: e.y, width: (e.w / 18) * (i % 3 ? 0.4 : 0.75), height: e.h * 0.8, fill: col });
    } else if (e.type === "image") {
      // A star marks the image slot: plainly a placeholder, not a logo
      const r = Math.min(e.w, e.h) * 0.48, cx = e.x + e.w / 2, cy = e.y + e.h / 2 + r * 0.06;
      const pts = Array.from({ length: 10 }, (_, j) => {
        const rj = j % 2 ? r * 0.4 : r, a = -Math.PI / 2 + j * Math.PI / 5;
        return `${cx + rj * Math.cos(a)},${cy + rj * Math.sin(a)}`;
      });
      add("polygon", { points: pts.join(" "), fill: col });
    }
  }
  return svg;
}

// ---------------------------------------------------------------------------
// Data records
// ---------------------------------------------------------------------------

// Fields and the values that fill them are worked out in fields.mjs, from the
// state here
const fields = () => fieldOps.fields(S);
const chain = () => fieldOps.chain(S);
const record = (row) => fieldOps.record(S, row);
const autoMap = () => fieldOps.autoMap(S);

const previewRecord = () => record(S.data ? S.data.rows[S.cur] : null);

// ---------------------------------------------------------------------------
// Preview rendering
// One request in flight at a time. Edits made meanwhile trigger one more
// render when it returns, so the preview keeps up while dragging.
// ---------------------------------------------------------------------------

let renderTimer = 0, renderBusy = false, renderAgain = false, previewURL = null;

// delay: debounce for typing; 0 while dragging
function schedule(delay = 90) {
  saveSoon();
  checkpointSoon();
  drawOverlay();
  clearTimeout(renderTimer);
  renderTimer = setTimeout(() => { if (renderBusy) renderAgain = true; else doRender(); }, delay);
}

async function doRender() {
  renderBusy = true; renderAgain = false;
  try {
    const r = await fetch("/api/render", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ layout: S.layout, record: previewRecord(), chain: chain() }) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `${r.status} ${r.statusText}`);
    const meta = (k) => JSON.parse(decodeURIComponent(r.headers.get(k) || "%5B%5D"));
    const warnings = meta("X-Warnings"), placeholders = meta("X-Placeholders"), blank = meta("X-Blank");
    const url = URL.createObjectURL(await r.blob());
    // Decode off-screen first so the swap never shows a blank frame
    const next = new Image();
    next.src = url;
    await next.decode().catch(() => {});
    $("#preview").src = url;
    if (previewURL) URL.revokeObjectURL(previewURL);
    previewURL = url;
    S.blank = new Map(blank.map((b) => [b.i, b.why]));
    drawOverlay();
    const changed = placeholders.join("\u0000") !== S.placeholders.join("\u0000");
    S.placeholders = placeholders;
    // New fields weren't in the record just sent, so draw once more with their values
    if (changed) { autoMap(); drawData(); renderAgain = true; }
    drawWarnings(warnings);
  } catch (e) {
    drawWarnings([e.message]);
  } finally {
    renderBusy = false;
    if (renderAgain) doRender();
  }
}

// Size the paper (cut size) and its print area to fit the stage
// (never larger than 2x; crisp pixels at 1x and up)
function fit() {
  if (!S.meta) return;
  const c = canvasMM(), p = paperMM(), k = dpmm();
  const st = $("#stage");
  S.scale = Math.max(0.1, Math.min(2, (st.clientWidth - 56) / (p.w * k), (st.clientHeight - 56) / (p.h * k)));
  const px = k * S.scale;
  const wrap = $("#labelWrap");
  wrap.style.padding = `${p.my * px}px ${p.mx * px}px`;
  wrap.classList.toggle("round", tape().round);
  Object.assign($("#printArea").style, { width: c.w * px + "px", height: c.h * px + "px" });
  $("#preview").style.imageRendering = S.scale >= 1 ? "pixelated" : "auto";
  $("#dims").textContent = `Cut ${fmt2(p.w, p.h)} · printable ${fmt2(c.w, c.h)}`;
  drawOverlay();
}

function drawWarnings(list) {
  $("#warnings").replaceChildren(...list.map((w) => h("li", {}, "⚠ " + w)));
}

// ---------------------------------------------------------------------------
// Overlay: selection boxes, drag to move, handles to resize, snapping,
// drag on empty space to select several
// ---------------------------------------------------------------------------

const HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];
const SNAP_PX = 6;   // snap distance on screen

function drawOverlay() {
  const ov = $("#overlay"), els = S.layout.elements;
  // Rebuild only when the element count changes. Otherwise update in place,
  // so a box being dragged is never replaced under the pointer.
  if (ov.children.length !== els.length) {
    ov.replaceChildren(...els.map((_, i) => h("div", { class: "box", "data-i": i },
      ...HANDLES.map((d) => h("div", { class: `handle ${d}${d.length === 1 ? " edge" : ""}`, "data-h": d })))));
  }
  els.forEach((e, i) => placeBox(ov.children[i], e, i));
}

function placeBox(box, e, i) {
  const k = dpmm() * S.scale, w = e.w * k, hh = e.h * k;
  // QR codes stay square, so corners only; small boxes too
  const small = e.type === "qr" || w < 36 || hh < 36;
  box.className = "box" + (S.pick.has(i) ? " sel" : "") + (S.pick.size === 1 ? " solo" : "")
    + (small ? " small" : "") + (i === S.editing ? " editing" : "");
  // Blank QR/barcode/image, or text whose fields are all empty: an editor-only
  // placeholder (never part of the printed image)
  const why = S.blank.get(i);
  if (why && ["qr", "barcode", "image", "text"].includes(e.type)) {
    box.classList.add("blank");
    box.dataset.blank = e.type === "text" ? "Text · empty fields"
      : e.type === "image" ? `★ Image · ${why === "invalid" ? "can't be read" : "none chosen"}`
      : `${e.type === "qr" ? "QR" : "Barcode"} · ${why === "invalid" ? "invalid data" : "no data"}`;
  } else delete box.dataset.blank;
  box.style.cssText = `left:${e.x * k}px;top:${e.y * k}px;width:${w}px;height:${hh}px`;
}

// Bounding box (mm) of the given element indexes
const bounds = (idx) => geo.bounds(idx.map((i) => S.layout.elements[i]));

// Snap lines in mm, leaving out the elements being dragged
const snapTargets = (skip) => geo.snapTargets(S.layout.elements, skip, canvasMM());

function drawGuides(gx = [], gy = []) {
  const k = dpmm() * S.scale, c = canvasMM(), ext = 10;
  const line = (x1, y1, x2, y2) => {
    const l = document.createElementNS("http://www.w3.org/2000/svg", "line");
    Object.entries({ x1, y1, x2, y2 }).forEach(([a, v]) => l.setAttribute(a, v));
    return l;
  };
  const px = (mm) => Math.round(mm * k) + 0.5;   // centre 1px lines on a pixel
  $("#guides").replaceChildren(
    ...gx.map((x) => line(px(x), -ext, px(x), c.h * k + ext)),
    ...gy.map((y) => line(-ext, px(y), c.w * k + ext, px(y))));
}

// Pointer drags: run fn(latest event) once per animation frame, then done()
function track(el, ev, fn, done) {
  let last = null, frame = 0;
  const apply = () => { frame = 0; fn(last); };
  const onMove = (m) => { last = m; if (!frame) frame = requestAnimationFrame(apply); };
  const end = (m) => {
    if (frame) { cancelAnimationFrame(frame); apply(); }
    dragging = false;
    checkpoint();
    el.removeEventListener("pointermove", onMove);
    el.removeEventListener("pointerup", end);
    el.removeEventListener("pointercancel", end);
    done(m, last !== null);
  };
  dragging = true;
  el.setPointerCapture(ev.pointerId);
  el.addEventListener("pointermove", onMove);
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
  ev.preventDefault();
}

const additive = (ev) => ev.shiftKey || ev.ctrlKey || ev.metaKey;

$("#overlay").addEventListener("pointerdown", (ev) => {
  if (ev.button !== 0) return;
  // Take focus out of any text field, so Ctrl+Z after a drag reaches the
  // app's undo rather than the field's (preventDefault below keeps focus put)
  if (document.activeElement?.matches("input, textarea, select")) document.activeElement.blur();
  const k = dpmm() * S.scale;
  const box = ev.target.closest(".box");
  if (!box) { marquee(ev, k); return; }
  const i = +box.dataset.i;
  if (additive(ev)) { select(i, true); ev.preventDefault(); return; }
  const wasPicked = S.pick.has(i);
  if (!wasPicked) select(i);
  const hd = S.pick.size === 1 ? ev.target.dataset.h || "" : "";   // resize direction; "" = move
  const start = { x: ev.clientX, y: ev.clientY };
  const thrOf = (m) => m.altKey ? 0 : SNAP_PX / k;

  if (hd) {
    // Resize one element: only the dragged edges move, each snapping on its own
    const e = S.layout.elements[i];
    const s0 = { l: e.x, t: e.y, r: e.x + e.w, b: e.y + e.h };
    const targets = snapTargets(new Set([i]));
    track(box, ev, (m) => {
      const dx = (m.clientX - start.x) / k, dy = (m.clientY - start.y) / k;
      const { l, t, r, b, gx, gy } = geo.resizeBox(s0, hd, dx, dy, targets, thrOf(m), e.type === "qr");
      e.x = r2(l); e.y = r2(t); e.w = r2(r - l); e.h = r2(b - t);
      placeBox(box, e, i);
      drawGuides(gx, gy);
      drawProps(true);
      schedule(0);
    }, () => { drawGuides(); save(); });
    return;
  }

  // Move the whole selection. Its bounding box snaps like a single element:
  // left/centre/right and top/middle/bottom lines.
  const idx = picked();
  const orig = idx.map((j) => ({ x: S.layout.elements[j].x, y: S.layout.elements[j].y }));
  const b0 = bounds(idx);
  const targets = snapTargets(new Set(idx));
  track(box, ev, (m) => {
    const { x, y, gx, gy } = geo.moveBox(b0, (m.clientX - start.x) / k, (m.clientY - start.y) / k, targets, thrOf(m));
    idx.forEach((j, n) => {
      const e = S.layout.elements[j];
      e.x = r2(orig[n].x + x - b0.l); e.y = r2(orig[n].y + y - b0.t);
    });
    drawGuides(gx, gy);
    drawProps(true);
    schedule(0);
  }, (m, moved) => {
    drawGuides(); save();
    // A plain click on part of a group selects just that element
    if (!moved && wasPicked && S.pick.size > 1) select(i);
  });
});

// Drag on empty space: select every element the rectangle touches
// (Shift/Ctrl adds to the selection). A plain click clears it.
function marquee(ev, k) {
  const ov = $("#overlay"), mq = $("#marquee");
  const o = ov.getBoundingClientRect();
  const x0 = ev.clientX - o.left, y0 = ev.clientY - o.top;
  const base = additive(ev) ? new Set(S.pick) : new Set();
  track(ov, ev, (m) => {
    const x1 = m.clientX - o.left, y1 = m.clientY - o.top;
    const l = Math.min(x0, x1), t = Math.min(y0, y1), r = Math.max(x0, x1), b = Math.max(y0, y1);
    Object.assign(mq.style, { display: "block", left: l + "px", top: t + "px", width: r - l + "px", height: b - t + "px" });
    const hit = new Set(base);
    S.layout.elements.forEach((e, i) => {
      if (e.x * k < r && (e.x + e.w) * k > l && e.y * k < b && (e.y + e.h) * k > t) hit.add(i);
    });
    setPick(hit);
  }, (m, moved) => {
    mq.style.display = "none";
    if (!moved && !additive(ev)) select(-1);
  });
}

// Align (geometry.mjs's ALIGN): one element to the printable area; several to
// their own bounding box or to the printable area (S.alignTo)

const svgIcon = (draw) => {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("width", 16); svg.setAttribute("height", 16);
  draw((tag, a) => {
    const n = document.createElementNS(ns, tag);
    for (const [key, v] of Object.entries(a)) n.setAttribute(key, v);
    svg.append(n);
  });
  return svg;
};
// Swap x/y attributes, to draw an icon once and get its vertical twin
const T_ATTR = { x: "y", y: "x", width: "height", height: "width", x1: "y1", y1: "x1", x2: "y2", y2: "x2" };
const transpose = (a) => Object.fromEntries(Object.entries(a).map(([k, v]) => [T_ATTR[k] || k, v]));

// 16px icon: a guide line and two bars, drawn for "left" then transposed
function alignIcon(kind) {
  const pos = { left: 0, top: 0, hcenter: 1, vcenter: 1, right: 2, bottom: 2 }[kind];
  const vert = ["top", "vcenter", "bottom"].includes(kind);
  return svgIcon((add) => {
    const put = (tag, a) => add(tag, vert ? transpose(a) : a);
    const at = [2.5, 8, 13.5][pos];
    put("line", { x1: at, y1: 1.5, x2: at, y2: 14.5, stroke: "currentColor", "stroke-width": 1 });
    for (const [len, y] of [[9, 4], [6, 9]]) {
      put("rect", { x: [4, 8 - len / 2, 12 - len][pos], y, width: len, height: 3, fill: "currentColor", rx: 0.5 });
    }
  });
}

// 16px icon: three bars with equal gaps, between two end lines
function distIcon(vert) {
  return svgIcon((add) => {
    const put = (tag, a) => add(tag, vert ? transpose(a) : a);
    for (const x of [1.5, 14.5]) put("line", { x1: x, y1: 1.5, x2: x, y2: 14.5, stroke: "currentColor", "stroke-width": 1 });
    for (const [x, hh] of [[3.5, 8], [7, 5], [10.5, 8]]) put("rect", { x, y: 8 - hh / 2, width: 2, height: hh, fill: "currentColor" });
  });
}

function alignRow() {
  return h("div", { class: "align" }, ...geo.ALIGN.map((a) => !a ? h("span", { class: "gap" }) :
    h("button", { type: "button", class: "icon", title: a[1], onclick: () => {
      const idx = picked(), c = canvasMM();
      const R = idx.length > 1 && S.alignTo === "selection" ? bounds(idx) : { l: 0, t: 0, r: c.w, b: c.h };
      geo.alignEls(pickedEls(), a, R);
      drawProps(true); schedule();
    } }, alignIcon(a[0]))));
}

// Distribute: equal gaps between three or more elements; the two outermost stay put
function distribute(vert) {
  if (S.pick.size < 3) return;
  geo.distribute(pickedEls(), vert);
  schedule();
}

// Keyboard: nudge with arrows (0.5 mm, Shift = 2 mm; in inches 0.02 in,
// Shift = 0.1 in), Delete or Backspace removes, Escape deselects, Ctrl+A
// selects all
document.addEventListener("keydown", (ev) => {
  if (ev.target.matches("input, textarea, select") || $("#settings").open) return;
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "a") {
    setPick(new Set(S.layout.elements.map((_, i) => i))); ev.preventDefault(); return;
  }
  if (!S.pick.size) return;
  const step = nudgeStep(ev.shiftKey);
  const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[ev.key];
  if (d) {
    geo.nudge(pickedEls(), ...d);
    drawProps(true); schedule(); ev.preventDefault();
  }
  else if (ev.key === "Delete" || ev.key === "Backspace") { removeEls(picked()); ev.preventDefault(); }
  else if (ev.key === "Escape") select(-1);
});

// Double-click a text, QR or barcode element: jump to its text field
$("#overlay").addEventListener("dblclick", (ev) => {
  const box = ev.target.closest(".box");
  if (!box) return;
  select(+box.dataset.i);
  const f = $("#props").querySelector('[data-key="text"], [data-key="data"]');
  if (f) { f.focus(); f.setSelectionRange?.(f.value.length, f.value.length); }
  else $("#props").querySelector('input[type="file"]')?.click();   // an image: choose one
});

// ---------------------------------------------------------------------------
// Elements list & properties
// ---------------------------------------------------------------------------

const KIND = { text: "Text", qr: "QR", barcode: "Barcode", image: "Image", rect: "Box" };
// A barcode type's name and what it takes, from the server (/api/meta)
const barcodeKind = (e) => S.meta.barcodes.find((k) => k.id === (e.symbology || "code128")) || S.meta.barcodes[0];
const summary = (e) => e.type === "text" ? e.text.replace(/\n/g, " ⏎ ") : e.type === "rect" ? fmt2(e.w, e.h)
  : e.type === "image" ? e.name || (e.src ? "Image" : "None chosen")
  : e.type === "barcode" && (e.symbology || "code128") !== "code128" ? `${barcodeKind(e).name} · ${e.data}` : e.data;

// Selection: S.pick is the set of selected indexes; S.sel is the one shown in
// the properties panel when exactly one is selected (otherwise -1)
const picked = () => [...S.pick].sort((a, b) => a - b);
const pickedEls = () => picked().map((i) => S.layout.elements[i]);

function setPick(set) {
  S.pick = set;
  S.sel = set.size === 1 ? [...set][0] : -1;
  drawList(); drawOverlay(); drawProps();
}

// add=true toggles i in the selection; otherwise i becomes the only one (-1 = none)
function select(i, add = false) {
  const set = add ? new Set(S.pick) : new Set();
  if (i >= 0) add && set.has(i) ? set.delete(i) : set.add(i);
  setPick(set);
}

function removeEls(idx) {
  S.layout.elements = elementOps.removeEls(S.layout.elements, idx);
  setPick(new Set()); schedule();
}

function moveEl(i, d) {
  const j = elementOps.moveEl(S.layout.elements, i, d);
  if (j < 0) return;
  select(j); schedule();
}

function drawList() {
  const els = S.layout.elements;
  // Listed top-most first: later elements are drawn on top
  const items = els.map((e, i) => i).reverse().map((i) => {
    const e = els[i];
    return h("li", { class: S.pick.has(i) ? "sel" : "", onclick: (ev) => select(i, additive(ev)) },
      h("span", { class: "swatch" + (e.color === "red" ? " red" : "") }),
      h("span", { class: "kind" }, KIND[e.type]),
      h("span", { class: "txt", title: summary(e) }, summary(e)),
      h("span", { class: "acts" },
        h("button", { class: "icon", title: "Bring forward", onclick: (ev) => { ev.stopPropagation(); moveEl(i, 1); } }, "↑"),
        h("button", { class: "icon", title: "Send backward", onclick: (ev) => { ev.stopPropagation(); moveEl(i, -1); } }, "↓"),
        h("button", { class: "icon", title: "Duplicate", onclick: (ev) => { ev.stopPropagation(); dupEls([i]); } }, "⧉"),
        h("button", { class: "icon", title: "Delete", onclick: (ev) => { ev.stopPropagation(); removeEls([i]); } }, "×")));
  });
  $("#elList").replaceChildren(...(items.length ? items : [h("li", { class: "empty" }, "No elements — add one or pick a quick layout")]));
}

// Each copy is stacked just above its original, 2 mm right and down; the copies end up selected
function dupEls(idx) {
  setPick(elementOps.duplicateEls(S.layout.elements, idx)); schedule();
}

// Form helpers bound to the selected element
function bind(key, input, conv = (v) => v) {
  const e = S.layout.elements[S.sel];
  input.value = e[key] ?? "";
  input.dataset.key = key;
  input.addEventListener("input", () => { e[key] = conv(input.value); drawList(); drawOverlay(); schedule(); });
  return input;
}
// Lengths: shown and typed in the display unit, stored in mm. min and step
// are given in mm; in inches the step is 0.02 in (0.01 in for fine ones).
const num = (key, { min, step = 0.5 } = {}) => {
  const e = S.layout.elements[S.sel];
  const input = bind(key, h("input", { type: "number",
    step: imperial() ? (step < 0.5 ? 0.01 : 0.02) : step,
    min: min == null ? null : imperial() ? Math.max(min && 0.01, toUnit(min)) : min }), (v) => fromUnit(+v || 0));
  input.value = toUnit(e[key] ?? 0);
  // The browser doesn't hold typing to `min`. Once typing is done, a value
  // below it (a width cleared, or set to 0) goes back up to it: an element
  // with no width can't be picked up on the label.
  if (min != null) input.addEventListener("change", () => {
    if (e[key] >= min) return;
    e[key] = min; input.value = toUnit(min);
    drawList(); drawOverlay(); schedule();
  });
  return input;
};
const fld = (label, ...kids) => h("label", { class: "field" }, label, ...kids);
const seg = (key, opts) => {
  const e = S.layout.elements[S.sel];
  const wrap = h("div", { class: "seg" });
  const draw = () => wrap.replaceChildren(...opts.map(([v, txt, extra = {}]) =>
    h("button", { type: "button", class: (e[key] === v ? "on " : "") + (extra.cls || ""), disabled: extra.disabled,
      title: extra.title, onclick: () => { e[key] = v; draw(); drawList(); schedule(); } }, txt)));
  draw();
  return wrap;
};
const chk = (key, label) => {
  const e = S.layout.elements[S.sel];
  const i = h("input", { type: "checkbox" });
  i.checked = !!e[key];
  i.addEventListener("change", () => { e[key] = i.checked; schedule(); });
  return h("label", { class: "check" }, i, label);
};

// While a text field has focus, its element is marked on the label
function editing(input) {
  const i = S.sel;
  input.addEventListener("focus", () => { S.editing = i; drawOverlay(); });
  input.addEventListener("blur", () => { if (S.editing === i) S.editing = -1; drawOverlay(); });
  return input;
}

const colourOpts = (redOK) => [
  ["black", "Black"],
  ["red", "Red", { cls: "red", disabled: !redOK, title: redOK ? "" : "Needs black/red tape (DK-2251)" }]];

// Several elements selected: align, distribute, colour, duplicate, delete
function drawMultiProps(box) {
  const idx = picked(), els = idx.map((i) => S.layout.elements[i]);
  const to = h("div", { class: "seg" });
  const drawTo = () => to.replaceChildren(...[["selection", "Selection"], ["label", "Label"]].map(([v, t]) =>
    h("button", { type: "button", class: S.alignTo === v ? "on" : "", onclick: () => { S.alignTo = v; drawTo(); } }, t)));
  drawTo();
  const colour = h("div", { class: "seg" });
  const drawColour = () => colour.replaceChildren(...colourOpts(tape().red).map(([v, t, x = {}]) =>
    h("button", { type: "button", class: (els.every((e) => e.color === v) ? "on " : "") + (x.cls || ""), disabled: x.disabled, title: x.title,
      onclick: () => { els.forEach((e) => { e.color = v; }); drawColour(); drawList(); schedule(); } }, t)));
  drawColour();
  const n3 = idx.length >= 3 ? {} : { disabled: true, title: "Select three or more" };
  box.replaceChildren(
    h("h2", {}, `${idx.length} elements`),
    h("div", { class: "field" }, "Align to", to),
    h("div", { class: "field" }, "Align", alignRow()),
    h("div", { class: "field" }, "Distribute", h("div", { class: "align" },
      h("button", { type: "button", class: "icon", title: n3.title || "Distribute horizontally", disabled: n3.disabled, onclick: () => distribute(false) }, distIcon(false)),
      h("button", { type: "button", class: "icon", title: n3.title || "Distribute vertically", disabled: n3.disabled, onclick: () => distribute(true) }, distIcon(true)))),
    h("div", { class: "field" }, "Colour", colour),
    h("div", { class: "row2" },
      h("button", { type: "button", onclick: () => dupEls(idx) }, "Duplicate"),
      h("button", { type: "button", onclick: () => removeEls(idx) }, "Delete")));
}

// light=true only refreshes geometry numbers (used while dragging)
function drawProps(light = false) {
  const box = $("#props");
  if (!light) S.editing = -1;   // a rebuilt panel has no focused field
  if (S.pick.size > 1) { if (!light) drawMultiProps(box); return; }
  const e = S.layout.elements[S.sel];
  if (!e) { box.replaceChildren(); return; }
  if (light) {
    for (const k of ["x", "y", "w", "h"]) {
      const inp = box.querySelector(`[data-key="${k}"]`);
      if (inp && document.activeElement !== inp) inp.value = toUnit(e[k]);
    }
    return;
  }
  const redOK = tape().red;
  const kids = [h("h2", {}, KIND[e.type])];

  if (e.type === "text") {
    kids.push(fld("Text", editing(bind("text", h("textarea", { rows: 3, spellcheck: false })))));
  } else if (e.type === "qr") {
    kids.push(fld("Data", editing(bind("data", h("input", { type: "text", spellcheck: false })))));
  } else if (e.type === "barcode") {
    const hint = h("div", { class: "sub under" }, barcodeKind(e).hint);
    const type = h("select", {}, ...S.meta.barcodes.map((k) => h("option", { value: k.id }, k.name)));
    type.value = barcodeKind(e).id;
    type.addEventListener("change", () => { e.symbology = type.value; hint.textContent = barcodeKind(e).hint; drawList(); schedule(); });
    kids.push(fld("Type", type));
    kids.push(fld("Data", editing(bind("data", h("input", { type: "text", spellcheck: false })))), hint);
  } else if (e.type === "image") {
    kids.push(imagePicker(e));
  }

  kids.push(h("div", { class: "row4 num4" },
    fld("X", num("x")), fld("Y", num("y")), fld("W", num("w", { min: 0.5 })), fld("H", num("h", { min: 0.5 }))));
  kids.push(h("div", { class: "field" }, "Align to label", alignRow()));
  kids.push(h("div", { class: "field" }, "Colour", seg("color", colourOpts(redOK))));

  if (e.type === "text") {
    const font = h("select", {}, ...S.meta.fonts.map((f) => h("option", { value: f }, { sans: "Sans", narrow: "Narrow", serif: "Serif", mono: "Mono" }[f] || f)));
    const size = bind("size", h("input", { type: "number", min: 0, step: 1, placeholder: "auto" }), (v) => +v || 0);
    // Max size only limits shrink-to-fit, so it's off while a size is set
    const max = bind("max_size", h("input", { type: "number", min: 0, step: 1, placeholder: "none" }), (v) => +v || 0);
    const maxOff = () => { max.disabled = e.size > 0; };
    size.addEventListener("input", maxOff);
    maxOff();
    const spacing = bind("spacing", h("input", { type: "number", min: 0.5, max: 3, step: 0.1, placeholder: "1" }),
      (v) => Math.min(3, Math.max(0.5, +v || 1)));
    kids.push(h("div", { class: "row2" }, fld("Font", bind("font", font)), fld("Size (pt)", size)));
    kids.push(h("div", { class: "row2" }, fld("Max size (pt)", max), fld("Line spacing", spacing)));
    kids.push(h("div", { class: "sub under" }, "Size 0 = shrink to fit the box, up to Max size"));
    kids.push(h("div", { class: "field" }, "Align", seg("align", [["left", "Left"], ["center", "Centre"], ["right", "Right"]])));
    kids.push(h("div", { class: "field" }, "Vertical", seg("valign", [["top", "Top"], ["middle", "Middle"], ["bottom", "Bottom"]])));
    kids.push(h("div", { class: "checks" }, chk("bold", "Bold"), chk("wrap", "Wrap"), chk("invert", "Inverted")));
    kids.push(h("div", { class: "row2" }, fld(`Padding (${units()})`, num("padding_mm", { min: 0 }))));
  } else if (e.type === "qr") {
    const ec = h("select", {}, ...[["L", "L — 7%"], ["M", "M — 15%"], ["Q", "Q — 25%"], ["H", "H — 30%"]].map(([v, t]) => h("option", { value: v }, t)));
    kids.push(fld("Error correction", bind("ec", ec)));
  } else if (e.type === "barcode") {
    kids.push(h("div", { class: "checks" }, chk("show_text", "Show text")));
  } else if (e.type === "image") {
    // The printer has no grey: the image prints as black and white dots in one colour
    const level = bind("threshold", h("input", { type: "range", min: 5, max: 95, step: 1 }), (v) => +v);
    const shown = h("span", {});
    const showLevel = () => { shown.textContent = `${e.threshold ?? 50}%`; level.disabled = e.mode === "dither"; };
    level.addEventListener("input", showLevel);
    const mode = seg("mode", [["threshold", "Threshold"], ["dither", "Dither"]]);
    mode.addEventListener("click", showLevel);
    showLevel();
    kids.push(h("div", { class: "field" }, "Black and white", mode));
    kids.push(h("label", { class: "field" }, h("span", { class: "range-label" }, "Threshold", shown), level));
    kids.push(h("div", { class: "sub under" }, "Threshold suits logos and line art; dither suits shading and photos."));
    kids.push(h("div", { class: "checks" }, chk("invert", "Inverted")));
  } else if (e.type === "rect") {
    kids.push(h("div", { class: "checks" }, chk("fill", "Filled")));
    kids.push(h("div", { class: "row2" }, fld(`Outline (${units()})`, num("stroke_mm", { min: 0.1, step: 0.1 }))));
  }
  box.replaceChildren(...kids);
}

// The chosen image (shown in grey, as it prints for now), and a button to choose another
function imagePicker(e) {
  // A file, or one fetched from an address, shrunk to fit and stored in the
  // layout. It goes to this element itself, not to whatever now sits at its
  // place in the list: a fetch can take ten seconds, and by then another
  // element may be selected, or this one deleted or undone, in which case
  // the image is dropped.
  const use = async (file, more) => {
    const src = await readImage(file);
    if (!S.layout.elements.includes(e)) return;
    Object.assign(e, { src, name: file.name, url: "", ...more });
    S.glyph = imageOf(e);
    drawList(); schedule();
    if (S.layout.elements[S.sel] === e) drawProps();   // only its own panel is rebuilt
  };
  const input = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp,image/gif,image/svg+xml" });
  input.addEventListener("change", async () => {
    if (!input.files[0]) return;
    try { await use(input.files[0]); } catch (err) { status(err.message, "err", "#imgStatus"); }
  });
  // From a web address: the server fetches it once (browsers block most sites),
  // and it's saved with the template like a chosen file
  const addr = h("input", { type: "url", placeholder: "or an address: https://…", value: e.url || "", spellcheck: false,
    maxlength: 2048, "aria-label": "Image address" });
  const get = h("button", { type: "button" }, "Get");
  const fetchIt = async () => {
    const url = addr.value.trim();
    if (!/^https?:\/\//i.test(url)) { status("Enter an address starting with http:// or https://", "err", "#imgStatus"); return; }
    get.disabled = true;
    status("Getting the image…", "", "#imgStatus");
    try {
      const j = await api("/api/image-url", { method: "POST", body: { url } });
      const blob = await (await fetch(j.data)).blob();
      await use(new File([blob], j.name, { type: blob.type }), { url: j.url });
    } catch (err) { status(err.message, "err", "#imgStatus"); get.disabled = false; }
  };
  get.addEventListener("click", fetchIt);
  addr.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); fetchIt(); } });
  return h("div", { class: "field" }, "Image",
    h("div", { class: "img-pick" },
      e.src ? h("img", { src: e.src, alt: "" }) : h("span", { class: "none" }, "None chosen"),
      h("div", {},
        h("label", { class: "file-btn" }, e.src ? "Replace…" : "Choose…", input),
        // What it adds to a template, and where it came from
        e.src && h("div", { class: "img-meta", title: e.url || e.name || null },
          `${e.name || "Image"} · ${Math.max(1, Math.round(e.src.length / 1024))} KB`))),
    h("div", { class: "inline img-url" }, addr, get),
    h("p", { class: "status img-status", id: "imgStatus", role: "status" }));
}

// An image file as a data URL that fits the server's budget (S.meta.image_budget,
// counted as stored in a template). PNG at up to IMAGE_MAX px on the long side
// first, which keeps logos lossless; then WebP, which suits photos; then the
// same at smaller sizes, down to IMAGE_MIN (images.mjs lists the sizes). SVGs
// are drawn here, scaled up to IMAGE_MAX, since the server can't read them.
async function readImage(file) {
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    try { await img.decode(); } catch { throw new Error("This browser can't read that file as an image"); }
    const svg = file.type === "image/svg+xml";
    const w0 = img.naturalWidth || IMAGE_MAX, h0 = img.naturalHeight || IMAGE_MAX;   // an SVG may have no size
    const budget = S.meta.image_budget;
    const { sides, least } = sidesToTry(w0, h0, svg);
    for (const side of sides) {
      const cv = h("canvas", sizeAt(w0, h0, side));
      cv.getContext("2d").drawImage(img, 0, 0, cv.width, cv.height);
      const png = cv.toDataURL("image/png");
      if (png.length <= budget) return png;
      const webp = cv.toDataURL("image/webp", 0.9);   // a browser without WebP gives PNG again
      if (webp.startsWith("data:image/webp") && webp.length <= budget) return webp;
    }
    throw new Error(`That image doesn't fit in ${Math.round(budget / 1024)} KB even at ${least} px; try a simpler one`);
  } finally { URL.revokeObjectURL(url); }
}

document.querySelectorAll("[data-add]").forEach((b) => b.addEventListener("click", () => {
  S.layout.elements.push(newElement(b.dataset.add, canvasMM()));
  select(S.layout.elements.length - 1);
  schedule();
}));

// ---------------------------------------------------------------------------
// Label setup
// ---------------------------------------------------------------------------

function drawTapes() {
  $("#tape").replaceChildren(...S.meta.tapes.map((t) => h("option", { value: t.id }, tapeName(t))));
}

function drawSetup() {
  const t = tape(), len = $("#length"), [min, max] = S.meta.limits.length_mm;
  $("#tape").value = t.id;
  $("#lengthUnit").textContent = units();
  Object.assign(len, { step: imperial() ? 0.1 : 1, min: toUnit(min), max: toUnit(max) });
  len.value = toUnit(S.layout.length_mm);
  $("#lengthRow").querySelector("label").hidden = !t.endless;
  $("#printable").textContent = t.endless ? `${fmt(t.printable_mm[0])} wide` : fmt2(...t.printable_mm);
  $("#orientation").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.v === S.layout.orientation));
  $("#units").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.v === units()));
}

// Redraw every panel and the label, after the layout is replaced, reshaped or
// shown in other units
function drawAll() {
  drawSetup(); drawPresets(); drawList(); drawProps(); drawData(); fit();
}

// Apply a label-shape change, scaling elements proportionally so the layout
// still fits the new canvas (QR codes stay square).
function reshape(change) {
  const a = canvasMM();
  change();
  const b = canvasMM();
  geo.rescale(S.layout.elements, b.w / a.w, b.h / a.h);
  drawAll(); schedule();
}

$("#tape").addEventListener("change", (ev) => reshape(() => { S.layout.tape = ev.target.value; }));
// "change" (not "input") so typing 50 doesn't pass through a 5 mm label
$("#length").addEventListener("change", (ev) => reshape(() => {
  const [min, max] = S.meta.limits.length_mm;
  S.layout.length_mm = Math.max(min, Math.min(max, fromUnit(+ev.target.value) || min));
}));
// Units change only what's shown, so there's no undo step
$("#units").addEventListener("click", (ev) => {
  const v = ev.target.dataset.v;
  if (!v || v === units()) return;
  setUnits(v);
  try { localStorage.setItem(UNITS, v); } catch {}
  drawTapes(); drawAll();
});
$("#orientation").addEventListener("click", (ev) => {
  const v = ev.target.dataset.v;
  if (v && v !== S.layout.orientation) reshape(() => { S.layout.orientation = v; });
});

// One collapsible section per category. Open sections are remembered in this
// browser; only Basic is open the first time.
const PRESETS_OPEN = "oh-brother:presets-open";
const openCats = () => {
  try { const j = JSON.parse(localStorage.getItem(PRESETS_OPEN) || "null"); if (Array.isArray(j)) return new Set(j); } catch {}
  return new Set(["basic"]);
};

function drawPresets() {
  const c = canvasMM(), red = tape().red, open = openCats();
  $("#presets").replaceChildren(...CATS.map(([id, label]) => {
    const list = PRESETS.filter((p) => p.cat === id);
    let fit = 0;
    const btns = list.map((p) => {
      const why = p.fits ? p.fits(c.w, c.h, red) : checkEls(p.make(c.w, c.h));
      if (!why) fit++;
      return h("button", { type: "button", class: "preset", disabled: !!why, title: why || null, onclick: () => {
        let els = roundAll(p.make(c.w, c.h));
        if (!red) els = els.map((e) => ({ ...e, color: "black" }));
        // The last image chosen fills the new layout's empty image slot, as typed
        // values carry over, even after a layout without one
        const had = S.layout.elements.find((e) => e.type === "image" && e.src);
        if (had) S.glyph = imageOf(had);
        if (S.glyph) for (const e of els) if (e.type === "image" && !e.src) Object.assign(e, S.glyph);
        S.layout.elements = els;
        select(-1); schedule(); checkpoint();
      } }, presetThumb(p, c.w, c.h), h("span", {}, p.name));
    });
    const d = h("details", { class: "preset-cat", open: open.has(id) || null },
      h("summary", {}, h("span", {}, label), h("span", { class: "count" }, `${fit}/${list.length}`)),
      h("div", { class: "presets" }, ...btns));
    d.addEventListener("toggle", () => {
      const now = openCats();
      d.open ? now.add(id) : now.delete(id);
      try { localStorage.setItem(PRESETS_OPEN, JSON.stringify([...now])); } catch {}
    });
    return d;
  }));
}

// ---------------------------------------------------------------------------
// Templates
// ---------------------------------------------------------------------------

async function drawTemplates() {
  const { templates, samples = [] } = await api("/api/templates");
  const own = templates.map((n) => h("li", { class: "own" },
    h("button", { class: "name", onclick: () => loadTemplate(n) }, n),
    h("button", { class: "icon", title: "Delete template", onclick: async () => {
      if (!confirm(`Delete template “${n}”?`)) return;
      try {
        await api(`/api/templates/${encodeURIComponent(n)}`, { method: "DELETE" });
        status("", "", "#tplStatus");
      } catch (e) { status(e.message, "err", "#tplStatus"); }
      drawTemplates();
    } }, "×")));
  // Samples ship with the app, after your own. They open like templates but
  // can't be saved over or deleted.
  const shipped = samples.map((n) => h("li", { class: "sample" },
    h("button", { class: "name", title: "Sample template. Save it under a name of your own to keep your changes.",
      onclick: () => loadTemplate(n, true) }, h("span", { class: "prefix" }, "Sample: "), n)));
  const items = [...own, ...shipped];
  $("#tplList").replaceChildren(...(items.length ? items : [h("li", { class: "empty" }, "None saved yet")]));
}

async function loadTemplate(n, sample = false) {
  let j;
  try {
    j = await api(`/api/${sample ? "samples" : "templates"}/${encodeURIComponent(n)}`);
  } catch (e) { status(e.message, "err", "#tplStatus"); return; }
  const layout = elementOps.tidyLayout(j.layout, S.meta.limits.length_mm);
  if (!layout) { status(`“${n}” has no layout, so it can't be opened`, "err", "#tplStatus"); return; }
  status("", "", "#tplStatus");
  S.layout = layout; S.fixed = lowerKeys(j.fixed);
  if (j.mapping) S.mapping = { ...S.mapping, ...lowerKeys(j.mapping) };
  $("#tplName").value = sample ? "" : n;   // so Save asks for a name, and can't overwrite one of yours
  S.sel = -1; S.pick = new Set();
  drawAll(); schedule();
}

// Saving over a template asks first. The server refuses (409) unless the
// request says to replace, so a template saved in another window counts too.
// Names the server can't use as file names come back with the reason.
$("#tplSave").addEventListener("click", async () => {
  const n = $("#tplName").value.trim();
  if (!n) { $("#tplName").focus(); return; }
  const put = (replace) => api(`/api/templates/${encodeURIComponent(n)}${replace ? "?replace=1" : ""}`,
    { method: "PUT", body: { layout: S.layout, fixed: S.fixed, mapping: S.mapping } });
  try {
    try {
      await put(false);
    } catch (e) {
      if (e.status !== 409) throw e;
      if (!confirm(`Replace your template “${n}”?`)) return;
      await put(true);
    }
    status(`Saved “${n}”`, "ok", "#tplStatus");
    drawTemplates();
  } catch (e) { status(e.message, "err", "#tplStatus"); }
});
$("#tplName").addEventListener("input", () => status("", "", "#tplStatus"));

// ---------------------------------------------------------------------------
// Data: fields table, data rows
// ---------------------------------------------------------------------------

function drawData() {
  const ph = fields();
  const rows = ph.map((p) => {
    const fixedIn = h("input", { type: "text", placeholder: "text or {{field}}", value: S.fixed[fkey(p)] ?? "",
      title: "Fixed text. May include other fields, such as {{item}}" });
    fixedIn.addEventListener("input", () => { S.fixed[fkey(p)] = fixedIn.value; schedule(); });
    // A newly referenced field gets its own row once typing is done
    fixedIn.addEventListener("change", () => { if (fields().join("\u0000") !== ph.join("\u0000")) { autoMap(); drawData(); } });
    let src = null;
    if (S.data) {
      src = h("select", {}, h("option", { value: "" }, "— fixed text —"),
        ...S.data.headers.map((c) => h("option", { value: c }, c)));
      src.value = S.mapping[fkey(p)] ?? "";
      fixedIn.hidden = !!src.value;
      src.addEventListener("change", () => {
        S.mapping[fkey(p)] = src.value; fixedIn.hidden = !!src.value; schedule();
        if (fields().join("\u0000") !== ph.join("\u0000")) drawData();
      });
    }
    return h("tr", {}, h("td", {}, `{{${p}}}`), src && h("td", {}, src), h("td", {}, fixedIn));
  });
  $("#fields").replaceChildren(...(rows.length ? rows : [h("tr", { class: "none" }, h("td", {}, "No fields in this layout"))]));

  $("#rowsWrap").hidden = !S.data;
  $("#dataClear").hidden = !S.data;
  // The hint, with the built-in fields as the server lists them
  if (!S.data) $("#dataInfo").replaceChildren("Type ", h("code", {}, "{{name}}"),
    " in any text, QR or barcode to create a field. Built-in:",
    ...S.meta.builtin_fields.flatMap((f) => [" ", h("code", {}, `{{${f}}}`)]));
  drawPicked();
}

// The rows table is built only when data is loaded: rebuilding it takes about
// a second per 5,000 rows. Clicks and ticks update it in place.

function drawRows() {
  if (!S.data) { $("#rows").replaceChildren(); return; }
  const { headers, rows } = S.data;
  const all = h("input", { type: "checkbox", title: "Select all", class: "all" });
  all.addEventListener("change", () => {
    S.picked = all.checked ? new Set(rows.map((_, i) => i)) : new Set();
    for (const cb of $("#rows tbody").querySelectorAll("input")) cb.checked = all.checked;
    drawPicked();
  });
  const thead = h("thead", {}, h("tr", {}, h("th", {}, all), h("th", {}, "#"), ...headers.map((c) => h("th", {}, c))));
  const tbody = h("tbody", {}, ...rows.map((r, i) => {
    const cb = h("input", { type: "checkbox" });
    cb.checked = S.picked.has(i);
    cb.addEventListener("click", (ev) => ev.stopPropagation());   // ticking doesn't preview the row
    cb.addEventListener("change", () => { cb.checked ? S.picked.add(i) : S.picked.delete(i); drawPicked(); });
    return h("tr", { class: i === S.cur ? "cur" : "", onclick: () => showRow(i) },
      h("td", {}, cb), h("td", { class: "n" }, i + 1), ...headers.map((c) => h("td", { title: r[c] }, r[c])));
  }));
  $("#rows").replaceChildren(thead, tbody);
  drawPicked();
}

function showRow(i) {
  const body = $("#rows tbody");
  body.children[S.cur]?.classList.remove("cur");
  body.children[i].classList.add("cur");
  S.cur = i;
  schedule();
}

// The selection count, the Select all box, and the print button
function drawPicked() {
  if (S.data) {
    const n = S.data.rows.length, all = $("#rows .all");
    $("#dataInfo").textContent = `${n} rows · ${S.picked.size} selected · click a row to preview it`;
    if (all) { all.checked = S.picked.size === n; all.indeterminate = S.picked.size > 0 && S.picked.size < n; }
  }
  drawPrintButton();
}

$("#dataFile").addEventListener("change", async (ev) => {
  const f = ev.target.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  status("", "", "#dataStatus");
  try {
    S.data = await api("/api/data", { method: "POST", body: fd });
    S.picked = new Set(S.data.rows.map((_, i) => i));
    S.cur = 0;
    autoMap(); drawRows(); drawData(); schedule();
  } catch (e) { status(e.message, "err", "#dataStatus"); }   // data already loaded stays
  ev.target.value = "";
});

$("#dataClear").addEventListener("click", () => {
  S.data = null; S.picked = new Set();
  status("", "", "#dataStatus");
  drawRows(); drawData(); schedule();
});

// ---------------------------------------------------------------------------
// Printing
// ---------------------------------------------------------------------------

// What a click on Print will send (job.mjs): the ticked data rows, the copies
// as the server will take them, and the number of labels that makes
const jobRows = () => job.jobRows(S.data, S.picked);
const copies = () => job.copiesOf($("#copies").value, S.meta.limits.copies);
const labelCount = () => job.labelCount(S.data, S.picked, copies());

function drawPrintButton() {
  const n = labelCount(), b = $("#printBtn");
  b.textContent = n === 1 ? "Print 1 label" : `Print ${n} labels`;
  b.disabled = n === 0;
}
$("#copies").addEventListener("input", drawPrintButton);
// Once typing is done, the box shows the number that will be used
$("#copies").addEventListener("change", (ev) => { ev.target.value = copies(); });

// A status line: the print bar's, or the templates' (#tplStatus) or Data panel's (#dataStatus)
function status(msg, cls = "", where = "#printStatus") {
  const s = $(where);
  if (!s) return;   // an image's line (#imgStatus) is gone once another element is selected
  s.textContent = msg;
  s.classList.remove("ok", "err");
  if (cls) s.classList.add(cls);
}

$("#printBtn").addEventListener("click", async () => {
  if (!S.meta.config.printer_host) { openSettings(); return; }
  const n = labelCount();
  if (n > job.CONFIRM_ABOVE && !confirm(`Print ${n} labels?`)) return;   // loading data ticks every row
  const b = $("#printBtn");
  b.disabled = true;
  status("Sending…");
  try {
    // rows: each record's row number as the Data table shows it, so the
    // server can name the row a label failed on
    const rows = jobRows();
    const j = await api("/api/print", { method: "POST", body: {
      layout: S.layout, records: rows ? rows.map((i) => record(S.data.rows[i])) : [record(null)],
      rows: rows?.map((i) => i + 1), chain: chain(), copies: copies(), cut: $("#cut").checked } });
    status(`Sent ${j.labels} label${j.labels === 1 ? "" : "s"}` + (j.warnings.length ? ` · ${j.warnings.length} warning(s)` : ""), "ok");
    if (j.warnings.length) drawWarnings(j.warnings);
  } catch (e) {
    status(e.message, "err");
  } finally {
    drawPrintButton();
  }
});

// ---------------------------------------------------------------------------
// Printer settings
// ---------------------------------------------------------------------------

function drawPrinterChip(ok) {
  const c = S.meta.config;
  $("#printerLabel").textContent = c.printer_host ? `${c.model} · ${c.printer_host}` : "No printer set";
  $("#printerDot").className = "dot" + (ok === true ? " ok" : ok === false ? " bad" : "");
}

function openSettings() {
  const c = S.meta.config;
  $("#cfgHost").value = c.printer_host;
  $("#cfgPort").value = c.printer_port;
  $("#cfgModel").replaceChildren(...S.meta.models.map((m) => h("option", { value: m }, m)));
  $("#cfgModel").value = c.model;
  $("#cfgStatus").textContent = "";
  $("#settings").showModal();
}

async function saveSettings() {
  const j = await api("/api/config", { method: "POST", body: {
    printer_host: $("#cfgHost").value.trim(), printer_port: +$("#cfgPort").value || 9100, model: $("#cfgModel").value } });
  S.meta.config = j.config;
  drawPrinterChip();
}

async function testPrinter(target) {
  const j = await api("/api/test", { method: "POST", body: {} });   // the server takes only JSON
  drawPrinterChip(j.ok);
  if (target) { target.textContent = j.message; target.className = "status " + (j.ok ? "ok" : "err"); }
  return j.ok;
}

// A setting the server refuses (a port out of range, say) is shown in the
// dialog, which stays open
const cfgError = (e) => { $("#cfgStatus").textContent = e.message; $("#cfgStatus").className = "status err"; };

$("#printerChip").addEventListener("click", openSettings);
$("#cfgSave").addEventListener("click", async () => {
  try { await saveSettings(); } catch (e) { cfgError(e); return; }
  $("#settings").close(); testPrinter();
});
$("#cfgTest").addEventListener("click", async () => {
  $("#cfgStatus").textContent = "Testing…"; $("#cfgStatus").className = "status";
  try { await saveSettings(); await testPrinter($("#cfgStatus")); } catch (e) { cfgError(e); }
});

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

// Module code isn't reachable from the browser's console, so the few things
// worth reaching are put here: the state, to look at, and the printer chip,
// which the README's screenshots set to "connected" (docs/development.md)
window.ohBrother = { state: S, drawPrinterChip };

(async function boot() {
  // Held open while this page is: the launcher stops the app once the last
  // page closes. EventSource reconnects by itself after a drop.
  new EventSource("/api/alive");
  S.meta = await api("/api/meta");
  $("#copies").max = S.meta.limits.copies;
  drawTapes();
  if (!restore() || !S.meta.tapes.some((t) => t.id === S.layout.tape)) {
    // First run: the Red header quick layout on the first tape listed
    S.layout = { tape: S.meta.tapes[0].id, length_mm: 30, orientation: "portrait", elements: [] };
    const c = canvasMM();
    S.layout.elements = roundAll(PRESETS.find((p) => p.name === "Red header").make(c.w, c.h));
  }
  drawAll(); drawPrinterChip(); drawTemplates(); schedule();
  checkpoint();
  if (S.meta.config.printer_host) testPrinter();
  new ResizeObserver(fit).observe($("#stage"));
})();
