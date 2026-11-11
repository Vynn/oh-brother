// Element defaults and the quick layouts. Nothing here touches the page: a
// quick layout is a function from a printable area's size to a list of
// elements, so the tests in tests/editor/ build every one at every tape size.

import { fmt, r1, r2 } from "./units.mjs";

// Text defaults, for new elements and quick layouts. The renderer has its own
// for templates that leave a key out.
export const TEXT = { font: "sans", bold: false, size: 0, align: "left", valign: "middle", wrap: true, invert: false, padding_mm: 0 };

// Image defaults. The image is kept in colour, ready for a two-colour mode
// later; for now it prints in the element's one colour.
export const IMAGE = { src: "", name: "", url: "", mode: "threshold", threshold: 50, invert: false };   // url: where it was fetched from
export const imageOf = (e) => Object.fromEntries(Object.keys(IMAGE).map((k) => [k, e[k] ?? IMAGE[k]]));   // its image settings

// A new element of the given type, sized for a printable area c ({w, h} in mm)
export function newElement(type, c) {
  const base = { type, color: "black", x: 2, y: 2 };
  switch (type) {
    case "text": return { ...base, ...TEXT, w: r1(c.w - 4), h: r1(Math.min(12, c.h - 4)), text: "Text" };
    case "qr": { const s = r1(Math.min(c.w, c.h) - 4); return { ...base, w: s, h: s, data: "{{code}}", ec: "M" }; }
    case "barcode": return { ...base, w: r1(Math.min(c.w - 4, 50)), h: r1(Math.min(c.h - 4, 12)), data: "{{code}}", symbology: "code128", show_text: true };
    case "rect": return { ...base, w: r1(c.w - 4), h: 1, fill: true, stroke_mm: 0.5 };
    case "image": { const s = r1(Math.min(20, Math.min(c.w, c.h) - 4)); return { ...base, ...IMAGE, w: s, h: s }; }
  }
}

export const T = (o) => ({ type: "text", color: "black", ...TEXT, ...o });

// Quick layouts. make(W, H) builds the elements for a printable area of W x H
// mm, picking an arrangement from its shape: "thin" labels (long strips, such
// as 12 mm tape run along) put parts side by side; "tall" ones stack them.
// fits(W, H, red) returns "" or the reason the layout can't work at that size
// (or tape); without one, the built elements are checked by checkEls().
// cat is the layout's category in the panel (CATS).
// Field names are shared ({{title}}, {{body}}, {{code}}, {{price}}) so values carry over
// when switching layouts.

// Margin scales with the short side: 2 mm on 62 mm tape, 0.5 mm on 12 mm
export const marginFor = (W, H) => Math.max(0.5, Math.min(2, Math.round(Math.min(W, H) * 0.14) / 2));
export const shapeOf = (W, H) => W / H >= 2.8 ? "thin" : H / W >= 1.4 ? "tall" : "normal";
export const QR = (o) => ({ type: "qr", color: "black", data: "{{code}}", ec: "M", ...o });
export const BAR = (o) => ({ type: "barcode", color: "black", data: "{{code}}", symbology: "code128", show_text: true, ...o });

export const RULE = (o) => ({ type: "rect", color: "black", fill: true, stroke_mm: 0.3, ...o });
export const IMG = (o) => ({ type: "image", color: "black", ...IMAGE, ...o });

// Generic size check for a built layout: scannable codes, readable text
export function checkEls(els) {
  for (const e of els) {
    if (e.type === "qr" && e.w < 7) return "Too small for a scannable QR code";
    if (e.type === "barcode" && e.w < 20) return "Needs a longer label for a barcode";
    if (e.type === "barcode" && e.h < 5) return "Needs a taller label for a barcode";
    if (e.type === "text" && (e.h < 2 || e.w < 5)) return "Needs a larger label";
  }
  return "";
}
const NEEDS_RED = "Needs black and red tape (DK-2251)";

