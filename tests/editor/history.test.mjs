import { eq, suite, test } from "./harness.mjs";
import { History } from "../../app/static/history.mjs";

suite("history");

test("undo and redo step through what was recorded", () => {
  const h = new History();
  eq([h.canUndo, h.canRedo], [false, false]);
  eq(h.record("a"), true);
  eq(h.canUndo, false);   // nothing before the first
  h.record("b"); h.record("c");
  eq([h.step(-1), h.step(-1), h.step(-1)], ["b", "a", null]);
  eq([h.canUndo, h.canRedo], [false, true]);
  eq([h.step(1), h.step(1), h.step(1)], ["b", "c", null]);
});

test("the same again isn't a step", () => {
  const h = new History();
  h.record("a");
  eq(h.record("a"), false);
  eq(h.step(-1), null);
});

test("a change after undoing drops what was undone", () => {
  const h = new History();
  for (const s of ["a", "b", "c"]) h.record(s);
  h.step(-1);
  h.record("d");
  eq([h.canRedo, h.step(1)], [false, null]);
  eq([h.step(-1), h.step(-1)], ["b", "a"]);
});

test("only the latest steps are kept", () => {
  const h = new History(3);
  for (const s of ["a", "b", "c", "d"]) h.record(s);
  eq([h.step(-1), h.step(-1), h.step(-1)], ["c", "b", null]);
});
