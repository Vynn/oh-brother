// Display units and rounding. Layouts are stored, drawn and printed in mm;
// inches are only shown and typed. The page (app.mjs) remembers the choice in
// each browser and sets it here.

export const INCH = 25.4;

let unit = "mm";
export const units = () => unit;   // "mm" or "in"
export const setUnits = (u) => { unit = u === "in" ? "in" : "mm"; };
export const imperial = () => unit === "in";

export const r1 = (v) => Math.round(v * 10) / 10;     // shown lengths, new elements' sizes
export const r2 = (v) => Math.round(v * 100) / 100;   // stored positions: snapped centres need 0.01 mm

export const toUnit = (mm) => imperial() ? Math.round(mm / INCH * 100) / 100 : r2(mm);   // input values
export const fromUnit = (v) => r2(imperial() ? v * INCH : v);
export const fmt = (mm) => imperial() ? `${(mm / INCH).toFixed(2)} in` : `${r1(mm)} mm`;
export const fmt2 = (w, hh) => imperial() ? `${(w / INCH).toFixed(2)} × ${(hh / INCH).toFixed(2)} in` : `${r1(w)} × ${r1(hh)} mm`;

// Tape names come from the server in mm (Brother's sizes); inches are added
export const tapeName = (t) => imperial()
  ? t.name.replace(/^([\d.]+)(?: × ([\d.]+))? mm/, (m, a, b) => `${m} (${(a / INCH).toFixed(2)}${b ? ` × ${(b / INCH).toFixed(2)}` : ""} in)`)
  : t.name;

// Snap grid: 0.5 mm, or 0.02 in (0.508 mm) in inches
export const snap = (v) => imperial() ? r2(Math.round(v / 0.508) * 0.508) : Math.round(v * 2) / 2;

// One press of an arrow key, in mm: a grid step, or with Shift a larger one
// (2 mm, or 0.1 in)
export const nudgeStep = (large) => imperial() ? (large ? 2.54 : 0.508) : (large ? 2 : 0.5);
