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
  // A number, or a default: the renderer's own, for a key that's missing or isn't one
  const or = (v, d) => (typeof v === "number" || (typeof v === "string" && v.trim() !== "")) && Number.isFinite(+v) ? +v : d;
  const [min, max] = lengths;
  const elements = (Array.isArray(l.elements) ? l.elements : [])
    .filter((e) => e && typeof e === "object" && !Array.isArray(e))
    .map((e) => ({ ...e, x: or(e.x, 0), y: or(e.y, 0), w: or(e.w, 10), h: or(e.h, 10),
      ...(e.type === "text" ? { text: String(e.text ?? "") } : {}) }));
  return { ...l, tape: typeof l.tape === "string" ? l.tape : "62red",
    length_mm: Math.max(min, Math.min(max, or(l.length_mm, 30))),
    orientation: l.orientation === "landscape" ? "landscape" : "portrait", elements };
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
