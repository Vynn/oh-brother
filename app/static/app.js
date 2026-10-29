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
  sel: -1,
  fixed: {},            // placeholder -> fixed text
  csv: null,            // {headers, rows}
  mapping: {},          // placeholder -> column name ("" = fixed text)
  picked: new Set(),    // selected CSV row indexes
  cur: 0,               // CSV row shown in preview
  placeholders: [],
  scale: 1,             // screen px per dot
};

const STORE = "oh-brother:v1";
const save = () => { try { localStorage.setItem(STORE, JSON.stringify({ layout: S.layout, fixed: S.fixed })); } catch {} };
const restore = () => {
  try {
    const j = JSON.parse(localStorage.getItem(STORE) || "null");
    if (j?.layout) { S.layout = j.layout; S.fixed = j.fixed || {}; return true; }
  } catch {}
  return false;
};

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

const r1 = (v) => Math.round(v * 10) / 10;
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

// Each preset maps canvas size (mm) to a list of elements; m = margin
const PRESETS = [
  { name: "Single line", make: (W, H, m = 2) => [T({ x: m, y: m, w: W - 2 * m, h: H - 2 * m, text: "{{Text}}", bold: true, align: "center", wrap: false })] },
  { name: "Title + body", make: (W, H, m = 2) => [
      T({ x: m, y: m, w: W - 2 * m, h: (H - 2 * m) * 0.4, text: "{{Title}}", bold: true }),
      T({ x: m, y: m + (H - 2 * m) * 0.45, w: W - 2 * m, h: (H - 2 * m) * 0.55, text: "{{Body}}", valign: "top" })] },
  { name: "Red header", make: (W, H, m = 2) => [
      T({ x: 0, y: 0, w: W, h: H * 0.32, text: "{{Title}}", bold: true, align: "center", invert: true, color: "red", padding_mm: 1, wrap: false }),
      T({ x: m, y: H * 0.32 + m, w: W - 2 * m, h: H * 0.68 - 2 * m, text: "{{Body}}" })] },
  { name: "Text + QR", make: (W, H, m = 2) => { const s = Math.min(H - 2 * m, W * 0.45); return [
      T({ x: m, y: m, w: W - s - 3 * m, h: H - 2 * m, text: "{{Name}}", bold: true }),
      { type: "qr", color: "black", x: W - s - m, y: (H - s) / 2, w: s, h: s, data: "{{Code}}", ec: "M" }]; } },
  { name: "Barcode", make: (W, H, m = 2) => [
      T({ x: m, y: m, w: W - 2 * m, h: (H - 2 * m) * 0.35, text: "{{Name}}", bold: true, align: "center" }),
      { type: "barcode", color: "black", x: m, y: m + (H - 2 * m) * 0.4, w: W - 2 * m, h: (H - 2 * m) * 0.6, data: "{{Code}}", show_text: true }] },
  { name: "Address", make: (W, H, m = 3) => [
      T({ x: m, y: m, w: W - 2 * m, h: H - 2 * m, text: "{{Name}}\n{{Street}}\n{{City}} {{Postcode}}\n{{Country}}", valign: "top", wrap: false })] },
];

function roundAll(els) {
  return els.map((e) => ({ ...e, x: r1(e.x), y: r1(e.y), w: r1(e.w), h: r1(e.h) }));
}

