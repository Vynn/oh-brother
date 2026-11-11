import { eq, suite, test } from "./harness.mjs";
import { CONFIRM_ABOVE, copiesOf, jobRows, labelCount } from "../../app/static/job.mjs";

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
