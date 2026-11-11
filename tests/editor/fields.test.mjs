import { eq, suite, test } from "./harness.mjs";
import * as f from "../../app/static/fields.mjs";

suite("fields");

// The server's own pattern (fields.PLACEHOLDER) and built-in fields, which
// the editor gets from /api/meta. A server-side test keeps this copy in step.
const PATTERN = "\\{\\{\\s*([^{}]+?)\\s*\\}\\}";
const meta = { field_pattern: PATTERN, builtin_fields: ["date", "time", "datetime"] };
const state = (o) => ({ placeholders: [], fixed: {}, data: null, mapping: {}, meta, ...o });

test("tags in a text", () => {
  eq([...f.tags("{{a}} and {{ b c }}, not {this}", PATTERN)].map((m) => m[1]), ["a", "b c"]);
});

test("names are re-keyed in lowercase, the first value set winning", () => {
  eq(f.lowerKeys({ Code: "a", code: "b" }), { code: "a" });
  eq(f.lowerKeys({ Code: "", code: "b" }), { code: "b" });
  eq([f.lowerKeys(null), f.lowerKeys("text"), f.lowerKeys(undefined)], [{}, {}, {}]);
});

test("a field named inside a fixed value gets a row of its own", () => {
  const s = state({ placeholders: ["Title", "code"], fixed: { title: "x", code: "{{item}}-{{date}}-{{Extra}}" } });
  eq(f.fields(s), ["Title", "code", "item", "Extra"]);   // {{date}} is built in
});

test("a field named inside one of those is found too", () => {
  const s = state({ placeholders: ["a"], fixed: { a: "{{b}}", b: "{{c}}", c: "{{A}}" } });
  eq(f.fields(s), ["a", "b", "c"]);   // {{A}} is {{a}} again
});

test("a data column needs no row: it comes straight from the data", () => {
  const s = state({ placeholders: ["code"], fixed: { code: "{{item}}-{{Extra}}" }, data: { headers: ["Item", "qty"], rows: [] } });
  eq(f.fields(s), ["code", "Extra"]);
});

test("a field taken from a column doesn't have its fixed text read", () => {
  const s = state({ placeholders: ["code"], fixed: { code: "{{item}}" }, data: { headers: ["qty"], rows: [] }, mapping: { code: "qty" } });
  eq(f.fields(s), ["code"]);
  eq(f.isFixed(s, "Code"), false);
  eq(f.chain(s), []);
});

test("without data every field is fixed text, whatever was chosen before", () => {
  const s = state({ placeholders: ["code"], mapping: { code: "qty" } });
  eq(f.isFixed(s, "code"), true);
  eq(f.chain(s), ["code"]);
});

test("a record holds the row's columns, then each field's value", () => {
  const s = state({ placeholders: ["Title", "code", "gone"], fixed: { title: "Bin {{item}}" },
    data: { headers: ["Item", "qty"], rows: [] }, mapping: { code: "qty", gone: "removed" } });
  eq(f.record(s, { Item: "Bolt", qty: "3" }), { Item: "Bolt", qty: "3", Title: "Bin {{item}}", code: "3", gone: "" });
});

test("a record without a row holds the fixed values", () => {
  const s = state({ placeholders: ["Title", "code"], fixed: { title: "Hello" } });
  eq(f.record(s, null), { Title: "Hello", code: "" });
});

test("fields are matched to columns of the same name, whatever the case", () => {
  const s = state({ placeholders: ["code", "title"], data: { headers: ["Code", "Name"], rows: [] } });
  f.autoMap(s);
  eq(s.mapping, { code: "Code", title: "" });
});

test("a column choice already made is kept, unless its column is gone", () => {
  const s = state({ placeholders: ["code", "title", "name"], data: { headers: ["Code", "Name", "Title"], rows: [] },
    mapping: { code: "Name", title: "", name: "Old" } });
  f.autoMap(s);
  eq(s.mapping, { code: "Name", title: "", name: "Name" });
});

test("nothing is matched without data", () => {
  const s = state({ placeholders: ["code"] });
  f.autoMap(s);
  eq(s.mapping, {});
});