// Thumbnail: draw the preset at a nominal 60x30 mm with text as grey bars
function presetThumb(p) {
  const W = 60, H = 30;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  const add = (tag, a) => { const n = document.createElementNS(svg.namespaceURI, tag); for (const k in a) n.setAttribute(k, a[k]); svg.append(n); };
  add("rect", { x: 0, y: 0, width: W, height: H, fill: "#fff", stroke: "#d6d3ce", "stroke-width": 0.6, rx: 1 });
  for (const e of p.make(W, H)) {
    const col = e.color === "red" ? "#d42b20" : "#2a2a2a";
    if (e.type === "text") {
      if (e.invert) add("rect", { x: e.x, y: e.y, width: e.w, height: e.h, fill: col });
      const lines = Math.max(1, (e.text.match(/\n/g) || []).length + 1);
      const lh = Math.min(e.h / lines * 0.55, e.bold ? 6 : 4);
      for (let i = 0; i < lines; i++) {
        const bw = e.w * (i % 2 ? 0.6 : 0.8);
        const bx = e.align === "center" ? e.x + (e.w - bw) / 2 : e.x + 1;
        const by = e.valign === "top" ? e.y + 1 + i * lh * 1.6 : e.y + (e.h - lines * lh * 1.6) / 2 + i * lh * 1.6 + lh * 0.3;
        add("rect", { x: bx, y: by, width: bw, height: lh, fill: e.invert ? "#fff" : col, rx: 0.5 });
      }
    } else if (e.type === "qr") {
      add("rect", { x: e.x, y: e.y, width: e.w, height: e.h, fill: "none", stroke: col, "stroke-width": 1.4 });
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

// Build the placeholder->value record for one CSV row (or fixed values only)
function record(row) {
  const rec = {};
  for (const p of S.placeholders) {
    const col = S.mapping[p];
    rec[p] = row && col ? (row[col] ?? "") : (S.fixed[p] ?? "");
  }
  return rec;
}

const previewRecord = () => record(S.csv ? S.csv.rows[S.cur] : null);

function autoMap() {
  if (!S.csv) return;
  for (const p of S.placeholders) {
    if (S.mapping[p] !== undefined && (S.mapping[p] === "" || S.csv.headers.includes(S.mapping[p]))) continue;
    const hit = S.csv.headers.find((c) => c.toLowerCase() === p.toLowerCase());
    S.mapping[p] = hit || "";
  }
}

// ---------------------------------------------------------------------------
// Preview rendering (debounced, stale responses dropped)
// ---------------------------------------------------------------------------

let renderTimer = 0, renderSeq = 0;
function schedule() {
  save();
  clearTimeout(renderTimer);
  renderTimer = setTimeout(doRender, 90);
}

async function doRender() {
  const seq = ++renderSeq;
  try {
    const j = await api("/api/render", { method: "POST", body: { layout: S.layout, record: previewRecord() } });
    if (seq !== renderSeq) return;
    const img = $("#preview");
    img.src = j.image;
    img.dataset.w = j.width; img.dataset.h = j.height;
    const placeholdersChanged = j.placeholders.join("\u0000") !== S.placeholders.join("\u0000");
    S.placeholders = j.placeholders;
    if (placeholdersChanged) { autoMap(); drawData(); }
    fit();
    drawWarnings(j.warnings);
  } catch (e) {
    drawWarnings([e.message]);
  }
}

// Scale the preview to fit the stage (never larger than 2x, crisp at 1x)
function fit() {
  const img = $("#preview");
  const W = +img.dataset.w, H = +img.dataset.h;
  if (!W) return;
  const st = $("#stage");
  const s = Math.min(2, (st.clientWidth - 56) / W, (st.clientHeight - 56) / H);
  S.scale = Math.max(0.1, s);
  img.style.width = W * S.scale + "px";
  img.style.height = H * S.scale + "px";
  // Hard pixels when zoomed in (true 1-bit look); smooth when shrunk, to avoid shimmer
  img.style.imageRendering = S.scale >= 1 ? "pixelated" : "auto";
  $("#labelWrap").classList.toggle("round", tape().round);
  const c = canvasMM();
  $("#dims").textContent = `${r1(c.w)} × ${r1(c.h)} mm`;
  drawOverlay();
}

function drawWarnings(list) {
  $("#warnings").replaceChildren(...list.map((w) => h("li", {}, "⚠ " + w)));
}

// ---------------------------------------------------------------------------
// Overlay: selection boxes, drag to move, handle to resize
// ---------------------------------------------------------------------------

function drawOverlay() {
  const k = dpmm() * S.scale;
  const ov = $("#overlay");
  ov.replaceChildren(...S.layout.elements.map((e, i) => {
    const box = h("div", { class: "box" + (i === S.sel ? " sel" : ""), "data-i": i },
      h("div", { class: "handle" }));
    Object.assign(box.style, { left: e.x * k + "px", top: e.y * k + "px", width: e.w * k + "px", height: e.h * k + "px" });
    return box;
  }));
}

$("#overlay").addEventListener("pointerdown", (ev) => {
  const box = ev.target.closest(".box");
  if (!box) { select(-1); return; }
  const i = +box.dataset.i;
  select(i);
  const e = S.layout.elements[i];
  const resize = ev.target.classList.contains("handle");
  const start = { x: ev.clientX, y: ev.clientY, ex: e.x, ey: e.y, ew: e.w, eh: e.h };
  const k = dpmm() * S.scale;
  const el = $("#overlay").querySelector(`[data-i="${i}"]`);
  el.setPointerCapture(ev.pointerId);
  const move = (m) => {
    const dx = (m.clientX - start.x) / k, dy = (m.clientY - start.y) / k;
    if (resize) {
      e.w = Math.max(1, snap(start.ew + dx));
      e.h = Math.max(0.5, snap(start.eh + dy));
      if (e.type === "qr") e.h = e.w;
    } else {
      e.x = snap(start.ex + dx);
      e.y = snap(start.ey + dy);
    }
    Object.assign(el.style, { left: e.x * k + "px", top: e.y * k + "px", width: e.w * k + "px", height: e.h * k + "px" });
    drawProps(true);
    schedule();
  };
  const up = () => { el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); };
  el.addEventListener("pointermove", move);
  el.addEventListener("pointerup", up);
  ev.preventDefault();
});

// Keyboard: nudge with arrows (Shift = 2 mm), Delete removes
document.addEventListener("keydown", (ev) => {
  if (S.sel < 0 || ev.target.matches("input, textarea, select") || $("#settings").open) return;
  const e = S.layout.elements[S.sel];
  const step = ev.shiftKey ? 2 : 0.5;
  const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[ev.key];
  if (d) { e.x = r1(e.x + d[0]); e.y = r1(e.y + d[1]); drawOverlay(); drawProps(true); schedule(); ev.preventDefault(); }
  else if (ev.key === "Delete" || ev.key === "Backspace") { removeEl(S.sel); ev.preventDefault(); }
  else if (ev.key === "Escape") select(-1);
});

// ---------------------------------------------------------------------------
// Elements list & properties
// ---------------------------------------------------------------------------

const KIND = { text: "Text", qr: "QR", barcode: "Code", rect: "Box" };
const summary = (e) => e.type === "text" ? e.text.replace(/\n/g, " ⏎ ") : e.type === "rect" ? `${e.w} × ${e.h} mm` : e.data;

function select(i) {
  S.sel = i;
  drawList(); drawOverlay(); drawProps();
}

function removeEl(i) {
  S.layout.elements.splice(i, 1);
  S.sel = Math.min(S.sel, S.layout.elements.length - 1);
  drawList(); drawProps(); schedule();
}

function moveEl(i, d) {
  const els = S.layout.elements, j = i + d;
  if (j < 0 || j >= els.length) return;
  [els[i], els[j]] = [els[j], els[i]];
  S.sel = j;
  drawList(); schedule();
}

function drawList() {
  const els = S.layout.elements;
  // Listed top-most first: later elements are drawn on top
  const items = els.map((e, i) => i).reverse().map((i) => {
    const e = els[i];
    return h("li", { class: i === S.sel ? "sel" : "", onclick: () => select(i) },
      h("span", { class: "swatch" + (e.color === "red" ? " red" : "") }),
      h("span", { class: "kind" }, KIND[e.type]),
      h("span", { class: "txt", title: summary(e) }, summary(e)),
      h("span", { class: "acts" },
        h("button", { class: "icon", title: "Bring forward", onclick: (ev) => { ev.stopPropagation(); moveEl(i, 1); } }, "↑"),
        h("button", { class: "icon", title: "Send backward", onclick: (ev) => { ev.stopPropagation(); moveEl(i, -1); } }, "↓"),
        h("button", { class: "icon", title: "Duplicate", onclick: (ev) => { ev.stopPropagation(); dupEl(i); } }, "⧉"),
        h("button", { class: "icon", title: "Delete", onclick: (ev) => { ev.stopPropagation(); removeEl(i); } }, "×")));
  });
  $("#elList").replaceChildren(...(items.length ? items : [h("li", { class: "empty" }, "No elements — add one or pick a quick layout")]));
}

function dupEl(i) {
  const c = structuredClone(S.layout.elements[i]);
  c.x = r1(c.x + 2); c.y = r1(c.y + 2);
  S.layout.elements.splice(i + 1, 0, c);
  select(i + 1); schedule();
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

// light=true only refreshes geometry numbers (used while dragging)
function drawProps(light = false) {
  const box = $("#props");
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
    kids.push(fld("Text", bind("text", h("textarea", { rows: 3, spellcheck: false }))));
  } else if (e.type === "qr" || e.type === "barcode") {
    kids.push(fld(e.type === "qr" ? "Data" : "Data (Code 128)", bind("data", h("input", { type: "text", spellcheck: false }))));
  }

  kids.push(h("div", { class: "row4 num4" },
    fld("X", num("x")), fld("Y", num("y")), fld("W", num("w", { min: 0.5 })), fld("H", num("h", { min: 0.5 }))));
  kids.push(h("div", { class: "field" }, "Colour", seg("color", [
    ["black", "Black"],
    ["red", "Red", { cls: "red", disabled: !redOK, title: redOK ? "" : "Needs black/red tape (DK-2251)" }]])));

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
  drawSetup(); drawList(); drawProps(); schedule();
}

$("#tape").addEventListener("change", (ev) => reshape(() => { S.layout.tape = ev.target.value; }));
// "change" (not "input") so typing 50 doesn't pass through a 5 mm label
$("#length").addEventListener("change", (ev) => reshape(() => { S.layout.length_mm = Math.max(5, Math.min(1000, +ev.target.value || 5)); }));
$("#orientation").addEventListener("click", (ev) => {
  const v = ev.target.dataset.v;
  if (v && v !== S.layout.orientation) reshape(() => { S.layout.orientation = v; });
});

function drawPresets() {
  $("#presets").replaceChildren(...PRESETS.map((p) => h("button", { type: "button", class: "preset", onclick: () => {
    if (S.layout.elements.length && !confirm("Replace the current elements with this layout?")) return;
    const c = canvasMM();
    let els = roundAll(p.make(c.w, c.h));
    if (!tape().red) els = els.map((e) => ({ ...e, color: "black" }));
    S.layout.elements = els;
    select(-1); schedule();
  } }, presetThumb(p), h("span", {}, p.name))));
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
  S.sel = -1;
  drawSetup(); drawList(); drawProps(); drawData(); schedule();
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
  const ph = S.placeholders;
  const rows = ph.map((p) => {
    const fixedIn = h("input", { type: "text", placeholder: S.csv ? "fixed text" : "value", value: S.fixed[p] ?? "" });
    fixedIn.addEventListener("input", () => { S.fixed[p] = fixedIn.value; schedule(); });
    let src = null;
    if (S.csv) {
      src = h("select", {}, h("option", { value: "" }, "— fixed text —"),
        ...S.csv.headers.map((c) => h("option", { value: c }, c)));
      src.value = S.mapping[p] ?? "";
      fixedIn.hidden = !!src.value;
      src.addEventListener("change", () => { S.mapping[p] = src.value; fixedIn.hidden = !!src.value; schedule(); });
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
      layout: S.layout, records: jobRecords(), copies: +$("#copies").value || 1, cut: $("#cut").checked } });
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
  schedule();
  if (S.meta.config.printer_host) testPrinter();
  new ResizeObserver(fit).observe($("#stage"));
})();
