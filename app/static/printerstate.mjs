// What the printer chip says, from the printer settings and the last answer
// from /api/status. Decided in design/printer-status.html (option A): the
// state first, then the tape; trouble in red, in words as well as colour.

// How often the editor asks, while its window is in front
export const STATUS_EVERY_MS = 5000;

// The loaded tape, short: "62 mm black/red", "29 × 90 mm labels"
export function tapeWords(tape) {
  if (tape.kind === "continuous") return `${tape.width_mm} mm${tape.two_colour ? " black/red" : ""}`;
  if (tape.kind === "die-cut") return `${tape.width_mm} × ${tape.length_mm} mm labels`;
  return tape.name;
}

// cfg: the printer settings ({printer_host, model}). info: /api/status's
// answer, or null before the first one. Returns
//   dot: "" (grey), "hollow", "ok" or "bad"; text: the state; detail: what
//   follows it, in grey; trouble: whether it's shown in red; title: the tooltip
export function chipState(cfg, info) {
  if (!cfg.printer_host) return { dot: "", text: "No printer set", detail: "", trouble: false, title: "" };
  const st = info?.status;
  const display = st?.display ? ` · display: ${st.display}` : "";
  const title = `${cfg.model} at ${cfg.printer_host}${display}`;
  const out = (dot, text, detail = "", trouble = false) => ({ dot, text, detail, trouble, title });
  if (!info) return out("hollow", "Checking the printer…");
  if (st) {
    if (st.state === "error") return out("bad", st.errors[0] || "Printer error", "", true);
    if (st.state === "printing") return out("ok", "Printing");
    if (!st.tape) return out("bad", "No tape", "", true);
    return out("ok", "Ready", tapeWords(st.tape));
  }
  // No status: the printer has SNMP off, or isn't there
  return info.reachable ? out("ok", "Connected", "no status") : out("bad", "Not answering", "", true);
}