// Price tags: the plain ones are black; the sale ones add a red SALE banner
// and a red price. Fields: {{title}}, {{price}}, {{code}} (the SKU).
function priceTag(code, sale) {
  const qr = code === "qr";
  const price = (o) => T({ text: "{{price}}", bold: true, align: "center", wrap: false, ...(sale ? { color: "red" } : {}), ...o });
  const sku = (o) => T({ text: "SKU {{code}}", size: 0, wrap: false, ...o });
  const banner = (o) => T({ text: "SALE", bold: true, align: "center", invert: true, color: "red", wrap: false, ...o });
  const make = (W, H, m = marginFor(W, H)) => {
    const els = [];
    if (shapeOf(W, H) === "thin") {
      // Left to right: [SALE] | title | price | code
      let x = 0;
      if (sale) { const bw = Math.min(W * 0.16, H * 1.8); els.push(banner({ x: 0, y: 0, w: bw, h: H, padding_mm: Math.min(1, m) })); x = bw; }
      x += m;
      const ih = H - 2 * m, avail = W - x - m;
      const cw = qr ? ih : Math.min(avail * 0.42, 50);
      const text = avail - cw - 2 * m, tw = text * 0.55, pw = text - tw;
      // The SKU goes under the title: text under the bars would be too small
      els.push(T({ x, y: m, w: tw, h: ih * 0.62, text: "{{title}}", bold: true }),
        sku({ x, y: m + ih * 0.62, w: tw, h: ih * 0.38 }),
        price({ x: x + tw + m, y: m, w: pw, h: ih }));
      const cx = W - m - cw;
      els.push(qr ? QR({ x: cx, y: m, w: cw, h: cw }) : BAR({ x: cx, y: m, w: cw, h: ih, show_text: false }));
      return els;
    }
    let top = m;
    if (sale) { const bh = Math.min(Math.max(H * 0.18, 4), 9); els.push(banner({ x: 0, y: 0, w: W, h: bh })); top = bh + m; }
    const ih = H - top - m, iw = W - 2 * m;
    if (shapeOf(W, H) === "tall") {
      // Stacked: title, price, code, SKU
      const th = ih * 0.2, ph = ih * 0.22, sh = ih * 0.1;
      const ch = ih - th - ph - sh - 3 * m;
      let y = top;
      els.push(T({ x: m, y, w: iw, h: th, text: "{{title}}", bold: true, align: "center" })); y += th + m;
      els.push(price({ x: m, y, w: iw, h: ph })); y += ph + m;
      if (qr) { const s = Math.min(iw, ch); els.push(QR({ x: (W - s) / 2, y, w: s, h: s })); }
      else els.push(BAR({ x: m, y, w: iw, h: Math.min(ch, 15), show_text: false }));
      y += ch + m;
      els.push(sku({ x: m, y, w: iw, h: sh, align: "center" }));
      return els;
    }
    if (qr) {
      // QR code down the right; title, price and SKU stacked beside it
      const s = Math.min(ih, W * 0.4), tw = iw - s - m;
      els.push(T({ x: m, y: top, w: tw, h: ih * 0.32, text: "{{title}}", bold: true }),
        price({ x: m, y: top + ih * 0.34, w: tw, h: ih * 0.44, align: "left" }),
        sku({ x: m, y: top + ih * 0.8, w: tw, h: ih * 0.2 }),
        QR({ x: W - m - s, y: top + (ih - s) / 2, w: s, h: s }));
      return els;
    }
    // Title across the top, price and barcode side by side, SKU at the bottom
    const th = ih * 0.28, sh = ih * 0.16, mh = ih - th - sh - 2 * m;
    const pw = iw * 0.38;
    els.push(T({ x: m, y: top, w: iw, h: th, text: "{{title}}", bold: true }),
      price({ x: m, y: top + th + m, w: pw, h: mh, align: "left" }),
      BAR({ x: 2 * m + pw, y: top + th + m, w: iw - pw - m, h: mh, show_text: false }),
      sku({ x: m, y: top + th + mh + 2 * m, w: iw, h: sh }));
    return els;
  };
  return { name: `${sale ? "Sale" : "Price"} tag + ${qr ? "QR" : "barcode"}`, cat: "retail", make,
    fits: (W, H, red) => sale && !red ? NEEDS_RED
      : shapeOf(W, H) !== "thin" && Math.min(W, H) < 20 ? "Needs a larger label" : checkEls(make(W, H)) };
}

