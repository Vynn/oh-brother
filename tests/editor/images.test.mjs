import { eq, suite, test } from "./harness.mjs";
import { IMAGE_MAX, IMAGE_MIN, sidesToTry, sizeAt } from "../../app/static/images.mjs";

suite("images");

test("a large image starts at the largest size and shrinks by a fifth", () => {
  eq([IMAGE_MAX, IMAGE_MIN], [600, 128]);
  eq(sidesToTry(2000, 1000), { sides: [600, 480, 384, 307, 245, 196, 156], least: 128 });
});

test("a mid-sized image starts at its own size", () => {
  eq(sidesToTry(200, 200), { sides: [200, 160, 128], least: 128 });
  eq(sidesToTry(128, 10), { sides: [128], least: 128 });
});

test("a small image is tried once, at its own size", () => {
  // It used to be refused untried: the sizes started below the least allowed
  eq(sidesToTry(40, 30), { sides: [40], least: 40 });
  eq(sidesToTry(1, 1), { sides: [1], least: 1 });
});

test("an SVG has no size of its own and starts at the largest", () => {
  eq(sidesToTry(10, 10, true).sides[0], 600);
});

test("width and height keep the image's shape, and are never nothing", () => {
  eq(sizeAt(2000, 1000, 600), { width: 600, height: 300 });
  eq(sizeAt(40, 30, 40), { width: 40, height: 30 });
  eq(sizeAt(3, 1000, 128), { width: 1, height: 128 });
});
