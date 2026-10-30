// Oh-Brother frontend. Plain JS, no build step.
// The server renders every preview; this file only edits the layout (all
// geometry in mm), draws selection boxes over the preview, and manages data.

"use strict";

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
  if (!r.ok) throw new Error(j.error || `${r.status} ${r.statusText}`);
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
  fixed: {},            // placeholder -> fixed text
  csv: null,            // {headers, rows}
  mapping: {},          // placeholder -> column name ("" = fixed text)
  picked: new Set(),    // selected CSV row indexes
  cur: 0,               // CSV row shown in preview
  placeholders: [],
  scale: 1,             // screen px per dot
};

const STORE = "oh-brother:v1";
const save = () => { clearTimeout(saveTimer); try { localStorage.setItem(STORE, JSON.stringify({ layout: S.layout, fixed: S.fixed })); } catch {} };
// Coalesce saves: dragging changes the layout every frame
let saveTimer = 0;
const saveSoon = () => { clearTimeout(saveTimer); saveTimer = setTimeout(save, 400); };
addEventListener("pagehide", save);
const restore = () => {
  try {
    const j = JSON.parse(localStorage.getItem(STORE) || "null");
    if (j?.layout) { S.layout = j.layout; S.fixed = j.fixed || {}; return true; }
  } catch {}
  return false;
};

// ---------------------------------------------------------------------------
// Undo history: snapshots of the layout and fixed values. Every edit calls
// schedule(), which takes a snapshot once edits pause; drags and discrete
// actions take one straight away. Typing inside a field keeps the browser's
// own undo for that field.
// ---------------------------------------------------------------------------

const HISTORY_MAX = 100;
let hist = [], histPos = -1, histTimer = 0, dragging = false;
const snapshot = () => JSON.stringify({ layout: S.layout, fixed: S.fixed });

function checkpoint() {
  clearTimeout(histTimer);
  const j = snapshot();
  if (j === hist[histPos]) return;
  hist = hist.slice(0, histPos + 1);
  hist.push(j);
  if (hist.length > HISTORY_MAX) hist.shift();
  histPos = hist.length - 1;
  drawUndo();
}
const checkpointSoon = () => { clearTimeout(histTimer); if (!dragging) histTimer = setTimeout(checkpoint, 500); };

function stepHistory(d) {
  checkpoint();   // keep any edit not yet recorded
  const to = histPos + d;
  if (to < 0 || to >= hist.length) return;
  histPos = to;
  const j = JSON.parse(hist[histPos]);
  S.layout = j.layout; S.fixed = j.fixed;
  const n = S.layout.elements.length;
  S.pick = new Set([...S.pick].filter((i) => i < n));
  S.sel = S.pick.size === 1 ? [...S.pick][0] : -1;
  drawSetup(); drawPresets(); drawList(); drawProps(); drawData(); fit(); schedule();
  drawUndo();
}
const undo = () => stepHistory(-1), redo = () => stepHistory(1);