// Layered shelf tag: a glyph (an image) and category across the top, the price in an
// outlined box at the right, then the product name, large, and a smaller
// variant line. Fields: {{category}}, {{title}}, {{variant}}, {{price}}, and
// {{note}} under the price, such as a bulk discount. Empty ones are hidden.
const layeredShelfTag = {
  name: "Layered shelf tag", cat: "retail",
  make: (W, H, m = marginFor(W, H)) => {
    const iw = W - 2 * m, ih = H - 2 * m, gap = Math.max(0.5, m / 2);
    const line = (o) => T({ wrap: false, ...o });
    const priceBox = (x, y, w, bh) => {
      const p = Math.min(1, bh * 0.08), ph = (bh - 2 * p) * 0.68;
      return [{ type: "rect", color: "black", fill: false, stroke_mm: 0.3, x, y, w, h: bh },
        line({ x: x + p, y: y + p, w: w - 2 * p, h: ph, text: "{{price}}", align: "center" }),
        line({ x: x + p, y: y + p + ph, w: w - 2 * p, h: bh - 2 * p - ph, text: "{{note}}", align: "center" })];
    };
    if (shapeOf(W, H) === "thin") {
      // Left to right: glyph | category, name and variant stacked | price box
      const g = ih, pw = Math.min(iw * 0.3, ih * 2.6), tx = m + g + gap, tw = iw - g - pw - 2 * gap;
      return [IMG({ x: m, y: m, w: g, h: g }),
        line({ x: tx, y: m, w: tw, h: ih * 0.28, text: "{{category}}" }),
        line({ x: tx, y: m + ih * 0.28, w: tw, h: ih * 0.46, text: "{{title}}" }),
        line({ x: tx, y: m + ih * 0.74, w: tw, h: ih * 0.26, text: "{{variant}}" }),
        ...priceBox(W - m - pw, m, pw, ih)];
    }
    if (shapeOf(W, H) === "tall") {
      // Stacked: glyph and category, name, variant, and the price box across the bottom
      const g = ih * 0.18, nh = ih * 0.2, vh = ih * 0.12, ph = ih * 0.3, ny = m + g + gap;
      return [IMG({ x: m, y: m, w: g, h: g }),
        line({ x: m + g + gap, y: m + g * 0.14, w: iw - g - gap, h: g * 0.72, text: "{{category}}" }),
        line({ x: m, y: ny, w: iw, h: nh, text: "{{title}}" }),
        line({ x: m, y: ny + nh, w: iw, h: vh, text: "{{variant}}" }),
        ...priceBox(m, H - m - ph, iw, ph)];
    }
    // As on a shop shelf: the top band holds the glyph and category at the
    // left and the price box at the right; the name and variant run below
    const bh = ih * 0.44, pw = iw * 0.4, g = bh * 0.8;
    const cx = m + g + gap, nh = ih * 0.3, ny = m + bh + gap;
    return [IMG({ x: m, y: m + (bh - g) / 2, w: g, h: g }),
      line({ x: cx, y: m + (bh - g * 0.72) / 2, w: W - m - pw - gap - cx, h: g * 0.72, text: "{{category}}" }),
      ...priceBox(W - m - pw, m, pw, bh),
      line({ x: m, y: ny, w: iw, h: nh, text: "{{title}}" }),
      line({ x: m, y: ny + nh, w: iw, h: H - m - ny - nh, text: "{{variant}}" })];
  },
  fits: (W, H) => shapeOf(W, H) === "thin" ? (H < 8.5 ? "Needs wider tape" : checkEls(layeredShelfTag.make(W, H)))
    : Math.min(W, H) < 18 ? "Needs a larger label" : checkEls(layeredShelfTag.make(W, H)),
};

// Quick-layout categories, in panel order
export const CATS = [["basic", "Basic"], ["storage", "Storage and inventory"], ["dates", "Dates and tracking"],
  ["cables", "Cables and mailing"], ["retail", "Retail"]];

