import { eq, near, suite, test } from "./harness.mjs";
import * as u from "../../app/static/units.mjs";

suite("units");

// Run fn with inches chosen, and go back to mm whatever happens
const inInches = (fn) => { u.setUnits("in"); try { return fn(); } finally { u.setUnits("mm"); } };

test("millimetres unless inches are chosen", () => {
  eq(u.units(), "mm");
  u.setUnits("furlongs");
  eq([u.units(), u.imperial()], ["mm", false]);
  inInches(() => eq([u.units(), u.imperial()], ["in", true]));
});

test("rounding to a tenth and a hundredth", () => {
  eq([u.r1(12.34), u.r1(12.36), u.r1(-0.26)], [12.3, 12.4, -0.3]);
  eq([u.r2(12.344), u.r2(12.346), u.r2(58.928)], [12.34, 12.35, 58.93]);
});

test("lengths shown and typed in mm", () => {
  eq(u.toUnit(12.346), 12.35);
  eq(u.fromUnit(3), 3);
  eq(u.fmt(12.34), "12.3 mm");
  eq(u.fmt2(58.928, 30), "58.9 × 30 mm");
});

test("lengths shown and typed in inches, stored in mm", () => inInches(() => {
  eq([u.toUnit(25.4), u.toUnit(12.7)], [1, 0.5]);
  eq([u.fromUnit(1), u.fromUnit(0.5)], [25.4, 12.7]);
  eq(u.fmt(25.4), "1.00 in");
  eq(u.fmt2(50.8, 25.4), "2.00 × 1.00 in");
}));

test("the snap grid is 0.5 mm, or 0.02 in", () => {
  eq([u.snap(3.2), u.snap(3.3), u.snap(3.74), u.snap(-0.2)].map(Math.abs), [3, 3.5, 3.5, 0]);
  inInches(() => {
    eq(u.snap(1), 1.02);      // 0.04 in is 1.016 mm, stored to 0.01 mm
    eq(u.snap(2.54), 2.54);   // 0.1 in
    eq(u.snap(0.2), 0);
  });
});

test("an arrow key moves a grid step, or a larger one with Shift", () => {
  eq([u.nudgeStep(false), u.nudgeStep(true)], [0.5, 2]);
  inInches(() => { near(u.nudgeStep(false), 0.508); near(u.nudgeStep(true), 2.54); });
});

test("tape names gain inches", () => {
  const tapes = [{ name: "62 mm continuous · black/red" }, { name: "12 mm round die-cut" }, { name: "29 × 90 mm die-cut" }];
  eq(tapes.map(u.tapeName), tapes.map((t) => t.name));
  inInches(() => eq(tapes.map(u.tapeName), ["62 mm (2.44 in) continuous · black/red",
    "12 mm (0.47 in) round die-cut", "29 × 90 mm (1.14 × 3.54 in) die-cut"]));
});