function drawUndo() {
  $("#undoBtn").disabled = histPos <= 0;
  $("#redoBtn").disabled = histPos >= hist.length - 1;
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

// Canvas size in mm as designed (mirrors render.canvas_dots on the server)
function canvasMM() {
  const t = tape();
  let w = t.dots[0] / dpmm();
  let hh = t.endless ? +S.layout.length_mm : t.dots[1] / dpmm();
  if (S.layout.orientation === "landscape") [w, hh] = [hh, w];
  return { w, h: hh };
}

// Cut label around the printable canvas, in mm and canvas orientation:
// side margins from the tape width, end margins from the feed (continuous)
// or the die-cut label length.
function paperMM() {
  const t = tape(), c = canvasMM();
  const across = Math.max(0, (t.tape_mm[0] - t.dots[0] / dpmm()) / 2);
  const along = t.endless ? t.feed_mm : Math.max(0, (t.tape_mm[1] - t.dots[1] / dpmm()) / 2);
  const [mx, my] = S.layout.orientation === "landscape" ? [along, across] : [across, along];
  return { mx, my, w: c.w + 2 * mx, h: c.h + 2 * my };
}

const r1 = (v) => Math.round(v * 10) / 10;
const r2 = (v) => Math.round(v * 100) / 100;   // snapped positions (centres) need 0.01 mm
const snap = (v) => Math.round(v * 2) / 2;   // 0.5 mm grid

// ---------------------------------------------------------------------------
// Element defaults & presets
// ---------------------------------------------------------------------------

function newElement(type) {
  const c = canvasMM();
  const base = { type, color: "black", x: 2, y: 2 };
  switch (type) {
    case "text": return { ...base, w: r1(c.w - 4), h: r1(Math.min(12, c.h - 4)), text: "Text", font: "sans", bold: false, size: 0, align: "left", valign: "middle", wrap: true, invert: false, padding_mm: 0 };
    case "qr": { const s = r1(Math.min(c.w, c.h) - 4); return { ...base, w: s, h: s, data: "{{Code}}", ec: "M" }; }
    case "barcode": return { ...base, w: r1(Math.min(c.w - 4, 50)), h: r1(Math.min(c.h - 4, 12)), data: "{{Code}}", show_text: true };
    case "rect": return { ...base, w: r1(c.w - 4), h: 1, fill: true, stroke_mm: 0.5 };
  }
}

const T = (o) => ({ type: "text", color: "black", font: "sans", bold: false, size: 0, align: "left", valign: "middle", wrap: true, invert: false, padding_mm: 0, ...o });

// Quick layouts. make(W, H) builds the elements for a printable area of W x H
// mm, picking an arrangement from its shape: "thin" labels (long strips, such
// as 12 mm tape run along) put parts side by side; "tall" ones stack them.
// fits(W, H) returns "" or the reason the layout can't work at that size.
// Field names are shared ({{Title}}, {{Body}}, {{Code}}) so values carry over
// when switching layouts.

// Margin scales with the short side: 2 mm on 62 mm tape, 0.5 mm on 12 mm
const marginFor = (W, H) => Math.max(0.5, Math.min(2, Math.round(Math.min(W, H) * 0.14) / 2));
const shapeOf = (W, H) => W / H >= 2.8 ? "thin" : H / W >= 1.4 ? "tall" : "normal";
const QR = (o) => ({ type: "qr", color: "black", data: "{{Code}}", ec: "M", ...o });
const BAR = (o) => ({ type: "barcode", color: "black", data: "{{Code}}", show_text: true, ...o });

const PRESETS = [
  { name: "Single line",
    fits: () => "",
    make: (W, H, m = marginFor(W, H)) => [
      T({ x: m, y: m, w: W - 2 * m, h: H - 2 * m, text: "{{Title}}", bold: true, align: "center", wrap: false })] },

  { name: "Title + body",
    fits: (W, H) => shapeOf(W, H) === "thin" ? (W < 30 ? "Needs a longer label" : "") : (H < 12 || W < 15 ? "Needs a larger label" : ""),
    make: (W, H, m = marginFor(W, H)) => {
      if (shapeOf(W, H) === "thin") {
        const tw = (W - 3 * m) * 0.4;
        return [
          T({ x: m, y: m, w: tw, h: H - 2 * m, text: "{{Title}}", bold: true }),
          T({ x: 2 * m + tw, y: m, w: W - 3 * m - tw, h: H - 2 * m, text: "{{Body}}" })];
      }
      return [
        T({ x: m, y: m, w: W - 2 * m, h: (H - 2 * m) * 0.4, text: "{{Title}}", bold: true }),
        T({ x: m, y: m + (H - 2 * m) * 0.45, w: W - 2 * m, h: (H - 2 * m) * 0.55, text: "{{Body}}", valign: "top" })];
    } },

  { name: "Red header",
    fits: (W, H) => shapeOf(W, H) === "thin" ? (W < 30 ? "Needs a longer label" : "") : (H < 12 || W < 15 ? "Needs a larger label" : ""),
    make: (W, H, m = marginFor(W, H)) => {
      const head = { text: "{{Title}}", bold: true, align: "center", invert: true, color: "red", padding_mm: Math.min(1, m), wrap: false };
      if (shapeOf(W, H) === "thin") {
        // Red block at the start of the strip
        const bw = W * 0.35;
        return [T({ ...head, x: 0, y: 0, w: bw, h: H }), T({ x: bw + m, y: m, w: W - bw - 2 * m, h: H - 2 * m, text: "{{Body}}" })];
      }
      const bh = Math.min(H * 0.32, W * 0.3);
      return [T({ ...head, x: 0, y: 0, w: W, h: bh }), T({ x: m, y: bh + m, w: W - 2 * m, h: H - bh - 2 * m, text: "{{Body}}" })];
    } },

  { name: "Text + QR",
    fits: (W, H) => {
      const m = marginFor(W, H);
      const s = shapeOf(W, H) === "tall" ? Math.min(W - 2 * m, H * 0.6) : Math.min(H - 2 * m, W * 0.45);
      return s < 7 ? "Too small for a scannable QR code" : "";
    },
    make: (W, H, m = marginFor(W, H)) => {
      if (shapeOf(W, H) === "tall") {
        // Text on top, QR code centred below
        const s = Math.min(W - 2 * m, H * 0.6);
        return [T({ x: m, y: m, w: W - 2 * m, h: H - s - 3 * m, text: "{{Title}}", bold: true, align: "center" }),
          QR({ x: (W - s) / 2, y: H - s - m, w: s, h: s })];
      }
      const s = Math.min(H - 2 * m, W * 0.45);
      return [T({ x: m, y: m, w: W - s - 3 * m, h: H - 2 * m, text: "{{Title}}", bold: true }),
        QR({ x: W - s - m, y: (H - s) / 2, w: s, h: s })];
    } },

  { name: "Barcode",
    fits: (W, H) => {
      const m = marginFor(W, H), thin = shapeOf(W, H) === "thin";
      const bw = thin ? (W - 3 * m) * 0.7 : W - 2 * m;
      return bw < 20 ? "Needs a wider label for a barcode" : (thin ? H : H * 0.6) < 7 ? "Needs a taller label for a barcode" : "";
    },
    make: (W, H, m = marginFor(W, H)) => {
      if (shapeOf(W, H) === "thin") {
        const tw = (W - 3 * m) * 0.3;
        return [T({ x: m, y: m, w: tw, h: H - 2 * m, text: "{{Title}}", bold: true }),
          BAR({ x: 2 * m + tw, y: m, w: W - 3 * m - tw, h: H - 2 * m })];
      }
      // Title above the barcode; on tall labels both keep sensible heights
      const ih = H - 2 * m;
      const th = Math.min(ih * 0.3, 12), bh = Math.min(ih - th - m, (W - 2 * m) * 0.5);
      const y0 = m + (ih - th - m - bh) / 2;
      return [T({ x: m, y: y0, w: W - 2 * m, h: th, text: "{{Title}}", bold: true, align: "center" }),
        BAR({ x: m, y: y0 + th + m, w: W - 2 * m, h: bh })];
    } },

  { name: "Address",
    fits: (W, H) => H < 14 || W < 25 ? "Needs a larger label" : "",
    make: (W, H, m = marginFor(W, H)) => [
      T({ x: m, y: m, w: W - 2 * m, h: H - 2 * m, text: "{{Name}}\n{{Street}}\n{{City}} {{Postcode}}\n{{Country}}", valign: "top", wrap: false })] },
];

// 0.01 mm, so full-width preset elements line up exactly with the label edges
function roundAll(els) {
  return els.map((e) => ({ ...e, x: r2(e.x), y: r2(e.y), w: r2(e.w), h: r2(e.h) }));
}

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
    } else if (e.type === "barcode") {
      for (let i = 0; i < 18; i++) add("rect", { x: e.x + (e.w / 18) * i, y: e.y, width: (e.w / 18) * (i % 3 ? 0.4 : 0.75), height: e.h * 0.8, fill: col });
    }
  }
  return svg;
}

