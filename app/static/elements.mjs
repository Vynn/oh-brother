// A layout's list of elements: making one safe to edit, and removing,
// copying and reordering what's in it. Later elements are drawn on top.

import { r2 } from "./units.mjs";

// A layout from a template or this browser's storage, made safe to edit, or
// null if it isn't a layout at all. The editor does arithmetic on every
// element's position and size, so one saved by an older build or edited by
// hand gets the missing pieces filled in rather than breaking the page.
// lengths: the least and most a continuous label may be, in mm (/api/meta).
export function tidyLayout(l, lengths) {
  if (!l || typeof l !== "object" || Array.isArray(l)) return null;
  const [min, max] = lengths;
  return { ...l, tape: typeof l.tape === "string" ? l.tape : "62red",
    length_mm: Math.max(min, Math.min(max, or(l.length_mm, 30))),
    orientation: l.orientation === "landscape" ? "landscape" : "portrait", elements: tidyElements(l.elements) };
}

// A number, or a default: the renderer's own, for a key that's missing or isn't one
const or = (v, d) => (typeof v === "number" || (typeof v === "string" && v.trim() !== "")) && Number.isFinite(+v) ? +v : d;

// A list of elements made safe to edit: whatever isn't an element is dropped,
// and each one has a position, a size and, if it's text, its text
export function tidyElements(list) {
  return (Array.isArray(list) ? list : [])
    .filter((e) => e && typeof e === "object" && !Array.isArray(e))
    .map((e) => ({ ...e, x: or(e.x, 0), y: or(e.y, 0), w: or(e.w, 10), h: or(e.h, 10),
      ...(e.type === "text" ? { text: String(e.text ?? "") } : {}) }));
}

// The list without the elements at the indexes in idx
export const removeEls = (els, idx) => { const gone = new Set(idx); return els.filter((_, i) => !gone.has(i)); };

// Swap the element at i with the one d places along. Returns where it went,
// or -1 if that's off the end of the list.
export function moveEl(els, i, d) {
  const j = i + d;
  if (j < 0 || j >= els.length) return -1;
  [els[i], els[j]] = [els[j], els[i]];
  return j;
}

// How far a copy sits from its original, right and down, in mm
export const COPY_OFFSET = 2;

// Duplicate the elements at idx. Each copy is stacked just above its
// original, a little right and down. Returns the copies' indexes.
export function duplicateEls(els, idx) {
  const copies = new Set();
  idx.slice().sort((a, b) => b - a).forEach((i) => {
    const c = structuredClone(els[i]);
    c.x = r2(c.x + COPY_OFFSET); c.y = r2(c.y + COPY_OFFSET);
    els.splice(i + 1, 0, c);
  });
  idx.slice().sort((a, b) => a - b).forEach((i, n) => copies.add(i + n + 1));
  return copies;
}

// Copies of the elements at idx, in their order in the list: what Copy keeps
export const copyEls = (els, idx) => idx.slice().sort((a, b) => a - b).map((i) => structuredClone(els[i]));

// Paste copied elements on top of the others. Returns the new ones' indexes.
// Each lands `shift` mm right and down from where it was copied, so a paste
// doesn't hide its original and a second paste doesn't hide the first. The
// label may be smaller than the one they came from: an element larger than
// it is cut down to it (a QR code staying square), and none lands off it.
// red: false when the tape prints black only.
export function pasteEls(els, clip, canvas, { shift = 0, red = true } = {}) {
  const added = new Set();
  for (const c of clip) {
    const e = structuredClone(c);
    if (!red) e.color = "black";
    e.w = r2(Math.min(e.w, canvas.w)); e.h = r2(Math.min(e.h, canvas.h));
    if (e.type === "qr") e.w = e.h = Math.min(e.w, e.h);
    e.x = r2(Math.max(0, Math.min(e.x + shift, canvas.w - e.w)));
    e.y = r2(Math.max(0, Math.min(e.y + shift, canvas.h - e.h)));
    els.push(e);
    added.add(els.length - 1);
  }
  return added;
}