export const PRESETS = [
  // ---- Basic ----
  { name: "Single line", cat: "basic",
    fits: () => "",
    make: (W, H, m = marginFor(W, H)) => [
      T({ x: m, y: m, w: W - 2 * m, h: H - 2 * m, text: "{{title}}", bold: true, align: "center", wrap: false })] },

  { name: "Title + body", cat: "basic",
    fits: (W, H) => shapeOf(W, H) === "thin" ? (W < 30 ? "Needs a longer label" : "") : (H < 12 || W < 15 ? "Needs a larger label" : ""),
    make: (W, H, m = marginFor(W, H)) => {
      if (shapeOf(W, H) === "thin") {
        const tw = (W - 3 * m) * 0.4;
        return [
          T({ x: m, y: m, w: tw, h: H - 2 * m, text: "{{title}}", bold: true }),
          T({ x: 2 * m + tw, y: m, w: W - 3 * m - tw, h: H - 2 * m, text: "{{body}}" })];
      }
      return [
        T({ x: m, y: m, w: W - 2 * m, h: (H - 2 * m) * 0.4, text: "{{title}}", bold: true }),
        T({ x: m, y: m + (H - 2 * m) * 0.45, w: W - 2 * m, h: (H - 2 * m) * 0.55, text: "{{body}}", valign: "top" })];
    } },

  { name: "Red header", cat: "basic",
    fits: (W, H) => shapeOf(W, H) === "thin" ? (W < 30 ? "Needs a longer label" : "") : (H < 12 || W < 15 ? "Needs a larger label" : ""),
    make: (W, H, m = marginFor(W, H)) => {
      const head = { text: "{{title}}", bold: true, align: "center", invert: true, color: "red", padding_mm: Math.min(1, m), wrap: false };
      if (shapeOf(W, H) === "thin") {
        // Red block at the start of the strip
        const bw = W * 0.35;
        return [T({ ...head, x: 0, y: 0, w: bw, h: H }), T({ x: bw + m, y: m, w: W - bw - 2 * m, h: H - 2 * m, text: "{{body}}" })];
      }
      const bh = Math.min(H * 0.32, W * 0.3);
      return [T({ ...head, x: 0, y: 0, w: W, h: bh }), T({ x: m, y: bh + m, w: W - 2 * m, h: H - bh - 2 * m, text: "{{body}}" })];
    } },

  { name: "Two columns", cat: "basic",
    fits: (W, H) => shapeOf(W, H) === "tall" ? (H < 16 ? "Needs a larger label" : "") : (W < 20 ? "Needs a wider label" : ""),
    make: (W, H, m = marginFor(W, H)) => {
      const col = { bold: true, align: "center" }, rule = 0.3;
      if (shapeOf(W, H) === "tall") {
        // Narrow labels: two rows with a rule between
        const rh = (H - 4 * m - rule) / 2;
        return [T({ ...col, x: m, y: m, w: W - 2 * m, h: rh, text: "{{title}}" }),
          RULE({ x: m, y: (H - rule) / 2, w: W - 2 * m, h: rule }),
          T({ ...col, x: m, y: H - m - rh, w: W - 2 * m, h: rh, text: "{{body}}" })];
      }
      const cw = (W - 4 * m - rule) / 2;
      return [T({ ...col, x: m, y: m, w: cw, h: H - 2 * m, text: "{{title}}" }),
        RULE({ x: (W - rule) / 2, y: m, w: rule, h: H - 2 * m }),
        T({ ...col, x: W - m - cw, y: m, w: cw, h: H - 2 * m, text: "{{body}}" })];
    } },

  // ---- Storage and inventory ----
  { name: "Text + QR", cat: "storage",
    fits: (W, H) => {
      const m = marginFor(W, H);
      const s = shapeOf(W, H) === "tall" ? Math.min(W - 2 * m, H * 0.6) : Math.min(H - 2 * m, W * 0.45);
      return s < 7 ? "Too small for a scannable QR code" : "";
    },
    make: (W, H, m = marginFor(W, H)) => {
      if (shapeOf(W, H) === "tall") {
        // Text on top, QR code centred below
        const s = Math.min(W - 2 * m, H * 0.6);
        return [T({ x: m, y: m, w: W - 2 * m, h: H - s - 3 * m, text: "{{title}}", bold: true, align: "center" }),
          QR({ x: (W - s) / 2, y: H - s - m, w: s, h: s })];
      }
      const s = Math.min(H - 2 * m, W * 0.45);
      return [T({ x: m, y: m, w: W - s - 3 * m, h: H - 2 * m, text: "{{title}}", bold: true }),
        QR({ x: W - s - m, y: (H - s) / 2, w: s, h: s })];
    } },

  { name: "Barcode", cat: "storage",
    fits: (W, H) => {
      const m = marginFor(W, H), thin = shapeOf(W, H) === "thin";
      const bw = thin ? (W - 3 * m) * 0.7 : W - 2 * m;
      return bw < 20 ? "Needs a wider label for a barcode" : (thin ? H : H * 0.6) < 7 ? "Needs a taller label for a barcode" : "";
    },
    make: (W, H, m = marginFor(W, H)) => {
      if (shapeOf(W, H) === "thin") {
        const tw = (W - 3 * m) * 0.3;
        return [T({ x: m, y: m, w: tw, h: H - 2 * m, text: "{{title}}", bold: true }),
          BAR({ x: 2 * m + tw, y: m, w: W - 3 * m - tw, h: H - 2 * m })];
      }
      // Title above the barcode; on tall labels both keep sensible heights
      const ih = H - 2 * m;
      const th = Math.min(ih * 0.3, 12), bh = Math.min(ih - th - m, (W - 2 * m) * 0.5);
      const y0 = m + (ih - th - m - bh) / 2;
      return [T({ x: m, y: y0, w: W - 2 * m, h: th, text: "{{title}}", bold: true, align: "center" }),
        BAR({ x: m, y: y0 + th + m, w: W - 2 * m, h: bh })];
    } },

  { name: "QR only", cat: "storage",
    make: (W, H, m = marginFor(W, H)) => {
      const ih = H - 2 * m, iw = W - 2 * m;
      if (W / H >= 1.5) {
        // Wide: QR code at the start, caption beside it
        const s = Math.min(ih, iw * 0.6);
        return [QR({ x: m, y: (H - s) / 2, w: s, h: s }),
          T({ x: 2 * m + s, y: m, w: iw - s - m, h: ih, text: "{{title}}", size: 0 })];
      }
      // Caption under the QR code, the pair centred
      const ch = Math.max(3, ih * 0.16), s = Math.min(iw, ih - ch - m);
      const y0 = m + (ih - s - m - ch) / 2;
      return [QR({ x: (W - s) / 2, y: y0, w: s, h: s }),
        T({ x: m, y: y0 + s + m, w: iw, h: ch, text: "{{title}}", align: "center", wrap: false })];
    } },

  { name: "Bin label", cat: "storage",
    make: (W, H, m = marginFor(W, H)) => {
      const ih = H - 2 * m, iw = W - 2 * m, rule = 0.3;
      // A small location line over a rule, the item name below
      const stack = (x, y, w, hh) => {
        const bh = hh * 0.3;
        return [T({ x, y, w, h: bh, text: "{{body}}", wrap: false }),
          RULE({ x, y: y + bh + m / 2, w, h: rule }),
          T({ x, y: y + bh + m + rule, w, h: hh - bh - m - rule, text: "{{title}}", bold: true })];
      };
      if (shapeOf(W, H) === "tall") {
        const s = Math.min(iw, H * 0.5);
        return [...stack(m, m, iw, ih - s - m), QR({ x: (W - s) / 2, y: H - m - s, w: s, h: s })];
      }
      if (shapeOf(W, H) === "thin" && H < 14) {
        // Too low to stack: item name, a rule, the location, then the QR code
        const tw = (iw - ih - 3 * m - rule) * 0.6, bx = 3 * m + tw + rule;
        return [T({ x: m, y: m, w: tw, h: ih, text: "{{title}}", bold: true }),
          RULE({ x: 2 * m + tw, y: m, w: rule, h: ih }),
          T({ x: bx, y: m, w: W - 2 * m - ih - bx, h: ih, text: "{{body}}" }),
          QR({ x: W - m - ih, y: m, w: ih, h: ih })];
      }
      const s = Math.min(ih, W * 0.4);
      return [...stack(m, m, iw - s - m, ih), QR({ x: W - m - s, y: (H - s) / 2, w: s, h: s })];
    } },

  // ---- Dates and tracking ----
  { name: "Date stamp", cat: "dates",
    fits: (W, H) => shapeOf(W, H) === "thin" ? (W < 25 ? "Needs a longer label" : "") : (H < 8 ? "Needs a larger label" : ""),
    make: (W, H, m = marginFor(W, H)) => {
      const ih = H - 2 * m, iw = W - 2 * m, date = { text: "Opened {{date}}", wrap: false };
      if (shapeOf(W, H) === "thin") {
        const tw = (iw - m) * 0.55;
        return [T({ x: m, y: m, w: tw, h: ih, text: "{{title}}", bold: true }),
          T({ ...date, x: 2 * m + tw, y: m, w: iw - tw - m, h: ih, align: "right" })];
      }
      const th = (ih - m) * 0.6;
      return [T({ x: m, y: m, w: iw, h: th, text: "{{title}}", bold: true }),
        T({ ...date, x: m, y: 2 * m + th, w: iw, h: ih - th - m })];
    } },

  { name: "Filament spool", cat: "dates",
    fits: (W, H) => shapeOf(W, H) === "thin" ? (W < 40 ? "Needs a longer label" : "") : (H < 14 || W < 20 ? "Needs a larger label" : ""),
    make: (W, H, m = marginFor(W, H)) => {
      // Material in a red band, colour below it, drying date last
      const band = { text: "{{title}}", bold: true, align: "center", invert: true, color: "red", padding_mm: Math.min(1, m), wrap: false };
      const date = { text: "Dried {{date}}", wrap: false };
      if (shapeOf(W, H) === "thin") {
        const bw = W * 0.28, rest = W - bw - 3 * m, cw = rest * 0.5;
        return [T({ ...band, x: 0, y: 0, w: bw, h: H }),
          T({ x: bw + m, y: m, w: cw, h: H - 2 * m, text: "{{body}}" }),
          T({ ...date, x: bw + 2 * m + cw, y: m, w: rest - cw, h: H - 2 * m, align: "right" })];
      }
      const bh = Math.min(H * 0.35, W * 0.3), rest = H - bh - 3 * m;
      return [T({ ...band, x: 0, y: 0, w: W, h: bh }),
        T({ x: m, y: bh + m, w: W - 2 * m, h: rest * 0.6, text: "{{body}}", bold: true }),
        T({ ...date, x: m, y: bh + 2 * m + rest * 0.6, w: W - 2 * m, h: rest * 0.4 })];
    } },

  // ---- Cables and mailing ----
  { name: "Cable flag", cat: "cables",
    fits: (W, H) => Math.max(W, H) < 45 ? `Needs a label at least ${fmt(45)} long` : "",
    make: (W, H, m = marginFor(W, H)) => {
      // The same text on both halves; the blank middle wraps around the
      // cable (15 mm suits cables up to about 4.5 mm across) and the halves
      // stick together back to back
      const WRAP = 15, along = W >= H, L = along ? W : H, half = (L - WRAP) / 2;
      const t = { text: "{{title}}", bold: true, align: "center" };
      return [0, half + WRAP].map((p) => along
        ? T({ ...t, x: p + m, y: m, w: half - 2 * m, h: H - 2 * m })
        : T({ ...t, x: m, y: p + m, w: W - 2 * m, h: half - 2 * m }));
    } },

  { name: "Address", cat: "cables",
    fits: (W, H) => H < 14 || W < 25 ? "Needs a larger label" : "",
    make: (W, H, m = marginFor(W, H)) => [
      T({ x: m, y: m, w: W - 2 * m, h: H - 2 * m, text: "{{name}}\n{{street}}\n{{city}} {{postcode}}\n{{country}}", valign: "top", wrap: false })] },

  { name: "Return address", cat: "cables",
    fits: (W, H) => shapeOf(W, H) === "thin" ? (W < 40 ? "Needs a longer label" : "") : (H < 8 || W < 20 ? "Needs a larger label" : ""),
    make: (W, H, m = marginFor(W, H)) => [
      T({ x: m, y: m, w: W - 2 * m, h: H - 2 * m, wrap: false, size: 0,
        text: shapeOf(W, H) === "thin" ? "{{name}} · {{street}} · {{city}} {{postcode}}" : "{{name}}\n{{street}}\n{{city}} {{postcode}}" })] },

  // ---- Retail ----
  priceTag("barcode", false), priceTag("qr", false), priceTag("barcode", true), priceTag("qr", true), layeredShelfTag,
];

// 0.01 mm, so full-width preset elements line up exactly with the label edges
export function roundAll(els) {
  return els.map((e) => ({ ...e, x: r2(e.x), y: r2(e.y), w: r2(e.w), h: r2(e.h) }));
}