// ---------------------------------------------------------------------------
// Data records
// ---------------------------------------------------------------------------

const TAG = /\{\{\s*([^{}]+?)\s*\}\}/g;
const BUILTIN = ["date", "time", "datetime"];

// A field takes fixed text unless a CSV is loaded and it's mapped to a column
const isFixed = (p) => !(S.csv && S.mapping[p]);

// The layout's fields, plus any field named inside a fixed value, so that
// {{SKU}} = "{{Item}}" gives Item a row even when the layout doesn't use it.
// CSV column names are left out: those come straight from the row.
function fields() {
  const out = [...S.placeholders];
  for (let i = 0; i < out.length; i++) {
    if (!isFixed(out[i])) continue;
    for (const m of (S.fixed[out[i]] || "").matchAll(TAG)) {
      if (!out.includes(m[1]) && !BUILTIN.includes(m[1]) && !S.csv?.headers.includes(m[1])) out.push(m[1]);
    }
  }
  return out;
}

// Fields whose fixed values may themselves contain {{tags}} (sent as "chain")
const chain = () => fields().filter(isFixed);

// Build the field->value record for one CSV row (or fixed values only). The
// row's own columns go in first, so a fixed value can refer to any column.
function record(row) {
  const rec = row ? { ...row } : {};
  for (const p of fields()) {
    rec[p] = isFixed(p) ? (S.fixed[p] ?? "") : (row?.[S.mapping[p]] ?? "");
  }
  return rec;
}

const previewRecord = () => record(S.csv ? S.csv.rows[S.cur] : null);

