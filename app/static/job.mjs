// What a click on Print will send

// Printing more labels than this asks first. Loading a data file ticks every
// row, so one click could otherwise send the whole file to the printer.
export const CONFIRM_ABOVE = 25;

// The ticked data rows, in order, or null without data (one label from fixed values).
// data: the loaded data file or null; picked: the set of ticked row indexes.
export const jobRows = (data, picked) => data ? [...picked].sort((a, b) => a - b) : null;

// Copies as the server will take them: a whole number from 1 to its limit
export const copiesOf = (value, limit) => Math.max(1, Math.min(limit, Math.floor(+value || 1)));

export const labelCount = (data, picked, copies) => (data ? picked.size : 1) * copies;

// A saved PNG's file name: the template's, or "label", and the data row it
// shows, if any. Characters no file system takes are swapped for a hyphen.
export function pngName(template, row = null) {
  const base = (template || "").trim().replace(/[/\\:*?"<>|\x00-\x1f]/g, "-") || "label";
  return `${base}${row ? `, row ${row}` : ""}.png`;
}

// What the print bar says about a print job from /api/jobs: { text, tone,
// share, stage }. tone: "now" (in progress, or printed), "" (sent,
// cancelled), "err". share: how far along, 0 to 1, or null for no line.
// stage: the part a screen reader is told about, which changes less often.
export function jobWords(j) {
  const n = (k) => `${k} label${k === 1 ? "" : "s"}`;
  const warned = j.warnings?.length ? ` · ${j.warnings.length} warning${j.warnings.length === 1 ? "" : "s"}` : "";
  switch (j.state) {
    case "queued": return { text: "Waiting for another print to finish", tone: "now", share: 0, stage: "Waiting" };
    case "drawing": return { text: `Drawing label ${Math.min(j.done + 1, j.total)} of ${j.total}`, tone: "now", share: j.done / j.total, stage: "Drawing the labels" };
    case "sending": return { text: "Sending to the printer…", tone: "now", share: 1, stage: "Sending" };
    case "printing":
      if (j.error) return { text: `${j.error} · ${j.done} of ${j.total} printed; it goes on once that's put right`, tone: "err", share: j.done / j.total, stage: j.error };
      return { text: `Printing ${Math.min(j.done + 1, j.total)} of ${j.total}`, tone: "now", share: j.done / j.total, stage: "Printing" };
    case "printed": return { text: `✓ Printed ${n(j.total)}${warned}`, tone: "now", share: null, stage: `Printed ${n(j.total)}` };
    case "sent": return { text: `Sent ${n(j.total)} · the printer didn't say when they were done${warned}`, tone: "", share: null, stage: `Sent ${n(j.total)}` };
    case "cancelled": return { text: "Cancelled · nothing was sent", tone: "", share: null, stage: "Cancelled" };
    default: return { text: j.error || "Printing failed", tone: "err", share: null, stage: j.error || "Printing failed" };
  }
}

// While a job can still be cancelled, the Print button cancels it
export const cancellable = (j) => j.state === "queued" || j.state === "drawing";
