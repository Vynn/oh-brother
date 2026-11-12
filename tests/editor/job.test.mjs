import { eq, suite, test } from "./harness.mjs";
import { CONFIRM_ABOVE, cancellable, copiesOf, jobRows, jobWords, labelCount, pngName } from "../../app/static/job.mjs";

suite("job");

test("the ticked rows, in the data's order", () => {
  eq(jobRows({ rows: [] }, new Set([5, 1, 3])), [1, 3, 5]);
  eq(jobRows(null, new Set([1])), null);   // no data: one label from the fixed values
});

test("copies are a whole number from 1 to the server's limit", () => {
  eq(["", 0, "2.7", 500, "abc", -3, 100, "7"].map((v) => copiesOf(v, 100)), [1, 1, 2, 100, 1, 1, 100, 7]);
});

test("labels are rows times copies", () => {
  eq(labelCount(null, new Set(), 3), 3);
  eq(labelCount({ rows: [] }, new Set([1, 2]), 3), 6);
  eq(labelCount({ rows: [] }, new Set(), 3), 0);
});

test("a job over 25 labels asks first", () => {
  eq(CONFIRM_ABOVE, 25);
});

test("a saved PNG's name", () => {
  eq(pngName("Bin label", 3), "Bin label, row 3.png");
  eq(pngName("Bin label"), "Bin label.png");
  eq(pngName("", 2), "label, row 2.png");
  eq(pngName("  "), "label.png");
  eq(pngName('a/b:c*?"<>|'), "a-b-c------.png");
});

const J = (o) => ({ state: "drawing", done: 0, total: 400, error: null, warnings: [], ...o });

test("a job's progress in words", () => {
  eq(jobWords(J({ done: 119 })), { text: "Drawing label 120 of 400", tone: "now", share: 119 / 400, stage: "Drawing the labels" });
  eq(jobWords(J({ state: "sending", done: 400 })).text, "Sending to the printer…");
  eq(jobWords(J({ state: "printing", done: 1, total: 5 })).text, "Printing 2 of 5");
  eq(jobWords(J({ state: "printing", done: 5, total: 5 })).text, "Printing 5 of 5");   // the last, until the printer is idle
  eq(jobWords(J({ state: "queued" })).text, "Waiting for another print to finish");
});

test("an error while printing", () => {
  const w = jobWords(J({ state: "printing", done: 2, total: 5, error: "Cover open" }));
  eq([w.text, w.tone, w.stage], ["Cover open · 2 of 5 printed; it goes on once that's put right", "err", "Cover open"]);
});

test("how a job ends", () => {
  eq(jobWords(J({ state: "printed", total: 1 })).text, "✓ Printed 1 label");
  eq(jobWords(J({ state: "printed", total: 5, warnings: ["a", "b"] })).text, "✓ Printed 5 labels · 2 warnings");
  eq(jobWords(J({ state: "sent", total: 5 })), { text: "Sent 5 labels · the printer didn't say when they were done", tone: "", share: null, stage: "Sent 5 labels" });
  eq(jobWords(J({ state: "cancelled" })).text, "Cancelled · nothing was sent");
  eq(jobWords(J({ state: "failed", error: "Send failed: no route" })).tone, "err");
  eq(jobWords(J({ state: "failed" })).text, "Printing failed");
});

test("only a job not yet sent can be cancelled", () => {
  eq(["queued", "drawing", "sending", "printing", "printed", "sent", "failed", "cancelled"].filter((s) => cancellable({ state: s })),
    ["queued", "drawing"]);
});