function autoMap() {
  if (!S.csv) return;
  for (const p of fields()) {
    if (S.mapping[p] !== undefined && (S.mapping[p] === "" || S.csv.headers.includes(S.mapping[p]))) continue;
    const hit = S.csv.headers.find((c) => c.toLowerCase() === p.toLowerCase());
    S.mapping[p] = hit || "";
  }
}

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
    const warnings = meta("X-Warnings"), placeholders = meta("X-Placeholders");
    const url = URL.createObjectURL(await r.blob());
    // Decode off-screen first so the swap never shows a blank frame
    const next = new Image();
    next.src = url;
    await next.decode().catch(() => {});
    $("#preview").src = url;
    if (previewURL) URL.revokeObjectURL(previewURL);
    previewURL = url;
    const changed = placeholders.join("\u0000") !== S.placeholders.join("\u0000");
    S.placeholders = placeholders;
    if (changed) { autoMap(); drawData(); }
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
  $("#dims").textContent = `Cut ${r1(p.w)} × ${r1(p.h)} mm · printable ${r1(c.w)} × ${r1(c.h)} mm`;
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
  box.style.cssText = `left:${e.x * k}px;top:${e.y * k}px;width:${w}px;height:${hh}px`;
}

// Bounding box (mm) of the given element indexes
function bounds(idx) {
  const els = idx.map((i) => S.layout.elements[i]);
  const l = Math.min(...els.map((e) => e.x)), t = Math.min(...els.map((e) => e.y));
  const r = Math.max(...els.map((e) => e.x + e.w)), b = Math.max(...els.map((e) => e.y + e.h));
  return { l, t, r, b };
}

// Snap lines in mm: the printable area's edges and centre, and the edges and
// centre of every element not being dragged
function snapTargets(skip) {
  const c = canvasMM();
  const xs = [0, c.w / 2, c.w], ys = [0, c.h / 2, c.h];
  S.layout.elements.forEach((o, j) => {
    if (skip.has(j) || o.hidden) return;
    xs.push(o.x, o.x + o.w / 2, o.x + o.w);
    ys.push(o.y, o.y + o.h / 2, o.y + o.h);
  });
  return { xs, ys };
}

// Closest target to any of the points, within thr: {d: offset, at: target}
function nearest(points, targets, thr) {
  let best = null;
  for (const p of points) for (const t of targets) {
    const d = t - p;
    if (Math.abs(d) <= thr && (!best || Math.abs(d) < Math.abs(best.d))) best = { d, at: t };
  }
  return best;
}

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
      const dx = (m.clientX - start.x) / k, dy = (m.clientY - start.y) / k, thr = thrOf(m);
      let gx = [], gy = [];
      const edge = (v, list, guides) => {
        if (!thr) return v;
        const s = nearest([v], list, thr);
        if (s) { guides.push(s.at); return s.at; }
        return snap(v);
      };
      let { l, t, r, b } = s0;
      if (hd.includes("w")) l = Math.min(edge(l + dx, targets.xs, gx), r - 1);
      if (hd.includes("e")) r = Math.max(edge(r + dx, targets.xs, gx), l + 1);
      if (hd.includes("n")) t = Math.min(edge(t + dy, targets.ys, gy), b - 0.5);
      if (hd.includes("s")) b = Math.max(edge(b + dy, targets.ys, gy), t + 0.5);
      if (e.type === "qr") {
        // Square, anchored at the opposite corner; keep only guides still on an edge
        const s = Math.max(r - l, b - t);
        if (hd.includes("w")) l = r - s; else r = l + s;
        if (hd.includes("n")) t = b - s; else b = t + s;
        gx = gx.filter((v) => Math.abs(v - l) < 1e-6 || Math.abs(v - r) < 1e-6);
        gy = gy.filter((v) => Math.abs(v - t) < 1e-6 || Math.abs(v - b) < 1e-6);
      }
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
  const b0 = bounds(idx), bw = b0.r - b0.l, bh = b0.b - b0.t;
  const targets = snapTargets(new Set(idx));
  track(box, ev, (m) => {
    const thr = thrOf(m), gx = [], gy = [];
    let x = b0.l + (m.clientX - start.x) / k, y = b0.t + (m.clientY - start.y) / k;
    const sx = thr && nearest([x, x + bw / 2, x + bw], targets.xs, thr);
    const sy = thr && nearest([y, y + bh / 2, y + bh], targets.ys, thr);
    if (sx) { x += sx.d; gx.push(sx.at); } else if (thr) x = snap(x);
    if (sy) { y += sy.d; gy.push(sy.at); } else if (thr) y = snap(y);
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

// Align: one element to the printable area; several to their own bounding
// box or to the printable area (S.alignTo)
const ALIGN = [
  ["left", "Align left", (e, R) => { e.x = R.l; }],
  ["hcenter", "Centre horizontally", (e, R) => { e.x = (R.l + R.r - e.w) / 2; }],
  ["right", "Align right", (e, R) => { e.x = R.r - e.w; }],
  null,
  ["top", "Align top", (e, R) => { e.y = R.t; }],
  ["vcenter", "Centre vertically", (e, R) => { e.y = (R.t + R.b - e.h) / 2; }],
  ["bottom", "Align bottom", (e, R) => { e.y = R.b - e.h; }],
];

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
  return h("div", { class: "align" }, ...ALIGN.map((a) => !a ? h("span", { class: "gap" }) :
    h("button", { type: "button", class: "icon", title: a[1], onclick: () => {
      const idx = picked(), c = canvasMM();
      const R = idx.length > 1 && S.alignTo === "selection" ? bounds(idx) : { l: 0, t: 0, r: c.w, b: c.h };
      for (const i of idx) {
        const e = S.layout.elements[i];
        a[2](e, R);
        e.x = r2(e.x); e.y = r2(e.y);
      }
      drawProps(true); schedule();
    } }, alignIcon(a[0]))));
}

// Distribute: equal gaps between three or more elements; the two outermost stay put
function distribute(vert) {
  const [p, s] = vert ? ["y", "h"] : ["x", "w"];
  const els = picked().map((i) => S.layout.elements[i]).sort((a, b) => a[p] - b[p]);
  if (els.length < 3) return;
  const first = els[0], end = Math.max(...els.map((e) => e[p] + e[s]));
  const gap = (end - first[p] - els.reduce((n, e) => n + e[s], 0)) / (els.length - 1);
  let at = first[p] + first[s] + gap;
  for (const e of els.slice(1, -1)) { e[p] = r2(at); at += e[s] + gap; }
  schedule();
}

// Keyboard: nudge with arrows (Shift = 2 mm), Delete removes, Ctrl+A selects all
document.addEventListener("keydown", (ev) => {
  if (ev.target.matches("input, textarea, select") || $("#settings").open) return;
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "a") {
    setPick(new Set(S.layout.elements.map((_, i) => i))); ev.preventDefault(); return;
  }
  if (!S.pick.size) return;
  const step = ev.shiftKey ? 2 : 0.5;
  const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[ev.key];
  if (d) {
    for (const i of S.pick) { const e = S.layout.elements[i]; e.x = r2(e.x + d[0]); e.y = r2(e.y + d[1]); }
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
});

// ---------------------------------------------------------------------------
// Elements list & properties
// ---------------------------------------------------------------------------

const KIND = { text: "Text", qr: "QR", barcode: "Code", rect: "Box" };
const summary = (e) => e.type === "text" ? e.text.replace(/\n/g, " ⏎ ") : e.type === "rect" ? `${e.w} × ${e.h} mm` : e.data;

// Selection: S.pick is the set of selected indexes; S.sel is the one shown in
// the properties panel when exactly one is selected (otherwise -1)
const picked = () => [...S.pick].sort((a, b) => a - b);

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
  const gone = new Set(idx);
  S.layout.elements = S.layout.elements.filter((_, i) => !gone.has(i));
  setPick(new Set()); schedule();
}

function moveEl(i, d) {
  const els = S.layout.elements, j = i + d;
  if (j < 0 || j >= els.length) return;
  [els[i], els[j]] = [els[j], els[i]];
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

// Each copy goes just above its original, offset 2 mm; the copies end up selected
function dupEls(idx) {
  const els = S.layout.elements, copies = new Set();
  idx.slice().sort((a, b) => b - a).forEach((i) => {
    const c = structuredClone(els[i]);
    c.x = r2(c.x + 2); c.y = r2(c.y + 2);
    els.splice(i + 1, 0, c);
  });
  idx.slice().sort((a, b) => a - b).forEach((i, n) => copies.add(i + n + 1));
  setPick(copies); schedule();
}

// Form helpers bound to the selected element
function bind(key, input, conv = (v) => v) {
  const e = S.layout.elements[S.sel];
  input.value = e[key] ?? "";
  input.dataset.key = key;
  input.addEventListener("input", () => { e[key] = conv(input.value); drawList(); drawOverlay(); schedule(); });
  return input;
}
const num = (key, attrs = {}) => bind(key, h("input", { type: "number", step: "0.5", ...attrs }), (v) => +v || 0);
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
      if (inp && document.activeElement !== inp) inp.value = e[k];
    }
    return;
  }
  const redOK = tape().red;
  const kids = [h("h2", {}, KIND[e.type] === "Code" ? "Barcode" : KIND[e.type])];

  if (e.type === "text") {
    kids.push(fld("Text", editing(bind("text", h("textarea", { rows: 3, spellcheck: false })))));
  } else if (e.type === "qr" || e.type === "barcode") {
    kids.push(fld(e.type === "qr" ? "Data" : "Data (Code 128)", editing(bind("data", h("input", { type: "text", spellcheck: false })))));
  }

  kids.push(h("div", { class: "row4 num4" },
    fld("X", num("x")), fld("Y", num("y")), fld("W", num("w", { min: 0.5 })), fld("H", num("h", { min: 0.5 }))));
  kids.push(h("div", { class: "field" }, "Align to label", alignRow()));
  kids.push(h("div", { class: "field" }, "Colour", seg("color", colourOpts(redOK))));

  if (e.type === "text") {
    const font = h("select", {}, ...S.meta.fonts.map((f) => h("option", { value: f }, { sans: "Sans", narrow: "Narrow", serif: "Serif", mono: "Mono" }[f] || f)));
    kids.push(h("div", { class: "row2" },
      fld("Font", bind("font", font)),
      fld("Size (pt)", bind("size", h("input", { type: "number", min: 0, step: 1, placeholder: "auto" }), (v) => +v || 0))));
    kids.push(h("div", { class: "sub", style: "margin:-6px 0 10px" }, "Size 0 = shrink to fit the box"));
    kids.push(h("div", { class: "field" }, "Align", seg("align", [["left", "Left"], ["center", "Centre"], ["right", "Right"]])));
    kids.push(h("div", { class: "field" }, "Vertical", seg("valign", [["top", "Top"], ["middle", "Middle"], ["bottom", "Bottom"]])));
    kids.push(h("div", { class: "checks" }, chk("bold", "Bold"), chk("wrap", "Wrap"), chk("invert", "Inverted")));
    kids.push(h("div", { class: "row2" }, fld("Padding (mm)", num("padding_mm", { min: 0 }))));
  } else if (e.type === "qr") {
    const ec = h("select", {}, ...[["L", "L — 7%"], ["M", "M — 15%"], ["Q", "Q — 25%"], ["H", "H — 30%"]].map(([v, t]) => h("option", { value: v }, t)));
    kids.push(fld("Error correction", bind("ec", ec)));
  } else if (e.type === "barcode") {
    kids.push(h("div", { class: "checks" }, chk("show_text", "Show text")));
  } else if (e.type === "rect") {
    kids.push(h("div", { class: "checks" }, chk("fill", "Filled")));
    kids.push(h("div", { class: "row2" }, fld("Outline (mm)", num("stroke_mm", { min: 0.1, step: 0.1 }))));
  }
  box.replaceChildren(...kids);
}

document.querySelectorAll("[data-add]").forEach((b) => b.addEventListener("click", () => {
  S.layout.elements.push(newElement(b.dataset.add));
  select(S.layout.elements.length - 1);
  schedule();
}));

// ---------------------------------------------------------------------------
// Label setup
// ---------------------------------------------------------------------------

function drawSetup() {
  const t = tape();
  $("#tape").value = t.id;
  $("#length").value = S.layout.length_mm;
  $("#lengthRow").querySelector("label").hidden = !t.endless;
  $("#printable").textContent = t.endless ? `${t.printable_mm[0]} mm wide` : `${t.printable_mm[0]} × ${t.printable_mm[1]} mm`;
  $("#orientation").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.v === S.layout.orientation));
}

// Apply a label-shape change, scaling elements proportionally so the layout
// still fits the new canvas (QR codes stay square).
function reshape(change) {
  const a = canvasMM();
  change();
  const b = canvasMM();
  const kx = b.w / a.w, ky = b.h / a.h;
  if (Math.abs(kx - 1) > 1e-6 || Math.abs(ky - 1) > 1e-6) {
    for (const e of S.layout.elements) {
      e.x = r1(e.x * kx); e.w = r1(e.w * kx);
      e.y = r1(e.y * ky); e.h = r1(e.h * ky);
      if (e.type === "qr") {
        const s = Math.min(e.w, e.h);
        e.x = r1(e.x + (e.w - s) / 2); e.y = r1(e.y + (e.h - s) / 2); e.w = e.h = s;
      }
    }
  }
  drawSetup(); drawPresets(); drawList(); drawProps(); fit(); schedule();
}

$("#tape").addEventListener("change", (ev) => reshape(() => { S.layout.tape = ev.target.value; }));
// "change" (not "input") so typing 50 doesn't pass through a 5 mm label
$("#length").addEventListener("change", (ev) => reshape(() => { S.layout.length_mm = Math.max(5, Math.min(1000, +ev.target.value || 5)); }));
$("#orientation").addEventListener("click", (ev) => {
  const v = ev.target.dataset.v;
  if (v && v !== S.layout.orientation) reshape(() => { S.layout.orientation = v; });
});

function drawPresets() {
  const c = canvasMM();
  $("#presets").replaceChildren(...PRESETS.map((p) => {
    const why = p.fits(c.w, c.h);
    return h("button", { type: "button", class: "preset", disabled: !!why, title: why || null, onclick: () => {
      let els = roundAll(p.make(c.w, c.h));
      if (!tape().red) els = els.map((e) => ({ ...e, color: "black" }));
      S.layout.elements = els;
      select(-1); schedule(); checkpoint();
    } }, presetThumb(p, c.w, c.h), h("span", {}, p.name));
  }));
}

// ---------------------------------------------------------------------------
// Templates
// ---------------------------------------------------------------------------

async function drawTemplates() {
  const { templates } = await api("/api/templates");
  $("#tplList").replaceChildren(...(templates.length ? templates.map((n) => h("li", {},
    h("button", { class: "name", onclick: () => loadTemplate(n) }, n),
    h("button", { class: "icon", title: "Delete template", onclick: async () => {
      if (!confirm(`Delete template “${n}”?`)) return;
      await api(`/api/templates/${encodeURIComponent(n)}`, { method: "DELETE" });
      drawTemplates();
    } }, "×"))) : [h("li", { class: "empty" }, "None saved yet")]));
}

async function loadTemplate(n) {
  const j = await api(`/api/templates/${encodeURIComponent(n)}`);
  S.layout = j.layout; S.fixed = j.fixed || {};
  if (j.mapping) S.mapping = { ...S.mapping, ...j.mapping };
  $("#tplName").value = n;
  S.sel = -1; S.pick = new Set();
  drawSetup(); drawPresets(); drawList(); drawProps(); drawData(); fit(); schedule();
}

$("#tplSave").addEventListener("click", async () => {
  const n = $("#tplName").value.trim();
  if (!n) { $("#tplName").focus(); return; }
  await api(`/api/templates/${encodeURIComponent(n)}`, { method: "PUT", body: { layout: S.layout, fixed: S.fixed, mapping: S.mapping } });
  drawTemplates();
});

// ---------------------------------------------------------------------------
// Data: fields table, CSV rows
// ---------------------------------------------------------------------------

function drawData() {
  const ph = fields();
  const rows = ph.map((p) => {
    const fixedIn = h("input", { type: "text", placeholder: "text or {{Field}}", value: S.fixed[p] ?? "",
      title: "Fixed text. May include other fields, such as {{Item}}" });
    fixedIn.addEventListener("input", () => { S.fixed[p] = fixedIn.value; schedule(); });
    // A newly referenced field gets its own row once typing is done
    fixedIn.addEventListener("change", () => { if (fields().join("\u0000") !== ph.join("\u0000")) { autoMap(); drawData(); } });
    let src = null;
    if (S.csv) {
      src = h("select", {}, h("option", { value: "" }, "— fixed text —"),
        ...S.csv.headers.map((c) => h("option", { value: c }, c)));
      src.value = S.mapping[p] ?? "";
      fixedIn.hidden = !!src.value;
      src.addEventListener("change", () => {
        S.mapping[p] = src.value; fixedIn.hidden = !!src.value; schedule();
        if (fields().join("\u0000") !== ph.join("\u0000")) drawData();
      });
    }
    return h("tr", {}, h("td", {}, `{{${p}}}`), src && h("td", {}, src), h("td", {}, fixedIn));
  });
  $("#fields").replaceChildren(...(rows.length ? rows : [h("tr", { class: "none" }, h("td", {}, "No fields in this layout"))]));

  $("#rowsWrap").hidden = !S.csv;
  $("#csvClear").hidden = !S.csv;
  if (S.csv) {
    $("#csvInfo").textContent = `${S.csv.rows.length} rows · ${S.picked.size} selected · click a row to preview it`;
    drawRows();
  } else {
    $("#csvInfo").innerHTML = "Type <code>{{Name}}</code> in any text, QR or barcode to create a field. Built-in: <code>{{date}}</code> <code>{{time}}</code>";
  }
  drawPrintButton();
}

function drawRows() {
  const { headers, rows } = S.csv;
  const all = h("input", { type: "checkbox", title: "Select all" });
  all.checked = S.picked.size === rows.length;
  all.indeterminate = S.picked.size > 0 && S.picked.size < rows.length;
  all.addEventListener("change", () => {
    S.picked = all.checked ? new Set(rows.map((_, i) => i)) : new Set();
    drawData();
  });
  const thead = h("thead", {}, h("tr", {}, h("th", {}, all), h("th", {}, "#"), ...headers.map((c) => h("th", {}, c))));
  const tbody = h("tbody", {}, ...rows.map((r, i) => {
    const cb = h("input", { type: "checkbox" });
    cb.checked = S.picked.has(i);
    cb.addEventListener("click", (ev) => ev.stopPropagation());
    cb.addEventListener("change", () => { cb.checked ? S.picked.add(i) : S.picked.delete(i); drawData(); });
    return h("tr", { class: i === S.cur ? "cur" : "", onclick: () => { S.cur = i; drawRows(); schedule(); } },
      h("td", {}, cb), h("td", { class: "n" }, i + 1), ...headers.map((c) => h("td", { title: r[c] }, r[c])));
  }));
  $("#rows").replaceChildren(thead, tbody);
}

$("#csvFile").addEventListener("change", async (ev) => {
  const f = ev.target.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  try {
    S.csv = await api("/api/csv", { method: "POST", body: fd });
    S.picked = new Set(S.csv.rows.map((_, i) => i));
    S.cur = 0;
    autoMap(); drawData(); schedule();
  } catch (e) { status(e.message, "err"); }
  ev.target.value = "";
});

$("#csvClear").addEventListener("click", () => { S.csv = null; S.picked = new Set(); drawData(); schedule(); });

// ---------------------------------------------------------------------------
// Printing
// ---------------------------------------------------------------------------

function jobRecords() {
  if (!S.csv) return [record(null)];
  return [...S.picked].sort((a, b) => a - b).map((i) => record(S.csv.rows[i]));
}

function drawPrintButton() {
  const n = (S.csv ? S.picked.size : 1) * Math.max(1, +$("#copies").value || 1);
  const b = $("#printBtn");
  b.textContent = n === 1 ? "Print 1 label" : `Print ${n} labels`;
  b.disabled = n === 0;
}
$("#copies").addEventListener("input", drawPrintButton);

function status(msg, cls = "") {
  const s = $("#printStatus");
  s.textContent = msg; s.className = "status " + cls;
}

$("#printBtn").addEventListener("click", async () => {
  if (!S.meta.config.printer_host) { openSettings(); return; }
  const b = $("#printBtn");
  b.disabled = true;
  status("Sending…");
  try {
    const j = await api("/api/print", { method: "POST", body: {
      layout: S.layout, records: jobRecords(), chain: chain(), copies: +$("#copies").value || 1, cut: $("#cut").checked } });
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
  const j = await api("/api/test", { method: "POST" });
  drawPrinterChip(j.ok);
  if (target) { target.textContent = j.message; target.className = "status " + (j.ok ? "ok" : "err"); }
  return j.ok;
}

$("#printerChip").addEventListener("click", openSettings);
$("#cfgSave").addEventListener("click", async () => { await saveSettings(); $("#settings").close(); testPrinter(); });
$("#cfgTest").addEventListener("click", async () => {
  $("#cfgStatus").textContent = "Testing…"; $("#cfgStatus").className = "status";
  await saveSettings();
  testPrinter($("#cfgStatus"));
});

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

(async function boot() {
  S.meta = await api("/api/meta");
  $("#tape").replaceChildren(...S.meta.tapes.map((t) => h("option", { value: t.id }, t.name)));
  if (!restore() || !S.meta.tapes.some((t) => t.id === S.layout.tape)) {
    S.layout = { tape: S.meta.tapes[0].id, length_mm: 30, orientation: "portrait", elements: [] };
    const c = canvasMM();
    S.layout.elements = roundAll(PRESETS[2].make(c.w, c.h));
  }
  drawSetup(); drawPresets(); drawList(); drawProps(); drawData(); drawPrinterChip();
  drawTemplates();
  fit(); schedule();
  checkpoint();
  if (S.meta.config.printer_host) testPrinter();
  new ResizeObserver(fit).observe($("#stage"));
})();
